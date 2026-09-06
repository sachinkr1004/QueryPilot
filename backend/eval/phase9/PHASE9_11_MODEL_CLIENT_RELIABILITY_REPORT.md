# Phase 9.11 — Stable Model Client + Reliability

## Objective

Phase 9.11 hardened QueryPilot's production LLM client without changing
the production prompt, model, schema router, RAG policy, SQL safety policy,
or self-correction policy.

The phase focused on provider-client reliability, malformed-response
handling, timeout/retry policy, and completion-token headroom.

## Production Changes

The production LLM client now:

- explicitly freezes Groq `max_retries=2`;
- explicitly freezes HTTP timeout policy:
  - connect: 5 seconds
  - read: 60 seconds
  - write: 60 seconds
  - pool: 60 seconds;
- validates provider responses before consuming message content;
- raises `LLMResponseError` for unusable responses;
- records safe diagnostic metadata for blank responses:
  - finish reason
  - completion-token count
  - reasoning-token count;
- does not expose or log reasoning text;
- uses a 2000-token completion ceiling for initial SQL generation;
- keeps correction and semantic-review ceilings at 1000 tokens.

No application-level retry loop was added because the Groq SDK already
provides retry behavior.

## Evidence for Generation Token Ceiling

A frozen Phase 9.11 benchmark case previously returned no usable SQL with:

- `finish_reason='length'`
- `completion_tokens=1000`
- `reasoning_tokens=998`

This demonstrated that the previous 1000-token generation ceiling could
occasionally be exhausted almost entirely by model reasoning.

A controlled diagnostic call with a 2000-token ceiling returned usable
content and stopped normally before reaching the new ceiling.

This does not establish an SQL-accuracy improvement. It establishes that
additional generation headroom is justified as a reliability safeguard.

## Deterministic Regression Validation

The following suites passed after the production changes:

| Suite | Result |
|---|---:|
| Phase 9.11 LLM reliability | 21/21 |
| Phase 9.9 SQL safety | 39/39 |
| Phase 9.10 self-correction | 5/5 |
| **Total** | **65/65** |

The reliability suite verifies malformed-response handling, typed provider
exception propagation, retry/timeout configuration, and per-operation
completion-token ceilings.

## Frozen 40-Question Validation

Experiment:

`phase9_11_generation_2000_validation`

Results:

| Metric | Phase 9.10 | Phase 9.11 | Delta |
|---|---:|---:|---:|
| Database routing | 92.5% | 92.5% | 0.0 pp |
| Strict accuracy | 70.0% | 70.0% | 0.0 pp |
| Semantic accuracy | 72.5% | 72.5% | 0.0 pp |
| Execution success | 100.0% | 100.0% | 0.0 pp |
| Total LLM calls | 42 | 40 | -2 |

Phase 9.11 therefore preserves the frozen Phase 9.10 correctness and
execution metrics while validating the model-client reliability changes.

The reduction in LLM calls must not be interpreted as a guaranteed causal
performance improvement because self-correction triggering depends on the
generated SQL in a stochastic model run.

## Reliability Failure Recheck

The `customers_and_orders_076` case that previously exposed the
1000-token blank-response failure produced usable SQL and executed
successfully under the validated Phase 9.11 configuration.

Its strict and semantic correctness remained false. Therefore this result
is treated as a reliability recovery, not an SQL-accuracy improvement.

## Provider Quota Handling

The validation run encountered provider HTTP 429 quota limits.

The existing benchmark quota guard behaved correctly:

- the interrupted case was not recorded;
- completed cases were checkpointed;
- the same experiment ID was resumed;
- no quota-contaminated case was included in the final 40-question result.

## Validated Artifact

Result file:

`eval/phase9/results/phase9_11_generation_2000_validation.json`

SHA-256:

`32c5d46112c7e23ba7421c68a26a31b48a553f1c71c1f5d2ca2e72ddf8cc840c`

The artifact contains 40/40 benchmark records and reports:

- routing accuracy: 92.5%
- strict accuracy: 70.0%
- semantic accuracy: 72.5%
- execution success: 100.0%
- total LLM calls: 40

## Decision

Phase 9.11 is accepted.

The stable model-client configuration is:

- model: `openai/gpt-oss-120b`
- Groq SDK retries: 2
- connect timeout: 5 seconds
- read/write/pool timeout: 60 seconds
- generation completion ceiling: 2000 tokens
- correction completion ceiling: 1000 tokens
- semantic-review completion ceiling: 1000 tokens
- malformed provider responses fail with controlled diagnostics
- provider exceptions continue to propagate through their typed SDK errors

No production prompt, router, RAG, SQL safety, or self-correction policy
change was required.
