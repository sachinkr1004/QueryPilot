# Phase 9.12 — Database & Safe Performance Optimization

## Status

Phase 9.12 implemented and validated locally.

The selected optimization is a short-lived in-process cache for database table
metadata used by SQL identifier repair. Connection pooling was intentionally
deferred so that this phase changes only one major database-performance
variable.

## Objective

Profile the production PostgreSQL execution path, identify a measured database
bottleneck, apply one safe optimization, and verify that SQL safety,
self-correction, model-client reliability, identifier repair, and production
execution behavior remain intact.

No model, prompt, schema router, RAG, semantic-review, or self-correction policy
was changed in Phase 9.12.

## Pre-Optimization Database Path

Before the optimization, every call to `execute_query()` performed:

1. SQL safety validation.
2. `repair_table_identifiers()`.
3. `get_table_metadata()`, which opened a PostgreSQL connection and queried
   `information_schema.tables`.
4. A second SQL safety validation.
5. A separate PostgreSQL connection for the actual query.
6. Read-only transaction configuration.
7. A 10-second local statement timeout.
8. Query execution and cleanup.

This meant the metadata lookup added an additional connection and metadata query
to the normal execution path.

## Controlled Baseline

Profiler:

`eval/phase9/run_db_performance_profile.py`

Experiment:

`phase9_12_db_performance_baseline`

Runs per operation: 50

Read-only SQL:

`SELECT "PetType" FROM pets_1."Pets";`

| Operation | Mean ms | Median ms | P95 ms |
|---|---:|---:|---:|
| Metadata lookup | 5.775 | 5.660 | 6.363 |
| prepare_sql | 5.384 | 5.346 | 5.687 |
| Connection only | 3.924 | 3.903 | 4.159 |
| Full execute_query | 10.107 | 10.104 | 10.553 |

The repeated metadata lookup was therefore a meaningful part of the local
database execution cost.

## Optimization

`db.py` now maintains an in-process table-metadata cache with a 60-second TTL.

The cache uses `time.monotonic()` for expiration tracking.

Behavior:

- First metadata request loads current table metadata from PostgreSQL.
- Requests inside the TTL reuse the cached metadata.
- After TTL expiry, metadata is fetched again.
- The cache is updated only after a successful metadata fetch/build.

A finite TTL was chosen instead of permanent caching so schema changes can
eventually become visible without restarting the backend.

The optimization does not alter:

- SQL safety validation.
- SQLGlot parsing.
- Identifier-repair semantics.
- PostgreSQL read-only mode.
- Statement timeout.
- Query cleanup.
- LLM configuration.
- Prompt configuration.
- Database routing.
- RAG retrieval.
- Self-correction policy.

Connection pooling was deliberately not introduced in this phase.

## Controlled Post-Optimization Result

Experiment:

`phase9_12_metadata_cache_validation`

Runs per operation: 50

| Operation | Before mean ms | After mean ms | Change |
|---|---:|---:|---:|
| Metadata lookup | 5.775 | 0.000 | effectively eliminated on warm path |
| prepare_sql | 5.384 | 0.177 | ~96.7% lower |
| Connection only | 3.924 | 4.432 | no optimization applied |
| Full execute_query | 10.107 | 5.458 | ~46.0% lower |

Mean `execute_query()` time decreased by approximately 4.649 ms in the
controlled local benchmark.

The connection-only measurement was slightly higher in the post-change run.
No connection optimization was made, so this is treated as measurement
variation rather than an effect to optimize in this phase.

## TTL Correctness Validation

A controlled cache lifecycle diagnostic verified:

- First lookup: one metadata database call.
- Immediate second lookup: cache hit; database-call count remained one.
- Lookup after TTL expiry: metadata refreshed; database-call count became two.
- Metadata before and after refresh remained equivalent.

Result: PASS.

## Multi-Schema Identifier Repair

Identifier repair was checked across multiple schemas while the metadata cache
was active:

- `pets_1."pets"` repaired to `pets_1."Pets"`.
- `"cre_Students_Information_Systems"."students"` repaired to
  `"cre_Students_Information_Systems"."Students"`.
- `"cre_Doc_Workflow"."documents"` repaired to
  `"cre_Doc_Workflow"."Documents"`.

All three queries executed successfully.

Result: 3/3 PASS.

## Deterministic Regression Gates

Post-change validation:

