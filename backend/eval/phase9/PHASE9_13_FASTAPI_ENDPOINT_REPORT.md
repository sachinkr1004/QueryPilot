# Phase 9.13 — Production FastAPI Endpoint

## Status

COMPLETE — validated locally before Git freeze.

## Goal

Expose the validated QueryPilot production pipeline through a stable,
frontend-ready FastAPI endpoint while preserving existing SQL safety,
self-correction, model reliability, and database protections.

## Production API

### POST /query

The new production endpoint accepts a JSON request containing a required
question and returns structured query results.

Successful responses expose:

- status
- question
- database
- generated_sql
- final_sql
- columns
- rows
- correction_used
- correction_attempts
- review_used
- latency_ms

Semantic review remains disabled on the production hot path, so
`review_used` is currently `false`.

### Legacy GET /ask

The existing GET `/ask` endpoint was preserved for backward compatibility
and routed through the same safe response layer.

## Input Validation

The production POST endpoint uses Pydantic validation.

Validated rules:
- question is required
- whitespace-only questions are rejected
- maximum question length is 1000 characters
- surrounding whitespace is removed

Invalid request bodies return HTTP 422 before the production query
pipeline is invoked.

## Safe Error Boundary

Internal pipeline details are not returned directly to API clients.
Generic safe responses are returned for unsafe SQL, pipeline failures,
and unexpected internal exceptions.

Tests explicitly verify that injected internal and database error text
is not leaked in HTTP response bodies.

## Column-Aware Database Execution

A shared internal database execution path now returns both columns and rows.
The existing `execute_query(sql)` remains backward compatible and continues
to return rows only.

The production pipeline uses `execute_query_with_columns(sql)` to expose
column metadata through the API.

Existing database protections remain unchanged:
- SQL safety validation
- PostgreSQL read-only session
- 10-second statement timeout
- cursor cleanup
- connection cleanup

## Pipeline Latency

The production pipeline measures total latency with `time.perf_counter()`.
The measurement covers retrieval, RAG, LLM generation, database execution,
and self-correction when required.

## Real Pipeline Validation

Question: `What pets do students have?`

Direct production-pipeline validation succeeded with:
- database: `pets_1`
- columns: `Fname`, `LName`, `PetType`, `pet_age`, `weight`
- 3 result rows
- correction used: false
- correction attempts: 0
- latency: 2210.31 ms

This confirmed real PostgreSQL column extraction and latency reporting.

## Real HTTP End-to-End Validation

A real Uvicorn server was started and `POST /query` was called with curl.

Observed result:
- HTTP request completed successfully
- status: success
- database: `pets_1`
- columns: `Fname`, `PetType`
- 3 rows returned
- correction used: true
- correction attempts: 1
- review used: false
- latency: 2923.49 ms

The real HTTP smoke test exercised the production correction path and
completed with a valid structured JSON response.

A real whitespace-only POST request returned HTTP 422, confirming
request validation at the HTTP boundary.

## API Contract Suite

Permanent suite: `eval/phase9/run_api_contract_suite.py`

Result: 10/10 PASS.

The suite validates success responses, legacy compatibility, request
validation, JSON row serialization, and safe error handling without
leaking injected internal error details.

## Regression Validation

- Phase 9.9 SQL safety: 39/39 PASS
- Phase 9.10 self-correction: 5/5 PASS
- Phase 9.11 LLM reliability: 21/21 PASS
- Core deterministic total: 65/65 PASS
- Phase 9.13 API contract: 10/10 PASS

No evidence of regression was observed in SQL safety, self-correction,
or frozen LLM-client reliability behavior.

## Non-Blocking Warnings

Testing showed an unauthenticated Hugging Face Hub warning and a
Starlette TestClient deprecation warning for the current httpx integration.
Neither warning caused a test failure, so dependencies were not changed
merely to suppress them.

## Conclusion

Phase 9.13 adds a validated production FastAPI boundary around QueryPilot.
The backend now exposes a structured POST query interface with input
validation, columns, rows, correction metadata, review status, latency,
and safe error handling while preserving previously validated safety,
self-correction, database, and model-client behavior.
