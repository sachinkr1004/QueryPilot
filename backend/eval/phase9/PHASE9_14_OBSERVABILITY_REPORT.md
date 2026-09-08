# Phase 9.14 — Observability & Diagnostics

## Status

VALIDATED

## Goal

Add safe request-level production observability without changing the
existing QueryPilot API contract or exposing sensitive query-processing
details.

## Production Changes

Phase 9.14 adds request-level logging at the FastAPI boundary in
`main.py`.

Each processed query receives an internal UUID request ID.

Successful requests emit an INFO event containing:

- event type
- request ID
- selected database
- total pipeline latency
- whether correction was used
- number of correction attempts

Failed requests emit a WARNING or ERROR event containing:

- event type
- request ID
- exception type

The application logger is named `querypilot.api` and is configured at
INFO level while continuing to propagate records to the surrounding
logging environment.

## Sensitive Data Policy

The new request logs intentionally do not include:

- user question text
- generated SQL
- final SQL
- result rows
- raw exception messages
- database error details
- credentials or API keys

`logger.exception()` is not used because traceback or exception content
could expose generated SQL or database details.

## Request ID Scope

The request ID is currently an internal diagnostic correlation ID.

It is not added to the public API response or response headers in Phase
9.14, preserving the Phase 9.13 API contract. External request-ID
exposure can be reconsidered during Phase 9.18 API contract freeze.

## Dedicated Observability Validation

Command:

`PYTHONPATH=. python eval/phase9/run_observability_suite.py`

Result:

- success metadata logging: PASS
- unique request IDs: PASS
- sensitive success payload exclusion: PASS
- UnsafeSQLError logging safety: PASS
- RuntimeError logging safety: PASS
- unexpected exception logging safety: PASS

Total: 6/6 PASS.

## API Contract Regression

Command:

`PYTHONPATH=. python eval/phase9/run_api_contract_suite.py`

Result:

10/10 PASS.

The Phase 9.13 API response contract remains unchanged.

## Deterministic Regression Validation

SQL safety:

`PYTHONPATH=. python eval/phase9/run_sql_safety_suite.py`

Result: 39/39 PASS.

Self-correction:

`PYTHONPATH=. python eval/phase9/run_self_correction_suite.py`

Result: 5/5 PASS.

LLM client reliability:

`PYTHONPATH=. python eval/phase9/run_llm_reliability_suite.py`

Result: 21/21 PASS.

Combined deterministic regression result: 65/65 PASS.

## Additional Validation

- `python -m py_compile main.py eval/phase9/run_observability_suite.py`
  passed.
- `git diff --check` passed.
- No production pipeline, SQL safety, self-correction, retrieval, RAG,
  prompt, model, or database behavior was changed.

## Known Non-Blocking Warnings

Existing Starlette TestClient/httpx deprecation warnings and
unauthenticated Hugging Face Hub warnings were observed during testing.
They are unrelated to the Phase 9.14 observability change and were not
addressed in this phase.

## Conclusion

Phase 9.14 adds safe, minimal request-level observability while
preserving the validated production behavior from earlier Phase 9
milestones.

Validation summary:

- Observability: 6/6 PASS
- API contract: 10/10 PASS
- Deterministic regressions: 65/65 PASS
- Sensitive log leakage detected: none
- API contract regression detected: none
