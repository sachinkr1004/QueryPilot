import json

from collections import Counter
from pathlib import Path

from finetuning.full_split import (
    FULL_SCALE_HOLDOUT_DATABASES,
)

from finetuning.full_scale_exclusions import (
    is_schema_inconsistent_exclusion,
)

from finetuning.value_grounding_audit import (
    extract_sql_literals,
)

from finetuning.schema_retriever import (
    retrieve_relevant_tables_with_fk_hops,
)

from finetuning.value_retriever import (
    retrieve_relevant_values,
    normalize_value_match_text,
    get_distinct_values,
)

from finetuning.spider_context import (
    build_database_metadata,
)

from finetuning.value_failure_classifier import (
    classify_missing_value,
)

from finetuning.numeric_semantic_precision_final import (
    boolean_semantic_value_matches_question,
    geographic_semantic_value_matches_question,
    numeric_semantic_value_matches_question,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

TRAIN_PATH = (
    PROJECT_ROOT
    / "dataset"
    / "spider"
    / "spider_data"
    / "spider_data"
    / "train_spider.json"
)


# ============================================================
# LOAD CLEAN CORPUS
# ============================================================

def load_clean_examples():

    with TRAIN_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        examples = json.load(file)

    return [
        item
        for item in examples
        if (
            item["db_id"]
            not in FULL_SCALE_HOLDOUT_DATABASES
            and not is_schema_inconsistent_exclusion(
                item["db_id"],
                item["question"],
            )
        )
    ]


# ============================================================
# HELPERS
# ============================================================

def is_like_pattern(value):

    return "%" in str(value)


# ============================================================
# SEMANTIC CANDIDATES
# ============================================================

def get_semantic_candidates(
    database_name,
    question,
    table_names,
):

    metadata = build_database_metadata(
        database_name
    )

    selected_tables = {
        table_name.lower()
        for table_name in table_names
    }

    candidates = set()

    for table_name, table_info in (
        metadata["tables"].items()
    ):

        if (
            table_name.lower()
            not in selected_tables
        ):
            continue

        for column_name in (
            table_info["columns"]
        ):

            column_type = (
                table_info[
                    "column_types"
                ][
                    column_name
                ]
            )

            if (
                str(column_type).lower()
                != "text"
            ):
                continue

            values = get_distinct_values(
                database_name,
                table_name,
                column_name,
            )

            for value in values:

                if (
                    boolean_semantic_value_matches_question(
                        value,
                        question,
                        column_name,
                    )
                    or geographic_semantic_value_matches_question(
                        value,
                        question,
                        table_name,
                        column_name,
                    )
                    or numeric_semantic_value_matches_question(
                        value,
                        question,
                        table_name,
                        column_name,
                    )
                ):

                    normalized = (
                        normalize_value_match_text(
                            value
                        )
                    )

                    if normalized:
                        candidates.add(
                            normalized
                        )

    return candidates


# ============================================================
# MAIN
# ============================================================

def main():

    examples = load_clean_examples()

    stats = Counter()
    category_counts = Counter()

    classified_failures = []

    print("=" * 90)

    print(
        "PHASE 7.2J.6K.2 - "
        "POST-NUMERIC REMAINING FAILURE AUDIT"
    )

    print("=" * 90)

    print()

    print(
        "Clean examples:",
        len(examples),
    )

    for index, item in enumerate(
        examples,
        1,
    ):

        literals = extract_sql_literals(
            item["query"]
        )

        raw_normal_values = {
            value
            for value in literals["strings"]
            if not is_like_pattern(value)
        }

        normal_values = {
            normalize_value_match_text(value)
            for value in raw_normal_values
            if normalize_value_match_text(value)
        }

        if not normal_values:
            continue

        # ----------------------------------------------------
        # Schema retrieval
        # ----------------------------------------------------

        table_results = (
            retrieve_relevant_tables_with_fk_hops(
                question=item["question"],
                database_name=item["db_id"],
                top_k=7,
                fk_hops=2,
            )
        )

        table_names = [
            result["table_name"]
            for result in table_results
        ]

        # ----------------------------------------------------
        # Current production retrieval
        # ----------------------------------------------------

        value_results = (
            retrieve_relevant_values(
                question=item["question"],
                database_name=item["db_id"],
                table_names=table_names,
            )
        )

        retrieved_values = {
            normalize_value_match_text(value)
            for result in value_results
            for value in result["values"]
            if normalize_value_match_text(value)
        }

        missing_before_semantic = (
            normal_values
            - retrieved_values
        )

        stats[
            "missing_before_semantic"
        ] += len(
            missing_before_semantic
        )

        # ----------------------------------------------------
        # Validated 100%-precision semantic layer
        # ----------------------------------------------------

        semantic_candidates = (
            get_semantic_candidates(
                database_name=item["db_id"],
                question=item["question"],
                table_names=table_names,
            )
        )

        validated_semantic_recoveries = (
            missing_before_semantic
            & semantic_candidates
        )

        stats[
            "semantic_recoveries"
        ] += len(
            validated_semantic_recoveries
        )

        # ----------------------------------------------------
        # TRUE remaining failures
        # ----------------------------------------------------

        remaining = (
            missing_before_semantic
            - validated_semantic_recoveries
        )

        if not remaining:
            continue

        stats[
            "failure_examples"
        ] += 1

        stats[
            "remaining_missing"
        ] += len(
            remaining
        )

        for value in sorted(
            remaining
        ):

            classification = (
                classify_missing_value(
                    db_id=item["db_id"],
                    question=item["question"],
                    value=value,
                )
            )

            category = (
                classification["category"]
            )

            category_counts[
                category
            ] += 1

            classified_failures.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "value": value,
                    "category": category,
                    "best_phrase": classification[
                        "best_phrase"
                    ],
                    "similarity": classification[
                        "similarity"
                    ],
                    "db_matches": classification[
                        "db_matches"
                    ],
                    "sql": item["query"],
                }
            )

        if index % 500 == 0:

            print(
                f"Processed {index}/"
                f"{len(examples)}..."
            )


    # ========================================================
    # REPORT
    # ========================================================

    print()

    print("=" * 90)
    print("RESULT")
    print("=" * 90)

    print()

    print(
        "Missing before semantic :",
        stats["missing_before_semantic"],
    )

    print(
        "Semantic recoveries     :",
        stats["semantic_recoveries"],
    )

    print(
        "Remaining missing       :",
        stats["remaining_missing"],
    )

    print(
        "Failure examples        :",
        stats["failure_examples"],
    )

    print()

    print("=" * 90)
    print("REMAINING CATEGORY COUNTS")
    print("=" * 90)

    print()

    for category, count in (
        category_counts.most_common()
    ):

        print(
            f"{category:30}: {count}"
        )

    print()

    print("=" * 90)
    print("FIRST 40 REMAINING FAILURES")
    print("=" * 90)

    for failure in (
        classified_failures[:40]
    ):

        print()
        print("-" * 90)

        print(
            "Index      :",
            failure["index"],
        )

        print(
            "DB         :",
            failure["db"],
        )

        print(
            "Question   :",
            failure["question"],
        )

        print(
            "Missing    :",
            repr(
                failure["value"]
            ),
        )

        print(
            "Category   :",
            failure["category"],
        )

        print(
            "Best phrase:",
            repr(
                failure["best_phrase"]
            ),
        )

        print(
            "Similarity :",
            f"{failure['similarity']:.4f}",
        )

        print(
            "DB matches :",
            failure["db_matches"],
        )

        print(
            "SQL        :",
            failure["sql"],
        )

    print()

    print("=" * 90)

    print(
        "✅ POST-NUMERIC REMAINING "
        "FAILURE AUDIT COMPLETE"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
