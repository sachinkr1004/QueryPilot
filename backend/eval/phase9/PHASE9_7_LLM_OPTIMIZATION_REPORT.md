# Phase 9.7 — LLM Call, Prompt & Token Optimization

## Objective

Reduce production LLM prompt/token usage and latency without reducing execution reliability or violating the frozen Phase 9 regression policy.

## Frozen Baseline

Artifact:

`eval/phase9/results/phase9_7_llm_token_baseline.json`

Results:

- Questions: 40
- Database routing accuracy: 92.5%
- Strict accuracy: 65.0%
- Semantic accuracy: 67.5%
- Execution success: 100.0%
- Total LLM calls: 40
- Prompt tokens: 60,570
- Completion tokens: 12,481
- Reasoning tokens: 10,283
- Total tokens: 73,051
- Mean production latency: 9,130.42 ms
- Median production latency: 7,957.53 ms
- P95 production latency: 16,514.60 ms

## Profiling Findings

The original SQL-generation prompt contained substantial repeated instruction text covering schema restrictions, quoting, joins, aggregation, DISTINCT, ordering, output formatting, and final verification.

Provider-reported token usage showed prompt tokens were the largest component of total token usage, motivating a controlled static-prompt compression experiment.

The production model, schema retrieval, RAG retrieval, correction policy, execution logic, benchmark, and evaluator remained frozen.

## Phase 9.7-A — Compact Prompt Experiment

Artifact:

`eval/phase9/results/phase9_7a_prompt_compression.json`

The experiment changed only the SQL-generation instruction prompt. The compact prompt retained the general rules for:

- SQL-only output
- schema-only identifiers
- identifier capitalization and quoting
- schema-qualified tables
- PostgreSQL datatype preservation
- valid JOIN conditions
- requested output columns
- COUNT and DISTINCT behavior
- ORDER BY and LIMIT behavior
- GROUP BY, WHERE, and HAVING behavior
- RAG examples as references rather than templates
- final identifier/join/type/executability verification

Results:

- Questions: 40
- Routing accuracy: 92.5%
- Strict accuracy: 67.5%
- Semantic accuracy: 70.0%
- Execution success: 100.0%
- Total LLM calls: 41
- Prompt tokens: 28,974
- Total tokens: 44,596
- Mean production latency: 6,373.18 ms
- Median production latency: 6,356.48 ms
- P95 production latency: 16,328.95 ms

Compared with the baseline:

- Prompt tokens reduced by approximately 52.2%
- Total tokens reduced by approximately 39.0%
- Mean production latency reduced by approximately 30.2%
- Execution remained 100%

One generation reached the 1,000-token completion limit and was successfully recovered by the existing correction path. This was treated as evidence not to reduce the completion cap during Phase 9.7.

Generation completion/reasoning usage increased on many questions, but the prompt-token reduction was substantially larger, so overall token usage still decreased significantly.

## Production Promotion Validation

The validated compact prompt was promoted into:

`llm/baseline_client.py`

Only the generation prompt was replaced. The following were preserved:

- model: `openai/gpt-oss-120b`
- `max_completion_tokens=1000`
- RAG configuration
- schema retrieval
- response cleaning
- SQL correction path
- SQL execution path
- semantic-review default behavior

Production validation artifact:

`eval/phase9/results/phase9_7_production_compact_validation.json`

Results:

- Questions: 40
- Routing accuracy: 92.5%
- Strict accuracy: 72.5%
- Semantic accuracy: 75.0%
- Execution success: 100.0%
- Self-correction triggered: 0
- Total LLM calls: 40
- Prompt tokens: 27,719
- Completion tokens: 15,511
- Reasoning tokens: 13,358
- Total tokens: 43,230
- Mean production latency: 5,024.35 ms
- Median production latency: 5,343.64 ms
- P95 production latency: 11,873.27 ms

Compared with the frozen Phase 9.7 baseline:

- Prompt tokens: 60,570 → 27,719 (~54.2% reduction)
- Total tokens: 73,051 → 43,230 (~40.8% reduction)
- Mean latency: 9,130.42 ms → 5,024.35 ms (~45.0% reduction)
- Median latency: 7,957.53 ms → 5,343.64 ms (~32.9% reduction)
- P95 latency: 16,514.60 ms → 11,873.27 ms (~28.1% reduction)
- Execution success: 100% → 100%
- Routing accuracy: 92.5% → 92.5%

Strict and semantic accuracy were higher in the production validation run. Because the model shows run-to-run generation variability, those gains are recorded as observed results rather than attributed entirely to prompt compression.

## Decision

The compact generation prompt is selected as the Phase 9.7 winner.

Reasons:

1. Large and repeatable reduction in prompt-token usage.
2. Large reduction in total token usage.
3. Lower mean, median, and P95 latency.
4. No execution regression.
5. No routing regression.
6. No need to lower the 1,000-token completion cap.
7. No benchmark-specific prompt rules were added.

Phase 9.7 is therefore considered successfully validated and ready to freeze after final Git review.
