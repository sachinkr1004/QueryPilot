"""
QueryPilot Phase 7
Fine-tuning leakage-protection policy.

Evaluation examples must never be used for fine-tuning.

Training candidates are excluded when:

1. The (db_id, question) exactly matches a protected
   evaluation example.

2. The normalized SQL exactly matches protected gold SQL
   from the same database.

3. Manual semantic review confirms that a candidate is a
   paraphrase of a protected evaluation task with the same
   SQL intent.

Embedding similarity alone is NOT sufficient for exclusion.
"""

# ============================================================
# MANUALLY VERIFIED SEMANTIC DUPLICATES
# ============================================================

MANUAL_SEMANTIC_EXCLUSIONS = {

    (
        "pets_1",
        "List the maximum weight and type for each type of pet.",
    ),

    (
        "pets_1",
        "What is the first name and gender of the all the students "
        "who have more than one pet?",
    ),

    (
        "car_1",
        "For each continent, list its id, name, and how many "
        "countries it has?",
    ),

    (
        "employee_hire_evaluation",
        "Count the number of employees for each city.",
    ),
}


def normalize_question(question):
    """
    Normalize a question for stable leakage comparisons.
    """

    return " ".join(
        question.strip().lower().split()
    )


MANUAL_SEMANTIC_EXCLUSION_KEYS = {
    (
        db_id,
        normalize_question(question),
    )
    for db_id, question
    in MANUAL_SEMANTIC_EXCLUSIONS
}


def is_manual_semantic_exclusion(
    db_id,
    question,
):
    """
    Return True when the candidate was manually verified
    as semantic leakage.
    """

    key = (
        db_id,
        normalize_question(question),
    )

    return key in MANUAL_SEMANTIC_EXCLUSION_KEYS
