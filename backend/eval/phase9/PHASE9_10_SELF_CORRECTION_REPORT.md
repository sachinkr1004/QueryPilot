# Phase 9.10 — Production Self-Correction

## Status

COMPLETE — validated production self-correction with fail-closed SQL safety behavior.

## Objective

Harden QueryPilot's production self-correction path so that:

- recoverable database execution errors may receive one LLM correction attempt;
- initial SQL safety-policy violations fail closed and are never sent to the correction model;
- corrected SQL remains subject to the production SQL safety layer;
- correction attempts remain bounded to one;
- evaluation provider quota failures cannot silently contaminate benchmark results.

## Production Changes

### Typed safety rejection

`db.py` now defines:

`UnsafeSQLError(ValueError)`

The SQL preparation layer raises this exception when generated or prepared SQL violates QueryPilot's read-only SQL policy.

Subclassing `ValueError` preserves compatibility with existing callers while allowing production orchestration to distinguish safety-policy rejection from ordinary database execution errors.

### Fail-closed initial safety behavior

`production/pipeline.py` now handles initial `UnsafeSQLError` separately.

Initial unsafe SQL:

1. is rejected by the safety layer;
2. does not invoke the LLM correction path;
3. propagates the safety exception immediately.

Ordinary execution errors may still invoke the existing single correction attempt.

Corrected SQL is executed through the same protected execution path, so unsafe corrected SQL is blocked and the pipeline terminates after the configured single correction attempt.

## Deterministic Self-Correction Suite

Permanent suite:

`eval/phase9/run_self_correction_suite.py`

Result:

- Passed: 5/5

Covered behavior:

1. valid initial SQL executes without correction;
2. recoverable database error receives one correction and succeeds;
3. initial unsafe SQL fails closed with zero correction calls;
4. unsafe corrected SQL is blocked;
5. failed correction stops after exactly one attempt.

The suite mocks execution to isolate production orchestration behavior. SQL parser and PostgreSQL safety behavior remain covered by the Phase 9.9 safety suite.

## SQL Safety Regression

Command:

`python -m eval.phase9.run_sql_safety_suite`

Result:

- Total: 39
- Passed: 39
- Failed: 0

Therefore the Phase 9.10 orchestration changes introduced no detected regression in the Phase 9.9 SQL safety layer.

## Frozen Phase 9 Regression Validation

Final artifact:

`eval/phase9/results/phase9_10_self_correction_validation_final.json`

Results:

- Questions: 40
- Database routing: 37/40 = 92.5%
- Strict correctness: 28/40 = 70.0%
- Semantic correctness: 29/40 = 72.5%
- Execution success: 40/40 = 100.0%
- Self-correction triggered: 2
- Successful corrections: 2
- Total LLM calls: 42
- Mean LLM calls/question: 1.05
- Mean production latency: 4867.07 ms
- Median production latency: 5107.77 ms
- P95 production latency: 11469.67 ms

The two correction cases were:

- `phase9_regression_government_shift_034`
- `phase9_regression_cre_Students_Information_Systems_023`

Both completed successfully after correction.

## Regression Comparison

Phase 9.9 validated benchmark:

- Strict: 67.5%
- Semantic: 70.0%
- Execution: 100.0%

Phase 9.10 final benchmark:

- Strict: 70.0%
- Semantic: 72.5%
- Execution: 100.0%

Observed delta:

- Strict: +2.5 percentage points
- Semantic: +2.5 percentage points
- Execution: 0.0 percentage points

The strict and semantic improvements are treated as observed run-to-run results, not as causal evidence that self-correction improved generation quality.

The important Phase 9.10 evidence is that execution remained at 100% and both cases that triggered the production correction path recovered successfully.

## Provider Quota Hardening

Two earlier Phase 9.10 benchmark attempts were contaminated by provider HTTP 429 quota failures and were not accepted as final validation evidence.

The evaluation runner was hardened so recognized provider rate-limit errors:

- are not recorded as benchmark failures;
- do not mark the current case complete;
- preserve already completed cases in the atomic `.partial.json` checkpoint;
- stop the benchmark cleanly;
- can be resumed later with the same experiment ID and `--resume`.

This behavior was validated deterministically without provider calls:

- cases 1 and 2 were checkpointed;
- simulated case 3 quota failure was not recorded;
- resume skipped cases 1 and 2;
- resume retried only case 3;
- final result ordering was preserved.

The final Phase 9.10 artifact was produced by recovering the 38 valid completed cases from the second benchmark attempt into a clean checkpoint, excluding its two provider-quota failures, validating that checkpoint, and resuming only the two unfinished benchmark cases.

Final artifact validation confirmed:

- 40 results;
- 40 unique benchmark IDs;
- 40 execution successes;
- 2 correction cases;
- no recorded provider quota failures;
- no remaining partial checkpoint.

## Decision

Phase 9.10 production self-correction is accepted.

Production policy:

- maximum correction attempts: 1;
- correct ordinary execution failures;
- never correct initial safety-policy violations;
- run corrected SQL through the same SQL safety layer;
- fail after the bounded correction attempt if recovery is unsuccessful.

No model, router, RAG configuration, semantic-review policy, or frozen benchmark definition was changed during Phase 9.10.
