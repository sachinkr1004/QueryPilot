import json
import random
import sqlite3
from pathlib import Path
from collections import Counter


# ============================================================
# CONFIGURATION
# ============================================================

SEED = 42

DATABASE_COUNT = 20
QUESTIONS_PER_DATABASE = 2

BASE_DIR = Path(__file__).resolve().parents[2]

SPIDER_ROOT = (
    BASE_DIR.parent
    / "dataset"
    / "spider"
    / "spider_data"
    / "spider_data"
)

TEST_PATH = SPIDER_ROOT / "test.json"
TEST_DB_ROOT = SPIDER_ROOT / "test_database"

PHASE8_DIR = BASE_DIR / "eval" / "phase8"
PHASE9_DIR = BASE_DIR / "eval" / "phase9"

PHASE8_MANIFEST_PATH = (
    PHASE8_DIR
    / "final_test_manifest.json"
)

PROFILE_PATH = (
    PHASE9_DIR
    / "regression_database_profile.json"
)

MANIFEST_PATH = (
    PHASE9_DIR
    / "regression_benchmark_manifest.json"
)


# ============================================================
# RECORD KEY
# ============================================================

def record_key(db_id, question, gold_sql):
    return (
        db_id,
        question,
        gold_sql,
    )


# ============================================================
# DATABASE STRUCTURAL PROFILE
# ============================================================

def profile_database(db_id, question_count):

    db_path = (
        TEST_DB_ROOT
        / db_id
        / f"{db_id}.sqlite"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database file missing: {db_path}"
        )

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )

    tables = [
        row[0]
        for row in cur.fetchall()
    ]

    column_count = 0
    fk_count = 0

    for table in tables:

        safe_table = table.replace('"', '""')

        cur.execute(
            f'PRAGMA table_info("{safe_table}")'
        )

        column_count += len(
            cur.fetchall()
        )

        cur.execute(
            f'PRAGMA foreign_key_list("{safe_table}")'
        )

        fk_count += len(
            cur.fetchall()
        )

    conn.close()

    return {
        "db_id": db_id,
        "question_count": question_count,
        "table_count": len(tables),
        "column_count": column_count,
        "foreign_key_count": fk_count,
    }


# ============================================================
# STRUCTURAL SCORE
# ============================================================

def structural_score(profile):

    return (
        profile["table_count"]
        + profile["column_count"] / 10
        + profile["foreign_key_count"]
    )


# ============================================================
# SELECT DATABASES
# ============================================================

