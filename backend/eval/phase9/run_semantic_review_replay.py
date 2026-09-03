import argparse
import json
import statistics
import time
from pathlib import Path

from db import execute_query
from eval.evaluate import (
    compare_results,
    execute_gold_sql,
    tie_aware_check,
)
from llm.baseline_client import (
    review_sql_semantics,
)
from llm.retrieve_schema import retrieve_schema
from production.pipeline import (
    MAX_CORRECTION_ATTEMPTS,
    RAG_TOP_K,
)


# ============================================================
# PATHS
# ============================================================

PHASE9_DIR = Path(__file__).resolve().parent

BENCHMARK_PATH = (
    PHASE9_DIR
    / "regression_benchmark_manifest.json"
)

RESULTS_DIR = (
    PHASE9_DIR
    / "results"
)

PHASE9_5_BASELINE_PATH = (
    RESULTS_DIR
    / "phase9_5_schema_router_baseline.json"
)


# ============================================================
# FROZEN BASELINE CONFIG
# ============================================================

SEMANTIC_REVIEW_CONFIG = {
    "experiment": "semantic_review_replay",
    "source": "phase9_5_schema_router_baseline",
    "sql_generation": False,
    "self_correction": False,
    "rag_retrieval": False,
    "semantic_review": True,
    "database_routing_replayed": True,
}


# ============================================================
# LOAD FROZEN BENCHMARK
# ============================================================

def load_benchmark_cases():

    with BENCHMARK_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        manifest = json.load(file)

    if manifest.get("status") != "frozen":
        raise ValueError(
            "Phase-9 benchmark is not frozen."
        )

    if (
        manifest.get(
            "phase8_final_test_excluded"
        )
        is not True
    ):
        raise ValueError(
            "Phase-8 final-test exclusion "
            "is not confirmed."
        )

    if manifest.get("phase8_overlap") != 0:
        raise ValueError(
            "Phase-9 benchmark overlaps "
            "with Phase-8 final test."
        )

    cases = manifest.get("records")

    if not cases:
        raise ValueError(
            "Phase-9 benchmark contains "
            "no records."
        )

    return cases


def load_phase9_5_baseline():
    with PHASE9_5_BASELINE_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        baseline = json.load(file)

    results = baseline.get("results")

    if not results:
        raise ValueError(
            "Phase-9.5 baseline contains no results."
        )

    return {
        item["id"]: item
        for item in results
    }


# ============================================================
# LATENCY HELPERS
# ============================================================

def elapsed_ms(start):

    return (
        time.perf_counter()
        - start
    ) * 1000


def percentile_95(values):

    if not values:
        return 0.0

    ordered = sorted(values)

    index = min(
        len(ordered) - 1,
        int(
            0.95
            * len(ordered)
        ),
    )

    return ordered[index]


# ============================================================
# EVALUATE ONE PRODUCTION CASE
# ============================================================

