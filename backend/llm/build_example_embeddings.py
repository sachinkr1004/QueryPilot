import json
import re
from pathlib import Path
from collections import defaultdict

from sentence_transformers import SentenceTransformer

from db import get_connection


# --------------------------------------------------
# FILE LOCATIONS
# --------------------------------------------------

SPIDER_DEV_PATH = Path(
    "../dataset/spider/spider_data/spider_data/dev.json"
)

BENCHMARK_PATH = Path(
    "eval/test_set.json"
)


DATABASES = {
    "concert_singer",
    "pets_1",
    "car_1",
    "employee_hire_evaluation",
    "world_1",
}


# --------------------------------------------------
# SQL NORMALIZATION
# --------------------------------------------------

def normalize_sql(sql):
    sql = sql.lower().strip()
    sql = sql.rstrip(";")
    sql = re.sub(r"\s+", " ", sql)

    return sql


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

print("📂 Loading Spider DEV dataset...")

with open(SPIDER_DEV_PATH) as f:
    spider = json.load(f)


print("📂 Loading QueryPilot benchmark...")

with open(BENCHMARK_PATH) as f:
    benchmark = json.load(f)


# --------------------------------------------------
# FIND SQL PATTERNS THAT MUST NOT ENTER RAG
# --------------------------------------------------

print()
print("🔒 Finding benchmark SQL patterns...")

blocked_sql = defaultdict(set)


for test in benchmark:

    db_id = test["db_id"]

    question = (
        test["question"]
        .strip()
        .lower()
    )

    for row in spider:

        if (
            row["db_id"] == db_id
            and row["question"].strip().lower()
            == question
        ):

            blocked_sql[db_id].add(
                normalize_sql(
                    row["query"]
                )
            )


# --------------------------------------------------
# BUILD CLEAN EXAMPLE LIST
# --------------------------------------------------

print()
print("🧹 Building clean RAG dataset...")


safe_examples = []


for row in spider:

    db_id = row["db_id"]

    if db_id not in DATABASES:
        continue

    normalized = normalize_sql(
        row["query"]
    )

    if normalized in blocked_sql[db_id]:
        continue

    safe_examples.append(
        {
            "database_name": db_id,
            "question": row["question"],
            "sql": row["query"],
        }
    )


print(
    f"✅ Safe examples found: "
    f"{len(safe_examples)}"
)


# --------------------------------------------------
# LOAD EMBEDDING MODEL
# --------------------------------------------------

print()
print("🧠 Loading embedding model...")


model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# --------------------------------------------------
# CONNECT TO POSTGRESQL
# --------------------------------------------------

print()
print("🐘 Connecting to PostgreSQL...")


conn = get_connection()

cursor = conn.cursor()


try:

    # --------------------------------------------------
    # CREATE TABLE
    # --------------------------------------------------

    print()
    print(
        "📦 Creating example_embeddings table..."
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS
        example_embeddings
        (
            id SERIAL PRIMARY KEY,

            database_name TEXT NOT NULL,

            question TEXT NOT NULL,

            sql TEXT NOT NULL,

            embedding vector(384) NOT NULL
        );
        """
    )


    # Start clean every time this script runs.

    cursor.execute(
        """
        TRUNCATE TABLE
        example_embeddings
        RESTART IDENTITY;
        """
    )


    # --------------------------------------------------
    # GENERATE EMBEDDINGS
    # --------------------------------------------------

    print()
    print("⚙️ Generating embeddings...")


    questions = [
        example["question"]
        for example in safe_examples
    ]


    embeddings = model.encode(
        questions,
        show_progress_bar=True,
    )


    # --------------------------------------------------
    # STORE EXAMPLES
    # --------------------------------------------------

    print()
    print("💾 Storing examples...")


    for example, embedding in zip(
        safe_examples,
        embeddings,
    ):

        cursor.execute(
            """
            INSERT INTO example_embeddings
            (
                database_name,
                question,
                sql,
                embedding
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s
            );
            """,
            (
                example["database_name"],
                example["question"],
                example["sql"],
                embedding.tolist(),
            ),
        )


    conn.commit()


    # --------------------------------------------------
    # VERIFY COUNTS
    # --------------------------------------------------

    print()
    print("=" * 70)
    print("📊 STORED EXAMPLE COUNTS")
    print("=" * 70)


    cursor.execute(
        """
        SELECT
            database_name,
            COUNT(*)
        FROM example_embeddings
        GROUP BY database_name
        ORDER BY database_name;
        """
    )


    total = 0


    for database_name, count in cursor.fetchall():

        print(
            f"{database_name:30} "
            f"{count}"
        )

        total += count


    print()
    print(
        f"🎯 TOTAL STORED EXAMPLES: {total}"
    )


finally:

    cursor.close()
    conn.close()


print()
print(
    "🎉 SAFE RAG EXAMPLE EMBEDDINGS "
    "CREATED SUCCESSFULLY!"
)
