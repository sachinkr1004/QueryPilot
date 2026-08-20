from sentence_transformers import SentenceTransformer

from db import get_connection


# Load once when this module is imported.
model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


def retrieve_examples(
    question: str,
    database_name: str,
    limit: int = 3,
):
    """
    Retrieve the most semantically similar SAFE Spider
    examples from the selected database.

    Returns:
        [
            {
                "question": "...",
                "sql": "...",
                "distance": 0.123
            },
            ...
        ]
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
                question,
                sql,
                embedding <=> %s::vector AS distance
            FROM example_embeddings
            WHERE database_name = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (
                question_embedding,
                database_name,
                question_embedding,
                limit,
            ),
        )

        rows = cursor.fetchall()

        examples = []

        for question_text, sql, distance in rows:

            examples.append(
                {
                    "question": question_text,
                    "sql": sql,
                    "distance": float(distance),
                }
            )

        return examples

    finally:

        cursor.close()
        conn.close()


if __name__ == "__main__":

    question = input(
        "Enter question: "
    )

    database_name = input(
        "Enter database name: "
    )

    examples = retrieve_examples(
        question,
        database_name,
        limit=3,
    )

    print()
    print("=" * 70)
    print("TOP SAFE EXAMPLES")
    print("=" * 70)

    for rank, example in enumerate(
        examples,
        1,
    ):

        print()
        print(
            f"{rank}. Distance: "
            f"{example['distance']:.6f}"
        )

        print(
            "Question:",
            example["question"],
        )

        print(
            "SQL:",
            example["sql"],
        )
