from finetuning.spider_context import (
    build_database_metadata,
)

from finetuning.schema_retriever import (
    retrieve_relevant_tables,
    retrieve_relevant_tables_with_fk_hops,
)

from finetuning.value_retriever import (
    retrieve_relevant_values,
    format_value_context,
)

from llm.retrieve_examples import (
    retrieve_examples,
)

from llm.baseline_client import (
    format_examples,
)


# ============================================================
# BUILD RETRIEVED SCHEMA TEXT
# ============================================================

def build_retrieved_schema_text(
    database_name,
    table_names,
):
    metadata = build_database_metadata(
        database_name
    )

    selected = set(table_names)

    lines = [
        f"DATABASE: {database_name}",
        "",
        "TABLES:",
    ]

    for table_name in table_names:

        table_info = metadata["tables"][
            table_name
        ]

        lines.append("")
        lines.append(
            f"TABLE: {table_name}"
        )

        primary_keys = set(
            table_info.get(
                "primary_keys",
                []
            )
        )

        for column_name in table_info[
            "columns"
        ]:
            column_type = table_info[
                "column_types"
            ][column_name]

            suffix = ""

            if column_name in primary_keys:
                suffix = " PRIMARY KEY"

            lines.append(
                f"  {column_name} "
                f"({column_type})"
                f"{suffix}"
            )

    relationships = []

    for fk in metadata["foreign_keys"]:

        if (
            fk["source_table"] in selected
            and
            fk["target_table"] in selected
        ):
            relationships.append(
                (
                    f'{fk["source_table"]}.'
                    f'{fk["source_column"]}'
                    " -> "
                    f'{fk["target_table"]}.'
                    f'{fk["target_column"]}'
                )
            )

    if relationships:
        lines.extend([
            "",
            "RELATIONSHIPS:",
        ])

        for relationship in relationships:
            lines.append(
                f"  {relationship}"
            )

    return "\n".join(lines)


# ============================================================
# BUILD PHASE-8 RETRIEVAL CONTEXT
# ============================================================

def build_phase8_retrieval_context(
    question,
    database_name,
    top_k=7,
    fk_expansion=True,
    fk_hops=2,
    value_grounding=True,
    rag_examples=True,
    rag_limit=5,
):

    # --------------------------------------------------------
    # TABLE RETRIEVAL
    # --------------------------------------------------------

    if fk_expansion:

        table_results = (
            retrieve_relevant_tables_with_fk_hops(
                question=question,
                database_name=database_name,
                top_k=top_k,
                fk_hops=fk_hops,
            )
        )

    else:

        table_results = (
            retrieve_relevant_tables(
                question=question,
                database_name=database_name,
                top_k=top_k,
            )
        )

    table_names = [
        item["table_name"]
        for item in table_results
    ]

    # --------------------------------------------------------
    # RETRIEVED-ONLY SCHEMA
    # --------------------------------------------------------

    schema_text = (
        build_retrieved_schema_text(
            database_name=database_name,
            table_names=table_names,
        )
    )

    # --------------------------------------------------------
    # VALUE GROUNDING
    # --------------------------------------------------------

    value_matches = []
    value_text = ""

    if value_grounding:

        value_matches = (
            retrieve_relevant_values(
                question=question,
                database_name=database_name,
                table_names=table_names,
            )
        )

        value_text = format_value_context(
            value_matches
        )

    # --------------------------------------------------------
    # RAG EXAMPLES
    # --------------------------------------------------------

    examples = []
    example_text = ""

    if rag_examples:

        examples = retrieve_examples(
            question=question,
            database_name=database_name,
            limit=rag_limit,
        )

        example_text = format_examples(
            examples
        )

    # --------------------------------------------------------
    # FINAL INPUT CONTEXT
    # --------------------------------------------------------

    sections = [
        "DATABASE SCHEMA:",
        "",
        schema_text,
    ]

    if value_grounding:
        sections.extend([
            "",
            "",
            "RELEVANT DATABASE VALUES:",
            "",
            value_text,
        ])

    if rag_examples:
        sections.extend([
            "",
            "",
            "SAFE RAG EXAMPLES:",
            "",
            example_text,
        ])

    sections.extend([
        "",
        "",
        "USER QUESTION:",
        "",
        question,
    ])

    input_context = "\n".join(
        sections
    ).strip()

    return {
        "database_name": database_name,
        "table_results": table_results,
        "table_names": table_names,
        "schema_text": schema_text,
        "value_matches": value_matches,
        "value_text": value_text,
        "examples": examples,
        "example_text": example_text,
        "input_context": input_context,
        "config": {
            "top_k": top_k,
            "fk_expansion": fk_expansion,
            "fk_hops": fk_hops,
            "value_grounding": value_grounding,
            "rag_examples": rag_examples,
            "rag_limit": rag_limit,
        },
    }
