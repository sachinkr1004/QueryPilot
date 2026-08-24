import json
import re
import sqlite3

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
    get_sqlite_database_path,
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
# SAFE BOUNDARY MATCH
# ============================================================

def boundary_match(
    value,
    question,
):

    value_norm = normalize_value_match_text(
        value
    )

    question_norm = normalize_value_match_text(
        question
    )

    if not value_norm:
        return False

    # --------------------------------------------------------
    # Multi-token fallback only.
    # --------------------------------------------------------

    if len(value_norm.split()) < 2:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(value_norm)
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
# REMOVE NESTED SHORTER MATCHES
# ============================================================

def remove_nested_matches(values):

    normalized = [
        (
            value,
            normalize_value_match_text(value),
        )
        for value in values
        if normalize_value_match_text(value)
    ]

    normalized.sort(
        key=lambda item: len(item[1]),
        reverse=True,
    )

    kept = []

    for value, value_norm in normalized:

        nested = False

        for _, kept_norm in kept:

            pattern = (
                r"(?<!\w)"
                + re.escape(value_norm)
                + r"(?!\w)"
            )

            if re.search(
                pattern,
                kept_norm,
                flags=re.IGNORECASE,
            ):
                nested = True
                break

        if not nested:
            kept.append(
                (
                    value,
                    value_norm,
                )
            )

    return [
        value
        for value, _ in kept
    ]


# ============================================================
# FULL-COLUMN FALLBACK
# ============================================================

def full_column_fallback(
    database_name,
    table_name,
    column_name,
    question,
):

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Only use the fallback when the ordinary retrieval window
    # is completely full. If fewer than 200 values exist,
    # there is no cutoff problem to solve.
    # --------------------------------------------------------

    first_200 = get_distinct_values(
        database_name,
        table_name,
        column_name,
        limit=200,
    )

    if len(first_200) < 200:
        return []

    path = get_sqlite_database_path(
        database_name
    )

    conn = sqlite3.connect(
        path
    )

    try:

        cursor = conn.cursor()

        query = (
            f'SELECT DISTINCT "{column_name}" '
            f'FROM "{table_name}" '
            f'WHERE "{column_name}" IS NOT NULL'
        )

        try:
            cursor.execute(
                query
            )
        except sqlite3.Error:
            return []

        matches = []

        for row in cursor.fetchall():

            value = row[0]

            if boundary_match(
                value,
                question,
            ):
                matches.append(
                    value
                )

        return remove_nested_matches(
            matches
        )

    finally:
        conn.close()


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
        "PHASE 7.2J.5W - "
        "FALLBACK RETURN COMPOSITION AUDIT"
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
            str(value)
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

        stats[
            "examples_with_normal"
        ] += 1

        stats[
            "gold_values"
        ] += len(
            gold_values
        )

        # ----------------------------------------------------
        # Normal schema retrieval
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

        selected_lower = {
            name.lower()
            for name in table_names
        }

        # ----------------------------------------------------
        # Baseline value retrieval
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
        # Safe multi-token fallback
        # ----------------------------------------------------

        metadata = build_database_metadata(
            item["db_id"]
        )

        fallback_raw = []

        for table_name, table_info in (
            metadata["tables"].items()
        ):

            if (
                table_name.lower()
                not in selected_lower
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

                matches = (
                    full_column_fallback(
                        database_name=item["db_id"],
                        table_name=table_name,
                        column_name=column_name,
                        question=item["question"],
                    )
                )

                fallback_raw.extend(
                    matches
                )

        fallback_values = {
            normalize_value_match_text(value)
            for value in fallback_raw
            if normalize_value_match_text(value)
        }

        # ----------------------------------------------------
        # Evaluate fallback
        # ----------------------------------------------------

        # ----------------------------------------------------
        # Fallback return composition
        # ----------------------------------------------------

        # Gold values that baseline missed and fallback
        # successfully recovered.
        recovered_new = (
            fallback_values
            & missing_before
        )

        # Fallback values that baseline had already retrieved.
        already_baseline = (
            fallback_values
            & baseline_values
        )

        # Of the baseline duplicates, these are also gold.
        already_baseline_gold = (
            already_baseline
            & gold_values
        )

        # Baseline duplicates that are not gold for this
        # particular example.
        already_baseline_non_gold = (
            already_baseline
            - gold_values
        )

        # Values introduced only by fallback and unsupported
        # by the gold SQL.
        extras = (
            fallback_values
            - gold_values
            - baseline_values
        )

        # Every fallback value must belong to exactly one of:
        #
        #   recovered_new
        #   already_baseline
        #   extras
        #
        composition_total = (
            len(recovered_new)
            + len(already_baseline)
            + len(extras)
        )

        if composition_total != len(fallback_values):
            raise RuntimeError(
                "❌ Fallback composition invariant failed."
            )

        stats[
            "new_recovered"
        ] += len(
            recovered_new
        )

        stats[
            "already_baseline"
        ] += len(
            already_baseline
        )

        stats[
            "already_baseline_gold"
        ] += len(
            already_baseline_gold
        )

        stats[
            "already_baseline_non_gold"
        ] += len(
            already_baseline_non_gold
        )

        stats[
            "fallback_values"
        ] += len(
            fallback_values
        )

        stats[
            "extras"
        ] += len(
            extras
        )

        if (
            recovered_new
            and len(recovery_samples) < 30
        ):

            recovery_samples.append(
                {
                    "index": index,
                    "db": item["db_id"],
                    "question": item["question"],
                    "recovered": sorted(
                        recovered_new
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

    remaining_missing = (
        stats["missing_before"]
        - stats["new_recovered"]
    )

    print()

    print("=" * 90)
    print("RESULT")
    print("=" * 90)

    print()

    print(
        "Examples with normal values :",
        stats["examples_with_normal"],
    )

    print(
        "Gold normal values          :",
        stats["gold_values"],
    )

    print(
        "Missing before fallback     :",
        stats["missing_before"],
    )

    print(
        "New values recovered        :",
        stats["new_recovered"],
    )

    print(
        "Fallback values returned    :",
        stats["fallback_values"],
    )

    print(
        "Already baseline            :",
        stats["already_baseline"],
    )

    print(
        "  ├─ Gold baseline values   :",
        stats["already_baseline_gold"],
    )

    print(
        "  └─ Non-gold baseline vals :",
        stats["already_baseline_non_gold"],
    )

    print(
        "Extra fallback values       :",
        stats["extras"],
    )

    print(
        "Remaining missing           :",
        remaining_missing,
    )


    print()

    print("=" * 90)
    print("NEW RECOVERIES")
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
    print("EXTRA FALLBACK VALUES")
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
        "✅ MULTI-TOKEN CUTOFF "
        "FALLBACK AUDIT COMPLETE"
    )

    print("=" * 90)


if __name__ == "__main__":
    main()
