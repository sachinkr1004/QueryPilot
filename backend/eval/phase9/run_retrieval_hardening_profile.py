import argparse
import json
import statistics
import time
from pathlib import Path

from eval.phase9.run_production_baseline import (
    load_benchmark_cases,
)
from eval.phase8.retrieval_context import (
    build_retrieved_schema_text,
)
from finetuning.schema_retriever import (
    retrieve_relevant_tables,
)
from finetuning.value_retriever import (
    format_value_context,
    retrieve_relevant_values,
)
from llm.retrieve_examples import retrieve_examples
from llm.retrieve_schema import (
    retrieve_schema,
    retrieve_schema_candidates,
)
from production.pipeline import RAG_TOP_K


# ============================================================
# PATHS
# ============================================================

PHASE9_DIR = Path(__file__).resolve().parent

RESULTS_DIR = PHASE9_DIR / "results"


# ============================================================
# FROZEN DIAGNOSTIC CONFIG
# ============================================================

TABLE_TOP_K = 7

PROFILE_CONFIG = {
    "benchmark": "phase9_regression",
    "production_rag_limit": RAG_TOP_K,
    "diagnostic_table_top_k": TABLE_TOP_K,
    "fk_expansion": False,
    "value_grounding": True,
    "llm_calls": 0,
    "production_modified": False,
}


# ============================================================
# HELPERS
# ============================================================

def elapsed_ms(start):
    return (time.perf_counter() - start) * 1000


def mean(values):
    if not values:
        return 0.0
    return round(statistics.mean(values), 2)


def percentile_95(values):
    if not values:
        return 0.0

    ordered = sorted(values)

    index = min(
        len(ordered) - 1,
        int(0.95 * len(ordered)),
    )

    return round(ordered[index], 2)


# ============================================================
# PROFILE ONE CASE
# ============================================================

