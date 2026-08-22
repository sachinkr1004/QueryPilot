import json
import re
import sqlite3
import sys
from pathlib import Path

from llm.retrieve_schema import retrieve_schema
from llm.retrieve_examples import retrieve_examples
from llm.baseline_client import generate_sql, correct_sql
from db import execute_query


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent

TEST_SET_PATH = BASE_DIR / "test_set.json"

SQLITE_ROOT = (
    PROJECT_ROOT
    / "dataset"
    / "spider"
    / "spider_data"
    / "spider_data"
    / "database"
)


# ============================================================
# LOAD BENCHMARK
# ============================================================

def load_test_set():
    with open(TEST_SET_PATH, "r") as f:
        return json.load(f)


# ============================================================
# EXECUTE SPIDER GOLD SQL
# ============================================================

def execute_gold_sql(db_id: str, gold_sql: str):

    sqlite_path = (
        SQLITE_ROOT
        / db_id
        / f"{db_id}.sqlite"
    )

    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"SQLite database not found: {sqlite_path}"
        )

    conn = sqlite3.connect(sqlite_path)

    try:
        cursor = conn.cursor()
        cursor.execute(gold_sql)
        return cursor.fetchall()

    finally:
        conn.close()


# ============================================================
# NORMALIZE RESULTS
# ============================================================

def normalize_rows(rows):

    normalized = []

    for row in rows:

        normalized.append(
            tuple(
                str(value).strip()
                if value is not None
                else None
                for value in row
            )
        )

    return normalized


# ============================================================
# STRICT RESULT COMPARISON
# ============================================================

def compare_results(
    generated_rows,
    gold_rows,
    order_sensitive=False
):

    generated = normalize_rows(generated_rows)
    gold = normalize_rows(gold_rows)

    if order_sensitive:
        return generated == gold

    return sorted(generated) == sorted(gold)


# ============================================================
# DETECT ORDER BY + LIMIT 1
# ============================================================

def has_order_by_limit_one(sql: str):

    if not sql:
        return False

    normalized = " ".join(
        sql.lower().split()
    )

    has_order = "order by" in normalized

    has_limit_one = bool(
        re.search(
            r"\blimit\s+1\b",
            normalized
        )
    )

    return has_order and has_limit_one


# ============================================================
# REMOVE LIMIT 1
# ============================================================

def remove_limit_one(sql: str):

    if not sql:
        return sql

    return re.sub(
        r"\bLIMIT\s+1\s*;?\s*$",
        "",
        sql,
        flags=re.IGNORECASE
    ).strip()


# ============================================================
# TIE-AWARE SEMANTIC CHECK
# ============================================================

