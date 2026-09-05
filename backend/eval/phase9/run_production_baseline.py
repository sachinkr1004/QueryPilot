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
    correct_sql,
    generate_sql,
)
from llm.retrieve_examples import retrieve_examples
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


# ============================================================
# FROZEN BASELINE CONFIG
# ============================================================

BASELINE_CONFIG = {
    "pipeline": "production_components",
    "rag_limit": RAG_TOP_K,
    "max_correction_attempts": (
        MAX_CORRECTION_ATTEMPTS
    ),
    "semantic_review": False,
    "database_routing": True,
}


# ============================================================
# PROVIDER QUOTA GUARD
# ============================================================

class ProviderRateLimitError(RuntimeError):
    """Raised when provider quota would contaminate evaluation."""

    pass


def raise_if_provider_rate_limited(error):
    message = str(error).lower()

    if (
        "429" in message
        or "rate_limit_exceeded" in message
        or "rate limit reached" in message
    ):
        raise ProviderRateLimitError(str(error)) from error


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
    expected_database = test_case["db_id"]
    question = test_case["question"]
    gold_sql = test_case["gold_sql"]

    retrieved_database = None
    schema_text = None
    routing_distance = None
    examples = []

    generated_sql = None
    corrected_sql = None
    final_sql = None

    generated_result = None
    gold_result = None

    original_error = None
    final_error = None
    error_stage = None

    correction_used = False
    correction_attempts = 0
    correction_success = False

    execution_success = False
    database_routing_correct = False

    strict_correct = False
    semantic_correct = False
    tie_accepted = False

    llm_calls = 0

    latency = {
        "schema_routing_retrieval": 0.0,
        "rag_retrieval": 0.0,
        "generation": 0.0,
        "initial_execution": 0.0,
        "correction": 0.0,
        "corrected_execution": 0.0,
        "gold_execution": 0.0,
        "evaluation": 0.0,
        "production_total": 0.0,
        "evaluation_total": 0.0,
    }

    production_start = time.perf_counter()

    # --------------------------------------------------------
    # 1. PRODUCTION DATABASE ROUTING + SCHEMA RETRIEVAL
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
            retrieved_database,
            schema_text,
            routing_distance,
        ) = retrieval_result

        database_routing_correct = (
            retrieved_database
            == expected_database
        )

    except Exception as error:
        latency[
            "schema_routing_retrieval"
        ] = elapsed_ms(
            retrieval_start
        )

        final_error = str(error)
        error_stage = (
            "schema_routing_retrieval"
        )

    # --------------------------------------------------------
    # 2. PRODUCTION RAG RETRIEVAL
    # --------------------------------------------------------

    if final_error is None:

        rag_start = time.perf_counter()

        try:
            examples = retrieve_examples(
                question,
                retrieved_database,
                limit=RAG_TOP_K,
            )

        except Exception as error:
            final_error = str(error)
            error_stage = "rag_retrieval"

        latency[
            "rag_retrieval"
        ] = elapsed_ms(
            rag_start
        )

    # --------------------------------------------------------
    # 3. PRODUCTION SQL GENERATION
    # --------------------------------------------------------

    if final_error is None:

        generation_start = (
            time.perf_counter()
        )

        try:
            llm_calls += 1

            generated_sql = generate_sql(
                question,
                schema_text,
                examples,
            )

            final_sql = generated_sql

        except Exception as error:
            raise_if_provider_rate_limited(error)
            final_error = str(error)
            error_stage = "generation"

        latency[
            "generation"
        ] = elapsed_ms(
            generation_start
        )

    # --------------------------------------------------------
    # 4. INITIAL SQL EXECUTION
    # --------------------------------------------------------

    if final_error is None:

        execution_start = (
            time.perf_counter()
        )

        try:
            generated_result = (
                execute_query(
                    generated_sql
                )
            )

            execution_success = True

        except Exception as error:
            original_error = str(error)

        latency[
            "initial_execution"
        ] = elapsed_ms(
            execution_start
        )

    # --------------------------------------------------------
    # 5. PRODUCTION SELF-CORRECTION
    # --------------------------------------------------------

    if (
        final_error is None
        and not execution_success
        and original_error is not None
    ):

        last_error = original_error
        failed_sql = generated_sql

        while (
            correction_attempts
            < MAX_CORRECTION_ATTEMPTS
        ):

            correction_attempts += 1
            correction_used = True

            correction_start = (
                time.perf_counter()
            )

            try:
                llm_calls += 1

                corrected_sql = correct_sql(
                    question=question,
                    schema_text=schema_text,
                    failed_sql=failed_sql,
                    error_message=last_error,
                    examples=examples,
                )

                final_sql = corrected_sql

            except Exception as error:
                raise_if_provider_rate_limited(error)
                final_error = str(error)
                error_stage = "correction"

            latency[
                "correction"
            ] += elapsed_ms(
                correction_start
            )

            if final_error is not None:
                break

            corrected_execution_start = (
                time.perf_counter()
            )

            try:
                generated_result = (
                    execute_query(
                        corrected_sql
                    )
                )

                execution_success = True
                correction_success = True

            except Exception as error:
                last_error = str(error)
                failed_sql = corrected_sql

            latency[
                "corrected_execution"
            ] += elapsed_ms(
                corrected_execution_start
            )

            if execution_success:
                break

        if (
            not execution_success
            and final_error is None
        ):
            final_error = last_error
            error_stage = (
                "corrected_execution"
            )

    latency[
        "production_total"
    ] = elapsed_ms(
        production_start
    )

    # ========================================================
    # EVALUATION BOUNDARY
    # Everything below this point is NOT production behavior.
    # ========================================================

    evaluation_total_start = (
        time.perf_counter()
    )

    # --------------------------------------------------------
    # 6. GOLD EXECUTION
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 7. CORRECTNESS
    # --------------------------------------------------------

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
            tie_accepted = (
                tie_aware_check(
                    expected_database,
                    final_sql,
                    gold_sql,
                    generated_result,
                    gold_result,
                )
            )

            semantic_correct = (
                tie_accepted
            )

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

        "rag_example_count": len(
            examples
        ),

        "generated_sql": generated_sql,
        "corrected_sql": corrected_sql,
        "final_sql": final_sql,
        "gold_sql": gold_sql,

        "generated_result": (
            generated_result
        ),
        "gold_result": gold_result,

        "correction_used": (
            correction_used
        ),
        "correction_attempts": (
            correction_attempts
        ),
        "correction_success": (
            correction_success
        ),

        "execution_success": (
            execution_success
        ),

        "strict_correct": (
            strict_correct
        ),
        "semantic_correct": (
            semantic_correct
        ),
        "tie_accepted": tie_accepted,

        "llm_calls": llm_calls,

        "original_error": (
            original_error
        ),
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
        "phase": "9.5",
        "experiment_id": (
            experiment_id
        ),
        "benchmark": (
            "phase9_regression"
        ),
        "config": BASELINE_CONFIG,
        "completed": len(results),
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

def run_baseline(
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
            != BASELINE_CONFIG
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

        try:
            result = evaluate_one(
                test_case
            )
        except ProviderRateLimitError as error:
            print(
                "⏸️ Provider rate limit reached."
            )
            print(
                "Current case was NOT recorded:",
                test_case["id"],
            )
            print(
                "Completed cases preserved:",
                len(results),
            )
            print(
                "Resume later with --resume."
            )
            print(
                "Provider error:",
                str(error),
            )
            raise

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

    try:
        (
            cases,
            results,
            summary,
            checkpoint_path,
        ) = run_baseline(
            experiment_id=(
                args.experiment_id
            ),
            one=args.one,
            resume=args.resume,
        )
    except ProviderRateLimitError:
        print()
        print(
            "⏸️ Benchmark interrupted by provider quota."
        )
        print(
            "Checkpoint preserved. Resume later "
            "with the same experiment ID and --resume."
        )
        return

    print()
    print("=" * 80)
    print("PHASE 9.5 SUMMARY")
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
            "phase": "9.5",
            "experiment_id": (
                args.experiment_id
            ),
            "benchmark": (
                "phase9_regression"
            ),
            "config": BASELINE_CONFIG,
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