def profile_one(test_case):
    test_id = test_case["id"]
    question = test_case["question"]
    expected_database = test_case["db_id"]

    error = None

    retrieved_database = None
    schema_text = ""
    routing_distance = None
    routing_candidates = []

    examples = []
    table_results = []
    table_names = []
    reduced_schema_text = ""

    value_matches = []
    value_text = ""

    latency = {
        "database_routing_ms": 0.0,
        "routing_candidates_ms": 0.0,
        "rag_retrieval_ms": 0.0,
        "table_retrieval_ms": 0.0,
        "reduced_schema_build_ms": 0.0,
        "value_grounding_ms": 0.0,
        "total_ms": 0.0,
    }

    total_start = time.perf_counter()

    # --------------------------------------------------------
    # 1. CURRENT PRODUCTION DATABASE ROUTER
    # --------------------------------------------------------

    start = time.perf_counter()

    try:
        (
            retrieved_database,
            schema_text,
            routing_distance,
        ) = retrieve_schema(question)
    except Exception as exc:
        error = f"database_routing: {exc}"

    latency["database_routing_ms"] = elapsed_ms(start)

    # --------------------------------------------------------
    # 2. ROUTING DIAGNOSTICS
    # --------------------------------------------------------

    if error is None:
        start = time.perf_counter()

        try:
            routing_candidates = (
                retrieve_schema_candidates(
                    question,
                    limit=5,
                )
            )
        except Exception as exc:
            error = f"routing_candidates: {exc}"

        latency["routing_candidates_ms"] = elapsed_ms(start)

    # --------------------------------------------------------
    # 3. CURRENT PRODUCTION RAG
    # --------------------------------------------------------

    if error is None:
        start = time.perf_counter()

        try:
            examples = retrieve_examples(
                question=question,
                database_name=retrieved_database,
                limit=RAG_TOP_K,
            )
        except Exception as exc:
            error = f"rag_retrieval: {exc}"

        latency["rag_retrieval_ms"] = elapsed_ms(start)

    # --------------------------------------------------------
    # 4. PHASE-8 STYLE TABLE RETRIEVAL
    #
    # Diagnostic only:
    # top_k=7, FK expansion OFF.
    # --------------------------------------------------------

    if error is None:
        start = time.perf_counter()

        try:
            table_results = retrieve_relevant_tables(
                question=question,
                database_name=retrieved_database,
                top_k=TABLE_TOP_K,
            )

            table_names = [
                item["table_name"]
                for item in table_results
            ]
        except Exception as exc:
            error = f"table_retrieval: {exc}"

        latency["table_retrieval_ms"] = elapsed_ms(start)

    # --------------------------------------------------------
    # 5. REDUCED SCHEMA
    # --------------------------------------------------------

    if error is None:
        start = time.perf_counter()

        try:
            reduced_schema_text = (
                build_retrieved_schema_text(
                    database_name=retrieved_database,
                    table_names=table_names,
                )
            )
        except Exception as exc:
            error = f"reduced_schema_build: {exc}"

        latency["reduced_schema_build_ms"] = elapsed_ms(start)

    # --------------------------------------------------------
    # 6. EXISTING VALUE GROUNDING
    # --------------------------------------------------------

    if error is None:
        start = time.perf_counter()

        try:
            value_matches = retrieve_relevant_values(
                question=question,
                database_name=retrieved_database,
                table_names=table_names,
            )

            value_text = format_value_context(
                value_matches
            )
        except Exception as exc:
            error = f"value_grounding: {exc}"

        latency["value_grounding_ms"] = elapsed_ms(start)

    latency["total_ms"] = elapsed_ms(total_start)

    # --------------------------------------------------------
    # ROUTING RANK OF EXPECTED DATABASE
    # --------------------------------------------------------

    expected_database_rank = None

    for index, candidate in enumerate(
        routing_candidates,
        start=1,
    ):
        if (
            candidate["database_name"]
            == expected_database
        ):
            expected_database_rank = index
            break

    # --------------------------------------------------------
    # RAG DIAGNOSTICS
    # --------------------------------------------------------

    rag_distances = [
        float(item["distance"])
        for item in examples
        if item.get("distance") is not None
    ]

    rag_questions = [
        str(item.get("question", "")).strip()
        for item in examples
    ]

    unique_rag_questions = len(
        set(rag_questions)
    )

    # --------------------------------------------------------
    # VALUE DIAGNOSTICS
    # --------------------------------------------------------

    grounded_value_count = sum(
        len(item["values"])
        for item in value_matches
    )

    grounded_column_count = len(
        value_matches
    )

    return {
        "id": test_id,
        "question": question,
        "expected_database": expected_database,
        "retrieved_database": retrieved_database,
        "database_routing_correct": (
            retrieved_database
            == expected_database
        ),
        "routing_distance": (
            float(routing_distance)
            if routing_distance is not None
            else None
        ),
        "expected_database_rank_top5": (
            expected_database_rank
        ),
        "routing_candidates": (
            routing_candidates
        ),
        "rag_example_count": len(examples),
        "rag_unique_question_count": (
            unique_rag_questions
        ),
        "rag_duplicate_question_count": (
            len(examples)
            - unique_rag_questions
        ),
        "rag_min_distance": (
            min(rag_distances)
            if rag_distances
            else None
        ),
        "rag_mean_distance": (
            round(
                statistics.mean(rag_distances),
                6,
            )
            if rag_distances
            else None
        ),
        "rag_max_distance": (
            max(rag_distances)
            if rag_distances
            else None
        ),
        "rag_examples": examples,
        "diagnostic_table_count": (
            len(table_names)
        ),
        "diagnostic_tables": table_results,
        "full_schema_chars": len(schema_text),
        "full_schema_words": len(
            schema_text.split()
        ),
        "reduced_schema_chars": len(
            reduced_schema_text
        ),
        "reduced_schema_words": len(
            reduced_schema_text.split()
        ),
        "grounded_column_count": (
            grounded_column_count
        ),
        "grounded_value_count": (
            grounded_value_count
        ),
        "value_context_chars": len(
            value_text
        ),
        "value_context_words": len(
            value_text.split()
        ),
        "value_matches": value_matches,
        "value_text": value_text,
        "latency_ms": {
            key: round(value, 2)
            for key, value in latency.items()
        },
        "error": error,
    }


# ============================================================
# SUMMARY
# ============================================================