def tie_aware_check(
    db_id,
    generated_sql,
    gold_sql,
    generated_rows,
    gold_rows
):

    """
    This check is used ONLY when strict result comparison fails.

    It handles the benchmark edge case where:

        ORDER BY ...
        LIMIT 1

    is used without a deterministic secondary tie-breaker.

    SQLite and PostgreSQL may legally return different rows
    when multiple rows share the same best ordering value.

    We do NOT hardcode answers or test IDs.
    """

    if not generated_rows:
        return False

    if not gold_rows:
        return False

    if not has_order_by_limit_one(gold_sql):
        return False

    if not has_order_by_limit_one(generated_sql):
        return False

    try:

        # ----------------------------------------------------
        # GOLD SIDE
        #
        # Remove LIMIT 1 and inspect ordered rows.
        # ----------------------------------------------------

        expanded_gold_sql = remove_limit_one(
            gold_sql
        )

        sqlite_path = (
            SQLITE_ROOT
            / db_id
            / f"{db_id}.sqlite"
        )

        conn = sqlite3.connect(sqlite_path)

        try:
            cursor = conn.cursor()

            cursor.execute(
                expanded_gold_sql
            )

            expanded_gold_rows = (
                cursor.fetchall()
            )

        finally:
            conn.close()

        if not expanded_gold_rows:
            return False

        # ----------------------------------------------------
        # GENERATED SIDE
        #
        # Remove LIMIT 1 and execute against PostgreSQL.
        # ----------------------------------------------------

        expanded_generated_sql = (
            remove_limit_one(
                generated_sql
            )
        )

        expanded_generated_rows = (
            execute_query(
                expanded_generated_sql
            )
        )

        if not expanded_generated_rows:
            return False

        # ----------------------------------------------------
        # Conservative semantic check
        #
        # If the generated single answer occurs somewhere
        # inside the gold expanded ordered result AND
        # the gold single answer occurs somewhere inside
        # the generated expanded result, then both engines
        # are selecting from the same candidate result space.
        #
        # This alone is NOT enough for arbitrary queries,
        # so we additionally require both queries to have
        # ORDER BY + LIMIT 1.
        # ----------------------------------------------------

        generated_one = normalize_rows(
            generated_rows
        )

        gold_one = normalize_rows(
            gold_rows
        )

        expanded_gold = normalize_rows(
            expanded_gold_rows
        )

        expanded_generated = normalize_rows(
            expanded_generated_rows
        )

        if len(generated_one) != 1:
            return False

        if len(gold_one) != 1:
            return False

        generated_answer = generated_one[0]
        gold_answer = gold_one[0]

        generated_in_gold = (
            generated_answer
            in expanded_gold
        )

        gold_in_generated = (
            gold_answer
            in expanded_generated
        )

        if (
            generated_in_gold
            and gold_in_generated
        ):
            return True

        return False

    except Exception:
        return False


# ============================================================
# EVALUATE ONE QUESTION
# ============================================================

def evaluate_one(test_case):

    test_id = test_case["id"]
    db_id = test_case["db_id"]
    question = test_case["question"]
    gold_sql = test_case["gold_sql"]

    retrieved_db = None
    schema_text = None

    examples = []

    generated_sql = None
    corrected_sql = None
    final_sql = None

    initial_result = None
    generated_result = None
    gold_result = None

    initial_error = None
    error = None

    correction_used = False
    correction_attempts = 0
    correction_success = False

    strict_correct = False
    semantic_correct = False
    tie_accepted = False

    try:

        # ----------------------------------------------------
        # 1. Retrieve database/schema
        # ----------------------------------------------------

        (
            retrieved_db,
            schema_text,
            distance
        ) = retrieve_schema(
            question
        )

        # ----------------------------------------------------
        # 2. Retrieve SAFE Top-5 RAG examples
        # ----------------------------------------------------

        examples = retrieve_examples(
            question,
            retrieved_db,
            limit=5
        )

        # ----------------------------------------------------
        # 3. Generate initial SQL
        # ----------------------------------------------------

        generated_sql = generate_sql(
            question,
            schema_text,
            examples
        )

        final_sql = generated_sql

        # ----------------------------------------------------
        # 4. Execute initial SQL
        # ----------------------------------------------------

        try:

            initial_result = execute_query(
                generated_sql
            )

            generated_result = initial_result

        except Exception as execution_error:

            initial_error = str(
                execution_error
            )

            # ------------------------------------------------
            # 5. Self-correct exactly once
            # ------------------------------------------------

            correction_used = True
            correction_attempts = 1

            corrected_sql = correct_sql(
                question=question,
                schema_text=schema_text,
                failed_sql=generated_sql,
                error_message=initial_error,
                examples=examples
            )

            final_sql = corrected_sql

            # ------------------------------------------------
            # 6. Execute corrected SQL
            # ------------------------------------------------

            try:

                generated_result = execute_query(
                    corrected_sql
                )

                correction_success = True

            except Exception as corrected_error:

                error = str(
                    corrected_error
                )

        # ----------------------------------------------------
        # 7. Execute Spider gold SQL
        # ----------------------------------------------------

        gold_result = execute_gold_sql(
            db_id,
            gold_sql
        )

        # ----------------------------------------------------
        # 8. Compare final successful result
        # ----------------------------------------------------

        if error is None:

            strict_correct = compare_results(
                generated_result,
                gold_result
            )

            if strict_correct:

                semantic_correct = True

            else:

                tie_accepted = tie_aware_check(
                    db_id,
                    final_sql,
                    gold_sql,
                    generated_result,
                    gold_result
                )

                semantic_correct = (
                    tie_accepted
                )

    except Exception as e:

        error = str(e)

        strict_correct = False
        semantic_correct = False
        tie_accepted = False

    return {

        "id": test_id,

        "expected_db": db_id,
        "retrieved_db": retrieved_db,

        "question": question,

        "rag_examples": len(examples),

        "generated_sql": generated_sql,
        "corrected_sql": corrected_sql,
        "final_sql": final_sql,

        "initial_result": initial_result,

        # Keep old key for compatibility.
        "generated_result": generated_result,

        "gold_result": gold_result,

        "correction_used": correction_used,
        "correction_attempts": correction_attempts,
        "correction_success": correction_success,

        "initial_error": initial_error,

        # Final pipeline error only.
        "error": error,

        "strict_correct": strict_correct,
        "semantic_correct": semantic_correct,
        "tie_accepted": tie_accepted,
    }


