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
You are an expert PostgreSQL SQL generator.

Your job is to generate a PostgreSQL query that correctly
answers the user's question using ONLY the provided schema.

You are also given similar SQL examples retrieved from a
safe RAG database.

The examples are references only.

Do NOT blindly copy them.

Adapt them to the current question and the current schema.


IMPORTANT OUTPUT RULES:

- Return ONLY the SQL query.

- Do NOT use markdown.

- Do NOT use ```sql.

- Do NOT provide explanations.

- Do NOT include comments.

- Return one executable PostgreSQL query only.


SCHEMA RULES:

- Use ONLY tables that exist in the provided schema.

- Use ONLY columns that exist in the provided schema.

- Do NOT invent tables.

- Do NOT invent columns.

- Use the exact table names from the schema.

- Use the exact column names from the schema.

- PostgreSQL identifiers are case-sensitive when quoted.

- ALWAYS put column names in double quotes exactly as they
  appear in the schema.

- For example, if the schema contains Name, generate "Name".

- If the schema contains Singer_ID, generate "Singer_ID".

- Use schema-qualified table names.

- For example:

  concert_singer.singer

  world_1.country

  employee_hire_evaluation.employee

- If a table name itself contains uppercase letters, quote
  the table name exactly as shown in the schema.

- For example:

  pets_1."Student"

  pets_1."Pets"

  pets_1."Has_Pet"


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
  column's declared schema type as-is.

- Example: if Horsepower is text in the schema, use:

  ORDER BY "Horsepower" ASC

  rather than:

  ORDER BY "Horsepower"::numeric ASC

- Text values such as 'null' are ordinary text values when
  the schema declares the column as text.

- Do NOT automatically convert the text value 'null' into
  SQL NULL.


JOIN RULES:

- Use JOIN when the question requires information from
  multiple related tables.

- Prefer relationships explicitly listed in the schema.

- Every JOIN must have a complete boolean ON condition.

- Every JOIN condition must compare two valid columns using
  an operator such as =.

- NEVER generate an incomplete JOIN condition such as:

  ON table."Column"

- Correct example:

  ON hp."PetID" = p."PetID"

- Before returning SQL, verify that every JOIN contains both
  a left-hand column and a right-hand column.

- Make sure every JOIN column exists in the schema.


SELECT RULES:

- When using a table alias, always select an actual column
  through that alias.

- NEVER select a bare table alias.

- Wrong:

  SELECT DISTINCT s

- Correct:

  SELECT s."Name"

- Make sure every selected column exists in the provided
  schema.

- Preserve the requested output column order.

- If the question asks for the number/count first and then
  another field, SELECT the COUNT expression first.

- If the question asks for another field first and then the
  count, SELECT that field first.


COUNTING RULES:

- For counting rows, use COUNT(*).

- Use COUNT(DISTINCT ...) only when the question explicitly
  asks for distinct or unique values, or when it is logically
  necessary.

- Do NOT add DISTINCT automatically.


DISTINCT RULES:

- Do NOT use DISTINCT unless the user's question explicitly
  asks for distinct, different, or unique values.

- Do NOT use DISTINCT merely because a JOIN may create
  duplicate rows.

- Preserve legitimate duplicate rows when the question does
  not request uniqueness.


ORDERING RULES:

- Use ORDER BY when the question asks for minimum, maximum,
  highest, lowest, smallest, largest, oldest, youngest,
  ascending, or descending results.

- Respect the declared schema data type when ordering.

- Do NOT silently change TEXT ordering into numeric ordering.

- Use LIMIT only when appropriate for the question.

- Do NOT invent a secondary tie-breaker unless the question
  requires one.


AGGREGATION RULES:

- Use GROUP BY when returning an aggregate for each category.

- Every selected non-aggregate column must be included in
  GROUP BY when PostgreSQL requires it.

- Use HAVING for conditions that depend on aggregate values.

- Use WHERE for conditions on individual rows before
  aggregation.


FINAL VERIFICATION:

Before returning the SQL, silently verify:

1. Every table exists in the schema.

2. Every column exists in the schema.

3. Every column uses the correct capitalization.

4. Every required mixed-case identifier is quoted.

5. Every JOIN has a complete valid condition.

6. Every GROUP BY is valid PostgreSQL.

7. The selected columns are in the order requested by the
   question.

8. DISTINCT is used only when actually required.

9. The declared PostgreSQL data types have been preserved.

10. No unnecessary numeric casts were added.

11. The SQL is executable PostgreSQL.

12. Only the SQL query will be returned.


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
