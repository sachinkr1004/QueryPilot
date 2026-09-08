# Phase 9.16 — Fresh Production Smoke + Safety Validation

## Status

**PASS — 92/92 checks passed.**

Phase 9.16 validated the final QueryPilot production path after completion
of the Phase 9 production hardening work.

No model, prompt, router, RAG, self-correction, SQL-safety, database, or
production API behavior was changed to obtain these results.

## Live Production Smoke

A dedicated smoke runner exercised the real production HTTP path:

`POST /query -> FastAPI -> production pipeline -> schema retrieval -> RAG
-> Groq generation -> SQL safety -> PostgreSQL execution -> API response`

Three fresh questions were used. Exact-question overlap was checked against
existing evaluation JSON artifacts before execution.

| Case | Expected database | Result | Correction | Latency |
| --- | --- | --- | --- | ---: |
| Simple SELECT | `concert_singer` | PASS | No | 1275.79 ms |
| Aggregation | `employee_hire_evaluation` | PASS | No | 1084.68 ms |
| JOIN | `car_1` | PASS | No | 1637.11 ms |

Live smoke result: **3/3 PASS**

All three requests:

- returned HTTP 200;
- returned `status=success`;
- routed to the expected database;
- produced non-empty generated and final SQL;
- returned structured columns and rows;
- preserved `review_used=false`;
- completed without self-correction.

## Infrastructure Authentication Incident

The first live smoke attempt stopped on the first case with a provider
`AuthenticationError`.

The failure was isolated using a minimal Groq SDK authentication request,
which independently returned HTTP 401. Local configuration successfully
contained a non-empty Groq-formatted credential, so the failure was
classified as an external credential/authentication issue rather than a
QueryPilot routing, generation, SQL-safety, execution, or API regression.

The credential was replaced locally without exposing it. A subsequent
minimal Groq authentication check succeeded.

The production code, smoke questions, model, prompts, router, and RAG
configuration were left unchanged. The same smoke suite was then rerun and
passed 3/3.

The failed authentication attempt is therefore not counted as a QueryPilot
functional regression.

## Deterministic Regression Validation

| Suite | Passed | Failed |
| --- | ---: | ---: |
| Phase 9.9 SQL safety | 39 | 0 |
| Phase 9.10 self-correction | 5 | 0 |
| Phase 9.11 LLM reliability | 21 | 0 |
| Phase 9.13 API contract | 10 | 0 |
| Phase 9.14 observability | 6 | 0 |
| Phase 9.15 configuration/security | 8 | 0 |
| Live production smoke | 3 | 0 |
| **Total** | **92** | **0** |

## Safety Properties Revalidated

The validation confirmed that:

- unsafe SQL remains blocked;
- PostgreSQL read-only enforcement remains active;
- the statement timeout remains active;
- unsafe initial SQL fails closed;
- unsafe corrected SQL remains blocked;
- self-correction remains limited to one attempt;
- Groq retry and timeout policies remain frozen;
- LLM output token ceilings remain frozen;
- API validation and error contracts remain intact;
- internal errors do not leak through API responses;
- production logs avoid questions, SQL, rows, credentials, and raw errors;
- required configuration fails safely when missing;
- `.env` remains protected from Git;
- configuration consumers remain centralized.

## Non-blocking Warnings

Two pre-existing warnings were observed during validation:

1. Starlette `TestClient` / `httpx` deprecation warning.
2. Hugging Face Hub unauthenticated-request warning.

Neither warning caused a test failure or affected the validated production
behavior.

## Repository Scope

Phase 9.16 introduces the dedicated runner:

`eval/phase9/run_production_smoke_suite.py`

and this validation report.

Historical untracked files under `eval/phase9/results/` remain local
diagnostic artifacts and are intentionally excluded from the Phase 9.16
commit.

## Conclusion

Phase 9.16 passes.

The final production path successfully handled fresh live queries, while all
previously frozen deterministic safety, reliability, API, observability, and
configuration guarantees remained intact.

**Final result: 92/92 PASS.**