def select_databases(profiles):

    eligible = [
        profile
        for profile in profiles
        if (
            profile["question_count"]
            >= QUESTIONS_PER_DATABASE
        )
    ]

    if len(eligible) < DATABASE_COUNT:
        raise RuntimeError(
            "Not enough eligible databases for "
            "Phase-9 benchmark."
        )

    ranked = sorted(
        eligible,
        key=lambda item: (
            structural_score(item),
            item["db_id"],
        ),
    )

    selected = []

    if DATABASE_COUNT == 1:
        return [
            ranked[len(ranked) // 2]
        ]

    for i in range(DATABASE_COUNT):

        position = round(
            i
            * (len(ranked) - 1)
            / (DATABASE_COUNT - 1)
        )

        selected.append(
            ranked[position]
        )

    if len(
        {
            item["db_id"]
            for item in selected
        }
    ) != DATABASE_COUNT:

        raise RuntimeError(
            "Database stratification produced "
            "duplicate selections."
        )

    return selected


# ============================================================
# SELECT QUESTIONS
# ============================================================

def select_questions(
    remaining_data,
    selected_profiles,
):

    rng = random.Random(SEED)

    records = []

    for profile in selected_profiles:

        db_id = profile["db_id"]

        candidates = [
            item
            for item in remaining_data
            if item["db_id"] == db_id
        ]

        if (
            len(candidates)
            < QUESTIONS_PER_DATABASE
        ):
            raise RuntimeError(
                f"{db_id} has only "
                f"{len(candidates)} fresh questions."
            )

        indices = list(
            range(len(candidates))
        )

        rng.shuffle(indices)

        selected_indices = sorted(
            indices[:QUESTIONS_PER_DATABASE]
        )

        for source_index in selected_indices:

            item = candidates[source_index]

            records.append(
                {
                    "id": (
                        f"phase9_regression_"
                        f"{db_id}_"
                        f"{source_index:03d}"
                    ),
                    "db_id": db_id,
                    "source": "spider_test",
                    "source_index_within_fresh_db_pool": (
                        source_index
                    ),
                    "question": item["question"],
                    "gold_sql": item["query"],
                }
            )

    return records


# ============================================================
# MAIN
# ============================================================

def main():

    test_data = json.loads(
        TEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    phase8_manifest = json.loads(
        PHASE8_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    phase8_records = (
        phase8_manifest["records"]
    )

    consumed_keys = {
        record_key(
            record["db_id"],
            record["question"],
            record["gold_sql"],
        )
        for record in phase8_records
    }

    remaining_data = [
        item
        for item in test_data
        if record_key(
            item["db_id"],
            item["question"],
            item["query"],
        )
        not in consumed_keys
    ]

    remaining_counts = Counter(
        item["db_id"]
        for item in remaining_data
    )

    profiles = [
        profile_database(
            db_id,
            remaining_counts[db_id],
        )
        for db_id in sorted(
            remaining_counts
        )
    ]

    selected_profiles = select_databases(
        profiles
    )

    records = select_questions(
        remaining_data,
        selected_profiles,
    )

    selected_keys = {
        record_key(
            record["db_id"],
            record["question"],
            record["gold_sql"],
        )
        for record in records
    }

    phase8_overlap = (
        selected_keys
        & consumed_keys
    )

    if phase8_overlap:
        raise RuntimeError(
            "Phase-9 benchmark overlaps with "
            "consumed Phase-8 final test."
        )

    if len(selected_keys) != len(records):
        raise RuntimeError(
            "Duplicate Phase-9 benchmark "
            "records detected."
        )

    expected_questions = (
        DATABASE_COUNT
        * QUESTIONS_PER_DATABASE
    )

    if len(records) != expected_questions:
        raise RuntimeError(
            "Unexpected Phase-9 benchmark size."
        )

    profile_payload = {
        "phase": "9.4",
        "seed": SEED,
        "candidate_source": "spider_test",
        "phase8_consumed_questions": (
            len(consumed_keys)
        ),
        "fresh_candidate_questions": (
            len(remaining_data)
        ),
        "database_count": DATABASE_COUNT,
        "questions_per_database": (
            QUESTIONS_PER_DATABASE
        ),
        "selected_databases": (
            selected_profiles
        ),
    }

    manifest_payload = {
        "phase": "9.4",
        "name": (
            "QueryPilot Phase-9 "
            "Regression Benchmark"
        ),
        "status": "frozen",
        "purpose": (
            "Phase-9 development, profiling, "
            "optimization, and regression testing."
        ),
        "source": "spider_test",
        "seed": SEED,
        "database_count": DATABASE_COUNT,
        "questions_per_database": (
            QUESTIONS_PER_DATABASE
        ),
        "questions": len(records),
        "phase8_final_test_excluded": True,
        "phase8_consumed_questions": (
            len(consumed_keys)
        ),
        "phase8_overlap": 0,
        "records": records,
    }

    PROFILE_PATH.write_text(
        json.dumps(
            profile_payload,
            indent=2,
        ),
        encoding="utf-8",
    )

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest_payload,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 90)
    print(
        "PHASE 9.4 — REGRESSION "
        "BENCHMARK CREATED"
    )
    print("=" * 90)

    print(
        "Spider TEST questions :",
        len(test_data),
    )

    print(
        "Phase-8 excluded       :",
        len(consumed_keys),
    )

    print(
        "Fresh candidate pool   :",
        len(remaining_data),
    )

    print(
        "Selected databases     :",
        len(selected_profiles),
    )

    print(
        "Questions per database :",
        QUESTIONS_PER_DATABASE,
    )

    print(
        "Regression questions   :",
        len(records),
    )

    print(
        "Phase-8 overlap        :",
        len(phase8_overlap),
    )

    print()
    print(
        "Profile saved :",
        PROFILE_PATH,
    )
    print(
        "Manifest saved:",
        MANIFEST_PATH,
    )

    print()
    print(
        "🔒 PHASE-9 REGRESSION "
        "BENCHMARK FROZEN"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
