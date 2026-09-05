# Phase 9.9 — Production SQL Safety Layer

## Status

COMPLETE — validated locally before commit.

## Objective

Harden QueryPilot's production SQL execution path against unsafe,
data-changing, multi-statement, locking, and runaway SQL while preserving
the existing production query behavior.

## Implementation

### 1. Parser-based SQL validation

Replaced the previous substring-based SQL safety filter with SQLGlot
PostgreSQL AST parsing.

The validator now:

- fails closed on empty or unparsable SQL;
- requires exactly one SQL statement;
- requires a read-only query expression;
- rejects INSERT, UPDATE, DELETE, MERGE, DROP, CREATE, ALTER,
  TRUNCATE, GRANT, and REVOKE nodes;
- rejects data-changing statements nested inside CTEs;
- rejects SELECT INTO anywhere in the AST;
- rejects row-locking clauses such as FOR UPDATE and FOR SHARE.

SQLGlot is pinned at:

    sqlglot==30.17.0

### 2. Defense in depth at PostgreSQL

The production execution path now enables PostgreSQL read-only transaction
mode before executing generated SQL:

    conn.set_session(readonly=True)

A controlled database test confirmed PostgreSQL rejected a CREATE TABLE
attempt with ReadOnlySqlTransaction.

### 3. Statement timeout

The production execution path applies a transaction-local 10-second
PostgreSQL statement timeout before executing generated SQL.

This prevents generated queries from consuming database resources
indefinitely.

A controlled 200 ms timeout test against pg_sleep(1) was cancelled by
PostgreSQL in approximately 0.203 seconds.

## Safety Regression Suite

Permanent suite:

    eval/phase9/run_sql_safety_suite.py

Final result:

- Total: 39
- Passed: 39
- Failed: 0

Coverage includes:

- normal SELECT;
- read-only CTE;
- UNION / INTERSECT / EXCEPT;
- subqueries and leading comments;
- multiple statements;
- INSERT / UPDATE / DELETE;
- CREATE / ALTER / DROP / TRUNCATE;
- MERGE;
- writable CTEs;
- SELECT INTO, including nested AST cases;
- FOR UPDATE / FOR SHARE;
- whitespace-obfuscated destructive statements;
- non-query commands;
- empty / invalid SQL;
- actual execute_query() blocking;
- PostgreSQL read-only enforcement;
- statement-timeout enforcement.

## Frozen Phase 9 Regression Validation

Experiment:

    phase9_9_sql_safety_validation

Questions: 40

Results:

- Database routing: 37/40 = 92.5%
- Strict accuracy: 27/40 = 67.5%
- Semantic accuracy: 28/40 = 70.0%
- Execution success: 40/40 = 100.0%
- Self-correction triggered: 0
- Total LLM calls: 40

Latency:

- Mean production latency: 5773.14 ms
- Median production latency: 5762.20 ms
- P95 production latency: 11584.79 ms

Compared with the frozen Phase 9.5 baseline:

- routing remained 92.5%;
- strict accuracy changed from 65.0% to 67.5%;
- semantic accuracy changed from 67.5% to 70.0%;
- execution remained 100%.

The strict/semantic increase is treated as observed run-to-run generation
variation and is not attributed causally to the SQL safety changes.

The frozen Phase 9 regression policy is satisfied:

- semantic regression: none;
- execution regression: none;
- strict regression: none;
- safety regressions: zero.

## Decision

KEEP the Phase 9.9 safety changes.

The production SQL path now has layered protection:

1. SQLGlot AST validation.
2. Identifier repair.
3. AST validation again.
4. PostgreSQL read-only transaction enforcement.
5. Transaction-local statement timeout.
6. SQL execution.

Phase 9.9 is ready for final Git validation and freeze.
