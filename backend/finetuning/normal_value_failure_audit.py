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
)
from finetuning.value_failure_classifier import (
    classify_missing_value,
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
    """
    Real LIKE patterns in the current clean corpus contain %.

    Values such as MK_MAN and PU_MAN contain underscores but
    are ordinary equality values, so they stay in the normal
    value bucket.
    """
    return "%" in str(value)


# ============================================================
# MAIN
# ============================================================

def main():
    examples = load_clean_examples()

    failure_examples = 0
    missing_value_count = 0

    category_counts = Counter()
    classified_failures = []

    print("=" * 90)
    print(
        "PHASE 7.2J.5P - "
        "NORMAL VALUE FAILURE CLASSIFICATION AUDIT"
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

        # ----------------------------------------------------
        # Keep LIKE patterns separate.
        # ----------------------------------------------------

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
        # Value retrieval
        # ----------------------------------------------------

        value_results = retrieve_relevant_values(
            question=item["question"],
            database_name=item["db_id"],
            table_names=table_names,
        )

        retrieved_values = {
            normalize_value_match_text(value)
            for result in value_results
            for value in result["values"]
            if normalize_value_match_text(value)
        }

        missing = (
            normal_values
            - retrieved_values
        )

        if not missing:
            continue

        failure_examples += 1
        missing_value_count += len(missing)

        for value in sorted(missing):
            classification = (
                classify_missing_value(
                    db_id=item["db_id"],
                    question=item["question"],
                    value=value,
                )
            )

            category = classification[
                "category"
            ]

            category_counts[category] += 1

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
        "Failure examples      :",
        failure_examples,
    )
    print(
        "Missing normal values :",
        missing_value_count,
    )

    print()
    print("=" * 90)
    print("CATEGORY COUNTS")
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
    print("FIRST 40 CLASSIFIED FAILURES")
    print("=" * 90)

    for failure in classified_failures[:40]:
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
            repr(failure["value"]),
        )
        print(
            "Category   :",
            failure["category"],
        )
        print(
            "Best phrase:",
            repr(failure["best_phrase"]),
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
        "✅ NORMAL VALUE FAILURE "
        "CLASSIFICATION AUDIT COMPLETE"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