def evaluate_one(test_case):
    test_id = test_case["id"]
    question = test_case["question"]

    baseline_by_id = load_phase9_5_baseline()

    if test_id not in baseline_by_id:
        raise KeyError(
            f"{test_id} missing from Phase-9.5 baseline."
        )

    baseline = baseline_by_id[test_id]

    expected_database = baseline[
        "expected_database"
    ]
    retrieved_database = baseline[
        "retrieved_database"
    ]
    database_routing_correct = baseline[
        "database_routing_correct"
    ]
    routing_distance = baseline.get(
        "routing_distance"
    )

    original_sql = baseline[
        "final_sql"
    ]
    final_sql = original_sql

    original_result = baseline.get(
        "generated_result"
    )
    generated_result = original_result

    gold_sql = baseline[
        "gold_sql"
    ]
    gold_result = baseline.get(
        "gold_result"
    )

    execution_success = baseline[
        "execution_success"
    ]

    semantic_review_used = False
    semantic_review_changed = False
    semantic_review_success = False
    semantic_review_error = None
    reviewed_sql = None

    strict_correct = False
    semantic_correct = False
    tie_accepted = False

    llm_calls = 0
    final_error = None
    error_stage = None

    latency = {
        "schema_routing_retrieval": 0.0,
        "rag_retrieval": 0.0,
        "generation": 0.0,
        "initial_execution": 0.0,
        "correction": 0.0,
        "corrected_execution": 0.0,
        "semantic_review": 0.0,
        "reviewed_execution": 0.0,
        "gold_execution": 0.0,
        "evaluation": 0.0,
        "production_total": 0.0,
        "evaluation_total": 0.0,
    }

    production_start = time.perf_counter()

    # --------------------------------------------------------
    # 1. RECONSTRUCT THE SAME SCHEMA CONTEXT
    # --------------------------------------------------------
    retrieval_start = time.perf_counter()

    try:
        retrieval_result = retrieve_schema(
            question
        )

        latency[
            "schema_routing_retrieval"
        ] = elapsed_ms(
            retrieval_start
        )

        if retrieval_result is None:
            raise RuntimeError(
                "No database could be routed."
            )

        (
            replay_retrieved_database,
            schema_text,
            replay_routing_distance,
        ) = retrieval_result

        if (
            replay_retrieved_database
            != retrieved_database
        ):
            raise RuntimeError(
                "Replay router mismatch: "
                f"baseline={retrieved_database}, "
                f"replay={replay_retrieved_database}"
            )

    except Exception as error:
        latency[
            "schema_routing_retrieval"
        ] = elapsed_ms(
            retrieval_start
        )
        final_error = str(error)
        error_stage = (
            "schema_context_reconstruction"
        )

    # --------------------------------------------------------
    # 2. SEMANTIC REVIEW ONLY
    #
    # Phase-9.5 had zero RAG examples for all 40 cases,
    # therefore examples=None is intentionally frozen here.
    # --------------------------------------------------------
    if (
        final_error is None
        and execution_success
        and generated_result is not None
    ):
        semantic_review_used = True
        review_start = time.perf_counter()

        try:
            llm_calls += 1

            reviewed_sql = (
                review_sql_semantics(
                    question=question,
                    schema_text=schema_text,
                    sql=original_sql,
                    examples=None,
                )
            )

            latency[
                "semantic_review"
            ] = elapsed_ms(
                review_start
            )

            semantic_review_changed = (
                reviewed_sql.strip()
                != original_sql.strip()
            )

            if semantic_review_changed:
                reviewed_execution_start = (
                    time.perf_counter()
                )

                try:
                    reviewed_result = (
                        execute_query(
                            reviewed_sql
                        )
                    )
                finally:
                    latency[
                        "reviewed_execution"
                    ] += elapsed_ms(
                        reviewed_execution_start
                    )

                generated_result = (
                    reviewed_result
                )
                final_sql = reviewed_sql

            semantic_review_success = True

        except Exception as error:
            semantic_review_error = str(error)

        if latency["semantic_review"] == 0.0:
            latency[
                "semantic_review"
            ] = elapsed_ms(
                review_start
            )

    latency[
        "production_total"
    ] = elapsed_ms(
        production_start
    )

    # ========================================================
    # EVALUATION BOUNDARY
    # ========================================================
    evaluation_total_start = (
        time.perf_counter()
    )

    # Reuse the frozen gold result whenever available.
    if gold_result is None:
        gold_start = time.perf_counter()

        try:
            gold_result = execute_gold_sql(
                expected_database,
                gold_sql,
            )
        except Exception as error:
            if final_error is None:
                final_error = (
                    "Gold execution failed: "
                    f"{error}"
                )
                error_stage = "gold_execution"

        latency[
            "gold_execution"
        ] = elapsed_ms(
            gold_start
        )

    evaluation_start = (
        time.perf_counter()
    )

    if (
        database_routing_correct
        and execution_success
        and generated_result is not None
        and gold_result is not None
    ):
        strict_correct = compare_results(
            generated_result,
            gold_result,
        )

        if strict_correct:
            semantic_correct = True
        else:
            tie_accepted = tie_aware_check(
                expected_database,
                final_sql,
                gold_sql,
                generated_result,
                gold_result,
            )

            semantic_correct = tie_accepted

    latency[
        "evaluation"
    ] = elapsed_ms(
        evaluation_start
    )

    latency[
        "evaluation_total"
    ] = elapsed_ms(
        evaluation_total_start
    )

    return {
        "id": test_id,
        "question": question,
        "expected_database": (
            expected_database
        ),
        "retrieved_database": (
            retrieved_database
        ),
        "database_routing_correct": (
            database_routing_correct
        ),
        "routing_distance": (
            float(routing_distance)
            if routing_distance is not None
            else None
        ),
        "rag_example_count": 0,
        "generated_sql": baseline.get(
            "generated_sql"
        ),
        "corrected_sql": baseline.get(
            "corrected_sql"
        ),
        "baseline_final_sql": (
            original_sql
        ),
        "final_sql": final_sql,
        "gold_sql": gold_sql,
        "baseline_generated_result": (
            original_result
        ),
        "generated_result": (
            generated_result
        ),
        "gold_result": gold_result,
        "correction_used": False,
        "correction_attempts": 0,
        "correction_success": False,
        "semantic_review_used": (
            semantic_review_used
        ),
        "semantic_review_changed": (
            semantic_review_changed
        ),
        "semantic_review_success": (
            semantic_review_success
        ),
        "semantic_review_error": (
            semantic_review_error
        ),
        "reviewed_sql": reviewed_sql,
        "execution_success": (
            execution_success
        ),
        "baseline_strict_correct": (
            baseline["strict_correct"]
        ),
        "baseline_semantic_correct": (
            baseline["semantic_correct"]
        ),
        "strict_correct": strict_correct,
        "semantic_correct": (
            semantic_correct
        ),
        "tie_accepted": tie_accepted,
        "llm_calls": llm_calls,
        "original_error": None,
        "error": final_error,
        "error_stage": error_stage,
        "latency_ms": {
            key: round(value, 2)
            for key, value
            in latency.items()
        },
    }