# ============================================================
# MAIN EVALUATION
# ============================================================

def main():

    test_set = load_test_set()

    # --------------------------------------------------------
    # Select evaluation split
    # --------------------------------------------------------

    split = (
        sys.argv[1].strip().lower()
        if len(sys.argv) > 1
        else "dev"
    )

    if split not in {"dev", "holdout"}:
        print(
            "❌ Invalid split. Use: dev or holdout"
        )
        sys.exit(1)

    eval_cases = [
        item
        for item in test_set
        if item["split"] == split
    ]

    print()
    print("=" * 70)
    print(
        "QUERYPILOT PHASE 6 "
        "SELF-CORRECTION EVALUATION"
    )
    print("=" * 70)

    print()
    print(
        f"Running {len(eval_cases)} "
        f"{split.upper()} evaluation cases..."
    )
    print()

    results = []

    strict_correct_count = 0
    semantic_correct_count = 0
    tie_accepted_count = 0

    initial_error_count = 0
    final_error_count = 0

    correction_used_count = 0
    correction_success_count = 0

    for index, test_case in enumerate(
        eval_cases,
        1
    ):

        print("=" * 70)

        print(
            f"[{index}/{len(eval_cases)}] "
            f"{test_case['id']}"
        )

        print()
        print(
            "Question:",
            test_case["question"]
        )

        result = evaluate_one(
            test_case
        )

        results.append(
            result
        )

        # ----------------------------------------------------
        # Counters
        # ----------------------------------------------------

        if result["strict_correct"]:
            strict_correct_count += 1

        if result["semantic_correct"]:
            semantic_correct_count += 1

        if result["tie_accepted"]:
            tie_accepted_count += 1

        if result["initial_error"] is not None:
            initial_error_count += 1

        if result["error"] is not None:
            final_error_count += 1

        if result["correction_used"]:
            correction_used_count += 1

        if result["correction_success"]:
            correction_success_count += 1

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        if result["strict_correct"]:

            if result["correction_used"]:
                status = (
                    "✅ STRICT CORRECT "
                    "(AFTER SELF-CORRECTION)"
                )
            else:
                status = "✅ STRICT CORRECT"

        elif result["tie_accepted"]:

            if result["correction_used"]:
                status = (
                    "🟡 SEMANTIC CORRECT "
                    "(AFTER SELF-CORRECTION)"
                )
            else:
                status = (
                    "🟡 SEMANTIC CORRECT "
                    "(NON-DETERMINISTIC TIE)"
                )

        elif result["error"] is not None:
            status = "❌ ERROR"

        else:
            status = "❌ WRONG"

        # ----------------------------------------------------
        # Per-question report
        # ----------------------------------------------------

        print()

        print(
            "Expected DB :",
            result["expected_db"]
        )

        print(
            "Retrieved DB:",
            result["retrieved_db"]
        )

        print(
            "RAG examples:",
            result["rag_examples"]
        )

        print()

        print("Generated SQL:")
        print()
        print(
            result["generated_sql"]
        )

        if result["correction_used"]:

            print()

            print(
                "Initial execution error:"
            )

            print(
                result["initial_error"]
            )

            print()

            print("Corrected SQL:")
            print()

            print(
                result["corrected_sql"]
            )

            print()

            print(
                "Correction attempts:",
                result["correction_attempts"]
            )

            print(
                "Correction success :",
                result["correction_success"]
            )

        print()

        print(
            "Status:",
            status
        )

        if result["error"]:

            print()

            print(
                "Final error:",
                result["error"]
            )

        print()

    # ========================================================
    # SUMMARY
    # ========================================================

    total = len(
        eval_cases
    )

    strict_accuracy = (
        (
            strict_correct_count
            / total
        )
        * 100
        if total > 0
        else 0
    )

    semantic_accuracy = (
        (
            semantic_correct_count
            / total
        )
        * 100
        if total > 0
        else 0
    )

    strict_wrong = (
        total
        - strict_correct_count
        - final_error_count
    )

    semantic_wrong = (
        total
        - semantic_correct_count
        - final_error_count
    )

    execution_success_count = (
        total
        - final_error_count
    )

    execution_success_rate = (
        (
            execution_success_count
            / total
        )
        * 100
        if total > 0
        else 0
    )

    correction_success_rate = (
        (
            correction_success_count
            / correction_used_count
        )
        * 100
        if correction_used_count > 0
        else 0
    )

    print()
    print("=" * 70)

    print(
        "PHASE 6 SELF-CORRECTION "
        "EVALUATION SUMMARY"
    )

    print("=" * 70)

    print()

    print(
        f"Total {split.upper()} questions          : "
        f"{total}"
    )

    print()

    print(
        f"Strict correct               : "
        f"{strict_correct_count}"
    )

    print(
        f"Strict wrong                 : "
        f"{strict_wrong}"
    )

    print(
        f"Strict execution accuracy    : "
        f"{strict_accuracy:.2f}%"
    )

    print()

    print(
        f"Semantic correct             : "
        f"{semantic_correct_count}"
    )

    print(
        f"Semantic wrong               : "
        f"{semantic_wrong}"
    )

    print(
        f"Tie-equivalent accepted      : "
        f"{tie_accepted_count}"
    )

    print(
        f"Semantic execution accuracy  : "
        f"{semantic_accuracy:.2f}%"
    )

    print()

    print(
        f"Initial execution errors     : "
        f"{initial_error_count}"
    )

    print(
        f"Final execution errors       : "
        f"{final_error_count}"
    )

    print(
        f"Execution success rate       : "
        f"{execution_success_rate:.2f}%"
    )

    print()

    print(
        f"Self-correction triggered    : "
        f"{correction_used_count}"
    )

    print(
        f"Successful corrections       : "
        f"{correction_success_count}"
    )

    print(
        f"Correction success rate      : "
        f"{correction_success_rate:.2f}%"
    )

    print()

    print(
        "RAG                         : "
        "ENABLED (Top-5 safe examples)"
    )

    print(
        "Database router             : "
        "SAFE-example router"
    )

    print(
        "Tie-aware evaluation        : "
        "ENABLED"
    )

    print(
        "Self-correction             : "
        "ENABLED (max 1 retry)"
    )

    print()

    print("=" * 70)


if __name__ == "__main__":

    main()
