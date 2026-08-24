import json
import re

from pathlib import Path
from collections import Counter

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

    return "%" in str(value)


def contains_phrase(question, phrase):

    question_norm = normalize_value_match_text(
        question
    )

    phrase_norm = normalize_value_match_text(
        phrase
    )

    if not phrase_norm:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(phrase_norm)
        + r"(?!\w)"
    )

    return bool(
        re.search(
            pattern,
            question_norm,
            flags=re.IGNORECASE,
        )
    )


# ============================================================
# SAFE BOOLEAN / CATEGORICAL SEMANTIC RULES
# ============================================================

def boolean_semantic_value_matches_question(
    value,
    question,
):

    value_norm = normalize_value_match_text(
        value
    )

    question_norm = normalize_value_match_text(
        question
    )

    if not value_norm or not question_norm:
        return False

    # --------------------------------------------------------
    # YES-like database values
    # --------------------------------------------------------

    if value_norm in {
        "yes",
        "y",
    }:

        positive_phrases = (
            "approved",
            "accepted",
            "successfully",
            "succeeded",
            "made the team",
            "on scholarship",
            "scholarship student",
            "scholarship students",
            "acting",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in positive_phrases
        )

    # --------------------------------------------------------
    # NO-like database values
    # --------------------------------------------------------

    if value_norm in {
        "no",
        "n",
    }:

        negative_phrases = (
            "not approved",
            "rejected",
            "got rejected",
            "not accepted",
            "did not have",
            "do not have",
            "does not have",
            "without",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in negative_phrases
        )

    # --------------------------------------------------------
    # Female encoded as F
    # --------------------------------------------------------

    if value_norm == "f":

        female_phrases = (
            "female",
            "females",
            "girl",
            "girls",
            "woman",
            "women",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in female_phrases
        )

    # --------------------------------------------------------
    # Male encoded as M
    # --------------------------------------------------------

    if value_norm == "m":

        male_phrases = (
            "male",
            "males",
            "boy",
            "boys",
            "man",
            "men",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in male_phrases
        )

    return False


# ============================================================
# MAIN AUDIT
# ============================================================

def main():

    examples = load_clean_examples()

    stats = Counter()

    recovery_samples = []
    extra_samples = []

    print("=" * 90)
    print(
        "PHASE 7.2J.6D.1 - "
        "BOOLEAN/CATEGORICAL SEMANTIC GROUNDING AUDIT"
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

        gold_values = {
            normalize_value_match_text(value)
            for value in raw_normal_values
            if normalize_value_match_text(value)
        }

        if not gold_values:
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
        # Current production value retrieval
        # ----------------------------------------------------

        value_results = retrieve_relevant_values(
            question=item["question"],
            database_name=item["db_id"],
            table_names=table_names,
        )

        baseline_values = {
            normalize_value_match_text(value)
            for result in value_results
            for value in result["values"]
            if normalize_value_match_text(value)
        }

        missing_before = (
            gold_values
            - baseline_values
        )

        if not missing_before:
            continue

        stats["failure_examples"] += 1
        stats["missing_before"] += len(
            missing_before
        )

        # ----------------------------------------------------
        # Test semantic rules ONLY against missing gold values.
        #
        # This first audit asks:
        # "Can these conservative rules recover known misses?"
        #
        # We are NOT integrating them into production yet.
        # ----------------------------------------------------

        semantic_candidates = {
            value
            for value in missing_before
            if boolean_semantic_value_matches_question(
                value,
                item["question"],
            )
        }

        recovered = (
            semantic_candidates
            & missing_before
        )

        extras = (
            semantic_candidates
            - missing_before
        )

        stats["semantic_candidates"] += len(
            semantic_candidates
        )

        stats["gold_recoveries"] += len(
            recovered
        )

        stats["extras"] += len(
            extras
        )

        if recovered:
            recovery_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "recovered": sorted(
                        recovered
                    ),
                    "missing_before": sorted(
                        missing_before
                    ),
                    "sql": item["query"],
                }
            )

        if extras:
            extra_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "extras": sorted(
                        extras
                    ),
                    "gold": sorted(
                        gold_values
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

    print()
    print("=" * 90)
    print("RESULT")
    print("=" * 90)

    print()
    print(
        "Failure examples             :",
        stats["failure_examples"],
    )

    print(
        "Missing before semantic      :",
        stats["missing_before"],
    )

    print(
        "New semantic candidates      :",
        stats["semantic_candidates"],
    )

    print(
        "Gold recoveries              :",
        stats["gold_recoveries"],
    )

    print(
        "Extra semantic values        :",
        stats["extras"],
    )

    print(
        "Remaining missing            :",
        (
            stats["missing_before"]
            - stats["gold_recoveries"]
        ),
    )

    print()
    print("=" * 90)
    print("BOOLEAN/SEMANTIC RECOVERIES")
    print("=" * 90)

    if not recovery_samples:

        print()
        print("None")

    else:

        for sample in recovery_samples:

            print()
            print("-" * 90)

            print(
                "Index     :",
                sample["index"],
            )

            print(
                "DB        :",
                sample["db"],
            )

            print(
                "Question  :",
                sample["question"],
            )

            print(
                "Recovered :",
                sample["recovered"],
            )

            print(
                "Missing   :",
                sample["missing_before"],
            )

            print(
                "SQL       :",
                sample["sql"],
            )

    print()
    print("=" * 90)
    print("SEMANTIC EXTRAS")
    print("=" * 90)

    if not extra_samples:

        print()
        print("None 🎯")

    else:

        for sample in extra_samples:

            print()
            print("-" * 90)

            print(
                "Index    :",
                sample["index"],
            )

            print(
                "DB       :",
                sample["db"],
            )

            print(
                "Question :",
                sample["question"],
            )

            print(
                "Extras   :",
                sample["extras"],
            )

            print(
                "Gold     :",
                sample["gold"],
            )

    print()
    print("=" * 90)

    print(
        "✅ BOOLEAN/CATEGORICAL SEMANTIC "
        "GROUNDING AUDIT COMPLETE"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
