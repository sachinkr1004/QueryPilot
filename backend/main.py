from fastapi import FastAPI

from db import execute_query

from llm.baseline_client import generate_sql, correct_sql

from llm.retrieve_schema import retrieve_schema

app = FastAPI()


@app.get("/")
def read_root():
    return {"message": "QueryPilot backend is running"}


@app.get("/ask")
def ask(question: str):

    # Step 1: Retrieve the most relevant database schema
    database_name, schema_text, distance = retrieve_schema(question)

    # Step 2: Generate SQL
    sql = generate_sql(question, schema_text)

    corrected_sql = None
    correction_used = False

    # Step 3: Try executing the generated SQL
    try:
        result = execute_query(sql)

    except Exception as e:

        # Step 4: If SQL fails, send the failed SQL + error to the LLM
        corrected_sql = correct_sql(
            question,
            schema_text,
            sql,
            str(e)
        )

        correction_used = True

        # Step 5: Execute the corrected SQL
        result = execute_query(corrected_sql)

    # Step 6: Return everything
    return {
        "question": question,
        "database": database_name,
        "generated_sql": sql,
        "correction_used": correction_used,
        "corrected_sql": corrected_sql,
        "result": result
    }
