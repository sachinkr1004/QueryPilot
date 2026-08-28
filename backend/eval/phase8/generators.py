from llm.baseline_client import (
    client,
    clean_sql,
    format_examples,
)


# ============================================================
# PHASE-8 BASELINE GENERATOR
# ============================================================

def generate_phase8_baseline_sql(
    question,
    context,
):
    """
    Phase-8 production-style baseline generator.

    Important:
    - Does NOT accept gold SQL.
    - Uses only inference-time information.
    - Supports configurable retrieved schema.
    - Supports value grounding ON/OFF.
    - Supports RAG examples ON/OFF.
    """

    schema_text = context["schema_text"]
    value_text = context["value_text"]
    examples = context["examples"]

    example_text = format_examples(
        examples
    )

    value_section = (
        value_text
        if value_text
        else (
            "No relevant database values "
            "were provided."
        )
    )

    prompt = f"""
You are an expert PostgreSQL SQL generator.

Your job is to generate a PostgreSQL query that correctly
answers the user's question using ONLY the provided
retrieved database schema, relevant database values,
and safe RAG examples.

The examples are references only.
Do NOT blindly copy them.
Adapt them to the current question and schema.


IMPORTANT OUTPUT RULES:

- Return ONLY the SQL query.
- Do NOT use markdown.
- Do NOT provide explanations.
- Do NOT include comments.
- Return one executable PostgreSQL query only.


SCHEMA RULES:

- Use ONLY tables present in the provided schema.
- Use ONLY columns present in the provided schema.
- Do NOT invent tables or columns.
- Use exact table and column names.
- Quote PostgreSQL mixed-case identifiers correctly.
- Use schema-qualified table names.


VALUE RULES:

- Use provided relevant database values only when they
  are actually required by the user's question.
- Do NOT invent database values.
- Do NOT force a retrieved value into the SQL when it
  does not match the user's intent.


POSTGRESQL DATA TYPE RULES:

- Respect declared PostgreSQL data types.
- Do NOT introduce unnecessary numeric casts.
- Preserve text semantics for text columns.
- Treat textual 'null' as text when appropriate.


JOIN RULES:

- Use JOIN when multiple related tables are required.
- Prefer relationships explicitly shown in the schema.
- Every JOIN must contain a complete boolean ON condition.
- Do NOT invent relationships.


AGGREGATION RULES:

- Use COUNT, MIN, MAX, AVG, SUM and GROUP BY according
  to the user's requested semantics.
- Use HAVING for aggregate conditions.
- Use WHERE for row-level conditions.


DISTINCT RULES:

- Do NOT add DISTINCT unless the question explicitly
  requires distinct/unique results or it is logically
  necessary.


ORDERING RULES:

- Use ORDER BY / LIMIT only when required by the question.
- Preserve the declared data type while ordering.
- Do NOT invent unnecessary tie-breakers.


FINAL VERIFICATION:

Before returning SQL, silently verify:

1. Every table exists in the provided schema.
2. Every column exists in the provided schema.
3. JOIN conditions are valid.
4. Requested output fields are present and ordered correctly.
5. Aggregation/grouping matches the question.
6. Comparison directions match the question.
7. The SQL is executable PostgreSQL.
8. Return SQL only.


DATABASE SCHEMA:

{schema_text}


RELEVANT DATABASE VALUES:

{value_section}


SAFE RAG EXAMPLES:

{example_text}


USER QUESTION:

{question}


POSTGRESQL SQL:
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_completion_tokens=1000,
        temperature=0,
        seed=42,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    sql = (
        response
        .choices[0]
        .message
        .content
    )

    return clean_sql(sql)
