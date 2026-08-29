import json
from pathlib import Path


RESULTS_DIR = Path(__file__).resolve().parent / "results"

EXPERIMENTS = [
    ("Reference K=7", "phase8_ref_full_deterministic.json"),
    ("Top-K = 3", "phase8_topk_3_deterministic.json"),
    ("Top-K = 5", "phase8_topk_5_deterministic.json"),
    ("FK OFF", "phase8_fk_off_deterministic.json"),
    ("FK hops = 1", "phase8_fk_hops_1_deterministic.json"),
    ("Value Grounding OFF", "phase8_values_off_deterministic.json"),
    ("RAG OFF", "phase8_rag_off_deterministic.json"),
    ("Self-Correction OFF", "phase8_correction_off_deterministic.json"),
    ("Semantic Review OFF", "phase8_review_off_deterministic.json"),
]


def load_result(filename):
    path = RESULTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Missing result file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    rows = []

    for label, filename in EXPERIMENTS:
        data = load_result(filename)

        summary = data["summary"]
        config = data["config"]

        rows.append(
            {
                "label": label,
                "experiment_id": data["experiment_id"],
                "strict": summary["strict_execution_accuracy"],
                "semantic": summary["semantic_accuracy"],
                "execution": summary["execution_success_rate"],
                "table_recall": summary["required_table_recall"],
                "mean_tables": summary["mean_retrieved_tables"],
                "context_chars": summary["mean_context_characters"],
                "context_words": summary["mean_context_words"],
                "mean_latency_ms": summary["mean_latency_ms"],
                "median_latency_ms": summary["median_latency_ms"],
                "p95_latency_ms": summary["p95_latency_ms"],
                "config": config,
            }
        )

    reference = rows[0]

    print("=" * 150)
    print("PHASE 8 — DETERMINISTIC CONTROLLED ABLATION COMPARISON")
    print("=" * 150)

    header = (
        f"{'Experiment':<24}"
        f"{'Strict':>9}"
        f"{'Semantic':>11}"
        f"{'Exec':>9}"
        f"{'Recall':>9}"
        f"{'CtxChars':>11}"
        f"{'Latency(s)':>12}"
        f"{'ΔStrict':>10}"
        f"{'ΔSem':>9}"
        f"{'ΔLat(s)':>10}"
    )

    print(header)
    print("-" * 150)

    for row in rows:
        delta_strict = row["strict"] - reference["strict"]
        delta_semantic = row["semantic"] - reference["semantic"]

        latency_s = row["mean_latency_ms"] / 1000
        reference_latency_s = reference["mean_latency_ms"] / 1000
        delta_latency_s = latency_s - reference_latency_s

        print(
            f"{row['label']:<24}"
            f"{row['strict']:>8.1f}%"
            f"{row['semantic']:>10.1f}%"
            f"{row['execution']:>8.1f}%"
            f"{row['table_recall']:>8.1f}%"
            f"{row['context_chars']:>11.1f}"
            f"{latency_s:>12.2f}"
            f"{delta_strict:>+9.1f}"
            f"{delta_semantic:>+9.1f}"
            f"{delta_latency_s:>+10.2f}"
        )

    print("=" * 150)

    best_semantic = max(rows, key=lambda row: row["semantic"])
    best_strict = max(rows, key=lambda row: row["strict"])
    fastest = min(rows, key=lambda row: row["mean_latency_ms"])

    print()
    print("KEY OBSERVATIONS")
    print("-" * 80)

    print(
        f"Best semantic accuracy : "
        f"{best_semantic['label']} "
        f"({best_semantic['semantic']:.1f}%)"
    )

    print(
        f"Best strict accuracy   : "
        f"{best_strict['label']} "
        f"({best_strict['strict']:.1f}%)"
    )

    print(
        f"Fastest configuration  : "
        f"{fastest['label']} "
        f"({fastest['mean_latency_ms'] / 1000:.2f}s)"
    )

    print()
    print("REFERENCE CONFIG")
    print("-" * 80)

    print(json.dumps(reference["config"], indent=2))


if __name__ == "__main__":
    main()
