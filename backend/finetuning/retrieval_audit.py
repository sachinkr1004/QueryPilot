import json

from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp

from finetuning.full_split import (
    FULL_SCALE_HOLDOUT_DATABASES,
)

from finetuning.schema_retriever import (
    retrieve_relevant_tables,
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
# LOAD FROZEN TRAINING EXAMPLES
# ============================================================

def load_frozen_training_examples():
    with TRAIN_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        examples = json.load(file)

    return [
        item
        for item in examples
        if item["db_id"]
        not in FULL_SCALE_HOLDOUT_DATABASES
    ]


# ============================================================
# EXTRACT GOLD TABLES FROM SPIDER SQL
# ============================================================

def extract_gold_tables(sql: str):
    """
    Parse Spider SQLite SQL and return the set of referenced
    table names.
    """

    tree = sqlglot.parse_one(
        sql,
        read="sqlite",
    )

    return {
        table.name.lower()
        for table in tree.find_all(
            exp.Table
        )
    }


# ============================================================
# RETRIEVAL COVERAGE
# ============================================================

def retrieved_table_names(
    question: str,
    database_name: str,
    top_k: int,
):
    results = retrieve_relevant_tables(
        question=question,
        database_name=database_name,
        top_k=top_k,
    )

    return {
        item["table_name"].lower()
        for item in results
    }


# ============================================================
# MAIN AUDIT
# ============================================================

def main():
    examples = load_frozen_training_examples()

    k_values = [
        1,
        2,
        3,
        4,
        5,
        7,
    ]

    full_coverage = Counter()

    total_gold_tables = Counter()

    retrieved_gold_tables = Counter()

    parse_failures = []

    print("=" * 90)
    print("PHASE 7.2I.2 - RETRIEVAL RECALL AUDIT")
    print("=" * 90)

    print()
    print(
        "Frozen training examples:",
        len(examples),
    )

    for index, item in enumerate(
        examples,
        1,
    ):
        question = item["question"]
        database_name = item["db_id"]
        sql = item["query"]

        try:
            gold_tables = extract_gold_tables(
                sql
            )

        except Exception as exc:
            parse_failures.append(
                {
                    "index": index,
                    "db": database_name,
                    "question": question,
                    "sql": sql,
                    "error": str(exc),
                }
            )
            continue

        for k in k_values:
            retrieved = retrieved_table_names(
                question=question,
                database_name=database_name,
                top_k=k,
            )

            total_gold_tables[k] += len(
                gold_tables
            )

            retrieved_gold_tables[k] += len(
                gold_tables
                & retrieved
            )

            if gold_tables.issubset(
                retrieved
            ):
                full_coverage[k] += 1

        if index % 500 == 0:
            print(
                f"Processed {index}/"
                f"{len(examples)}..."
            )

    valid_examples = (
        len(examples)
        - len(parse_failures)
    )

    print()
    print("=" * 90)
    print("RESULT")
    print("=" * 90)

    print()
    print(
        "Valid examples :",
        valid_examples,
    )

    print(
        "Parse failures :",
        len(parse_failures),
    )

    print()
    print(
        "TOP-K GOLD TABLE COVERAGE:"
    )

    print()

    for k in k_values:
        full_accuracy = (
            full_coverage[k]
            / valid_examples
            * 100
            if valid_examples
            else 0
        )

        table_recall = (
            retrieved_gold_tables[k]
            / total_gold_tables[k]
            * 100
            if total_gold_tables[k]
            else 0
        )

        print(
            f"Top-{k:<2} "
            f"Full coverage: "
            f"{full_coverage[k]:4}/"
            f"{valid_examples} "
            f"({full_accuracy:6.2f}%) "
            f"| Gold-table recall: "
            f"{table_recall:6.2f}%"
        )

    if parse_failures:
        print()
        print("=" * 90)
        print("FIRST 10 PARSE FAILURES")
        print("=" * 90)

        for failure in (
            parse_failures[:10]
        ):
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
                "Error   :",
                failure["error"],
            )

    print()
    print("=" * 90)
    print(
        "✅ RETRIEVAL RECALL AUDIT COMPLETE"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
