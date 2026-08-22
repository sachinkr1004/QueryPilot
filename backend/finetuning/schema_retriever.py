from functools import lru_cache

import numpy as np

from sentence_transformers import SentenceTransformer

from finetuning.spider_context import (
    build_database_metadata,
)


# ============================================================
# EMBEDDING MODEL
# ============================================================

model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# ============================================================
# TABLE DESCRIPTION
# ============================================================

def build_table_description(
    database_name: str,
    table_name: str,
):
    """
    Build a semantic description of one table for retrieval.
    """

    metadata = build_database_metadata(
        database_name
    )

    table_info = metadata[
        "tables"
    ][
        table_name
    ]

    parts = [
        f"Database: {database_name}",
        f"Table: {table_name}",
        "Columns:",
    ]

    for column_name in table_info["columns"]:

        column_type = (
            table_info[
                "column_types"
            ][
                column_name
            ]
        )

        parts.append(
            f"{column_name} ({column_type})"
        )

    return " ".join(parts)


# ============================================================
# CACHE TABLE EMBEDDINGS
# ============================================================

@lru_cache(maxsize=None)
def get_table_embedding_bundle(
    database_name: str,
):
    """
    Return table names + normalized table embeddings for one DB.
    """

    metadata = build_database_metadata(
        database_name
    )

    table_names = list(
        metadata["tables"].keys()
    )

    descriptions = [
        build_table_description(
            database_name,
            table_name,
        )
        for table_name in table_names
    ]

    embeddings = model.encode(
        descriptions,
        normalize_embeddings=True,
    )

    return (
        table_names,
        descriptions,
        embeddings,
    )


# ============================================================
# SEMANTIC TABLE RETRIEVAL
# ============================================================

def retrieve_relevant_tables(
    question: str,
    database_name: str,
    top_k: int = 3,
    include_all_if_at_most: int = 5,
):
    """
    Retrieve semantically relevant tables.

    Small schemas are kept whole because retrieval adds little
    benefit and can accidentally remove a required table.

    Larger schemas use semantic ranking.
    """

    (
        table_names,
        descriptions,
        table_embeddings,
    ) = get_table_embedding_bundle(
        database_name
    )

    total_tables = len(
        table_names
    )

    # --------------------------------------------------------
    # Small schema: keep everything.
    # --------------------------------------------------------

    if total_tables <= include_all_if_at_most:

        return [
            {
                "table_name": table_name,
                "score": None,
                "description": description,
            }
            for table_name, description
            in zip(
                table_names,
                descriptions,
            )
        ]

    # --------------------------------------------------------
    # Large schema: semantic ranking.
    # --------------------------------------------------------

    question_embedding = model.encode(
        question,
        normalize_embeddings=True,
    )

    scores = np.dot(
        table_embeddings,
        question_embedding,
    )

    ranking = np.argsort(
        -scores
    )

    limit = min(
        top_k,
        total_tables,
    )

    results = []

    for index in ranking[:limit]:

        results.append(
            {
                "table_name": table_names[index],
                "score": float(scores[index]),
                "description": descriptions[index],
            }
        )

    return results


# ============================================================
# FOREIGN-KEY NEIGHBOUR GRAPH
# ============================================================

def build_fk_adjacency(
    database_name: str,
):
    """
    Build an undirected table-level FK graph.

    Example:

        student <-> advisor <-> instructor
    """

    metadata = build_database_metadata(
        database_name
    )

    adjacency = {
        table_name: set()
        for table_name
        in metadata["tables"]
    }

    for relationship in (
        metadata["foreign_keys"]
    ):

        source_table = relationship[
            "source_table"
        ]

        target_table = relationship[
            "target_table"
        ]

        adjacency[
            source_table
        ].add(
            target_table
        )

        adjacency[
            target_table
        ].add(
            source_table
        )

    return adjacency


# ============================================================
# SEMANTIC + FK RETRIEVAL
# ============================================================

