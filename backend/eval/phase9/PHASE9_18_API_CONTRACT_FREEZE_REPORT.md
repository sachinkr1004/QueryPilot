# Phase 9.18 — API Contract Freeze Report

## Status

**PASS — QueryPilot API v1.0.0 contract frozen.**

Phase 9.18 freezes the validated public API surface of QueryPilot without changing production pipeline behavior.

No production code, model configuration, prompt configuration, schema routing, RAG behavior, SQL safety behavior, database execution behavior, or self-correction behavior was changed in this phase.

---

## API Identity

- Title: `QueryPilot API`
- Version: `1.0.0`

The identity was verified from FastAPI's generated OpenAPI schema.

---

## Frozen Public Endpoints

The frozen public endpoints are:

- `GET /` — root/backend availability endpoint.
- `POST /query` — primary production natural-language query endpoint.
- `GET /ask` — legacy compatibility endpoint.

The root endpoint returns `{"message":"QueryPilot backend is running"}`.

---

## POST /query Request Contract

The request body contains one required field:

- `question`: string
- Minimum declared length: 1 character
- Maximum length: 1000 characters
- Leading and trailing whitespace is removed
- Whitespace-only input is rejected with HTTP 422
- Missing `question` is rejected with HTTP 422
- Input longer than 1000 characters is rejected with HTTP 422

---

## Frozen Successful Query Response

The successful response contains exactly these 11 required public fields:

1. `status`
2. `question`
3. `database`
4. `generated_sql`
5. `final_sql`
6. `columns`
7. `rows`
8. `correction_used`
9. `correction_attempts`
10. `review_used`
11. `latency_ms`

Frozen field types:

- `status`: string constrained to `"success"`
- `question`: string
- `database`: string
- `generated_sql`: string
- `final_sql`: string
- `columns`: array of strings
- `rows`: array of arrays
- `correction_used`: boolean
- `correction_attempts`: integer
- `review_used`: boolean
- `latency_ms`: number

`review_used` remains `false` in the production API because semantic review is intentionally not part of the production hot path.

---

## Validation Error Policy

For `POST /query`, HTTP 422 is frozen for invalid request input.

The complete FastAPI/Pydantic generated validation-error JSON is intentionally not frozen byte-for-byte. This avoids coupling QueryPilot to framework-internal formatting while preserving the intended HTTP validation behavior.

For legacy `GET /ask`, whitespace-only and oversized questions return HTTP 422 with application-generated safe error messages.

---

## Frozen Runtime Error Contract

Production runtime failures expose safe generic responses rather than internal exception details.

- Unsafe SQL: HTTP 500 with `"Query could not be completed safely."`
- Query-processing failure: HTTP 500 with `"Query processing failed."`
- Unexpected internal failure: HTTP 500 with `"Internal server error."`

Each runtime error response contains only `status: "error"` and the corresponding safe `message`.

The contract tests verify that underlying exception details are not returned to the client.

---

## Legacy Compatibility

`GET /ask` remains part of QueryPilot API v1.0.0 for backward compatibility.

It accepts the `question` query parameter, trims surrounding whitespace, and returns the same successful `QueryResponse` structure as `POST /query`.

---

## Internal Observability Boundary

The API creates an internal UUID request identifier for logging.

The request identifier is intentionally not included in the public response and is therefore not part of the QueryPilot v1.0.0 API contract.

Logs retain safe operational metadata without exposing the natural-language question, generated SQL, result rows, raw database errors, credentials, or API keys.

---

## OpenAPI Verification

FastAPI's generated OpenAPI schema was inspected before freezing the contract.

Verified public paths:

- `/` -> `GET`
- `/query` -> `POST`
- `/ask` -> `GET`

Verified schema components:

- `QueryRequest`
- `QueryResponse`

The freeze targets QueryPilot's intentional public semantic contract rather than freezing the entire generated OpenAPI document byte-for-byte.

---

## Phase 9.18 Freeze Validation

Dedicated suite: `eval/phase9/run_api_contract_freeze_suite.py`

Validated:

- API identity
- public routes and HTTP methods
- request schema and length constraints
- complete successful response schema
- `POST /query` runtime behavior
- request validation behavior
- legacy `GET /ask` compatibility
- legacy validation behavior
- safe runtime error behavior
- root endpoint behavior

**Phase 9.18 freeze suite: 10/10 PASS**

---

## Backward Regression Validation

Existing suite: `eval/phase9/run_api_contract_suite.py`

**Existing Phase 9.13 API contract suite: 10/10 PASS**

This confirms that the Phase 9.18 freeze work did not regress previously validated API behavior.

**Combined API validation: 20/20 PASS**

---

## Non-blocking Warnings

Validation emitted existing environment/dependency warnings:

- unauthenticated Hugging Face Hub access warning
- Starlette TestClient/httpx deprecation warning

These warnings did not cause test failures and are not API-contract regressions.

Expected `query_failed` log entries were produced by tests deliberately exercising safe error handling.

---

## Compatibility Policy

QueryPilot API v1.0.0 is frozen at the end of Phase 9.18.

Future changes that remove or rename frozen endpoints, remove required response fields, change frozen field meanings or types, weaken validation, or alter established safe-error behavior require explicit API compatibility review.

Additive internal implementation changes that preserve this public contract do not by themselves require an API version change.

---

## Phase 9.18 Decision

**ACCEPTED.**

The existing production API is retained without modification.

QueryPilot now has an explicit, deterministic, regression-tested v1.0.0 public API contract.

Phase 9.18 is ready to be frozen after Git validation and commit.
