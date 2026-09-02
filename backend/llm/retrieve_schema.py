import re

from sentence_transformers import SentenceTransformer

from db import get_connection


# ============================================================
# EMBEDDING MODEL
# ============================================================

model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# ============================================================
# TOKEN / LEXICAL MATCHING
# ============================================================

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "each",
    "for",
    "from",
    "have",
    "how",
    "in",
    "is",
    "it",
    "list",
    "many",
    "name",
    "number",
    "of",
    "on",
    "or",
    "show",
    "that",
    "the",
    "to",
    "what",
    "which",
    "who",
    "with",
}


def normalize_word(word):
    """
    Lightweight singular/plural normalization.
    """

    word = word.lower().strip()

    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"

    if word.endswith("s") and len(word) > 3:
        return word[:-1]

    return word


def tokenize(text):
    """
    Extract useful normalized words.
    """

    words = re.findall(
        r"[A-Za-z][A-Za-z0-9_]*",
        text.lower(),
    )

    tokens = set()

    for word in words:

        normalized = normalize_word(
            word
        )

        if normalized not in STOP_WORDS:
            tokens.add(normalized)

    return tokens


def schema_match_score(
    question,
    schema_text,
):
    """
    Compare meaningful question words
    with schema vocabulary.
    """

    question_tokens = tokenize(
        question
    )

    schema_tokens = tokenize(
        schema_text
    )

    if not question_tokens:
        return 0.0, []

    matches = sorted(
        question_tokens.intersection(
            schema_tokens
        )
    )

    score = (
        len(matches)
        / len(question_tokens)
    )

    return score, matches


# ============================================================
# VECTOR + LEXICAL RETRIEVAL
# ============================================================

def retrieve_schema_candidates(
    question: str,
    limit: int = 5,
):
    """
    Retrieve candidate databases using:

    1. Embedding similarity
    2. Lexical schema evidence

    Lower final_score is better.
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
                schema_text,
                embedding <=> %s::vector
                    AS distance
            FROM schema_embeddings
            ORDER BY
                embedding <=> %s::vector;
            """,
            (
                question_embedding,
                question_embedding,
            ),
        )

        rows = cursor.fetchall()

        candidates = []

        for (
            database_name,
            schema_text,
            distance,
        ) in rows:

            lexical_score, matches = (
                schema_match_score(
                    question,
                    schema_text,
                )
            )

            final_score = (
                float(distance)
                - (
                    0.15
                    * lexical_score
                )
            )

            candidates.append(
                {
                    "database_name":
                        database_name,

                    "schema_text":
                        schema_text,

                    "vector_distance":
                        float(distance),

                    "lexical_score":
                        lexical_score,

                    "matched_terms":
                        matches,

                    "final_score":
                        final_score,
                }
            )

        candidates.sort(
            key=lambda item:
                item["final_score"]
        )

        return candidates[:limit]

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
    QueryPilot production database router.

    Flow:
        question
            ↓
        schema embedding similarity
            +
        lexical schema matching
            ↓
        top-1 database
            ↓
        return database + schema + routing score

    Return format:
        (
            database_name,
            schema_text,
            routing_score,
        )
    """

    candidates = retrieve_schema_candidates(
        question,
        limit=1,
    )

    if not candidates:
        return None

    best = candidates[0]

    return (
        best["database_name"],
        best["schema_text"],
        best["final_score"],
    )


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":
    question = input(
        "Enter your question: "
    )

    candidates = retrieve_schema_candidates(
        question,
        limit=5,
    )

    print()
    print("=" * 80)
    print("DATABASE ROUTING CANDIDATES")
    print("=" * 80)

    for rank, candidate in enumerate(
        candidates,
        start=1,
    ):
        print()
        print(
            f"{rank}. "
            f"{candidate['database_name']}"
        )
        print(
            "   Vector distance : "
            f"{candidate['vector_distance']:.6f}"
        )
        print(
            "   Lexical score   : "
            f"{candidate['lexical_score']:.6f}"
        )
        print(
            "   Final score     : "
            f"{candidate['final_score']:.6f}"
        )
        print(
            "   Matched terms   : "
            f"{candidate['matched_terms']}"
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
        (
            database_name,
            schema_text,
            routing_score,
        ) = result

        print(
            "Database:",
            database_name,
        )

        print(
            "Routing score:",
            f"{routing_score:.6f}",
        )

        print()
        print(schema_text)
