import json
import re

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
    get_distinct_values,
)

from finetuning.spider_context import (
    build_database_metadata,
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
# BASIC HELPERS
# ============================================================

def is_like_pattern(value):

    return "%" in str(value)


def contains_phrase(
    question,
    phrase,
):

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
# BOOLEAN / CATEGORICAL SEMANTIC RULES
# ============================================================

def boolean_semantic_value_matches_question(
    value,
    question,
    column_name,
):
    value_norm = normalize_value_match_text(
        value
    )
    question_norm = normalize_value_match_text(
        question
    )
    column_norm = normalize_value_match_text(
        column_name
    )

    if (
        not value_norm
        or not question_norm
        or not column_norm
    ):
        return False

    # --------------------------------------------------------
    # Column families
    # --------------------------------------------------------

    approval_columns = {
        "fda approved",
        "approved",
        "approval",
    }

    decision_columns = {
        "decision",
    }

    scholarship_columns = {
        "onscholarship",
        "on scholarship",
        "scholarship",
    }

    acting_columns = {
        "temporary acting",
        "acting",
    }

    wifi_columns = {
        "wifi",
    }

    gender_columns = {
        "sex",
        "gender",
        "is male",
    }

    # --------------------------------------------------------
    # YES / Y
    #
    # IMPORTANT:
    # Negative phrases take precedence over positive phrases.
    # --------------------------------------------------------

    if value_norm in {
        "yes",
        "y",
    }:

        if column_norm in approval_columns:
            if contains_phrase(
                question_norm,
                "not approved",
            ):
                return False

            return contains_phrase(
                question_norm,
                "approved",
            )

        if column_norm in decision_columns:
            positive_decision_phrases = (
                "accepted",
                "successfully",
                "succeeded",
                "made the team",
                "successfully tried out",
                "successfully made the team",
                "got accepted",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in positive_decision_phrases
            )

        if column_norm in scholarship_columns:
            scholarship_phrases = (
                "on scholarship",
                "scholarship student",
                "scholarship students",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in scholarship_phrases
            )

        if column_norm in acting_columns:
            return contains_phrase(
                question_norm,
                "acting",
            )

        return False

    # --------------------------------------------------------
    # NO / N
    #
    # Do NOT use generic:
    #   without
    #   do not have
    #   does not have
    #
    # Those phrases may describe absence of an entity rather
    # than a boolean/categorical database value.
    # --------------------------------------------------------

    if value_norm in {
        "no",
        "n",
    }:

        if column_norm in approval_columns:
            return contains_phrase(
                question_norm,
                "not approved",
            )

        if column_norm in decision_columns:
            negative_decision_phrases = (
                "rejected",
                "got rejected",
                "not accepted",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in negative_decision_phrases
            )

        if column_norm in wifi_columns:
            wifi_negative_phrases = (
                "do not have wifi",
                "does not have wifi",
                "without wifi",
                "do not have the wifi function",
                "does not have the wifi function",
            )
            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in wifi_negative_phrases
            )

        return False

    # --------------------------------------------------------
    # FEMALE -> F
    #
    # Only gender-like columns may use this semantic mapping.
    #
    # Avoid generic "girl" because:
    #   "girl named Lisa"
    # may identify Lisa without requiring Sex = F.
    # --------------------------------------------------------

    if (
        value_norm == "f"
        and column_norm in gender_columns
    ):
        female_phrases = (
            "female",
            "females",
            "girl student",
            "girl students",
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
    # MALE -> M
    # --------------------------------------------------------

    if (
        value_norm == "m"
        and column_norm in gender_columns
    ):
        male_phrases = (
            "male",
            "males",
            "boy student",
            "boy students",
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
# MAIN PRECISION AUDIT
# ============================================================

def main():

    examples = load_clean_examples()

    stats = Counter()

    recovery_samples = []
    extra_samples = []

    print("=" * 90)

    print(
        "PHASE 7.2J.6D.2 - "
        "REAL DB-CANDIDATE BOOLEAN SEMANTIC PRECISION AUDIT"
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

        raw_gold = {
            value
            for value in literals["strings"]
            if not is_like_pattern(value)
        }

        gold_values = {
            normalize_value_match_text(value)
            for value in raw_gold
            if normalize_value_match_text(value)
        }

        if not gold_values:
            continue

        # ----------------------------------------------------
        # Retrieve relevant schema tables
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

        selected_tables = {
            table_name.lower()
            for table_name in table_names
        }

        # ----------------------------------------------------
        # Current production retrieval
        # ----------------------------------------------------

        baseline_results = (
            retrieve_relevant_values(
                question=item["question"],
                database_name=item["db_id"],
                table_names=table_names,
            )
        )

        baseline_values = {
            normalize_value_match_text(value)
            for result in baseline_results
            for value in result["values"]
            if normalize_value_match_text(value)
        }

        missing_before = (
            gold_values
            - baseline_values
        )

        stats[
            "missing_before"
        ] += len(
            missing_before
        )

        # ----------------------------------------------------
        # Scan REAL DB candidate values.
        # ----------------------------------------------------

        metadata = build_database_metadata(
            item["db_id"]
        )

        semantic_candidates = set()

        for table_name, table_info in (
            metadata["tables"].items()
        ):

            if (
                table_name.lower()
                not in selected_tables
            ):
                continue

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

                values = get_distinct_values(
                    item["db_id"],
                    table_name,
                    column_name,
                )

                for value in values:

                    if (
                        boolean_semantic_value_matches_question(
                            value,
                            item["question"],
                            column_name,
                        )
                    ):

                        normalized = (
                            normalize_value_match_text(
                                value
                            )
                        )

                        if normalized:
                            semantic_candidates.add(
                                normalized
                            )

        # ----------------------------------------------------
        # Only evaluate genuinely NEW semantic additions.
        # ----------------------------------------------------

        new_values = (
            semantic_candidates
            - baseline_values
        )

        correct_new = (
            new_values
            & gold_values
        )

        extras = (
            new_values
            - gold_values
        )

        stats[
            "new_values"
        ] += len(
            new_values
        )

        stats[
            "correct_new"
        ] += len(
            correct_new
        )

        stats[
            "extras"
        ] += len(
            extras
        )

        if new_values:
            stats[
                "examples_with_new_values"
            ] += 1

        if correct_new:
            stats[
                "examples_with_recoveries"
            ] += 1

        if extras:
            stats[
                "examples_with_extras"
            ] += 1

        if (
            correct_new
            and len(recovery_samples) < 40
        ):

            recovery_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item[
                        "question"
                    ],
                    "correct": sorted(
                        correct_new
                    ),
                    "new_values": sorted(
                        new_values
                    ),
                    "gold": sorted(
                        gold_values
                    ),
                }
            )

        if (
            extras
            and len(extra_samples) < 40
        ):

            extra_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item[
                        "question"
                    ],
                    "extras": sorted(
                        extras
                    ),
                    "new_values": sorted(
                        new_values
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
    # METRICS
    # ========================================================

    precision = (
        stats["correct_new"]
        / stats["new_values"]
        * 100
        if stats["new_values"]
        else 0
    )

    remaining_missing = (
        stats["missing_before"]
        - stats["correct_new"]
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
        "Missing before semantic       :",
        stats["missing_before"],
    )

    print(
        "New semantic DB values        :",
        stats["new_values"],
    )

    print(
        "Correct new values            :",
        stats["correct_new"],
    )

    print(
        "Extra / wrong values          :",
        stats["extras"],
    )

    print(
        "Semantic precision            :",
        f"{precision:.2f}%",
    )

    print(
        "Examples with new values      :",
        stats["examples_with_new_values"],
    )

    print(
        "Examples with recoveries      :",
        stats["examples_with_recoveries"],
    )

    print(
        "Examples with extras          :",
        stats["examples_with_extras"],
    )

    print(
        "Remaining missing             :",
        remaining_missing,
    )

    # ========================================================
    # RECOVERIES
    # ========================================================

    print()

    print("=" * 90)
    print("CORRECT NEW SEMANTIC VALUES")
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
                "Correct   :",
                sample["correct"],
            )

            print(
                "New values:",
                sample["new_values"],
            )

            print(
                "Gold      :",
                sample["gold"],
            )

    # ========================================================
    # EXTRAS
    # ========================================================

    print()

    print("=" * 90)
    print("FALSE / EXTRA SEMANTIC VALUES")
    print("=" * 90)

    if not extra_samples:

        print()
        print("None 🎯")

    else:

        for sample in extra_samples:

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
                "Extras    :",
                sample["extras"],
            )

            print(
                "New values:",
                sample["new_values"],
            )

            print(
                "Gold      :",
                sample["gold"],
            )

    print()

    print("=" * 90)

    print(
        "✅ REAL DB-CANDIDATE BOOLEAN "
        "SEMANTIC PRECISION AUDIT COMPLETE"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
