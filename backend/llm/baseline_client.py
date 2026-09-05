import os

from dotenv import load_dotenv
from groq import Groq


# ============================================================
# ENVIRONMENT + GROQ CLIENT
# ============================================================

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


# ============================================================
# HELPER: CLEAN SQL RETURNED BY LLM
# ============================================================

def clean_sql(sql: str) -> str:

    sql = sql.strip()

    # Remove markdown fences if the model adds them.
    if sql.startswith("```sql"):
        sql = sql[6:]

    if sql.startswith("```"):
        sql = sql[3:]

    if sql.endswith("```"):
        sql = sql[:-3]

    return sql.strip()


# ============================================================
# HELPER: FORMAT RAG EXAMPLES
# ============================================================

def format_examples(examples):

    if not examples:
        return (
            "No similar examples were retrieved. "
            "Generate the SQL using only the schema."
        )

    parts = []

    for index, example in enumerate(
        examples,
        1
    ):

        parts.append(
            f"""
Example {index}

Question:
{example["question"]}

SQL:
{example["sql"]}
""".strip()
        )

    return "\n\n".join(parts)


# ============================================================
# SQL GENERATION
# ============================================================

def generate_sql(
    question: str,
    schema_text: str,
    examples=None
) -> str:

    example_text = format_examples(
        examples
    )

    prompt = f"""
Generate one executable PostgreSQL query answering the
question using ONLY the provided schema and safe RAG examples.
RAG examples are references only; adapt them to the current
question and schema.

Rules:
- Return SQL only: no markdown, explanation, comments, or fences.
- Use only schema tables/columns; never invent identifiers.
- Preserve exact identifier capitalization. Double-quote column
  names exactly as shown. Schema-qualify tables and quote
  mixed-case table names exactly.
- Preserve declared PostgreSQL data types. Never cast text to
  numeric just because values look numeric, and treat textual
  'null' as text when the schema declares text.
- Use JOINs only when needed and prefer schema relationships.
  Every JOIN must have a complete boolean ON condition comparing
  valid columns.
- Select real columns, never bare aliases, and preserve requested
  output-column order.
- Use COUNT(*) for row counts. Use COUNT(DISTINCT ...) or DISTINCT
  only when explicitly requested or logically necessary; do not
  add DISTINCT merely to remove JOIN duplicates.
- Use ORDER BY/LIMIT when required by the question, preserve the
  declared type's ordering semantics, and do not invent secondary
  tie-breakers.
- For aggregates, use valid GROUP BY, HAVING for aggregate
  conditions, and WHERE for row conditions.
- Before returning, verify all identifiers exist, quoting and
  JOIN/GROUP BY syntax are valid, data types are preserved, and
  the SQL answers the question.

DATABASE SCHEMA:
{schema_text}

SAFE RAG EXAMPLES:
{example_text}

USER QUESTION:
{question}

POSTGRESQL SQL:
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_completion_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    sql = (
        response
        .choices[0]
        .message
        .content
    )

    return clean_sql(sql)


# ============================================================
# SQL SELF-CORRECTION
# ============================================================

def correct_sql(
    question: str,
    schema_text: str,
    failed_sql: str,
    error_message: str,
    examples=None
) -> str:

    example_text = format_examples(
        examples
    )

    prompt = f"""
You are an expert PostgreSQL SQL debugger.

A PostgreSQL SQL query failed during execution.

Your job is to correct the SQL using ONLY:

1. The user's original question
2. The provided database schema
3. The PostgreSQL error
4. The safe RAG examples


IMPORTANT OUTPUT RULES:

- Return ONLY the corrected SQL query.

- Do NOT use markdown.

- Do NOT provide explanations.

- Do NOT include comments.

- Return one executable PostgreSQL query only.


SCHEMA RULES:

- Use ONLY tables from the provided schema.

- Use ONLY columns from the provided schema.

- Use exact table names.

- Use exact column names.

- ALWAYS quote column names exactly as shown in the schema.

- Use schema-qualified table names.

- Quote mixed-case table names when necessary.


