# Phase 9.17 — Final Optimization & Regression Validation

## Status

**PASS — final production regression validation completed successfully.**

Phase 9.17 performed the final production-quality and performance validation
before the API contract freeze.

No model, prompt, router, RAG, value-grounding, self-correction, SQL-safety,
database, model-client, observability, configuration, or production API
behavior was changed during Phase 9.17.

The final engineering decision is to retain the validated production
implementation without introducing another optimization variable.

## Frozen 40-Question Production Regression

Experiment:

`phase9_17_final_regression`

Benchmark:

`phase9_regression`

Production configuration:

- pipeline: `production_components`
- RAG limit: `5`
- maximum correction attempts: `1`
- semantic review: disabled
- database routing: enabled

The benchmark contains 40 questions across 20 databases.

The first execution was interrupted after 35 completed cases by a Groq
provider rate limit. The current case was not recorded as a QueryPilot
failure, the completed checkpoint was preserved, and the benchmark was later
continued with the same experiment ID using the runner's resume behavior.

No model, prompt, router, RAG, token limit, or benchmark setting was changed
to work around the provider quota.

The resumed run completed all 40 questions.

## Final Quality Results

| Metric | Result |
| --- | ---: |
| Database routing | 37/40 = 92.5% |
| Strict correctness | 28/40 = 70.0% |
| Semantic correctness | 29/40 = 72.5% |
| Execution success | 40/40 = 100.0% |
| Self-correction triggered | 0 |
| Successful corrections | 0 |
| Total LLM calls | 40 |
| Mean LLM calls/question | 1.0 |

The Phase 9.17 quality result matches the accepted Phase 9.11 quality level:

- routing: 92.5%;
- strict: 70.0%;
- semantic: 72.5%;
- execution: 100.0%.

The observed Phase 9.12 acceptance run recorded 67.5% strict and 70.0%
semantic accuracy after one changed generation outcome. The Phase 9.12
investigation isolated that difference to nondeterministic LLM generation
under unchanged generation-relevant configuration.

Therefore, the Phase 9.17 result is recorded as evidence that no final quality
regression was detected. It is not reported as an accuracy improvement caused
by a Phase 9.17 optimization.

## Final Latency Profile

| Metric | Result |
| --- | ---: |
| Mean schema routing/retrieval | 77.41 ms |
| Mean RAG retrieval | 28.65 ms |
| Mean generation | 4601.64 ms |
| Mean initial execution | 29.55 ms |
| Mean correction | 0.0 ms |
| Mean corrected execution | 0.0 ms |
| Mean production latency | 4737.26 ms |
| Median production latency | 4577.78 ms |
| P95 production latency | 9430.90 ms |

LLM generation accounted for approximately 97% of measured mean production
latency in this run.

Schema routing/retrieval, RAG retrieval, and initial database execution
together represented only a small fraction of the end-to-end latency.

The absolute end-to-end latency remains sensitive to external provider and
generation variability. It is therefore not interpreted as an isolated
database or retrieval benchmark.

## Final Optimization Decision

No additional production optimization is introduced in Phase 9.17.

Reasons:

1. Final execution success remained 100%.
2. Database routing remained 92.5%.
3. Strict and semantic quality showed no final regression.
4. Mean LLM calls remained 1.0 per question.
5. All deterministic regression gates passed.
6. LLM generation dominates the measured end-to-end latency.
7. Additional database or retrieval optimization would target only a small
   portion of the current production latency.
8. Changing the model, prompt, router, RAG policy, or token policy would
   introduce a new major variable immediately before the production contract
   freeze.
9. The Phase 9 roadmap requires one major optimization variable at a time and
   preservation of validated quality and safety behavior.

The safest final optimization decision is therefore to preserve the current
validated production implementation.

## Deterministic Regression Validation

After the completed 40-question production benchmark, all deterministic
regression suites were rerun against the final code state.

| Suite | Passed | Failed |
| --- | ---: | ---: |
| Phase 9.9 SQL safety | 39 | 0 |
| Phase 9.10 self-correction | 5 | 0 |
| Phase 9.11 LLM reliability | 21 | 0 |
| Phase 9.13 API contract | 10 | 0 |
| Phase 9.14 observability | 6 | 0 |
| Phase 9.15 configuration/security | 8 | 0 |
| **Total** | **89** | **0** |

**Deterministic regression result: 89/89 PASS.**

This revalidates the frozen SQL-safety, correction-control, model-client,
API, observability, configuration, and secret-protection guarantees.

## Provider Rate-Limit Handling

During the initial full regression run, Groq returned HTTP 429 after 35
completed benchmark cases.

The benchmark runner:

- did not record the provider-limited current case as a QueryPilot failure;
- preserved the 35 completed cases;
- resumed using the same experiment ID;
- skipped the already completed cases;
- completed the remaining five cases successfully.

The provider quota event is therefore treated as an external infrastructure
interruption rather than a QueryPilot correctness regression.

## Artifact Notes

The completed result is stored at:

`eval/phase9/results/phase9_17_final_regression.json`

The artifact contains 40 stored case results and identifies the experiment as:

`phase9_17_final_regression`

The reused historical production-baseline runner stores `"phase": "9.5"` in
its artifact schema. This label is retained unchanged because the runner is
historical infrastructure. The experiment ID and benchmark identify this
artifact as the Phase 9.17 final regression run.

The earlier one-question sanity artifact:

`eval/phase9/results/phase9_17_final_validation.partial.json`

is an incomplete diagnostic artifact and is not part of the Phase 9.17 final
acceptance evidence.

Historical untracked evaluation artifacts remain local and are intentionally
excluded from the Phase 9.17 commit unless explicitly selected.

## Non-blocking Warnings

Two pre-existing warnings were observed during deterministic validation:

1. Starlette `TestClient` / `httpx` deprecation warning.
2. Hugging Face Hub unauthenticated-request warning.

Neither warning caused a regression-suite failure.

## Conclusion

Phase 9.17 passes.

The final 40-question production regression completed with:

- 92.5% database routing accuracy;
- 70.0% strict correctness;
- 72.5% semantic correctness;
- 100.0% execution success;
- 1.0 mean LLM calls per question.

All final deterministic regression gates passed 89/89.

No additional production optimization is justified before the API contract
freeze. The current validated production implementation is retained.

**Phase 9.17 final result: PASS.**

The project is ready to proceed to Phase 9.18:

**API Contract Freeze.**
