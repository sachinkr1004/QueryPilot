# QueryPilot — Phase 8 Final Evaluation Report

## 1. Purpose

Phase 8 evaluates QueryPilot through controlled ablations, configuration selection, and an untouched final test. Configuration selection was performed only on the frozen 20-question selection benchmark. The untouched final test was not used for configuration tuning.

## 2. Evaluation Safeguards

- Frozen experiment protocol and metrics.
- One-variable-at-a-time ablations.
- Deterministic saved experiment artifacts.
- Untouched final test excluded from configuration selection.
- Raw and hybrid generator results reported separately.
- Infrastructure failures separated from model failures.
- Official final-test scores preserved after failure analysis.

### Semantic-evaluation independence

Semantic review may rewrite SQL before execution, but it does not determine whether an answer is correct. Strict correctness is determined by deterministic result comparison. The semantic fallback is a deterministic tie-aware check for supported ORDER BY ... LIMIT 1 tie cases. Therefore the semantic-review model is not used as the correctness judge.

## 3. Reference and Component Ablations

| Configuration | Strict | Semantic | Execution | Mean latency ms |
|---|---:|---:|---:|---:|
| Reference K7 + FK ON | 85.0% | 90.0% | 100.0% | 18922.43 |
| Top-K 3 | 90.0% | 95.0% | 100.0% | 13847.12 |
| Top-K 5 | 95.0% | 100.0% | 100.0% | 20926.54 |
| FK hops 1 | 90.0% | 95.0% | 100.0% | 17830.05 |
| FK expansion OFF | 95.0% | 100.0% | 100.0% | 17175.70 |
| K5 + FK OFF | 90.0% | 95.0% | 100.0% | 15084.36 |
| Value grounding OFF | 80.0% | 90.0% | 100.0% | 18669.37 |
| RAG OFF | 80.0% | 90.0% | 100.0% | 13299.12 |
| Self-correction OFF | 85.0% | 90.0% | 95.0% | 13630.95 |
| Semantic review OFF | 75.0% | 85.0% | 100.0% | 6429.02 |

### Component findings

- K5 alone and FK expansion OFF each reached 95% strict and 100% semantic accuracy on the selection benchmark.
- Their gains were not additive: K5 + FK OFF reached 90% strict and 95% semantic accuracy.
- Disabling value grounding reduced strict accuracy to 80%.
- Disabling RAG reduced strict accuracy to 80%.
- Disabling self-correction reduced execution success to 95%.
- Disabling semantic review reduced strict/semantic accuracy to 75%/85%, while substantially reducing latency.
- Required-table recall remained 100% across the validated component experiments.

## 4. Generator Ablation

Raw generator performance must be separated from full hybrid pipeline performance because the hybrid Qwen pipelines can use GPT-OSS correction and semantic review.

| Generator | Mode | Strict | Semantic | Execution |
|---|---|---:|---:|---:|
| GPT-OSS | RAW | 90.0% | 95.0% | 100.0% |
| Base Qwen | RAW | 0.0% | 0.0% | 0.0% |
| Qwen LoRA | RAW | 55.0% | 60.0% | 70.0% |
| GPT-OSS | FULL | 95.0% | 100.0% | 100.0% |
| Base Qwen | FULL HYBRID | 95.0% | 100.0% | 100.0% |
| Qwen LoRA | FULL HYBRID | 80.0% | 85.0% | 95.0% |

GPT-OSS was the strongest independently evaluated raw generator. The Base-Qwen hybrid result must not be interpreted as 95% independent Base-Qwen generation accuracy.

## 5. Final Configuration

- **generator:** `baseline`
- **generator_model:** `openai/gpt-oss-120b`
- **top_k:** `7`
- **fk_expansion:** `False`
- **fk_hops:** `2`
- **value_grounding:** `True`
- **rag_examples:** `True`
- **rag_limit:** `5`
- **self_correction:** `True`
- **semantic_review:** `True`

FK hops is stored as 2 but is inactive while FK expansion is OFF.

## 6. Accuracy–Latency Trade-off

The reference configuration achieved 85% strict / 90% semantic accuracy with mean latency 18922.43 ms. FK expansion OFF improved selection-benchmark accuracy to 95% strict / 100% semantic while reducing mean latency to 17175.70 ms.

Semantic review OFF reduced mean latency to 6429.02 ms but reduced accuracy to 75% strict / 85% semantic. This exposes a substantial accuracy-latency trade-off.

## 7. Cost and Token Audit

The normal successful final-test path consists of one generation call and one semantic-review call. Self-correction adds a call only when initial execution fails.

- Final-test questions: 100
- Expected generation calls: 100
- Correction calls: 0
- Semantic-review calls: 100
- Expected normal LLM calls: 200

The monetary diagnostic uses the pricing assumptions recorded during the Phase-8 audit: $0.15 per 1M input tokens and $0.60 per 1M output tokens. These rates are recorded for reproducibility and should be re-verified before making future cost claims.