POSTGRESQL DATA TYPE RULES:

- Respect the PostgreSQL data types exactly as shown in the
  provided schema.

- If a column is defined as text, preserve its text semantics
  unless the user's question explicitly requires numeric
  conversion.

- NEVER cast a text column to numeric merely because its
  values appear numeric.

- Do NOT use CAST(... AS numeric), ::numeric, ::integer,
  or similar conversions unless the question explicitly
  requires numeric conversion.

- For MIN, MAX, ORDER BY, comparisons, and sorting, use the
  declared schema type as-is.

- Text values such as 'null' must remain text values when
  the schema declares that column as text.

- Do NOT automatically interpret the string 'null' as
  SQL NULL.


JOIN RULES:

- Every JOIN must have a complete boolean condition.

- Every JOIN condition must compare valid columns.

- Prefer relationships explicitly listed in the schema.

- Do not invent relationships.


DISTINCT RULES:

- Do NOT add DISTINCT unless the question requires unique
  or distinct values.

- Preserve duplicate rows when duplicates are legitimate.


SELECT ORDER RULES:

- Preserve the output order requested by the question.

- If the question asks for count first, put COUNT first.

- If the question asks for another field first, put that
  field first.


CORRECTION RULES:

- Fix the PostgreSQL error shown below.

- Do not change unrelated parts of a query that are already
  correct.

- Do not introduce unnecessary type casts.

- Do not introduce arbitrary tie-breakers.

- Make sure the final SQL is valid PostgreSQL.


DATABASE SCHEMA:

{schema_text}


SAFE RAG EXAMPLES:

{example_text}


ORIGINAL QUESTION:

{question}


FAILED SQL:

{failed_sql}


POSTGRESQL ERROR:

{error_message}


CORRECTED POSTGRESQL SQL:
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_completion_tokens=1000,
        temperature=0,
        seed=42,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    sql = (
        response
        .choices[0]
        .message
        .content
    )

    return clean_sql(sql)


# ============================================================
# SQL SEMANTIC REVIEW
# ============================================================

