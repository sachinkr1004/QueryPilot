import json
import re

from collections import Counter
from pathlib import Path

from finetuning.leakage_policy import (
    is_manual_semantic_exclusion,
    normalize_question,
)

from llm.retrieve_schema import (
    get_schema_for_database,
)

from llm.retrieve_examples import (
    retrieve_examples,
)

from llm.baseline_client import (
    format_examples,
)

from finetuning.schema_retriever import (
    retrieve_relevant_tables_with_fk_hops,
)

from finetuning.value_retriever import (
    retrieve_relevant_values,
    format_value_context,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

SPIDER_DEV_PATH = (
    PROJECT_ROOT
    / "dataset"
    / "spider"
    / "evaluation_examples"
    / "examples"
    / "dev.json"
)

EVAL_SET_PATH = (
    BACKEND_DIR
    / "eval"
    / "test_set.json"
)


# ============================================================
# TARGET DATABASES
# ============================================================

TARGET_DATABASES = {
    "concert_singer",
    "pets_1",
    "car_1",
    "employee_hire_evaluation",
    "world_1",
}


# ============================================================
# HELPERS
# ============================================================

def load_json(path: Path):
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def normalize_sql(sql: str):
    sql = sql.lower()
    sql = sql.replace('"', "")
    sql = sql.replace("`", "")
    sql = re.sub(
        r"\s+",
        " ",
        sql,
    )
    sql = re.sub(
        r"\s*;\s*$",
        "",
        sql,
    )

    return sql.strip()


# ============================================================
# LOAD TARGET SPIDER EXAMPLES
# ============================================================

def load_target_examples():
    spider_dev = load_json(
        SPIDER_DEV_PATH
    )

    return [
        item
        for item in spider_dev
        if item["db_id"] in TARGET_DATABASES
    ]


# ============================================================
# BUILD PROTECTED EVALUATION KEYS
# ============================================================

def build_protected_keys():
    evaluation = load_json(
        EVAL_SET_PATH
    )

    protected_questions = {
        (
            item["db_id"],
            normalize_question(
                item["question"]
            ),
        )
        for item in evaluation
    }

    protected_sql = {
        (
            item["db_id"],
            normalize_sql(
                item["gold_sql"]
            ),
        )
        for item in evaluation
    }

    return (
        protected_questions,
        protected_sql,
    )


# ============================================================
# APPLY LEAKAGE FILTERS
# ============================================================

def filter_training_candidates(
    target_examples,
):
    (
        protected_questions,
        protected_sql,
    ) = build_protected_keys()

    clean_examples = []

    stats = {
        "exact_question": 0,
        "exact_sql": 0,
        "semantic": 0,
    }

    for item in target_examples:

        question_key = (
            item["db_id"],
            normalize_question(
                item["question"]
            ),
        )

        sql_key = (
            item["db_id"],
            normalize_sql(
                item["query"]
            ),
        )

        if question_key in protected_questions:
            stats["exact_question"] += 1
            continue

        if sql_key in protected_sql:
            stats["exact_sql"] += 1
            continue

        if is_manual_semantic_exclusion(
            item["db_id"],
            item["question"],
        ):
            stats["semantic"] += 1
            continue

        clean_examples.append(
            item
        )

    return (
        clean_examples,
        stats,
    )


# ============================================================
# BUILD PRODUCTION-STYLE RETRIEVAL CONTEXT
# ============================================================

def build_retrieval_context(
    question: str,
    database_name: str,
    gold_sql: str,
):
    """
    Build the same retrieval context used by QueryPilot
    during SQL generation.

    Training uses the known gold database_name so dataset
    construction cannot be corrupted by a routing mistake.
    """

    schema_text = get_schema_for_database(
        database_name
    )

    if schema_text is None:
        raise ValueError(
            "Schema not found for database: "
            f"{database_name}"
        )

    # --------------------------------------------------------
    # Production-style table + value retrieval
    # --------------------------------------------------------

    table_results = (
        retrieve_relevant_tables_with_fk_hops(
            question=question,
            database_name=database_name,
            top_k=7,
            fk_hops=2,
        )
    )

    table_names = [
        item["table_name"]
        for item in table_results
    ]

    value_matches = retrieve_relevant_values(
        question=question,
        database_name=database_name,
        table_names=table_names,
    )

    value_text = format_value_context(
        value_matches
    )

    # Retrieve extra candidates because the current
    # training question may retrieve itself.
    retrieved_examples = retrieve_examples(
        question=question,
        database_name=database_name,
        limit=10,
    )

    normalized_current_question = (
        normalize_question(question)
    )

    normalized_gold_sql = normalize_sql(
        gold_sql
    )

    examples = [
        example
        for example in retrieved_examples
        if (
            normalize_question(
                example["question"]
            ) != normalized_current_question
            and normalize_sql(
                example["sql"]
            ) != normalized_gold_sql
        )
    ][:5]

    if len(examples) < 5:
        raise ValueError(
            "Could not retrieve 5 leakage-safe RAG examples "
            f"for database={database_name}, "
            f"question={question!r}"
        )

    example_text = format_examples(
        examples
    )

    input_context = f"""DATABASE SCHEMA:

{schema_text}


RELEVANT DATABASE VALUES:

{value_text}


SAFE RAG EXAMPLES:

{example_text}


USER QUESTION:

{question}
"""

    return {
        "database_name": database_name,
        "schema_text": schema_text,
        "table_names": table_names,
        "value_matches": value_matches,
        "value_text": value_text,
        "examples": examples,
        "input_context": input_context.strip(),
    }


# ============================================================
# BUILD LORA TRAINING RECORD
# ============================================================

def build_training_record(
    item,
):
    """
    Build one leakage-safe QueryPilot fine-tuning example.

    Input:
        Spider training example.

    Output:
        {
            "database_name": ...,
            "instruction": ...,
            "input": ...,
            "output": ...
        }

    The output SQL is converted into validated PostgreSQL
    syntax using the Phase 7.1D converter.
    """

    from finetuning.sql_converter import (
        convert_spider_sql,
    )

    database_name = item["db_id"]
    question = item["question"]
    spider_sql = item["query"]

    postgres_sql = convert_spider_sql(
        sql=spider_sql,
        database_name=database_name,
    )

    context = build_retrieval_context(
        question=question,
        database_name=database_name,
        gold_sql=spider_sql,
    )

    instruction = (
        "Generate the correct PostgreSQL SQL query "
        "for the user's question using only the "
        "provided database schema, relevant database "
        "values, and safe RAG examples. "
        "Return only one executable PostgreSQL query."
    )

    return {
        "database_name": database_name,
        "instruction": instruction,
        "input": context["input_context"],
        "output": postgres_sql,
    }


# ============================================================
# BUILD COMPLETE TRAINING DATASET
# ============================================================

def build_training_dataset():
    """
    Build all leakage-safe fine-tuning records.

    Expected final count: 298.
    """

    target_examples = load_target_examples()

    clean_examples, stats = (
        filter_training_candidates(
            target_examples
        )
    )

    records = []

    for item in clean_examples:

        record = build_training_record(
            item
        )

        records.append(
            record
        )

    return records, stats



# ============================================================
# MAIN
# ============================================================

def main():
    target_examples = load_target_examples()

    (
        clean_examples,
        stats,
    ) = filter_training_candidates(
        target_examples
    )

    counts = Counter(
        item["db_id"]
        for item in clean_examples
    )

    print("=" * 75)
    print(
        "PHASE 7.1B - "
        "LEAKAGE-SAFE TRAINING CANDIDATES"
    )
    print("=" * 75)

    print()
    print(
        "Original target examples :",
        len(target_examples),
    )

    print()
    print(
        "Exact question excluded  :",
        stats["exact_question"],
    )

    print(
        "Exact SQL excluded       :",
        stats["exact_sql"],
    )

    print(
        "Semantic excluded        :",
        stats["semantic"],
    )

    total_excluded = (
        stats["exact_question"]
        + stats["exact_sql"]
        + stats["semantic"]
    )

    print()
    print(
        "Total excluded           :",
        total_excluded,
    )

    print()
    print(
        "Clean training candidates:",
        len(clean_examples),
    )

    print()
    print("Clean examples per database:")
    print()

    for database_name in sorted(
        TARGET_DATABASES
    ):
        print(
            f"  {database_name:30} "
            f"{counts.get(database_name, 0)}"
        )

    print()

    expected = 298

    if len(clean_examples) == expected:
        print(
            "✅ EXPECTED CLEAN COUNT CONFIRMED:",
            expected,
        )
    else:
        print(
            "❌ CLEAN COUNT MISMATCH:",
            len(clean_examples),
            "expected",
            expected,
        )

    print("=" * 75)


if __name__ == "__main__":
    main()
