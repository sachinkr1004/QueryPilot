"""
QueryPilot Phase 7.2

Full-scale training exclusions.

These examples are excluded only when they are proven
unresolvable against the supplied Spider schema/database.
"""


# ============================================================
# SCHEMA-INCONSISTENT EXAMPLES
# ============================================================

SCHEMA_INCONSISTENT_EXCLUSIONS = {
    (
        "assets_maintenance",
        (
            "What is the description of the type of the "
            "company who concluded its contracts most recently?"
        ),
    ),
}


def normalize_question(question: str):
    return " ".join(
        question.strip().lower().split()
    )


SCHEMA_INCONSISTENT_KEYS = {
    (
        db_id,
        normalize_question(question),
    )
    for db_id, question
    in SCHEMA_INCONSISTENT_EXCLUSIONS
}


def is_schema_inconsistent_exclusion(
    db_id: str,
    question: str,
):
    key = (
        db_id,
        normalize_question(question),
    )

    return (
        key
        in SCHEMA_INCONSISTENT_KEYS
    )