def retrieve_relevant_tables_with_fk(
    question: str,
    database_name: str,
    top_k: int = 3,
    include_all_if_at_most: int = 5,
):
    """
    First perform semantic retrieval.

    Then add every table that is directly connected by a
    foreign-key relationship to one of the semantically
    retrieved tables.

    Semantic tables remain first in ranking order.
    FK neighbours are appended afterward.
    """

    semantic_results = retrieve_relevant_tables(
        question=question,
        database_name=database_name,
        top_k=top_k,
        include_all_if_at_most=include_all_if_at_most,
    )

    metadata = build_database_metadata(
        database_name
    )

    # Small schemas already return every table.
    if (
        len(metadata["tables"])
        <= include_all_if_at_most
    ):
        return semantic_results

    adjacency = build_fk_adjacency(
        database_name
    )

    final_results = list(
        semantic_results
    )

    selected_names = {
        item["table_name"]
        for item in semantic_results
    }

    # Preserve deterministic table order.
    table_order = {
        table_name: index
        for index, table_name
        in enumerate(
            metadata["tables"].keys()
        )
    }

    neighbours = set()

    for table_name in selected_names:

        neighbours.update(
            adjacency.get(
                table_name,
                set(),
            )
        )

    neighbours -= selected_names

    for table_name in sorted(
        neighbours,
        key=lambda name: table_order[name],
    ):

        final_results.append(
            {
                "table_name": table_name,
                "score": None,
                "description": (
                    build_table_description(
                        database_name,
                        table_name,
                    )
                ),
                "retrieval_source": "fk_neighbor",
            }
        )

    # Mark original semantic results too.
    normalized_results = []

    for item in final_results:

        item = dict(item)

        item.setdefault(
            "retrieval_source",
            "semantic",
        )

        normalized_results.append(
            item
        )

    return normalized_results



# ============================================================
# SEMANTIC + MULTI-HOP FK RETRIEVAL
# ============================================================

def retrieve_relevant_tables_with_fk_hops(
    question: str,
    database_name: str,
    top_k: int = 3,
    fk_hops: int = 2,
    include_all_if_at_most: int = 5,
):
    """
    Perform semantic retrieval first, then expand through the
    table-level foreign-key graph for up to fk_hops steps.

    Example:

        tracks
          -> invoice_lines
          -> invoices
          -> customers

    A multi-hop expansion can recover bridge/end tables that
    direct one-hop expansion misses.
    """

    semantic_results = retrieve_relevant_tables(
        question=question,
        database_name=database_name,
        top_k=top_k,
        include_all_if_at_most=include_all_if_at_most,
    )

    metadata = build_database_metadata(
        database_name
    )

    # Small schemas already contain every table.
    if (
        len(metadata["tables"])
        <= include_all_if_at_most
    ):
        return [
            {
                **dict(item),
                "retrieval_source": "semantic",
                "fk_distance": 0,
            }
            for item in semantic_results
        ]

    adjacency = build_fk_adjacency(
        database_name
    )

    table_order = {
        table_name: index
        for index, table_name
        in enumerate(
            metadata["tables"].keys()
        )
    }

    selected_names = {
        item["table_name"]
        for item in semantic_results
    }

    final_results = []

    # --------------------------------------------------------
    # Original semantic results
    # --------------------------------------------------------

    for item in semantic_results:

        normalized = dict(item)

        normalized[
            "retrieval_source"
        ] = "semantic"

        normalized[
            "fk_distance"
        ] = 0

        final_results.append(
            normalized
        )

    # --------------------------------------------------------
    # Breadth-first FK expansion
    # --------------------------------------------------------

    visited = set(
        selected_names
    )

    frontier = set(
        selected_names
    )

    for hop in range(
        1,
        fk_hops + 1,
    ):

        next_frontier = set()

        for table_name in frontier:

            next_frontier.update(
                adjacency.get(
                    table_name,
                    set(),
                )
            )

        next_frontier -= visited

        for table_name in sorted(
            next_frontier,
            key=lambda name: table_order[name],
        ):

            final_results.append(
                {
                    "table_name": table_name,
                    "score": None,
                    "description": (
                        build_table_description(
                            database_name,
                            table_name,
                        )
                    ),
                    "retrieval_source": (
                        "fk_neighbor"
                    ),
                    "fk_distance": hop,
                }
            )

        visited.update(
            next_frontier
        )

        frontier = (
            next_frontier
        )

        if not frontier:
            break

    return final_results



# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    database_name = "college_2"

    question = (
        "What are the names of students "
        "and the departments they belong to?"
    )

    results = retrieve_relevant_tables(
        question=question,
        database_name=database_name,
        top_k=3,
    )

    print("=" * 80)
    print("PHASE 7.2I.1 - TABLE RETRIEVAL TEST")
    print("=" * 80)

    print()
    print("Database:", database_name)
    print("Question:", question)

    print()
    print("Retrieved tables:")
    print()

    for rank, item in enumerate(
        results,
        1,
    ):

        score = item["score"]

        if score is None:
            score_text = "ALL-SCHEMA"
        else:
            score_text = f"{score:.6f}"

        print(
            f"{rank}. "
            f"{item['table_name']:30} "
            f"{score_text}"
        )

    print()
    print("=" * 80)
    print("✅ TABLE RETRIEVER READY")
    print("=" * 80)
