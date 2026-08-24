import json
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
    fuzzy_value_matches_question,
    normalize_value_match_text,
    get_distinct_values,
    value_matches_question,
    value_alias_matches_question,
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
# SETTINGS
# ============================================================

THRESHOLDS = (
    0.90,
    0.89,
    0.88,
    0.87,
    0.86,
    0.85,
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
# MAIN
# ============================================================

def main():

    examples = load_clean_examples()

    stats = {
        threshold: Counter()
        for threshold in THRESHOLDS
    }

    samples = {
        threshold: {
            "recoveries": [],
            "extras": [],
        }
        for threshold in THRESHOLDS
    }

    print("=" * 90)
    print(
        "PHASE 7.2J.5Y.1 - "
        "FUZZY THRESHOLD PRECISION/RECALL AUDIT"
    )
    print("=" * 90)
    print()
    print(
        "Clean examples:",
        len(examples),
    )
    print(
        "Thresholds    :",
        THRESHOLDS,
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

        # ----------------------------------------------------
        # Current production retrieval.
        # This includes the verified 0.90 fuzzy matcher and
        # the safe multi-token cutoff fallback.
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

        missing_baseline = (
            gold_values
            - baseline_values
        )

        metadata = build_database_metadata(
            item["db_id"]
        )

        # ----------------------------------------------------
        # Evaluate each candidate fuzzy threshold.
        #
        # Only values NOT already accepted by the ordinary
        # lexical/alias rules are treated as candidate fuzzy
        # additions.
        # ----------------------------------------------------

        for threshold in THRESHOLDS:

            candidate_values = set()

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

                        # Already covered by deterministic
                        # matching; don't count it as a fuzzy
                        # threshold effect.
                        if (
                            value_matches_question(
                                value,
                                item["question"],
                            )
                            or value_alias_matches_question(
                                value,
                                item["question"],
                            )
                        ):
                            continue

                        if fuzzy_value_matches_question(
                            value,
                            item["question"],
                            threshold=threshold,
                        ):
                            normalized = (
                                normalize_value_match_text(
                                    value
                                )
                            )

                            if normalized:
                                candidate_values.add(
                                    normalized
                                )

            new_values = (
                candidate_values
                - baseline_values
            )

            recovered = (
                missing_baseline
                & new_values
            )

            extras = (
                new_values
                - gold_values
            )

            stats[threshold][
                "new_values"
            ] += len(new_values)

            stats[threshold][
                "recoveries"
            ] += len(recovered)

            stats[threshold][
                "extras"
            ] += len(extras)

            if (
                recovered
                and len(
                    samples[threshold][
                        "recoveries"
                    ]
                ) < 10
            ):
                samples[threshold][
                    "recoveries"
                ].append(
                    {
                        "index": index,
                        "db": item["db_id"],
                        "question": item[
                            "question"
                        ],
                        "values": sorted(
                            recovered
                        ),
                    }
                )

            if (
                extras
                and len(
                    samples[threshold][
                        "extras"
                    ]
                ) < 10
            ):
                samples[threshold][
                    "extras"
                ].append(
                    {
                        "index": index,
                        "db": item["db_id"],
                        "question": item[
                            "question"
                        ],
                        "values": sorted(
                            extras
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
    print("THRESHOLD COMPARISON")
    print("=" * 90)
    print()

    print(
        f"{'Threshold':<12}"
        f"{'New values':<15}"
        f"{'Recoveries':<15}"
        f"{'Extras':<15}"
    )

    print("-" * 57)

    for threshold in THRESHOLDS:

        result = stats[threshold]

        print(
            f"{threshold:<12.2f}"
            f"{result['new_values']:<15}"
            f"{result['recoveries']:<15}"
            f"{result['extras']:<15}"
        )

    # ========================================================
    # SAMPLE CHANGES
    # ========================================================

    for threshold in THRESHOLDS:

        if threshold == 0.90:
            continue

        print()
        print("=" * 90)
        print(
            f"THRESHOLD {threshold:.2f} "
            f"- SAMPLE RECOVERIES"
        )
        print("=" * 90)

        recoveries = (
            samples[threshold][
                "recoveries"
            ]
        )

        if not recoveries:
            print()
            print("None")
        else:
            for sample in recoveries:
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
                    "Recovered:",
                    sample["values"],
                )

        print()
        print("=" * 90)
        print(
            f"THRESHOLD {threshold:.2f} "
            f"- SAMPLE EXTRAS"
        )
        print("=" * 90)

        extras = (
            samples[threshold][
                "extras"
            ]
        )

        if not extras:
            print()
            print("None 🎯")
        else:
            for sample in extras:
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
                    sample["values"],
                )

    print()
    print("=" * 90)
    print(
        "✅ FUZZY THRESHOLD "
        "PRECISION/RECALL AUDIT COMPLETE"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
