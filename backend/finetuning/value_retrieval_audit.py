import json
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
    normalize_text,
    normalize_value_match_text,
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
# MAIN
# ============================================================

def main():

    examples = load_clean_examples()

    examples_with_strings = 0

    total_gold_strings = 0

    recovered_gold_strings = 0

    full_string_coverage = 0

    failures = []


    print("=" * 90)
    print("PHASE 7.2J.2C - FULL VALUE RETRIEVAL AUDIT")
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

        gold_strings = {
            normalize_value_match_text(value)
            for value in literals["strings"]
            if normalize_value_match_text(value)
        }

        if not gold_strings:
            continue


        examples_with_strings += 1

        total_gold_strings += len(
            gold_strings
        )


        # ----------------------------------------------------
        # Retrieve schema tables first
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
        # Retrieve matching DB values
        # ----------------------------------------------------

        value_results = (
            retrieve_relevant_values(
                question=item["question"],
                database_name=item["db_id"],
                table_names=table_names,
            )
        )


        retrieved_values = set()

        for result in value_results:

            for value in result["values"]:

                normalized = (
                    normalize_value_match_text(
                        value
                    )
                )

                if normalized:
                    retrieved_values.add(
                        normalized
                    )


        recovered = (
            gold_strings
            & retrieved_values
        )

        missing = (
            gold_strings
            - retrieved_values
        )


        recovered_gold_strings += len(
            recovered
        )


        if not missing:

            full_string_coverage += 1

        else:

            failures.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "sql": item["query"],
                    "gold_strings": sorted(
                        gold_strings
                    ),
                    "retrieved": sorted(
                        retrieved_values
                    ),
                    "missing": sorted(
                        missing
                    ),
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

    string_recall = (
        recovered_gold_strings
        / total_gold_strings
        * 100
        if total_gold_strings
        else 0
    )

    full_coverage_percent = (
        full_string_coverage
        / examples_with_strings
        * 100
        if examples_with_strings
        else 0
    )


    print()
    print("=" * 90)
    print("RESULT")
    print("=" * 90)

    print()

    print(
        "Examples with strings :",
        examples_with_strings,
    )

    print(
        "Gold string values    :",
        total_gold_strings,
    )

    print(
        "Recovered strings     :",
        recovered_gold_strings,
    )

    print(
        "String-value recall   :",
        f"{string_recall:.2f}%",
    )

    print()

    print(
        "Full example coverage :",
        f"{full_string_coverage}/"
        f"{examples_with_strings}"
    )

    print(
        "Coverage percentage   :",
        f"{full_coverage_percent:.2f}%",
    )

    print(
        "Failures              :",
        len(failures),
    )


    if failures:

        print()
        print("=" * 90)
        print("FIRST 20 VALUE FAILURES")
        print("=" * 90)

        for failure in failures[:20]:

            print()
            print("-" * 90)

            print(
                "Index   :",
                failure["index"],
            )

            print(
                "DB      :",
                failure["db"],
            )

            print(
                "Question:",
                failure["question"],
            )

            print(
                "SQL     :",
                failure["sql"],
            )

            print(
                "Gold    :",
                failure["gold_strings"],
            )

            print(
                "Retrieved:",
                failure["retrieved"],
            )

            print(
                "Missing :",
                failure["missing"],
            )


    print()
    print("=" * 90)
    print(
        "✅ FULL VALUE RETRIEVAL AUDIT COMPLETE"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
