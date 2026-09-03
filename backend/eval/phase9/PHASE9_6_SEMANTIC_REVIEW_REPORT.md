# Phase 9.6 — Semantic Review Optimization

## Objective

Determine whether QueryPilot's semantic SQL reviewer should be placed in
the production query path.

Phase 9.6 evaluates the reviewer experimentally rather than assuming that
an additional LLM review call improves correctness.

## Phase 9.5 Baseline

- Questions: 40
- Database routing accuracy: 92.5%
- Strict accuracy: 65.0%
- Semantic accuracy: 67.5%
- Execution success rate: 100.0%
- Mean LLM calls per question: 1.025
- Mean production latency: 11022.5 ms

## Experiment 9.6-A — Full Pipeline With Unconditional Review

This experiment ran the normal production-style pipeline and reviewed every
successfully executable query.

Results:

- Questions: 40
- Strict accuracy: 67.5%
- Semantic accuracy: 70.0%
- Execution success rate: 100.0%
- Semantic reviews: 40
- Semantic rewrites: 1
- Total LLM calls: 80
- Mean LLM calls per question: 2.0
- Mean semantic-review latency: 9207.01 ms
- Mean production latency: 18922.83 ms

At first, the aggregate accuracy looked better than Phase 9.5.

However, case-level validation showed that the apparent improvement came
from fresh SQL-generation variability, not from a semantic-review rewrite.

Therefore, Experiment 9.6-A is not valid evidence that semantic review
improves correctness.

## Experiment 9.6-B — Isolated Semantic Reviewer Replay

To remove SQL-generation variability, this experiment replayed the exact
final SQL stored in the frozen Phase 9.5 baseline.

No new SQL generation, self-correction, or RAG retrieval was performed.

Results:

- Questions: 40
- Database routing accuracy: 92.5%
- Strict accuracy: 65.0%
- Semantic accuracy: 67.5%
- Execution success rate: 100.0%
- Semantic reviews: 40
- Semantic rewrites: 3
- Total reviewer LLM calls: 40
- Mean reviewer calls per question: 1.0
- Mean semantic-review latency: 3564.17 ms
- Mean replay production latency: 3632.13 ms

Exact correctness delta versus Phase 9.5:

- Strict fixes: 0
- Strict regressions: 0
- Semantic fixes: 0
- Semantic regressions: 0

Therefore, the isolated semantic reviewer produced zero demonstrated
correctness improvement on the frozen Phase 9 benchmark.

## Rewrite and Failure Audit

The isolated reviewer changed SQL in three cases:

1. phase9_regression_vehicle_rent_019
   - Database routing was wrong.
   - Reviewer rewrote the SQL.
   - Result remained incorrect.
   - The reviewer could not repair the underlying routing failure.

2. phase9_regression_customers_and_orders_076
   - Database routing was correct.
   - Reviewer rewrote the SQL.
   - Result remained incorrect.
   - The rewrite did not repair the semantic mismatch.

3. phase9_regression_cre_Doc_Workflow_032
   - Query was already strict and semantically correct.
   - Reviewer changed COUNT(*) to COUNT(DISTINCT staff_id).
   - Benchmark correctness remained unchanged.
   - This was an unnecessary modification of an already-correct query.

Phase 9.5 contained 13 semantic failures:

- 3 were database-routing failures.
- 10 were correctly routed failures.
- Among the 10 correctly routed failures, the reviewer kept 9 unchanged.
- It rewrote 1 correctly routed failure but did not fix it.

Some failures are affected by evaluation artifacts such as PostgreSQL versus
SQLite numeric/date representation differences or output-column ordering.
These should not all be interpreted as pure LLM semantic failures.

Even with this limitation, the isolated experiment provides no evidence
that the current reviewer repairs the genuine semantic failures needed to
justify its production cost.

## Production Decision

Semantic review remains OFF by default in the production hot path.

Reasons:

- 40 isolated semantic-review calls were made.
- Only 3 SQL rewrites occurred.
- Strict correctness fixes: 0.
- Semantic correctness fixes: 0.
- No demonstrated accuracy improvement.
- Mean semantic-review latency was 3564.17 ms.
- An already-correct query was modified without demonstrated necessity.

A selective trigger for the same reviewer is not justified by the current
evidence. Reducing review frequency would lower cost, but would not solve
the demonstrated inability of the current reviewer to identify and repair
the relevant semantic failures.

Future semantic-review work should require a materially improved reviewer,
new independent evidence, or a separately validated high-confidence
trigger.

## Phase 9.6 Outcome

Phase 9.6 is complete as an optimization study.

The experiment prevented an additional expensive LLM stage from being
added to the production path without demonstrated correctness benefit.

QueryPilot therefore continues from the Phase 9.5 production configuration
with semantic review disabled by default.
