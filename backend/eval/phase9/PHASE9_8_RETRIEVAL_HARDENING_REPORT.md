# Phase 9.8 — Retrieval, Value Grounding & RAG Hardening

## Status

Phase 9.8 retrieval hardening evaluation completed.

Production decisions:

- Keep the validated value-grounding matcher performance optimization.
- Keep production RAG at Top-5.
- Keep the current full routed-database schema path.
- Do not promote value grounding into the production generation hot path.
- Do not tune the schema router on the frozen Phase 9 regression benchmark.
- Production pipeline remains unchanged by Phase 9.8-A.

## Evaluation Discipline

Phase 9.8 used the frozen 40-question Phase 9 regression benchmark.

The benchmark was used for regression evaluation and diagnosis, not for
special-case tuning.

No schema-router lexical weights, benchmark-specific aliases, RAG Top-K,
model, or frozen questions were modified to improve benchmark scores.

Provider 429 errors were not counted as QueryPilot failures. The
Phase 9.8-A run was resumed from its valid checkpoint after a temporary
rate-limit response.

## 1. Retrieval Hardening Profile

A retrieval-only profiler was added:

`eval/phase9/run_retrieval_hardening_profile.py`

The profiler makes zero LLM calls and measures:

- current production database routing,
- Top-5 database candidate recall,
- current database-scoped RAG retrieval,
- diagnostic Top-7 table retrieval,
- Phase-8-style value grounding,
- schema/context sizes,
- retrieval latency.

### Baseline Retrieval Profile

Results on 40 frozen regression questions:

- Valid questions: 40/40
- LLM calls: 0
- Top-1 database routing: 37/40 = 92.5%
- Expected database in Top-5 candidates: 40/40 = 100%
- Questions with grounded values: 16/40 = 40%
- Exact duplicate RAG questions: 0
- Mean full schema size: 1006.33 characters
- Mean reduced schema size: 966.55 characters
- Mean value context size: 20.75 characters
- Mean grounded values/question: 0.68
- Mean RAG retrieval latency: 20.50 ms
- Mean diagnostic table retrieval latency: 16.74 ms
- Mean value-grounding latency: 270.46 ms
- Mean total retrieval-profile latency: 356.93 ms
- Median total latency: 104.64 ms
- P95 total latency: 4600.99 ms

### Router Decision

The expected database appeared within the Top-5 candidates for all
40 questions, while production Top-1 routing remained 92.5%.

The three known Top-1 routing failures were not used to tune lexical
weights or introduce benchmark-specific rules.

Future router reranking work should use independent development evidence.

## 2. RAG Audit

Production RAG remains database-scoped and uses Top-5 examples.

The retrieval profile found zero exact duplicate RAG questions across
the frozen 40-question benchmark.

No evidence justified changing the validated Top-5 production setting.

Decision: keep production RAG Top-5 unchanged.

## 3. Schema Reduction Audit

The diagnostic Top-7 table retrieval path produced:

- Mean full schema: 1006.33 characters
- Mean reduced schema: 966.55 characters

This is only a modest average reduction while introducing an additional
retrieval stage.

There was not enough evidence of a production benefit to replace the
current full schema of the already-routed database.

Decision: keep the current production schema path unchanged.

## 4. Value-Grounding Performance Bottleneck

Profiling identified a severe latency tail in the existing
full-column multi-token fallback.

The initial DISTINCT ... LIMIT 200 database queries were fast.

The bottleneck was Python-side matching over high-cardinality columns.
The previous implementation repeatedly normalized the same question
and constructed/executed a regular expression for each database value.

For normalized value text, the existing word-boundary test is
equivalent to padded normalized substring matching.

The fallback was optimized to:

1. normalize the question once,
2. pad the normalized question once,
3. normalize each database value,
4. preserve the existing multi-token-only eligibility rule,
5. perform padded substring matching instead of a per-value regex.

The fallback trigger, SQL query, nested-match removal, first-200 scan,
semantic matchers, aliases, fuzzy matching, morphology, geographic,
boolean, and numeric semantic logic were not changed.

### Microbenchmark

Across high-cardinality `aan_1` columns:

- Previous total matching time: 3626.91 ms
- Optimized total matching time: 141.30 ms
- Approximate speedup: 25.67x
- Output differences: 0

For `aan_1.Paper.title`:

- Previous: 1380.61 ms
- Optimized: 57.13 ms
- Approximate speedup: 24.16x

An additional 103,100-comparison equivalence diagnostic on
`aan_1.Paper.title` produced zero matcher differences.

## 5. Full Retrieval Regression After Matcher Optimization

The complete 40-question retrieval profile was rerun after the
optimization.

Before -> after:

- Top-1 routing: 92.5% -> 92.5%
- Expected database Top-5 recall: 100% -> 100%
- Grounded questions: 16/40 -> 16/40
- Mean grounded values/question: 0.68 -> 0.68
- Duplicate RAG questions: 0 -> 0
- Mean value-grounding latency: 270.46 -> 84.87 ms
- Mean total profile latency: 356.93 -> 170.57 ms
- Median total latency: 104.64 -> 103.83 ms
- P95 total latency: 4600.99 -> 1022.53 ms

