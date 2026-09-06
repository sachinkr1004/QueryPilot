import time

from db import (
    UnsafeSQLError,
    execute_query_with_columns,
)

from llm.baseline_client import (
    generate_sql,
    correct_sql,
)
from llm.retrieve_schema import retrieve_schema
from llm.retrieve_examples import retrieve_examples


# ============================================================
# PRODUCTION PIPELINE CONFIGURATION
# ============================================================

RAG_TOP_K = 5
MAX_CORRECTION_ATTEMPTS = 1


# ============================================================
# QUERY PIPELINE
# ============================================================

def run_query_pipeline(question: str):
    pipeline_started_at = time.perf_counter()

    # --------------------------------------------------------
    # Step 1: Retrieve database + schema
    # --------------------------------------------------------

    database_name, schema_text, distance = retrieve_schema(
        question
    )

    # --------------------------------------------------------
    # Step 2: Retrieve SAFE Top-K RAG examples
    # --------------------------------------------------------

    examples = retrieve_examples(
        question,
        database_name,
        limit=RAG_TOP_K,
    )

    # --------------------------------------------------------
    # Step 3: Generate initial SQL
    # --------------------------------------------------------

    generated_sql = generate_sql(
        question,
        schema_text,
        examples,
    )

    corrected_sql = None
    correction_used = False
    correction_attempts = 0
    original_error = None
    final_sql = generated_sql
    columns = []

    # --------------------------------------------------------
    # Step 4: Execute initial SQL
    # --------------------------------------------------------

    try:
        columns, result = execute_query_with_columns(
            generated_sql
        )

    except UnsafeSQLError:
        # Safety-policy violations are not SQL debugging errors.
        # Fail closed instead of asking the LLM to rewrite them.
        raise
    except Exception as execution_error:

        original_error = str(
            execution_error
        )

        last_error = original_error
        failed_sql = generated_sql
        result = None

        # ----------------------------------------------------
        # Step 5: Controlled self-correction
        # ----------------------------------------------------

        while (
            correction_attempts
            < MAX_CORRECTION_ATTEMPTS
        ):
            correction_attempts += 1
            correction_used = True

            corrected_sql = correct_sql(
                question=question,
                schema_text=schema_text,
                failed_sql=failed_sql,
                error_message=last_error,
                examples=examples,
            )

            final_sql = corrected_sql

            # ------------------------------------------------
            # Step 6: Execute corrected SQL
            # ------------------------------------------------

            try:
                columns, result = execute_query_with_columns(
                    corrected_sql
                )
                break

            except Exception as corrected_error:
                last_error = str(
                    corrected_error
                )
                failed_sql = corrected_sql

        # ----------------------------------------------------
        # Step 7: Correction failed
        # ----------------------------------------------------

        if result is None:
            raise RuntimeError(
                {
                    "message": (
                        "SQL execution failed after "
                        "self-correction."
                    ),
                    "database": database_name,
                    "generated_sql": generated_sql,
                    "corrected_sql": corrected_sql,
                    "correction_attempts": (
                        correction_attempts
                    ),
                    "error": last_error,
                }
            )

    # --------------------------------------------------------
    # Step 8: Structured pipeline result
    # --------------------------------------------------------

    return {
        "question": question,
        "database": database_name,
        "schema_distance": float(distance),
        "rag_examples_used": len(examples),
        "generated_sql": generated_sql,
        "correction_used": correction_used,
        "correction_attempts": correction_attempts,
        "original_error": original_error,
        "corrected_sql": corrected_sql,
        "final_sql": final_sql,
        "columns": columns,
        "result": result,
        "latency_ms": round(
            (time.perf_counter() - pipeline_started_at) * 1000,
            2,
        ),
    }
