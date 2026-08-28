import argparse
import json
import statistics
import time
from pathlib import Path

from db import execute_query

from eval.evaluate import (
    execute_gold_sql,
    compare_results,
    tie_aware_check,
)

from eval.phase8.retrieval_context import (
    build_phase8_retrieval_context,
)

from eval.phase8.generators import (
    generate_phase8_baseline_sql,
)

from eval.phase8.metrics_utils import (
    required_table_recall,
)

from llm.baseline_client import (
    correct_sql,
    review_sql_semantics,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

TEST_SET_PATH = (
    BASE_DIR
    / "test_set.json"
)

RESULTS_DIR = (
    BASE_DIR
    / "phase8"
    / "results"
)


# ============================================================
# LOAD ABLATION BENCHMARK
# ============================================================

def load_ablation_cases():

    with TEST_SET_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


# ============================================================
# EVALUATE ONE CASE
# ============================================================

def evaluate_one(
    test_case,
    config,
):

    test_id = test_case["id"]
    db_id = test_case["db_id"]
    question = test_case["question"]
    gold_sql = test_case["gold_sql"]

    generated_sql = None
    corrected_sql = None
    reviewed_sql = None
    final_sql = None

    generated_result = None
    gold_result = None

    initial_error = None
    review_error = None
    error = None

    correction_used = False
    correction_success = False

    semantic_review_used = False
    semantic_review_changed = False
    semantic_review_success = False

    strict_correct = False
    semantic_correct = False
    tie_accepted = False

    context = None

    total_start = time.perf_counter()

    # --------------------------------------------------------
    # 1. RETRIEVAL
    # --------------------------------------------------------

    retrieval_start = time.perf_counter()

    context = build_phase8_retrieval_context(
        question=question,
        database_name=db_id,
        top_k=config["top_k"],
        fk_expansion=config["fk_expansion"],
        fk_hops=config["fk_hops"],
        value_grounding=config[
            "value_grounding"
        ],
        rag_examples=config["rag_examples"],
        rag_limit=config["rag_limit"],
    )

    retrieval_ms = (
        time.perf_counter()
        - retrieval_start
    ) * 1000

    retrieval_evaluation = required_table_recall(
        gold_sql=gold_sql,
        retrieved_tables=context["table_names"],
    )

    input_context = context["input_context"]

    context_characters = len(
        input_context
    )

    context_words = len(
        input_context.split()
    )

    # --------------------------------------------------------
    # 2. GENERATION
    # --------------------------------------------------------

    generation_start = time.perf_counter()

    generated_sql = (
        generate_phase8_baseline_sql(
            question=question,
            context=context,
        )
    )

    generation_ms = (
        time.perf_counter()
        - generation_start
    ) * 1000

    final_sql = generated_sql

    # --------------------------------------------------------
    # 3. EXECUTE RAW SQL
    # --------------------------------------------------------

    execution_start = time.perf_counter()

    try:

        generated_result = execute_query(
            generated_sql
        )

    except Exception as execution_error:

        initial_error = str(
            execution_error
        )

        # ----------------------------------------------------
        # 4. SELF-CORRECTION
        # ----------------------------------------------------

        if config["self_correction"]:

            correction_used = True

            corrected_sql = correct_sql(
                question=question,
                schema_text=context[
                    "schema_text"
                ],
                failed_sql=generated_sql,
                error_message=initial_error,
                examples=context["examples"],
            )

            final_sql = corrected_sql

            try:

                generated_result = execute_query(
                    corrected_sql
                )

                correction_success = True

            except Exception as corrected_error:

                error = str(
                    corrected_error
                )

        else:

            error = initial_error

    execution_ms = (
        time.perf_counter()
        - execution_start
    ) * 1000

    # --------------------------------------------------------
    # 5. SEMANTIC REVIEW
    # --------------------------------------------------------

    review_ms = 0.0

    if (
        config["semantic_review"]
        and error is None
        and generated_result is not None
    ):

        semantic_review_used = True

        review_start = time.perf_counter()

        try:

            reviewed_sql = (
                review_sql_semantics(
                    question=question,
                    schema_text=context[
                        "schema_text"
                    ],
                    sql=final_sql,
                    examples=context[
                        "examples"
                    ],
                )
            )

            semantic_review_changed = (
                reviewed_sql.strip()
                != final_sql.strip()
            )

            if semantic_review_changed:

                reviewed_result = (
                    execute_query(
                        reviewed_sql
                    )
                )

                generated_result = (
                    reviewed_result
                )

                final_sql = reviewed_sql

            semantic_review_success = True

        except Exception as semantic_error:

            review_error = str(
                semantic_error
            )

            semantic_review_success = False

        review_ms = (
            time.perf_counter()
            - review_start
        ) * 1000

    # --------------------------------------------------------
    # 6. GOLD EXECUTION
    # --------------------------------------------------------

    gold_result = execute_gold_sql(
        db_id,
        gold_sql,
    )

    # --------------------------------------------------------
    # 7. CORRECTNESS
    # --------------------------------------------------------

    if (
        error is None
        and generated_result is not None
    ):

        strict_correct = compare_results(
            generated_result,
            gold_result,
        )

        if strict_correct:

            semantic_correct = True

        else:

            tie_accepted = tie_aware_check(
                db_id,
                final_sql,
                gold_sql,
                generated_result,
                gold_result,
            )

            semantic_correct = (
                tie_accepted
            )

    total_ms = (
        time.perf_counter()
        - total_start
    ) * 1000

    return {
        "id": test_id,
        "db_id": db_id,
        "split": test_case["split"],
        "question": question,

        "retrieved_tables": (
            context["table_names"]
        ),

        "retrieved_table_count": len(
            context["table_names"]
        ),

        "required_tables": (
            retrieval_evaluation[
                "required_tables"
            ]
        ),

        "retrieved_required_tables": (
            retrieval_evaluation[
                "retrieved_required_tables"
            ]
        ),

        "missing_required_tables": (
            retrieval_evaluation[
                "missing_required_tables"
            ]
        ),

        "required_table_recall": (
            retrieval_evaluation[
                "required_table_recall"
            ]
        ),

        "context_characters": (
            context_characters
        ),

        "context_words": (
            context_words
        ),

        "rag_example_count": len(
            context["examples"]
        ),

        "value_match_count": len(
            context["value_matches"]
        ),

        "generated_sql": generated_sql,
        "corrected_sql": corrected_sql,
        "reviewed_sql": reviewed_sql,
        "final_sql": final_sql,
        "gold_sql": gold_sql,

        "generated_result": generated_result,
        "gold_result": gold_result,

        "initial_error": initial_error,
        "review_error": review_error,
        "error": error,

        "correction_used": correction_used,
        "correction_success": (
            correction_success
        ),

        "semantic_review_used": (
            semantic_review_used
        ),

        "semantic_review_changed": (
            semantic_review_changed
        ),

        "semantic_review_success": (
            semantic_review_success
        ),

        "strict_correct": strict_correct,
        "semantic_correct": semantic_correct,
        "tie_accepted": tie_accepted,

        "latency_ms": {
            "retrieval": round(
                retrieval_ms,
                2,
            ),
            "generation": round(
                generation_ms,
                2,
            ),
            "execution_and_correction": round(
                execution_ms,
                2,
            ),
            "semantic_review": round(
                review_ms,
                2,
            ),
            "total": round(
                total_ms,
                2,
            ),
        },
    }


# ============================================================
# BUILD SUMMARY
# ============================================================

def build_summary(results):

    total = len(results)

    strict_correct = sum(
        item["strict_correct"]
        for item in results
    )

    semantic_correct = sum(
        item["semantic_correct"]
        for item in results
    )

    execution_successes = sum(
        item["error"] is None
        for item in results
    )

    correction_used = sum(
        item["correction_used"]
        for item in results
    )

    correction_success = sum(
        item["correction_success"]
        for item in results
    )

    semantic_review_used = sum(
        item["semantic_review_used"]
        for item in results
    )

    semantic_rewrites = sum(
        item["semantic_review_changed"]
        for item in results
    )

    semantic_review_success = sum(
        item["semantic_review_success"]
        for item in results
    )

    total_latencies = [
        item["latency_ms"]["total"]
        for item in results
    ]

    table_recalls = [
        item["required_table_recall"]
        for item in results
    ]

    retrieved_table_counts = [
        item["retrieved_table_count"]
        for item in results
    ]

    context_character_counts = [
        item["context_characters"]
        for item in results
    ]

    context_word_counts = [
        item["context_words"]
        for item in results
    ]

    mean_latency = (
        statistics.mean(
            total_latencies
        )
        if total_latencies
        else 0
    )

    median_latency = (
        statistics.median(
            total_latencies
        )
        if total_latencies
        else 0
    )

    p95_latency = 0

    if total_latencies:

        ordered = sorted(
            total_latencies
        )

        index = min(
            len(ordered) - 1,
            int(
                0.95
                * len(ordered)
            ),
        )

        p95_latency = ordered[
            index
        ]

    return {
        "questions": total,

        "strict_correct": strict_correct,

        "strict_execution_accuracy": round(
            strict_correct / total * 100,
            2,
        ) if total else 0,

        "semantic_correct": semantic_correct,

        "semantic_accuracy": round(
            semantic_correct / total * 100,
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
            correction_used
        ),

        "successful_corrections": (
            correction_success
        ),

        "self_correction_success_rate": round(
            correction_success
            / correction_used
            * 100,
            2,
        ) if correction_used else 0,

        "semantic_reviews_run": (
            semantic_review_used
        ),

        "semantic_rewrites": (
            semantic_rewrites
        ),

        "successful_semantic_reviews": (
            semantic_review_success
        ),

        "semantic_review_success_rate": round(
            semantic_review_success
            / semantic_review_used
            * 100,
            2,
        ) if semantic_review_used else 0,

        "required_table_recall": round(
            statistics.mean(
                table_recalls
            ),
            2,
        ) if table_recalls else 0,

        "mean_retrieved_tables": round(
            statistics.mean(
                retrieved_table_counts
            ),
            2,
        ) if retrieved_table_counts else 0,

        "mean_context_characters": round(
            statistics.mean(
                context_character_counts
            ),
            2,
        ) if context_character_counts else 0,

        "mean_context_words": round(
            statistics.mean(
                context_word_counts
            ),
            2,
        ) if context_word_counts else 0,

        "mean_latency_ms": round(
            mean_latency,
            2,
        ),

        "median_latency_ms": round(
            median_latency,
            2,
        ),

        "p95_latency_ms": round(
            p95_latency,
            2,
        ),
    }


# ============================================================
# RUN EXPERIMENT
# ============================================================

def run_experiment(
    experiment_id,
    config,
    one=False,
    resume=False,
):
    cases = load_ablation_cases()

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

    # --------------------------------------------------------
    # LOAD CHECKPOINT
    # --------------------------------------------------------

    if resume and checkpoint_path.exists():
        checkpoint = json.loads(
            checkpoint_path.read_text(
                encoding="utf-8",
            )
        )

        checkpoint_config = checkpoint.get(
            "config"
        )

        if checkpoint_config != config:
            raise ValueError(
                "Checkpoint config does not match "
                "the current experiment config. "
                "Refusing to mix ablation runs."
            )

        results = checkpoint.get(
            "results",
            [],
        )

        print()
        print(
            "RESUME CHECKPOINT FOUND:",
            checkpoint_path,
        )
        print(
            "Completed cases:",
            f"{len(results)}/{len(cases)}",
        )
        print()

    elif checkpoint_path.exists():
        raise RuntimeError(
            "Partial checkpoint already exists: "
            f"{checkpoint_path}. "
            "Use --resume to continue it."
        )

    completed_ids = {
        result["id"]
        for result in results
    }

    print("=" * 90)
    print(
        "PHASE 8.2 — CONTROLLED "
        "ABLATION EXPERIMENT"
    )
    print("=" * 90)
    print()

    print(
        "Experiment:",
        experiment_id,
    )
    print()

    print("CONFIG")
    print("-" * 90)

    for key, value in config.items():
        print(
            f"{key:<25}: {value}"
        )

    print()

    # --------------------------------------------------------
    # EVALUATE CASES
    # --------------------------------------------------------

    for index, test_case in enumerate(
        cases,
        start=1,
    ):
        print("=" * 90)
        print(
            f"[{index}/{len(cases)}] "
            f"{test_case['id']}"
        )
        print()

        if test_case["id"] in completed_ids:
            print(
                "Already completed — skipping."
            )
            print()
            continue

        result = evaluate_one(
            test_case,
            config,
        )

        results.append(
            result
        )

        completed_ids.add(
            test_case["id"]
        )

        # Keep checkpoint results in benchmark order.
        result_by_id = {
            item["id"]: item
            for item in results
        }

        results = [
            result_by_id[case["id"]]
            for case in cases
            if case["id"] in result_by_id
        ]

        # ----------------------------------------------------
        # ATOMIC CHECKPOINT SAVE
        # ----------------------------------------------------

        checkpoint_output = {
            "phase": "8.2",
            "experiment_id": experiment_id,
            "benchmark": "phase7_consumed_20",
            "config": config,
            "completed": len(results),
            "total": len(cases),
            "results": results,
        }

        temp_checkpoint_path = Path(
            str(checkpoint_path) + ".tmp"
        )

        temp_checkpoint_path.write_text(
            json.dumps(
                checkpoint_output,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        temp_checkpoint_path.replace(
            checkpoint_path
        )

        print(
            "Checkpoint saved :",
            f"{len(results)}/{len(cases)}",
        )

        print(
            "Strict correct   :",
            result["strict_correct"],
        )

        print(
            "Semantic correct :",
            result["semantic_correct"],
        )

        print(
            "Execution error  :",
            result["error"],
        )

        print(
            "Total latency ms :",
            result[
                "latency_ms"
            ]["total"],
        )

        print()

    summary = build_summary(
        results
    )

    return (
        results,
        summary,
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
        "--top-k",
        type=int,
        default=7,
    )

    parser.add_argument(
        "--fk-hops",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--fk-expansion",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    parser.add_argument(
        "--value-grounding",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    parser.add_argument(
        "--rag-examples",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    parser.add_argument(
        "--self-correction",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    parser.add_argument(
        "--semantic-review",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    parser.add_argument(
        "--rag-limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--one",
        action="store_true",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted experiment "
            "from its checkpoint."
        ),
    )

    args = parser.parse_args()

    config = {
        "generator": "phase8_baseline",
        "top_k": args.top_k,
        "fk_expansion": (
            args.fk_expansion
        ),
        "fk_hops": args.fk_hops,
        "value_grounding": (
            args.value_grounding
        ),
        "rag_examples": (
            args.rag_examples
        ),
        "rag_limit": args.rag_limit,
        "self_correction": (
            args.self_correction
        ),
        "semantic_review": (
            args.semantic_review
        ),
    }

    results, summary = run_experiment(
        experiment_id=(
            args.experiment_id
        ),
        config=config,
        one=args.one,
        resume=args.resume,
    )

    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)

    print(
        json.dumps(
            summary,
            indent=2,
        )
    )

    if not args.one:

        RESULTS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            RESULTS_DIR
            / (
                f"{args.experiment_id}.json"
            )
        )

        output = {
            "phase": "8.2",
            "experiment_id": (
                args.experiment_id
            ),
            "benchmark": (
                "phase7_consumed_20"
            ),
            "config": config,
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

        print()
        print(
            "Results saved:",
            output_path,
        )

        # Remove checkpoint only after the final
        # experiment result has been saved safely.
        checkpoint_path = (
            RESULTS_DIR
            / f"{args.experiment_id}.partial.json"
        )

        if checkpoint_path.exists():
            checkpoint_path.unlink()

            print(
                "Checkpoint removed:",
                checkpoint_path,
            )

    print()
    print("=" * 90)
    print(
        "🎯 PHASE 8 EXPERIMENT FINISHED"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
