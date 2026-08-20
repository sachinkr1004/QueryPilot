from sentence_transformers import SentenceTransformer

from db import get_connection


# ============================================================
# EMBEDDING MODEL
# ============================================================

# Load the model only once when this module is imported.
model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# ============================================================
# EXAMPLE-BASED DATABASE ROUTING
# ============================================================

def retrieve_database_candidates(
    question: str,
    limit: int = 5,
):
    """
    Find the SAFE Spider examples that are most similar
    to the user's question.

    These examples are used as evidence for selecting
    the correct database.

    Lower distance = more similar.
    """

    question_embedding = model.encode(
        question
    ).tolist()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                database_name,
                question,
                sql,
                embedding <=> %s::vector AS distance
            FROM example_embeddings
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (
                question_embedding,
                question_embedding,
                limit,
            ),
        )

        rows = cursor.fetchall()

        candidates = []

        for (
            database_name,
            example_question,
            sql,
            distance,
        ) in rows:

            candidates.append(
                {
                    "database_name": database_name,
                    "question": example_question,
                    "sql": sql,
                    "distance": float(distance),
                }
            )

        return candidates

    finally:
        cursor.close()
        conn.close()


# ============================================================
# FETCH SCHEMA
# ============================================================

def get_schema_for_database(
    database_name: str,
):
    """
    Fetch the authoritative schema text that was created by
    build_schema_embeddings.py.

    This schema includes:
      - tables
      - columns
      - data types
      - primary keys
      - relationships
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT schema_text
            FROM schema_embeddings
            WHERE database_name = %s
            LIMIT 1;
            """,
            (database_name,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return row[0]

    finally:
        cursor.close()
        conn.close()


# ============================================================
# MAIN SCHEMA RETRIEVER
# ============================================================

def retrieve_schema(
    question: str,
):
    """
    QueryPilot database routing pipeline:

        User question
              ↓
        Question embedding
              ↓
        Nearest SAFE RAG example
              ↓
        Database selection
              ↓
        Fetch authoritative schema
              ↓
        Return database + schema

    Return format remains compatible with the rest
    of QueryPilot:

        (
            database_name,
            schema_text,
            routing_distance
        )
    """

    candidates = retrieve_database_candidates(
        question,
        limit=1,
    )

    if not candidates:
        return None

    best = candidates[0]

    database_name = best[
        "database_name"
    ]

    routing_distance = best[
        "distance"
    ]

    schema_text = get_schema_for_database(
        database_name
    )

    if schema_text is None:
        raise ValueError(
            "Schema not found for database: "
            f"{database_name}"
        )

    return (
        database_name,
        schema_text,
        routing_distance,
    )


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    question = input(
        "Enter your question: "
    )

    candidates = retrieve_database_candidates(
        question,
        limit=5,
    )

    print()
    print("=" * 80)
    print("DATABASE ROUTING CANDIDATES")
    print("=" * 80)

    for rank, candidate in enumerate(
        candidates,
        1,
    ):

        print()
        print(
            f"{rank}. "
            f"{candidate['database_name']}"
        )

        print(
            "   Distance : "
            f"{candidate['distance']:.6f}"
        )

        print(
            "   Example  : "
            f"{candidate['question']}"
        )

    result = retrieve_schema(
        question
    )

    print()
    print("=" * 80)
    print("SELECTED DATABASE")
    print("=" * 80)

    if result is None:

        print(
            "No database could be selected."
        )

    else:

        database_name, schema_text, distance = result

        print(
            "Database:",
            database_name
        )

        print(
            "Routing distance:",
            f"{distance:.6f}"
        )

        print()

        print(schema_text)