def build_summary(results):
    total = len(results)

    valid = [
        item
        for item in results
        if item["error"] is None
    ]

    routing_correct = sum(
        item["database_routing_correct"]
        for item in results
    )

    grounded_questions = sum(
        item["grounded_value_count"] > 0
        for item in valid
    )

    duplicate_rag_questions = sum(
        item["rag_duplicate_question_count"] > 0
        for item in valid
    )

    expected_in_top5 = sum(
        item["expected_database_rank_top5"]
        is not None
        for item in results
    )

    full_schema_chars = [
        item["full_schema_chars"]
        for item in valid
    ]

    reduced_schema_chars = [
        item["reduced_schema_chars"]
        for item in valid
    ]

    value_context_chars = [
        item["value_context_chars"]
        for item in valid
    ]

    grounded_values = [
        item["grounded_value_count"]
        for item in valid
    ]

    total_latencies = [
        item["latency_ms"]["total_ms"]
        for item in valid
    ]

    value_latencies = [
        item["latency_ms"][
            "value_grounding_ms"
        ]
        for item in valid
    ]

    rag_latencies = [
        item["latency_ms"]["rag_retrieval_ms"]
        for item in valid
    ]

    table_latencies = [
        item["latency_ms"]["table_retrieval_ms"]
        for item in valid
    ]

    return {
        "questions": total,
        "valid_profiles": len(valid),
        "errors": total - len(valid),
        "llm_calls": 0,
        "database_routing_correct": (
            routing_correct
        ),
        "database_routing_accuracy": (
            round(
                routing_correct / total * 100,
                2,
            )
            if total
            else 0
        ),
        "expected_database_in_top5": (
            expected_in_top5
        ),
        "expected_database_top5_rate": (
            round(
                expected_in_top5 / total * 100,
                2,
            )
            if total
            else 0
        ),
        "questions_with_grounded_values": (
            grounded_questions
        ),
        "grounded_question_rate": (
            round(
                grounded_questions
                / len(valid)
                * 100,
                2,
            )
            if valid
            else 0
        ),
        "questions_with_duplicate_rag_questions": (
            duplicate_rag_questions
        ),
        "mean_full_schema_chars": mean(
            full_schema_chars
        ),
        "mean_reduced_schema_chars": mean(
            reduced_schema_chars
        ),
        "mean_value_context_chars": mean(
            value_context_chars
        ),
        "mean_grounded_values_per_question": (
            mean(grounded_values)
        ),
        "mean_rag_retrieval_ms": mean(
            rag_latencies
        ),
        "mean_table_retrieval_ms": mean(
            table_latencies
        ),
        "mean_value_grounding_ms": mean(
            value_latencies
        ),
        "mean_total_profile_ms": mean(
            total_latencies
        ),
        "median_total_profile_ms": (
            round(
                statistics.median(
                    total_latencies
                ),
                2,
            )
            if total_latencies
            else 0
        ),
        "p95_total_profile_ms": percentile_95(
            total_latencies
        ),
    }


# ============================================================
# RUN PROFILE
# ============================================================

def run_profile(one=False):
    cases = load_benchmark_cases()

    if one:
        cases = cases[:1]

    results = []

    for index, case in enumerate(
        cases,
        start=1,
    ):
        print(
            f"[{index}/{len(cases)}] "
            f"{case['id']}"
        )

        result = profile_one(case)
        results.append(result)

        if result["error"] is not None:
            print(
                "  ERROR:",
                result["error"],
            )
        else:
            print(
                "  routed:",
                result["retrieved_database"],
                "| values:",
                result["grounded_value_count"],
                "| tables:",
                result["diagnostic_table_count"],
            )

    return results, build_summary(results)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--one",
        action="store_true",
        help="Profile one frozen benchmark case.",
    )

    parser.add_argument(
        "--experiment-id",
        default="phase9_8_retrieval_profile",
    )

    args = parser.parse_args()

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    results, summary = run_profile(
        one=args.one
    )

    output = {
        "phase": "9.8",
        "experiment_id": args.experiment_id,
        "benchmark": "phase9_regression",
        "config": PROFILE_CONFIG,
        "completed": len(results),
        "summary": summary,
        "results": results,
    }

    suffix = (
        "_smoke"
        if args.one
        else ""
    )

    output_path = (
        RESULTS_DIR
        / f"{args.experiment_id}{suffix}.json"
    )

    output_path.write_text(
        json.dumps(
            output,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print()
    print("SUMMARY")
    print(
        json.dumps(
            summary,
            indent=2,
        )
    )
    print()
    print(
        "Saved:",
        output_path,
    )


if __name__ == "__main__":
    main()
