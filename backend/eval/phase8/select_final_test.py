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
QUESTIONS_PER_DATABASE = 5

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

OUTPUT_DIR = BASE_DIR / "eval" / "phase8"

PROFILE_PATH = (
    OUTPUT_DIR
    / "final_test_database_profile.json"
)

MANIFEST_PATH = (
    OUTPUT_DIR
    / "final_test_manifest.json"
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

    ranked = sorted(
        profiles,
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
    test_data,
    selected_profiles,
):

    rng = random.Random(SEED)

    final_records = []

    for profile in selected_profiles:

        db_id = profile["db_id"]

        candidates = [
            item
            for item in test_data
            if item["db_id"] == db_id
        ]

        if len(candidates) < QUESTIONS_PER_DATABASE:
            raise RuntimeError(
                f"{db_id} has only "
                f"{len(candidates)} questions."
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

            final_records.append(
                {
                    "id": (
                        f"phase8_final_"
                        f"{db_id}_"
                        f"{source_index:03d}"
                    ),
                    "db_id": db_id,
                    "source": "spider_test",
                    "source_index_within_db": (
                        source_index
                    ),
                    "question": item["question"],
                    "gold_sql": item["query"],
                }
            )

    return final_records


# ============================================================
# MAIN
# ============================================================

def main():

    test_data = json.loads(
        TEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    db_counts = Counter(
        item["db_id"]
        for item in test_data
    )

    profiles = [
        profile_database(
            db_id,
            db_counts[db_id],
        )
        for db_id in sorted(db_counts)
    ]

    selected_profiles = (
        select_databases(
            profiles
        )
    )

    final_records = select_questions(
        test_data,
        selected_profiles,
    )

    PROFILE_PATH.write_text(
        json.dumps(
            {
                "seed": SEED,
                "database_count": DATABASE_COUNT,
                "questions_per_database": (
                    QUESTIONS_PER_DATABASE
                ),
                "selected_databases": (
                    selected_profiles
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "phase": "8.1",
                "name": (
                    "QueryPilot Untouched "
                    "Final Test Manifest"
                ),
                "status": "frozen_not_evaluated",
                "seed": SEED,
                "database_count": (
                    DATABASE_COUNT
                ),
                "questions_per_database": (
                    QUESTIONS_PER_DATABASE
                ),
                "questions": len(
                    final_records
                ),
                "results_inspected": False,
                "records": final_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 90)
    print(
        "PHASE 8.1 — FINAL TEST "
        "MANIFEST CREATED"
    )
    print("=" * 90)
    print()

    print(
        "Selected databases:",
        len(selected_profiles),
    )

    for profile in selected_profiles:
        print(
            f"  {profile['db_id']:<35}"
            f"tables={profile['table_count']:<3} "
            f"columns={profile['column_count']:<3} "
            f"fks={profile['foreign_key_count']}"
        )

    print()
    print(
        "Final questions:",
        len(final_records),
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
        "🔒 FINAL TEST CREATED "
        "BUT NOT EVALUATED"
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
