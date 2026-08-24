import difflib
import re
import sqlite3

from finetuning.spider_context import (
    build_database_metadata,
    get_sqlite_database_path,
)
from finetuning.value_retriever import (
    normalize_value_match_text,
)


# ============================================================
# HELPERS
# ============================================================

def normalize(value):
    return normalize_value_match_text(value)


def best_question_similarity(
    value,
    question,
):
    """
    Find the phrase in the question most similar to the
    missing database/gold value.
    """

    target = normalize(value)
    question_norm = normalize(question)

    if not target or not question_norm:
        return "", 0.0

    target_words = target.split()
    question_words = question_norm.split()

    target_len = len(target_words)

    min_size = max(
        1,
        target_len - 1,
    )
    max_size = min(
        len(question_words),
        target_len + 1,
    )

    best_phrase = ""
    best_score = 0.0

    for size in range(
        min_size,
        max_size + 1,
    ):
        for start in range(
            0,
            len(question_words) - size + 1,
        ):
            phrase = " ".join(
                question_words[
                    start:start + size
                ]
            )

            score = difflib.SequenceMatcher(
                None,
                target,
                phrase,
            ).ratio()

            if score > best_score:
                best_score = score
                best_phrase = phrase

    return (
        best_phrase,
        best_score,
    )


def find_value_in_database(
    db_id,
    target,
):
    """
    Search all text columns in the database for the target.

    This is diagnostic only. It is intentionally broader than
    the production value retriever.
    """

    metadata = build_database_metadata(
        db_id
    )

    target_norm = normalize(
        target
    )

    matches = []

    path = get_sqlite_database_path(
        db_id
    )

    conn = sqlite3.connect(
        path
    )

    try:
        cursor = conn.cursor()

        for table_name, table_info in (
            metadata["tables"].items()
        ):
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

                query = (
                    f'SELECT DISTINCT '
                    f'"{column_name}" '
                    f'FROM "{table_name}" '
                    f'WHERE "{column_name}" '
                    f'IS NOT NULL'
                )

                try:
                    cursor.execute(
                        query
                    )
                except sqlite3.Error:
                    continue

                for row in cursor.fetchall():
                    db_value = row[0]

                    if (
                        normalize(db_value)
                        == target_norm
                    ):
                        matches.append(
                            (
                                table_name,
                                column_name,
                                db_value,
                            )
                        )

        cursor.close()

    finally:
        conn.close()

    return matches


def classify_missing_value(
    db_id,
    question,
    value,
):
    """
    Conservative diagnostic classification.

    Categories are evidence-based rather than attempts to
    automatically repair every failure.
    """

    db_matches = find_value_in_database(
        db_id,
        value,
    )

    phrase, similarity = (
        best_question_similarity(
            value,
            question,
        )
    )

    if db_matches:
        if similarity >= 0.90:
            category = "FUZZY_CANDIDATE"

        elif similarity >= 0.75:
            category = "POSSIBLE_FUZZY"

        else:
            category = "IMPLICIT_OR_SEMANTIC"

    else:
        if similarity >= 0.90:
            category = "GOLD_DB_MISMATCH_OR_TYPO"

        else:
            category = "VALUE_NOT_IN_DATABASE"

    return {
        "value": value,
        "category": category,
        "db_matches": db_matches,
        "best_phrase": phrase,
        "similarity": similarity,
    }


# ============================================================
# MANUAL DIAGNOSTIC
# ============================================================

if __name__ == "__main__":

    tests = [
        (
            "store_1",
            "How many albums has Billy Cobam released?",
            "billy cobham",
        ),
        (
            "store_1",
            (
                "What is the name of the album that has "
                "the track Ball to the Wall?"
            ),
            "balls to the wall",
        ),
        (
            "medicine_enzyme_interaction",
            (
                "What is the id and name of the enzyme "
                "with most number of medicines that can "
                "interact as 'activator'?"
            ),
            "activitor",
        ),
        (
            "coffee_shop",
            (
                "Give me the names of members whose "
                "address is in Harford or Waterbury."
            ),
            "harford",
        ),
        (
            "department_management",
            (
                "What are the distinct ages of the "
                "heads who are acting?"
            ),
            "yes",
        ),
    ]

    print("=" * 90)
    print(
        "PHASE 7.2J.2X - "
        "VALUE FAILURE CLASSIFIER"
    )
    print("=" * 90)

    for db_id, question, value in tests:

        result = classify_missing_value(
            db_id,
            question,
            value,
        )

        print()
        print("-" * 90)
        print("Database   :", db_id)
        print("Question   :", question)
        print("Gold value :", value)
        print(
            "Category   :",
            result["category"],
        )
        print(
            "Best phrase:",
            result["best_phrase"],
        )
        print(
            "Similarity :",
            f"{result['similarity']:.4f}",
        )
        print(
            "DB matches :",
            result["db_matches"],
        )

    print()
    print("=" * 90)
    print(
        "✅ VALUE FAILURE CLASSIFIER TEST COMPLETE"
    )
    print("=" * 90)
