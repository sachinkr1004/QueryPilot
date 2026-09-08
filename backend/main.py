import logging
import uuid
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from db import UnsafeSQLError
from production.pipeline import run_query_pipeline


logger = logging.getLogger("querypilot.api")
logger.setLevel(logging.INFO)


app = FastAPI(
    title="QueryPilot API",
    version="1.0.0",
)


# ============================================================
# API MODELS
# ============================================================

class QueryRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
    )

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Question must not be empty."
            )

        return value


class QueryResponse(BaseModel):
    status: Literal["success"]
    question: str
    database: str
    generated_sql: str
    final_sql: str
    columns: list[str]
    rows: list[list[Any]]
    correction_used: bool
    correction_attempts: int
    review_used: bool
    latency_ms: float


# ============================================================
# RESPONSE HELPERS
# ============================================================

def _error_response(
    status_code: int,
    message: str,
):
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "message": message,
        },
    )


def _run_query(question: str):
    request_id = str(uuid.uuid4())

    try:
        result = run_query_pipeline(question)

        logger.info(
            "event=query_success request_id=%s "
            "database=%s latency_ms=%s "
            "correction_used=%s correction_attempts=%s",
            request_id,
            result["database"],
            result["latency_ms"],
            result["correction_used"],
            result["correction_attempts"],
        )

        return {
            "status": "success",
            "question": question,
            "database": result["database"],
            "generated_sql": result["generated_sql"],
            "final_sql": result["final_sql"],
            "columns": result["columns"],
            "rows": result["result"],
            "correction_used": result["correction_used"],
            "correction_attempts": result[
                "correction_attempts"
            ],
            "review_used": False,
            "latency_ms": result["latency_ms"],
        }

    except UnsafeSQLError as error:
        logger.warning(
            "event=query_failed request_id=%s error_type=%s",
            request_id,
            type(error).__name__,
        )
        return _error_response(
            status_code=500,
            message=(
                "Query could not be completed safely."
            ),
        )

    except RuntimeError as error:
        logger.error(
            "event=query_failed request_id=%s error_type=%s",
            request_id,
            type(error).__name__,
        )
        return _error_response(
            status_code=500,
            message=(
                "Query processing failed."
            ),
        )

    except Exception as error:
        logger.error(
            "event=query_failed request_id=%s error_type=%s",
            request_id,
            type(error).__name__,
        )
        return _error_response(
            status_code=500,
            message=(
                "Internal server error."
            ),
        )


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "QueryPilot backend is running"
    }


# ============================================================
# PRODUCTION QUERY ENDPOINT
# ============================================================

@app.post(
    "/query",
    response_model=QueryResponse,
)
def query(request: QueryRequest):
    return _run_query(
        request.question
    )


# ============================================================
# LEGACY ASK ENDPOINT
# ============================================================

@app.get(
    "/ask",
    response_model=QueryResponse,
)
def ask(question: str):
    question = question.strip()

    if not question:
        return _error_response(
            status_code=422,
            message="Question must not be empty.",
        )

    if len(question) > 1000:
        return _error_response(
            status_code=422,
            message=(
                "Question must be at most "
                "1000 characters."
            ),
        )

    return _run_query(question)