| Suite | Result |
|---|---:|
| SQL safety | 39/39 PASS |
| Self-correction | 5/5 PASS |
| LLM reliability | 21/21 PASS |
| Combined deterministic suites | 65/65 PASS |

The SQL safety suite confirms that the Phase 9.9 safety behavior remains intact.
The self-correction suite confirms that Phase 9.10 behavior remains intact.
The reliability suite confirms that the Phase 9.11 model-client policy remains
intact.

## Frozen 40-Question Production Acceptance Run

Experiment:

`phase9_12_metadata_cache_acceptance`

The benchmark was resumed from checkpoints when provider 429 quota limits were
encountered. Provider-limited cases were not recorded as QueryPilot failures and
were retried later using the same experiment ID.

Final result:

| Metric | Phase 9.11 | Phase 9.12 | Delta |
|---|---:|---:|---:|
| Database routing accuracy | 92.5% | 92.5% | 0.0 pp |
| Strict accuracy | 70.0% | 67.5% | -2.5 pp |
| Semantic accuracy | 72.5% | 70.0% | -2.5 pp |
| Execution success | 100.0% | 100.0% | 0.0 pp |

Phase 9.12 latency summary:

- Mean production latency: 2563.03 ms
- Median production latency: 1569.64 ms
- P95 production latency: 9677.09 ms
- Mean generation latency: 2430.37 ms
- Mean initial execution latency: 25.74 ms

These end-to-end latency values include LLM generation variability and are not
used as evidence for the database-cache speedup. The controlled database
profiler is the evidence for the performance effect.

## Accuracy-Delta Investigation

The frozen acceptance run showed a one-question net strict and semantic
regression relative to the accepted Phase 9.11 run.

A question-by-question comparison found exactly one changed quality outcome:

`phase9_regression_boat_1_025`

Phase 9.11:

- Strict: PASS
- Semantic: PASS
- Execution: PASS

Phase 9.12:

- Strict: FAIL
- Semantic: FAIL
- Execution: PASS

The question, expected database, retrieved database, routing distance, RAG
example count, and stored production configuration were identical between the
two runs.

The generated SQL differed.

Phase 9.11 generated logic requiring both red and blue boat reservations using
grouping and `HAVING COUNT(DISTINCT color) = 2`, producing the gold result.

Phase 9.12 generated an `IN ('red', 'blue')` filter without the grouping/HAVING
condition, which accepted sailors with either color and produced an extra row.

The stored Phase 9.11 and Phase 9.12 production configurations were exactly
equal:

- database routing enabled
- maximum correction attempts = 1
- production-components pipeline
- RAG limit = 5
- semantic review disabled

All other 39/40 questions retained the same strict/semantic/execution quality
classification.

This investigation is consistent with LLM generation variability rather than a
behavioral effect of the database metadata cache. The observed benchmark values
remain recorded as 67.5% strict and 70.0% semantic; they are not rewritten or
reported as an accuracy improvement.

The nominal frozen semantic zero-drop threshold was therefore missed by the
observed run. Phase 9.12 acceptance relies on the controlled isolation evidence:
the database-only optimization produced a measurable execution-path benefit,
all deterministic regression gates passed, execution remained 100%, routing
remained unchanged, and the sole quality delta occurred in LLM generation with
unchanged generation-relevant benchmark configuration.

## Decision

The metadata TTL cache is retained as the Phase 9.12 database optimization.

Reasons:

1. The pre-change bottleneck was measured before modification.
2. The optimization reduced controlled mean `prepare_sql()` time from
   5.384 ms to 0.177 ms.
3. Controlled mean `execute_query()` time decreased from 10.107 ms to
   5.458 ms, approximately 46%.
4. Cache hit and TTL refresh behavior were validated.
5. Multi-schema identifier repair remained correct.
6. SQL safety, self-correction, and model-client reliability suites all passed.
7. Frozen benchmark execution success remained 100%.
8. Database routing remained 92.5%.
9. The single observed accuracy delta was investigated rather than hidden and
   was isolated to different LLM generation under unchanged benchmark
   configuration.
10. No second major optimization variable was introduced.

Connection pooling remains deferred until future measurement demonstrates that
its complexity is justified.

## Phase 9.12 Conclusion

Phase 9.12 successfully identified and removed a repeated metadata-query cost
from the warm production database path while preserving the validated safety
and reliability architecture.

The production database path is now ready to proceed to Phase 9.13:
Production FastAPI Endpoint.
