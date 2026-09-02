from fastapi import FastAPI, HTTPException

from production.pipeline import run_query_pipeline


app = FastAPI()


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "QueryPilot backend is running"
    }


# ============================================================
# ASK ENDPOINT
# ============================================================

@app.get("/ask")
def ask(question: str):
    try:
        return run_query_pipeline(
            question
        )

    except RuntimeError as pipeline_error:
        detail = (
            pipeline_error.args[0]
            if pipeline_error.args
            else {
                "message": "Query pipeline failed."
            }
        )

        raise HTTPException(
            status_code=500,
            detail=detail,
        ) from pipeline_error