Measured diagnostic token examples:

| Sample | Input | Output | Total | Cost/question | Illustrative ×100 |
|---|---:|---:|---:|---:|---:|
| Low context | 1,935 | 223 | 2,158 | $0.00042405 | $0.042405 |
| Heavy context | 2,894 | 1,022 | 3,916 | $0.00104730 | $0.104730 |

These are measured diagnostic examples, not the exact historical 100-question token consumption or bill. The illustrative ×100 figures must not be reported as the actual final-test cost.

## 8. Untouched Final Test

The final evaluation used the Spider TEST split. From 2,147 candidate questions across 40 candidate databases, the frozen construction selected 20 databases with 5 questions each using structural stratification and deterministic seed 42. The final-test databases/questions were excluded from configuration selection. PostgreSQL mirrors were validated for all 20 selected databases: 92 tables and 243,765 rows with zero row-count mismatches.

- Questions: **100**
- Strict accuracy: **77/100 = 77.0%**
- Semantic accuracy: **79/100 = 79.0%**
- Execution success: **100/100 = 100.0%**
- Correction triggers: **0**
- Semantic reviews: **100**
- Successful semantic reviews: **97**
- Semantic-review errors: **3**
- Semantic rewrites: **4**
- Required-table recall: **100%**

The 100% execution-success rate means that every final generated query executed successfully; it does not imply answer correctness. The independent correctness metrics remained 77% strict and 79% semantic.

### Final-test latency

- Mean: **14326.48 ms**
- Median: **13778.17 ms**
- Saved P95: **26754.08 ms**

The saved P95 follows the evaluator's existing percentile-index convention. It is preserved rather than recomputed post hoc.

## 9. Failure Taxonomy

The final test contained **21 semantic failures**.

| Category | Count |
|---|---:|
| benchmark mismatch or ambiguity | 4 |
| cross engine numeric equivalence | 1 |
| genuine sql reasoning | 6 |
| projection result shape | 8 |
| semantic review regression | 2 |

Required-table retrieval failures: **0**.

The taxonomy distinguishes genuine SQL reasoning failures, projection/result-shape errors, benchmark ambiguity/mismatch, semantic-review regressions, and a cross-engine numeric equivalence limitation. Failure analysis did not alter the official 77% strict / 79% semantic score.

## 10. Semantic-Review Rewrite Audit

Among the four final-test SQL rewrites:

- Improved: **0**
- Regressed: **2**
- Unchanged correct: **1**
- Unchanged wrong: **1**

This small rewrite sample does not establish a universal effect, but it provides evidence that the current reviewer can be over-aggressive. Conditional or conservative review is therefore a Phase-9 optimization candidate.

## 11. Infrastructure and Model-Failure Separation

Final-test preparation exposed infrastructure issues involving TEST schema metadata, SQLite path resolution, PostgreSQL TEST mirrors, gold-SQL resolution, mixed-case schemas, tie-aware TEST resolution, NULL-safe result comparison, and a Groq 429 rate-limit event. These were treated separately from SQL-model failures.

An invalid early attempt caused by missing PostgreSQL TEST schemas was excluded. Infrastructure fixes were validated without changing the frozen model, prompts, retrieval configuration, grounding configuration, correction policy, or semantic-review policy. The official final result comes from the subsequent clean 100-question evaluation.

## 12. Generalization Result

The selected configuration achieved 95% strict / 100% semantic accuracy on the 20-question configuration-selection benchmark, but 77% strict / 79% semantic accuracy on the untouched 100-question final test.

This gap is retained as an important generalization result rather than being tuned away using the final test.

## 13. Final Architecture

Natural-language question → schema retrieval (K7) → retrieved-only schema context → value grounding → optional retrieved examples → GPT-OSS SQL generation → safe database execution → correction on execution failure → semantic review → final execution/result.

FK expansion is disabled in the selected configuration.

## 14. Limitations

- Final-test semantic accuracy is 79%, leaving meaningful room for improvement.
- Projection/result-shape errors are the largest failure category.
- Semantic review adds substantial latency/token cost and caused two audited regressions.
- The final TEST split returned zero RAG examples despite RAG being configured ON.
- Cross-engine result comparison can expose numeric representation differences.
- Monetary cost figures are diagnostic estimates rather than an exact historical bill.

## 15. Phase-9 Candidates

- Conditional/conservative semantic review.
- Reduce unnecessary LLM calls and token usage.
- Improve latency while preserving correctness.
- Improve projection/result-shape reasoning.
- Improve genuine multi-table SQL reasoning.
- Strengthen cross-engine numeric normalization where methodologically appropriate.

## 16. Phase-8 Status

All controlled ablations, methodology audits, configuration selection, untouched final testing, failure analysis, latency analysis, and diagnostic cost/token analysis are complete.

**Phase 8 is ready for final report validation and artifact freeze.**