Relative improvements:

- Mean value-grounding latency: approximately 68.6% lower
- Mean total retrieval-profile latency: approximately 52.2% lower
- P95 total retrieval-profile latency: approximately 77.8% lower

Exact before/after comparison across all 40 questions found:

- Value-match differences: 0
- Routing differences: 0
- RAG differences: 0
- Table-retrieval differences: 0

Decision: retain the matcher optimization as a behavior-preserving
performance hardening change.

## 6. Phase 9.8-A — Controlled Value-Grounding Experiment

A controlled experiment was added:

`eval/phase9/run_value_grounding_experiment.py`

Control behavior corresponds to the current compact production
generation configuration.

The experiment changed one major retrieval variable:

- retrieve grounded values from all tables in the already-routed database,
- add a `RELEVANT DATABASE VALUES` section to generation context.

Unchanged:

- GPT-OSS-120B model
- compact generation rules
- Top-1 database router
- RAG Top-5
- full routed-database schema
- existing correction policy
- semantic review disabled
- maximum completion-token policy

Value grounding affected initial generation only. The existing correction
prompt was not changed.

### Grounding Coverage

Across 40 questions:

- Questions receiving grounded values: 16/40 = 40%
- Total grounded values: 27
- Questions receiving no grounded values: 24/40

The retriever remained conservative.

Examples of retrieved categorical/literal values included:

- Boats.color: red, blue
- staff.Nationality: Canada
- university.State: Wisconsin
- Products.product_type_code: Hardware
- Affiliation.address: China
- Customers_and_Services_Details: Satisfied, Unsatisfied

No audited case demonstrated an obviously hallucinated database value.

## 7. Phase 9.8-A Quality Result

Completed 40-question result:

- Database routing: 37/40 = 92.5%
- Strict accuracy: 27/40 = 67.5%
- Semantic accuracy: 28/40 = 70.0%
- Execution success: 40/40 = 100%
- Self-correction triggered: 0
- Total LLM calls: 40
- Total prompt tokens: 28,512
- Total completion tokens: 15,161
- Total reasoning tokens: 12,952
- Total tokens: 43,673
- Mean total tokens/question: 1091.83
- Mean production latency: 4808.09 ms
- Median production latency: 4548.40 ms
- P95 production latency: 10917.11 ms

For reference, the previous Phase 9.7 production compact validation
observed:

- Strict accuracy: 72.5%
- Semantic accuracy: 75.0%
- Execution success: 100%
- Total tokens: 43,230
- Mean production latency: 5024.35 ms
- Median production latency: 5343.64 ms
- P95 production latency: 11873.27 ms

Because these are separate LLM generations, latency and quality
differences must not be interpreted as fully causal.

## 8. Per-Question Quality Audit

Only two questions changed strict/semantic classification between the
Phase 9.7 production validation and Phase 9.8-A:

### boat_1_025

Grounded values:

`Boats.color: red, blue`

Phase 9.7 was strict/semantic correct.

Phase 9.8-A was strict/semantic incorrect.

The grounded query still correctly enforced reservations involving both
red and blue boats using COUNT(DISTINCT color) = 2, but returned output
columns as `name, sid` while the benchmark gold SQL returned `sid, name`.

The retrieved values themselves were correct.

### government_shift_034

Grounded values:

`Customers_and_Services_Details: Satisfied, Unsatisfied`

The grounded generation used the exact database predicate:

`Customers_and_Services_Details = 'Unsatisfied'`

which matches the gold predicate more directly than the earlier
case-insensitive substring predicate.

However, the grounded generation dropped `DISTINCT`, which can change
the result multiplicity.

This is a real benchmark/result-set regression, but the retrieved
database value itself was correct.

## 9. Production Decision

Phase 9.8-A does not provide sufficient evidence to enable value
grounding in the production hot path.

Reasons:

1. Execution remained 100%, but semantic accuracy in the measured run
   was below the previous production validation.
2. The frozen regression policy allows no aggregate semantic regression.
3. No clear aggregate quality improvement was demonstrated.
4. Additional context and retrieval complexity should not be added
   without measurable production benefit.
5. The audited value matches were generally high precision, so the
   retrieval capability remains useful for future controlled work.

Therefore:

**Value grounding remains OFF in the production generation pipeline.**

No benchmark-specific prompt or retrieval tuning is introduced to fix
the two changed frozen cases.

## 10. Final Phase 9.8 Decisions

- Schema router: unchanged
- Router lexical weight: unchanged
- Production schema strategy: unchanged
- RAG: database-scoped Top-5, unchanged
- Semantic review: remains OFF
- Production value grounding: OFF
- Value-grounding matcher optimization: KEEP
- Production pipeline: unchanged
- Frozen benchmark: unchanged

Phase 9.8 therefore hardens retrieval infrastructure without accepting
an unproven production-context expansion.