# ============================================================
# SUMMARY
# ============================================================

def build_summary(results):

    total = len(results)

    routing_correct = sum(
        item[
            "database_routing_correct"
        ]
        for item in results
    )

    strict_correct = sum(
        item["strict_correct"]
        for item in results
    )

    semantic_correct = sum(
        item["semantic_correct"]
        for item in results
    )

    execution_successes = sum(
        item["execution_success"]
        for item in results
    )

    corrections_triggered = sum(
        item["correction_used"]
        for item in results
    )

    successful_corrections = sum(
        item["correction_success"]
        for item in results
    )

    semantic_reviews = sum(
        item["semantic_review_used"]
        for item in results
    )

    semantic_rewrites = sum(
        item["semantic_review_changed"]
        for item in results
    )

    successful_semantic_reviews = sum(
        item["semantic_review_success"]
        for item in results
    )

    total_llm_calls = sum(
        item["llm_calls"]
        for item in results
    )

    total_latencies = [
        item[
            "latency_ms"
        ][
            "production_total"
        ]
        for item in results
    ]

    def mean_component(name):

        values = [
            item[
                "latency_ms"
            ][name]
            for item in results
        ]

        return round(
            statistics.mean(values),
            2,
        ) if values else 0

    return {
        "questions": total,

        "database_routing_correct": (
            routing_correct
        ),
        "database_routing_accuracy": round(
            routing_correct
            / total
            * 100,
            2,
        ) if total else 0,

        "strict_correct": strict_correct,
        "strict_accuracy": round(
            strict_correct
            / total
            * 100,
            2,
        ) if total else 0,

        "semantic_correct": (
            semantic_correct
        ),
        "semantic_accuracy": round(
            semantic_correct
            / total
            * 100,
            2,
        ) if total else 0,

        "execution_successes": (
            execution_successes
        ),
        "execution_success_rate": round(
            execution_successes
            / total
            * 100,
            2,
        ) if total else 0,

        "self_correction_triggered": (
            corrections_triggered
        ),
        "successful_corrections": (
            successful_corrections
        ),

        "semantic_reviews": (
            semantic_reviews
        ),
        "semantic_rewrites": (
            semantic_rewrites
        ),
        "successful_semantic_reviews": (
            successful_semantic_reviews
        ),
        "total_llm_calls": (
            total_llm_calls
        ),
        "mean_llm_calls_per_question": (
            round(
                total_llm_calls
                / total,
                3,
            )
            if total
            else 0
        ),

        "mean_schema_routing_retrieval_ms": (
            mean_component(
                "schema_routing_retrieval"
            )
        ),
        "mean_rag_retrieval_ms": (
            mean_component(
                "rag_retrieval"
            )
        ),
        "mean_generation_ms": (
            mean_component(
                "generation"
            )
        ),
        "mean_initial_execution_ms": (
            mean_component(
                "initial_execution"
            )
        ),
        "mean_correction_ms": (
            mean_component(
                "correction"
            )
        ),
        "mean_corrected_execution_ms": (
            mean_component(
                "corrected_execution"
            )
        ),

        "mean_semantic_review_ms": (
            mean_component(
                "semantic_review"
            )
        ),
        "mean_reviewed_execution_ms": (
            mean_component(
                "reviewed_execution"
            )
        ),
        "mean_production_latency_ms": round(
            statistics.mean(
                total_latencies
            ),
            2,
        ) if total_latencies else 0,

        "median_production_latency_ms": (
            round(
                statistics.median(
                    total_latencies
                ),
                2,
            )
            if total_latencies
            else 0
        ),

        "p95_production_latency_ms": round(
            percentile_95(
                total_latencies
            ),
            2,
        ),
    }


# ============================================================
# ATOMIC CHECKPOINT
# ============================================================

