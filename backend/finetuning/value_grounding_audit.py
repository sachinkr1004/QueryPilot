import json
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp

from finetuning.full_split import (
    FULL_SCALE_HOLDOUT_DATABASES,
)

from finetuning.full_scale_exclusions import (
    is_schema_inconsistent_exclusion,
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
# LOAD CLEAN TRAINING EXAMPLES
# ============================================================

def load_clean_training_examples():

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
# EXTRACT SQL LITERALS
# ============================================================

def extract_sql_literals(
    sql: str,
):
    """
    Extract literal values from Spider SQL.

    Returns:
        {
            "strings": [...],
            "numbers": [...],
            "total": ...
        }
    """

    tree = sqlglot.parse_one(
        sql,
        read="sqlite",
    )

    strings = []
    numbers = []

    # --------------------------------------------------------
    # Normal SQL literal nodes
    # --------------------------------------------------------

    for literal in tree.find_all(
        exp.Literal
    ):

        if literal.is_string:

            strings.append(
                str(literal.this)
            )

        else:

            numbers.append(
                str(literal.this)
            )

    # --------------------------------------------------------
    # SQLite double-quoted values
    #
    # Example:
    #
    #   WHERE Name = "Brazil"
    #
    # SQLGlot can represent "Brazil" as a quoted Column.
    # --------------------------------------------------------

    for column in tree.find_all(
        exp.Column
    ):

        identifier = column.this

        quoted = (
            getattr(
                identifier,
                "args",
                {},
            ).get(
                "quoted"
            )
        )

        if (
            quoted
            and not column.table
        ):

            strings.append(
                column.name
            )

    return {
        "strings": strings,
        "numbers": numbers,
        "total": (
            len(strings)
            + len(numbers)
        ),
    }


# ============================================================
# MAIN AUDIT
# ============================================================

def main():

    examples = load_clean_training_examples()

    examples_with_values = 0

    examples_without_values = 0

    total_string_literals = 0

    total_numeric_literals = 0

    parse_failures = []

    db_value_counts = Counter()

    string_examples = []

    numeric_examples = []

    mixed_examples = []


    print("=" * 90)
    print("PHASE 7.2J.1 - VALUE GROUNDING AUDIT")
    print("=" * 90)

    print()
    print(
        "Clean training examples:",
        len(examples),
    )


    for index, item in enumerate(
        examples,
        1,
    ):

        try:

            literals = extract_sql_literals(
                item["query"]
            )

        except Exception as exc:

            parse_failures.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "sql": item["query"],
                    "error": str(exc),
                }
            )

            continue


        strings = literals[
            "strings"
        ]

        numbers = literals[
            "numbers"
        ]


        total_string_literals += len(
            strings
        )

        total_numeric_literals += len(
            numbers
        )


        if literals["total"] > 0:

            examples_with_values += 1

            db_value_counts[
                item["db_id"]
            ] += 1

        else:

            examples_without_values += 1


        if (
            strings
            and len(string_examples) < 10
        ):

            string_examples.append(
                (
                    item["db_id"],
                    item["question"],
                    item["query"],
                    strings,
                )
            )


        if (
            numbers
            and len(numeric_examples) < 10
        ):

            numeric_examples.append(
                (
                    item["db_id"],
                    item["question"],
                    item["query"],
                    numbers,
                )
            )


        if (
            strings
            and numbers
            and len(mixed_examples) < 10
        ):

            mixed_examples.append(
                (
                    item["db_id"],
                    item["question"],
                    item["query"],
                    strings,
                    numbers,
                )
            )


    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)

    print()

    print(
        "Valid examples        :",
        len(examples)
        - len(parse_failures),
    )

    print(
        "Parse failures        :",
        len(parse_failures),
    )

    print()

    print(
        "Examples with values  :",
        examples_with_values,
    )

    print(
        "Examples without      :",
        examples_without_values,
    )

    print()

    print(
        "String literals       :",
        total_string_literals,
    )

    print(
        "Numeric literals      :",
        total_numeric_literals,
    )

    print()

    if examples:

        percentage = (
            examples_with_values
            / len(examples)
            * 100
        )

        print(
            "Examples needing some "
            "value grounding:",
            f"{percentage:.2f}%",
        )


    print()
    print("=" * 90)
    print("TOP DATABASES WITH VALUE-CONTAINING QUERIES")
    print("=" * 90)
    print()

    for db_id, count in (
        db_value_counts.most_common(20)
    ):

        print(
            f"  {db_id:40} "
            f"{count:4}"
        )


    print()
    print("=" * 90)
    print("STRING LITERAL EXAMPLES")
    print("=" * 90)

    for (
        db_id,
        question,
        sql,
        values,
    ) in string_examples:

        print()
        print("-" * 90)
        print("DB      :", db_id)
        print("Question:", question)
        print("SQL     :", sql)
        print("Strings :", values)


    print()
    print("=" * 90)
    print("NUMERIC LITERAL EXAMPLES")
    print("=" * 90)

    for (
        db_id,
        question,
        sql,
        values,
    ) in numeric_examples:

        print()
        print("-" * 90)
        print("DB      :", db_id)
        print("Question:", question)
        print("SQL     :", sql)
        print("Numbers :", values)


    if mixed_examples:

        print()
        print("=" * 90)
        print("MIXED STRING + NUMERIC EXAMPLES")
        print("=" * 90)

        for (
            db_id,
            question,
            sql,
            strings,
            numbers,
        ) in mixed_examples:

            print()
            print("-" * 90)
            print("DB      :", db_id)
            print("Question:", question)
            print("SQL     :", sql)
            print("Strings :", strings)
            print("Numbers :", numbers)


    if parse_failures:

        print()
        print("=" * 90)
        print("PARSE FAILURES")
        print("=" * 90)

        for failure in (
            parse_failures[:10]
        ):

            print()
            print("-" * 90)
            print(
                "Index:",
                failure["index"],
            )
            print(
                "DB:",
                failure["db"],
            )
            print(
                "Question:",
                failure["question"],
            )
            print(
                "SQL:",
                failure["sql"],
            )
            print(
                "Error:",
                failure["error"],
            )


    print()
    print("=" * 90)

    if (
        len(examples) == 6359
        and len(parse_failures) == 0
    ):

        print(
            "✅ VALUE GROUNDING AUDIT COMPLETE"
        )

    else:

        print(
            "❌ VALUE GROUNDING AUDIT "
            "NEEDS ATTENTION"
        )

    print("=" * 90)


if __name__ == "__main__":
    main()
