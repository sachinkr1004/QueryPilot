import json
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"


# ============================================================
# FROZEN MODEL-COMPARISON RESULTS
# ============================================================

EXPERIMENTS = [
    {
        "model": "GPT-OSS",
        "mode": "RAW",
        "file": "phase8_model_raw_gptoss_k7_fkoff.json",
        "hybrid": False,
    },
    {
        "model": "Base Qwen",
        "mode": "RAW",
        "file": "phase8_model_raw_base_qwen_k7_fkoff.json",
        "hybrid": False,
    },
    {
        "model": "Qwen LoRA",
        "mode": "RAW",
        "file": "phase8_model_raw_qwen_lora_k7_fkoff.json",
        "hybrid": False,
    },
    {
        "model": "GPT-OSS",
        "mode": "FULL",
        "file": "phase8_fk_off_deterministic.json",
        "hybrid": False,
    },
    {
        "model": "Base Qwen",
        "mode": "FULL",
        "file": "phase8_model_full_base_qwen_k7_fkoff.json",
        "hybrid": True,
    },
    {
        "model": "Qwen LoRA",
        "mode": "FULL",
        "file": "phase8_model_full_qwen_lora_k7_fkoff.json",
        "hybrid": True,
    },
]


def load_result(filename):
    path = RESULTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Missing result file: {path}")

    with path.open() as f:
        return json.load(f)


def get_summary(data):
    summary = data.get("summary")

    if summary is None:
        raise ValueError("Result file does not contain a summary.")

    return summary


def build_rows():
    rows = []

    for experiment in EXPERIMENTS:
        data = load_result(experiment["file"])
        summary = get_summary(data)

        rows.append(
            {
                "model": experiment["model"],
                "mode": experiment["mode"],
                "hybrid": experiment["hybrid"],
                "questions": summary["questions"],
                "strict": summary["strict_execution_accuracy"],
                "semantic": summary["semantic_accuracy"],
                "execution": summary["execution_success_rate"],
                "latency": summary["mean_latency_ms"],
                "corrections": summary["self_correction_triggered"],
                "successful_corrections": summary["successful_corrections"],
                "reviews": summary["semantic_reviews_run"],
                "rewrites": summary["semantic_rewrites"],
            }
        )

    return rows


def find_row(rows, model, mode):
    for row in rows:
        if row["model"] == model and row["mode"] == mode:
            return row

    raise ValueError(f"Missing row for {model} {mode}")


def print_table(rows):
    print("=" * 125)
    print("PHASE 8.9 — MODEL COMPARISON")
    print("=" * 125)

    header = (
        f"{'Model':<14}"
        f"{'Mode':<8}"
        f"{'Strict %':>10}"
        f"{'Semantic %':>13}"
        f"{'Exec %':>10}"
        f"{'Latency ms':>14}"
        f"{'Corrections':>13}"
        f"{'Reviews':>10}"
        f"{'Hybrid':>10}"
    )

    print(header)
    print("-" * 125)

    for row in rows:
        print(
            f"{row['model']:<14}"
            f"{row['mode']:<8}"
            f"{row['strict']:>10.2f}"
            f"{row['semantic']:>13.2f}"
            f"{row['execution']:>10.2f}"
            f"{row['latency']:>14.2f}"
            f"{row['corrections']:>13}"
            f"{row['reviews']:>10}"
            f"{str(row['hybrid']):>10}"
        )

    print("=" * 125)


def print_raw_to_full(rows):
    print("\nRAW → FULL CHANGE")
    print("-" * 80)

    for model in ["GPT-OSS", "Base Qwen", "Qwen LoRA"]:
        raw = find_row(rows, model, "RAW")
        full = find_row(rows, model, "FULL")

        print(f"\n{model}")
        print(
            f"  Strict    : {raw['strict']:.2f}% -> "
            f"{full['strict']:.2f}% "
            f"({full['strict'] - raw['strict']:+.2f} pp)"
        )
        print(
            f"  Semantic  : {raw['semantic']:.2f}% -> "
            f"{full['semantic']:.2f}% "
            f"({full['semantic'] - raw['semantic']:+.2f} pp)"
        )
        print(
            f"  Execution : {raw['execution']:.2f}% -> "
            f"{full['execution']:.2f}% "
            f"({full['execution'] - raw['execution']:+.2f} pp)"
        )
        print(
            f"  Latency   : {raw['latency']:.2f} ms -> "
            f"{full['latency']:.2f} ms"
        )


def print_lora_effect(rows):
    base = find_row(rows, "Base Qwen", "RAW")
    lora = find_row(rows, "Qwen LoRA", "RAW")

    print("\nLoRA EFFECT — RAW GENERATOR")
    print("-" * 80)

    print(
        f"Strict    : {base['strict']:.2f}% -> "
        f"{lora['strict']:.2f}% "
        f"({lora['strict'] - base['strict']:+.2f} pp)"
    )
    print(
        f"Semantic  : {base['semantic']:.2f}% -> "
        f"{lora['semantic']:.2f}% "
        f"({lora['semantic'] - base['semantic']:+.2f} pp)"
    )
    print(
        f"Execution : {base['execution']:.2f}% -> "
        f"{lora['execution']:.2f}% "
        f"({lora['execution'] - base['execution']:+.2f} pp)"
    )


def print_notes():
    print("\nINTERPRETATION NOTES")
    print("-" * 80)

    print(
        "1. RAW results measure generator behavior without "
        "self-correction or semantic review."
    )

    print(
        "2. Base Qwen FULL and Qwen LoRA FULL are hybrid "
        "QueryPilot pipelines because correction/review use GPT-OSS."
    )

    print(
        "3. Therefore FULL hybrid scores must not be reported "
        "as pure local-model accuracy."
    )

    print(
        "4. GPT-OSS FULL reuses the validated K7 + FK-off "
        "deterministic experiment."
    )

    print(
        "5. The comparison benchmark contains 20 frozen Phase-8 "
        "questions; it is not the untouched final test."
    )


def main():
    rows = build_rows()

    question_counts = {row["questions"] for row in rows}

    if len(question_counts) != 1:
        raise ValueError(
            f"Model-comparison question counts differ: {question_counts}"
        )

    print_table(rows)
    print_raw_to_full(rows)
    print_lora_effect(rows)
    print_notes()


if __name__ == "__main__":
    main()