def save_checkpoint(
    checkpoint_path,
    experiment_id,
    cases,
    results,
):

    output = {
        "phase": "9.6",
        "experiment_id": (
            experiment_id
        ),
        "benchmark": (
            "phase9_regression"
        ),
        "config": SEMANTIC_REVIEW_CONFIG,
        "completed": sum(
            not is_rate_limit_result(item)
            for item in results
        ),
        "total": len(cases),
        "results": results,
    }

    temp_path = Path(
        str(checkpoint_path)
        + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            output,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temp_path.replace(
        checkpoint_path
    )


# ============================================================
# RUN BASELINE
# ============================================================

def is_rate_limit_result(result):
    error_messages = [
        result.get("error"),
        result.get("semantic_review_error"),
    ]

    error_text = " ".join(
        str(message)
        for message in error_messages
        if message
    ).lower()

    return (
        "rate_limit_exceeded" in error_text
        or "error code: 429" in error_text
        or "status code: 429" in error_text
    )


def run_semantic_review_replay(
    experiment_id,
    one=False,
    resume=False,
):

    cases = load_benchmark_cases()

    if one:
        cases = cases[:1]

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    checkpoint_path = (
        RESULTS_DIR
        / f"{experiment_id}.partial.json"
    )

    results = []

    if (
        resume
        and checkpoint_path.exists()
    ):
        checkpoint = json.loads(
            checkpoint_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            checkpoint.get("config")
            != SEMANTIC_REVIEW_CONFIG
        ):
            raise ValueError(
                "Checkpoint config mismatch."
            )

        results = checkpoint.get(
            "results",
            [],
        )

        print(
            "Resuming:",
            f"{len(results)}/{len(cases)}",
        )

    elif checkpoint_path.exists():
        raise RuntimeError(
            "Checkpoint already exists. "
            "Use --resume."
        )

    completed_ids = {
        item["id"]
        for item in results
        if not is_rate_limit_result(
            item
        )
    }

    for index, test_case in enumerate(
        cases,
        start=1,
    ):

        print(
            "=" * 80
        )

        print(
            f"[{index}/{len(cases)}]",
            test_case["id"],
        )

        if (
            test_case["id"]
            in completed_ids
        ):
            print(
                "Already completed."
            )
            continue

        result = evaluate_one(
            test_case
        )

        results.append(
            result
        )

        completed_ids.add(
            test_case["id"]
        )

        result_by_id = {
            item["id"]: item
            for item in results
        }

        results = [
            result_by_id[
                case["id"]
            ]
            for case in cases
            if case["id"]
            in result_by_id
        ]

        save_checkpoint(
            checkpoint_path,
            experiment_id,
            cases,
            results,
        )

        if is_rate_limit_result(
            result
        ):
            print(
                "Infrastructure interruption:"
            )
            print(
                "LLM rate limit detected."
            )
            print(
                "Checkpoint preserved:",
                checkpoint_path,
            )
            raise RuntimeError(
                "Experiment stopped because "
                "of LLM rate limiting. "
                "Resume later with --resume."
            )

        print(
            "Expected DB       :",
            result[
                "expected_database"
            ],
        )

        print(
            "Retrieved DB      :",
            result[
                "retrieved_database"
            ],
        )

        print(
            "Routing correct   :",
            result[
                "database_routing_correct"
            ],
        )

        print(
            "Execution success :",
            result[
                "execution_success"
            ],
        )

        print(
            "Strict correct    :",
            result[
                "strict_correct"
            ],
        )

        print(
            "Semantic correct  :",
            result[
                "semantic_correct"
            ],
        )

        print(
            "LLM calls         :",
            result[
                "llm_calls"
            ],
        )

        print(
            "Production ms     :",
            result[
                "latency_ms"
            ][
                "production_total"
            ],
        )

    summary = build_summary(
        results
    )

    return (
        cases,
        results,
        summary,
        checkpoint_path,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--experiment-id",
        required=True,
    )

    parser.add_argument(
        "--one",
        action="store_true",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
    )

    args = parser.parse_args()

    (
        cases,
        results,
        summary,
        checkpoint_path,
    ) = run_semantic_review_replay(
        experiment_id=(
            args.experiment_id
        ),
        one=args.one,
        resume=args.resume,
    )

    print()
    print("=" * 80)
    print("PHASE 9.6-B SEMANTIC REVIEW REPLAY SUMMARY")
    print("=" * 80)

    print(
        json.dumps(
            summary,
            indent=2,
        )
    )

    if not args.one:

        output_path = (
            RESULTS_DIR
            / (
                f"{args.experiment_id}.json"
            )
        )

        output = {
            "phase": "9.6",
            "experiment_id": (
                args.experiment_id
            ),
            "benchmark": (
                "phase9_regression"
            ),
            "config": SEMANTIC_REVIEW_CONFIG,
            "summary": summary,
            "results": results,
        }

        output_path.write_text(
            json.dumps(
                output,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        if checkpoint_path.exists():
            checkpoint_path.unlink()

        print()
        print(
            "Results saved:",
            output_path,
        )


if __name__ == "__main__":
    main()
