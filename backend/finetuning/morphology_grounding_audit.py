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
# LIKE CLASSIFICATION
# ============================================================

def is_like_pattern(value):

    return "%" in str(value)


# ============================================================
# TOKENIZATION
# ============================================================

def question_tokens(question):

    normalized = normalize_value_match_text(
        question
    )

    return {
        token
        for token in normalized.split()
        if token
    }


# ============================================================
# SAFE SINGULAR / PLURAL FORMS
# ============================================================

def morphology_forms(word):

    """
    Conservative morphology experiment.

    Examples:
        egg   -> eggs
        eggs  -> egg
        herb  -> herbs
        herbs -> herb

    Also includes simple -es handling for words such as:
        class   -> classes
        classes -> class

    This is diagnostic only.
    """

    word = normalize_value_match_text(
        word
    )

    if (
        not word
        or " " in word
        or len(word) < 3
        or not word.isalpha()
    ):
        return set()

    forms = set()

    # --------------------------------------------------------
    # Singular -> plural
    # --------------------------------------------------------

    if word.endswith(
        (
            "s",
            "x",
            "z",
            "ch",
            "sh",
        )
    ):
        forms.add(
            word + "es"
        )
    else:
        forms.add(
            word + "s"
        )

    # --------------------------------------------------------
    # Plural -> singular
    # --------------------------------------------------------

    if (
        word.endswith("es")
        and len(word) > 4
    ):
        forms.add(
            word[:-2]
        )

    if (
        word.endswith("s")
        and not word.endswith("ss")
        and len(word) > 3
    ):
        forms.add(
            word[:-1]
        )

    forms.discard(
        word
    )

    return {
        form
        for form in forms
        if len(form) >= 3
    }


def morphology_value_matches_question(
    value,
    question,
):

    """
    Match only single-token DB values through a simple,
    deterministic singular/plural transformation.
    """

    value_norm = normalize_value_match_text(
        value
    )

    if (
        not value_norm
        or " " in value_norm
        or not value_norm.isalpha()
    ):
        return False

    tokens = question_tokens(
        question
    )

    if value_norm in tokens:
        return False

    # Generate forms from the DB value and compare against
    # complete question tokens only.
    for form in morphology_forms(
        value_norm
    ):
        if form in tokens:
            return True

    # Also generate forms from question tokens so that the
    # transformation can work in either direction.
    for token in tokens:

        if (
            value_norm
            in morphology_forms(token)
        ):
            return True

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    examples = load_clean_examples()

    stats = Counter()

    recovery_samples = []
    extra_samples = []

    print("=" * 90)

    print(
        "PHASE 7.2J.5Z.2 - "
        "SAFE MORPHOLOGY GROUNDING AUDIT"
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
            str(value)
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
        # Current production retrieval baseline
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
            name.lower()
            for name in table_names
        }

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
        # Morphology candidates from selected text columns
        # ----------------------------------------------------

        metadata = build_database_metadata(
            item["db_id"]
        )

        morphology_candidates = set()

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

                    if morphology_value_matches_question(
                        value,
                        item["question"],
                    ):

                        normalized = (
                            normalize_value_match_text(
                                value
                            )
                        )

                        if normalized:
                            morphology_candidates.add(
                                normalized
                            )

        # ----------------------------------------------------
        # Evaluate
        # ----------------------------------------------------

        new_values = (
            morphology_candidates
            - baseline_values
        )

        recovered = (
            missing_before
            & new_values
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
            "recoveries"
        ] += len(
            recovered
        )

        stats[
            "extras"
        ] += len(
            extras
        )

        if (
            recovered
            and len(recovery_samples) < 30
        ):

            recovery_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "recovered": sorted(
                        recovered
                    ),
                }
            )

        if (
            extras
            and len(extra_samples) < 30
        ):

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
        "Missing before morphology :",
        stats["missing_before"],
    )

    print(
        "New morphology values     :",
        stats["new_values"],
    )

    print(
        "Gold recoveries           :",
        stats["recoveries"],
    )

    print(
        "Extra morphology values   :",
        stats["extras"],
    )

    remaining = (
        stats["missing_before"]
        - stats["recoveries"]
    )

    print(
        "Remaining missing         :",
        remaining,
    )


    print()

    print("=" * 90)
    print("MORPHOLOGY RECOVERIES")
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


    print()

    print("=" * 90)
    print("MORPHOLOGY EXTRAS")
    print("=" * 90)

    if not extra_samples:

        print()
        print("None 🎯")

    else:

        for sample in extra_samples:

            print()
            print("-" * 90)

            print(
                "Index   :",
                sample["index"],
            )

            print(
                "DB      :",
                sample["db"],
            )

            print(
                "Question:",
                sample["question"],
            )

            print(
                "Extras  :",
                sample["extras"],
            )

            print(
                "Gold    :",
                sample["gold"],
            )


    print()

    print("=" * 90)

    print(
        "✅ SAFE MORPHOLOGY "
        "GROUNDING AUDIT COMPLETE"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