def review_sql_semantics(
    question: str,
    schema_text: str,
    sql: str,
    examples=None,
) -> str:
    """
    Review an executable SQL query for semantic mistakes.

    Unlike correct_sql(), this function is NOT for database
    execution errors. It checks whether the SQL actually
    matches the user's intent.

    If the SQL is already semantically correct, return it
    unchanged.

    If there is a concrete semantic mismatch, return one
    corrected executable PostgreSQL query.
    """

    example_text = format_examples(
        examples
    )

    prompt = f"""

You are an expert PostgreSQL SQL semantic reviewer.

The SQL query below is already executable PostgreSQL.

Your job is to verify whether it correctly answers the
user's original question using ONLY:

1. The user's question
2. The provided database schema
3. The executable SQL query
4. The safe RAG examples


IMPORTANT:

Do NOT rewrite the query unless there is a concrete semantic
mistake.

You must make one explicit decision:

KEEP
or
REWRITE


If the SQL correctly answers the question, return exactly:

KEEP


If there is a concrete semantic mismatch, return:

REWRITE
<corrected SQL>


A concrete semantic mismatch means the existing SQL clearly
contradicts the user's request, for example:

- wrong comparison direction
- missing requested output field
- missing required table or relationship
- incorrect grouping level
- incorrect aggregate operation
- singular-result intent incorrectly returning multiple rows

Do NOT rewrite merely because another SQL formulation looks
cleaner or more conventional.

Do NOT change duplicate semantics unless the user explicitly
requests unique or distinct results.


IMPORTANT OUTPUT RULES:

- Return either KEEP or REWRITE followed by one SQL query.
- Do NOT use markdown.
- Do NOT provide explanations.
- Do NOT include comments.


SEMANTIC CHECKS:

- Verify comparison direction carefully.

Examples:

  "under 30"
      means < 30

  "older than 30"
      means > 30

  "at least 3"
      means >= 3

  "more than 3"
      means > 3


- Verify requested output fields.

If the question asks for:

  continent id,
  continent name,
  number of countries

then the SQL must return those requested fields.


- Verify required tables and joins.

If a requested attribute belongs to another table,
use the necessary relationship from the schema.


- Verify grouping semantics.

For questions containing phrases such as:

  each
  every
  per
  for each

make sure the SQL groups at the correct entity level.


- Verify aggregate semantics.

COUNT, MIN, MAX, AVG, SUM and GROUP BY must match the
question exactly.


- Verify singular result intent.

If the question clearly asks for one entity such as:

  "Which model has the minimum horsepower?"
  "What is the highest..."
  "Which employee has the largest..."

then prefer a query that returns one best row when that is
the intended benchmark semantics, for example using:

  ORDER BY ... ASC/DESC
  LIMIT 1

Do NOT return all tied rows unless the question explicitly
asks for all ties.


IMPORTANT SINGULAR EXTREMUM RULE:

When the question clearly asks for ONE entity associated with
a minimum or maximum value, for example:

  "Which model has the minimum horsepower?"
  "Which employee has the highest bonus?"
  "What car has the lowest weight?"

then a query of the form:

  WHERE column = (SELECT MIN(column) ...)
  WHERE column = (SELECT MAX(column) ...)

may return multiple tied rows.

If the question asks for one entity and does NOT explicitly
ask for all tied entities, such a query is a CONCRETE
SEMANTIC MISMATCH when it has no mechanism that limits the
answer to one row.

In that situation you MUST choose REWRITE and prefer:

  ORDER BY column ASC LIMIT 1

for minimum / lowest / smallest, or:

  ORDER BY column DESC LIMIT 1

for maximum / highest / largest.

Respect the declared schema data type when ordering.

Do NOT introduce numeric casts merely to implement this rule.


- Do NOT add DISTINCT unless the question requires unique
  values or DISTINCT is logically necessary.


POSTGRESQL DATA TYPE RULES:

- Respect the declared PostgreSQL data type exactly as shown
  in the provided schema.

- If a column is defined as text, preserve its text semantics
  unless the user's question explicitly requires numeric
  conversion.

- NEVER cast a text column to numeric merely because its
  values appear numeric.

- Do NOT use CAST(... AS numeric),
  CAST(... AS double precision),
  ::numeric,
  ::integer,
  ::double precision,
  or similar conversions unless the question explicitly
  requires numeric conversion.

- For MIN, MAX, ORDER BY, comparisons, and sorting, use the
  declared schema type as-is.

- Text values such as 'null' are ordinary text values when
  the schema declares the column as text.

- Do NOT automatically interpret the string 'null' as
  SQL NULL.


SCHEMA RULES:

- Use ONLY tables and columns present in the schema.
- Use exact PostgreSQL identifiers from the schema.
- Quote column names exactly when required.
- Use schema-qualified table names.
- Prefer relationships explicitly listed in the schema.


DATABASE SCHEMA:

{schema_text}


SAFE RAG EXAMPLES:

{example_text}


ORIGINAL QUESTION:

{question}


EXECUTABLE SQL TO REVIEW:

{sql}


REVIEW DECISION:

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

    review_response = (
        response
        .choices[0]
        .message
        .content
    )

    review_response = (
        review_response.strip()
    )

    # --------------------------------------------------------
    # KEEP
    # --------------------------------------------------------

    if review_response.upper() == "KEEP":
        return sql

    # --------------------------------------------------------
    # REWRITE
    # --------------------------------------------------------

    if review_response.upper().startswith(
        "REWRITE"
    ):
        rewritten_sql = (
            review_response[
                len("REWRITE"):
            ]
            .strip()
        )

        rewritten_sql = clean_sql(
            rewritten_sql
        )

        if not rewritten_sql:
            raise ValueError(
                "Semantic reviewer returned REWRITE "
                "without SQL."
            )

        return rewritten_sql

    # --------------------------------------------------------
    # INVALID REVIEW RESPONSE
    # --------------------------------------------------------

    raise ValueError(
        "Invalid semantic-review response. "
        "Expected KEEP or REWRITE. "
        f"Received: {review_response!r}"
    )
