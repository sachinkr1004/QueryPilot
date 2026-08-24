import json
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
    grounded_like_pattern_matches_question,
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
    """
    In the current clean Spider corpus, all real LIKE
    patterns contain %.

    Underscore-containing literals such as MK_MAN and PU_MAN
    are ordinary equality values, not LIKE patterns.
    """

    return "%" in str(value)


# ============================================================
# MAIN
# ============================================================

def main():

    examples = load_clean_examples()

    normal_total = 0
    normal_recovered = 0

    like_total = 0
    like_recovered = 0

    examples_with_normal = 0
    normal_full_coverage = 0

    examples_with_like = 0
    like_full_coverage = 0

    normal_failures = []
    like_failures = []

    print("=" * 90)
    print(
        "PHASE 7.2J.5C - "
        "CORRECTED SEPARATED VALUE GROUNDING AUDIT"
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

        raw_strings = {
            str(value)
            for value in literals["strings"]
            if str(value).strip()
        }

        if not raw_strings:
            continue

        # ----------------------------------------------------
        # Separate LIKE patterns BEFORE normalization.
        #
        # This is important because value-match
        # normalization removes punctuation such as "%".
        # ----------------------------------------------------

        raw_normal_values = {
            value
            for value in raw_strings
            if not is_like_pattern(value)
        }

        raw_like_values = {
            value
            for value in raw_strings
            if is_like_pattern(value)
        }

        # ----------------------------------------------------
        # Normalize ordinary DB values only after
        # classification.
        # ----------------------------------------------------

        normal_values = {
            normalize_value_match_text(value)
            for value in raw_normal_values
            if normalize_value_match_text(value)
        }

        # Keep LIKE patterns in their original form because
        # the wildcard shape (%Swift%, A%, %m, 8/%) is needed
        # by the dedicated LIKE grounding logic.
        like_values = raw_like_values

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
        # DB-backed value retrieval
        # ----------------------------------------------------

        value_results = (
            retrieve_relevant_values(
                question=item["question"],
                database_name=item["db_id"],
                table_names=table_names,
            )
        )

        retrieved_values = set()

        for result in value_results:

            for value in result["values"]:

                normalized = (
                    normalize_value_match_text(
                        value
                    )
                )

                if normalized:

                    retrieved_values.add(
                        normalized
                    )

        # ====================================================
        # NORMAL VALUES
        # ====================================================

        if normal_values:

            examples_with_normal += 1

            normal_total += len(
                normal_values
            )

            recovered_normal = (
                normal_values
                & retrieved_values
            )

            missing_normal = (
                normal_values
                - retrieved_values
            )

            normal_recovered += len(
                recovered_normal
            )

            if not missing_normal:

                normal_full_coverage += 1

            else:

                normal_failures.append(
                    {
                        "index": index,
                        "db": item["db_id"],
                        "question": item["question"],
                        "sql": item["query"],
                        "gold": sorted(
                            normal_values
                        ),
                        "retrieved": sorted(
                            retrieved_values
                        ),
                        "missing": sorted(
                            missing_normal
                        ),
                    }
                )

        # ====================================================
        # LIKE PATTERNS
        # ====================================================

        if like_values:

            examples_with_like += 1

            like_total += len(
                like_values
            )

            missing_like = []

            for pattern in like_values:

                if (
                    grounded_like_pattern_matches_question(
                        pattern,
                        item["question"],
                    )
                ):

                    like_recovered += 1

                else:

                    missing_like.append(
                        pattern
                    )

            if not missing_like:

                like_full_coverage += 1

            else:

                like_failures.append(
                    {
                        "index": index,
                        "db": item["db_id"],
                        "question": item["question"],
                        "sql": item["query"],
                        "missing": sorted(
                            missing_like
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

    normal_recall = (
        normal_recovered
        / normal_total
        * 100
        if normal_total
        else 0
    )

    normal_coverage = (
        normal_full_coverage
        / examples_with_normal
        * 100
        if examples_with_normal
        else 0
    )

    like_recall = (
        like_recovered
        / like_total
        * 100
        if like_total
        else 0
    )

    like_coverage = (
        like_full_coverage
        / examples_with_like
        * 100
        if examples_with_like
        else 0
    )

    # ========================================================
    # REPORT
    # ========================================================

    print()
    print("=" * 90)
    print("NORMAL DB VALUES")
    print("=" * 90)

    print()
    print(
        "Examples with normal values :",
        examples_with_normal,
    )

    print(
        "Gold normal values          :",
        normal_total,
    )

    print(
        "Recovered normal values     :",
        normal_recovered,
    )

    print(
        "Normal-value recall         :",
        f"{normal_recall:.2f}%",
    )

    print(
        "Full example coverage       :",
        f"{normal_full_coverage}/"
        f"{examples_with_normal}",
    )

    print(
        "Coverage percentage         :",
        f"{normal_coverage:.2f}%",
    )

    print(
        "Normal failures             :",
        len(normal_failures),
    )

    print()
    print("=" * 90)
    print("LIKE PATTERNS")
    print("=" * 90)

    print()
    print(
        "Examples with LIKE patterns :",
        examples_with_like,
    )

    print(
        "Gold LIKE patterns          :",
        like_total,
    )

    print(
        "Grounded LIKE patterns      :",
        like_recovered,
    )

    print(
        "LIKE grounding recall       :",
        f"{like_recall:.2f}%",
    )

    print(
        "Full example coverage       :",
        f"{like_full_coverage}/"
        f"{examples_with_like}",
    )

    print(
        "Coverage percentage         :",
        f"{like_coverage:.2f}%",
    )

    print(
        "LIKE failures               :",
        len(like_failures),
    )

    # ========================================================
    # NORMAL FAILURES
    # ========================================================

    print()
    print("=" * 90)
    print("FIRST 30 NORMAL VALUE FAILURES")
    print("=" * 90)

    for failure in normal_failures[:30]:

        print()
        print("-" * 90)

        print(
            "Index    :",
            failure["index"],
        )

        print(
            "DB       :",
            failure["db"],
        )

        print(
            "Question :",
            failure["question"],
        )

        print(
            "Gold     :",
            failure["gold"],
        )

        print(
            "Retrieved:",
            failure["retrieved"],
        )

        print(
            "Missing  :",
            failure["missing"],
        )

        print(
            "SQL      :",
            failure["sql"],
        )

    # ========================================================
    # LIKE FAILURES
    # ========================================================

    print()
    print("=" * 90)
    print("REMAINING LIKE FAILURES")
    print("=" * 90)

    if not like_failures:

        print()
        print("None 🎯")

    else:

        for failure in like_failures:

            print()
            print("-" * 90)

            print(
                "DB       :",
                failure["db"],
            )

            print(
                "Question :",
                failure["question"],
            )

            print(
                "Missing  :",
                failure["missing"],
            )

            print(
                "SQL      :",
                failure["sql"],
            )

    print()
    print("=" * 90)
    print(
        "✅ CORRECTED SEPARATED VALUE "
        "GROUNDING AUDIT COMPLETE"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
