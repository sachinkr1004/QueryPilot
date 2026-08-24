import argparse
import json
from pathlib import Path

import torch

from peft import PeftModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)

from db import execute_query

from llm.baseline_client import (
    correct_sql,
    review_sql_semantics,
)

from eval.evaluate import (
    execute_gold_sql,
    compare_results,
    tie_aware_check,
)

from finetuning.prepare_data import (
    build_retrieval_context,
)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"

BASE_DIR = Path(__file__).resolve().parent

TEST_SET_PATH = BASE_DIR / "test_set.json"

ADAPTER_PATH = (
    BASE_DIR.parent
    / "finetuning"
    / "outputs"
    / "querypilot_qwen_lora"
)

RESULTS_DIR = BASE_DIR / "results"

INSTRUCTION = (
    "Generate the correct PostgreSQL SQL query "
    "for the user's question using only the "
    "provided database schema, relevant database "
    "values, and safe RAG examples. "
    "Return only one executable PostgreSQL query."
)

MAX_NEW_TOKENS = 256


# ============================================================
# LOAD TEST SET
# ============================================================

def load_test_set():
    with TEST_SET_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


# ============================================================
# LOAD TRAINED LORA MODEL
# ============================================================

def load_lora_model():

    print("=" * 80)
    print("LOADING TRAINED QUERYPILOT LORA")
    print("=" * 80)
    print()

    print("Base model :", BASE_MODEL)
    print("Adapter    :", ADAPTER_PATH)
    print()

    print("Loading tokenizer...")

    tokenizer = AutoTokenizer.from_pretrained(
        ADAPTER_PATH
    )

    print("✅ Tokenizer loaded")
    print()

    print("Loading base model...")

    base_model = (
        AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype="auto",
        )
    )

    print("✅ Base model loaded")
    print()

    print("Loading LoRA adapter...")

    model = PeftModel.from_pretrained(
        base_model,
        ADAPTER_PATH,
    )

    print("✅ LoRA adapter loaded")
    print()

    if torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    model = model.to(device)
    model.eval()

    print("Device:", device)
    print()

    print(
        "🎯 TRAINED LORA READY FOR EVALUATION"
    )
    print("=" * 80)
    print()

    return tokenizer, model, device


# ============================================================
# GENERATE SQL WITH TRAINED LORA
# ============================================================

def generate_lora_sql(
    question,
    database_name,
    gold_sql,
    tokenizer,
    model,
    device,
):

    context = build_retrieval_context(
        question=question,
        database_name=database_name,
        gold_sql=gold_sql,
    )

    messages = [
        {
            "role": "system",
            "content": INSTRUCTION,
        },
        {
            "role": "user",
            "content": context["input_context"],
        },
    ]

    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    prompt_length = (
        inputs["input_ids"].shape[1]
    )

    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated_tokens = generated[
        0,
        prompt_length:
    ]

    sql = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True,
    ).strip()

    return sql, context


# ============================================================
# EVALUATE ONE CASE
# ============================================================

def evaluate_one(
    test_case,
    tokenizer,
    model,
    device,
):

    test_id = test_case["id"]
    db_id = test_case["db_id"]
    question = test_case["question"]
    gold_sql = test_case["gold_sql"]

    generated_sql = None
    corrected_sql = None
    reviewed_sql = None
    final_sql = None

    initial_result = None
    generated_result = None
    gold_result = None

    initial_error = None
    review_error = None
    error = None

    correction_used = False
    correction_attempts = 0
    correction_success = False

    semantic_review_used = False
    semantic_review_changed = False
    semantic_review_success = False

    strict_correct = False
    semantic_correct = False
    tie_accepted = False

    rag_examples = 0

    try:

        # ----------------------------------------------------
        # 1. Generate SQL using trained LoRA
        # ----------------------------------------------------

        generated_sql, context = (
            generate_lora_sql(
                question=question,
                database_name=db_id,
                gold_sql=gold_sql,
                tokenizer=tokenizer,
                model=model,
                device=device,
            )
        )

        final_sql = generated_sql

        rag_examples = len(
            context["examples"]
        )

        # ----------------------------------------------------
        # 2. Execute raw LoRA SQL
        # ----------------------------------------------------

        try:

            initial_result = execute_query(
                generated_sql
            )

            generated_result = initial_result

        except Exception as execution_error:

            initial_error = str(
                execution_error
            )

            # ------------------------------------------------
            # 3. Self-correct exactly once
            # ------------------------------------------------

            correction_used = True
            correction_attempts = 1

            corrected_sql = correct_sql(
                question=question,
                schema_text=context["schema_text"],
                failed_sql=generated_sql,
                error_message=initial_error,
                examples=context["examples"],
            )

            final_sql = corrected_sql

            # ------------------------------------------------
            # 4. Execute corrected SQL
            # ------------------------------------------------

            try:

                generated_result = execute_query(
                    corrected_sql
                )

                correction_success = True

            except Exception as corrected_error:

                error = str(
                    corrected_error
                )

        # ----------------------------------------------------
        # 5. Semantic review successful executable SQL
        # ----------------------------------------------------

        if (
            error is None
            and generated_result is not None
        ):

            semantic_review_used = True

            try:

                reviewed_sql = review_sql_semantics(
                    question=question,
                    schema_text=context["schema_text"],
                    sql=final_sql,
                    examples=context["examples"],
                )

                semantic_review_changed = (
                    reviewed_sql.strip()
                    != final_sql.strip()
                )

                if semantic_review_changed:

                    reviewed_result = execute_query(
                        reviewed_sql
                    )

                    final_sql = reviewed_sql
                    generated_result = reviewed_result

                semantic_review_success = True

            except Exception as semantic_error:

                review_error = str(
                    semantic_error
                )

                # Preserve the already executable SQL if
                # semantic review itself fails.
                reviewed_sql = None
                semantic_review_changed = False
                semantic_review_success = False

        # ----------------------------------------------------
        # 6. Execute gold SQL
        # ----------------------------------------------------

        gold_result = execute_gold_sql(
            db_id,
            gold_sql,
        )

        # ----------------------------------------------------
        # 7. Compare final successful result
        # ----------------------------------------------------

        if (
            error is None
            and generated_result is not None
        ):

            strict_correct = compare_results(
                generated_result,
                gold_result,
            )

            if strict_correct:

                semantic_correct = True

            else:

                tie_accepted = tie_aware_check(
                    db_id,
                    final_sql,
                    gold_sql,
                    generated_result,
                    gold_result,
                )

                semantic_correct = tie_accepted

    except Exception as exception:

        error = str(exception)

        strict_correct = False
        semantic_correct = False
        tie_accepted = False

    return {
        "id": test_id,
        "db_id": db_id,
        "question": question,
        "rag_examples": rag_examples,

        "generated_sql": generated_sql,
        "corrected_sql": corrected_sql,
        "reviewed_sql": reviewed_sql,
        "final_sql": final_sql,

        "gold_sql": gold_sql,

        "initial_result": initial_result,
        "generated_result": generated_result,
        "gold_result": gold_result,

        "correction_used": correction_used,
        "correction_attempts": correction_attempts,
        "correction_success": correction_success,

        "semantic_review_used": semantic_review_used,
        "semantic_review_changed": semantic_review_changed,
        "semantic_review_success": semantic_review_success,

        "initial_error": initial_error,
        "review_error": review_error,
        "error": error,

        "strict_correct": strict_correct,
        "semantic_correct": semantic_correct,
        "tie_accepted": tie_accepted,
    }


# ============================================================
# RUN EVALUATION
# ============================================================

def run_evaluation(
    cases,
    tokenizer,
    model,
    device,
):

    results = []

    for index, test_case in enumerate(
        cases,
        start=1,
    ):

        print("=" * 80)

        print(
            f"[{index}/{len(cases)}] "
            f"{test_case['id']}"
        )

        print()

        print(
            "Question:",
            test_case["question"],
        )

        print()

        result = evaluate_one(
            test_case,
            tokenizer,
            model,
            device,
        )

        results.append(result)

        print("Generated SQL:")
        print()
        print(result["generated_sql"])

        if result["correction_used"]:

            print()
            print("Initial execution error:")
            print()
            print(result["initial_error"])

            print()
            print("Corrected SQL:")
            print()
            print(result["corrected_sql"])

            print()
            print(
                "Correction attempts:",
                result["correction_attempts"],
            )

            print(
                "Correction success :",
                result["correction_success"],
            )

        if result["semantic_review_used"]:

            print()
            print(
                "Semantic review used   :",
                result["semantic_review_used"],
            )

            print(
                "Semantic review changed:",
                result["semantic_review_changed"],
            )

            print(
                "Semantic review success:",
                result["semantic_review_success"],
            )

            if result["semantic_review_changed"]:

                print()
                print("Reviewed SQL:")
                print()
                print(result["reviewed_sql"])

            if result["review_error"]:

                print()
                print("Semantic review error:")
                print()
                print(result["review_error"])

        print()

        if result["strict_correct"]:

            if result["semantic_review_changed"]:
                status = (
                    "✅ STRICT CORRECT "
                    "(AFTER SEMANTIC REVIEW)"
                )

            elif result["correction_used"]:
                status = (
                    "✅ STRICT CORRECT "
                    "(AFTER SELF-CORRECTION)"
                )

            else:
                status = "✅ STRICT CORRECT"

        elif result["tie_accepted"]:

            if result["semantic_review_changed"]:
                status = (
                    "🟡 SEMANTIC CORRECT "
                    "(AFTER SEMANTIC REVIEW)"
                )

            elif result["correction_used"]:
                status = (
                    "🟡 SEMANTIC CORRECT "
                    "(AFTER SELF-CORRECTION)"
                )

            else:
                status = (
                    "🟡 SEMANTIC CORRECT "
                    "(NON-DETERMINISTIC TIE)"
                )

        elif result["error"]:

            status = "❌ ERROR"

        else:

            status = "❌ WRONG"

        print("Status:", status)

        if result["error"]:

            print()
            print("Final error:")
            print()
            print(result["error"])

        print()

    return results


# ============================================================
# BUILD SUMMARY
# ============================================================

def build_summary(results):

    total = len(results)

    strict_correct = sum(
        item["strict_correct"]
        for item in results
    )

    semantic_correct = sum(
        item["semantic_correct"]
        for item in results
    )

    tie_accepted = sum(
        item["tie_accepted"]
        for item in results
    )

    errors = sum(
        item["error"] is not None
        for item in results
    )

    correction_used = sum(
        item["correction_used"]
        for item in results
    )

    correction_success = sum(
        item["correction_success"]
        for item in results
    )

    semantic_review_used = sum(
        item["semantic_review_used"]
        for item in results
    )

    semantic_review_changed = sum(
        item["semantic_review_changed"]
        for item in results
    )

    semantic_review_success = sum(
        item["semantic_review_success"]
        for item in results
    )

    semantic_review_failures = sum(
        (
            item["semantic_review_used"]
            and not item["semantic_review_success"]
        )
        for item in results
    )

    execution_success = (
        total
        - errors
    )

    strict_accuracy = (
        strict_correct / total * 100
        if total
        else 0
    )

    semantic_accuracy = (
        semantic_correct / total * 100
        if total
        else 0
    )

    execution_success_rate = (
        execution_success / total * 100
        if total
        else 0
    )

    correction_success_rate = (
        correction_success
        / correction_used
        * 100
        if correction_used
        else 0
    )

    semantic_review_success_rate = (
        semantic_review_success
        / semantic_review_used
        * 100
        if semantic_review_used
        else 0
    )

    return {
        "questions": total,

        "strict_correct": strict_correct,
        "strict_accuracy": round(
            strict_accuracy,
            2,
        ),

        "semantic_correct": semantic_correct,
        "semantic_accuracy": round(
            semantic_accuracy,
            2,
        ),

        "tie_equivalent_accepted": (
            tie_accepted
        ),

        "execution_errors": errors,
        "execution_success_rate": round(
            execution_success_rate,
            2,
        ),

        "self_correction_triggered": (
            correction_used
        ),

        "successful_corrections": (
            correction_success
        ),

        "correction_success_rate": round(
            correction_success_rate,
            2,
        ),

        "semantic_reviews_run": (
            semantic_review_used
        ),

        "semantic_rewrites": (
            semantic_review_changed
        ),

        "successful_semantic_reviews": (
            semantic_review_success
        ),

        "semantic_review_failures": (
            semantic_review_failures
        ),

        "semantic_review_success_rate": round(
            semantic_review_success_rate,
            2,
        ),
    }


# ============================================================
# PRINT SUMMARY
# ============================================================

def print_summary(
    split,
    summary,
):

    print()

    print("=" * 80)

    print(
        "PHASE 7.8 — POST-LORA "
        f"{split.upper()} SUMMARY"
    )

    print("=" * 80)
    print()

    print(
        "Questions              :",
        summary["questions"],
    )

    print(
        "Strict correct         :",
        summary["strict_correct"],
    )

    print(
        "Strict accuracy        :",
        f"{summary['strict_accuracy']:.2f}%",
    )

    print()

    print(
        "Semantic correct       :",
        summary["semantic_correct"],
    )

    print(
        "Semantic accuracy      :",
        f"{summary['semantic_accuracy']:.2f}%",
    )

    print(
        "Tie-equivalent accepted:",
        summary["tie_equivalent_accepted"],
    )

    print()

    print(
        "Execution errors       :",
        summary["execution_errors"],
    )

    print(
        "Execution success rate :",
        f"{summary['execution_success_rate']:.2f}%",
    )

    print()

    print(
        "Self-correction triggered:",
        summary["self_correction_triggered"],
    )

    print(
        "Successful corrections   :",
        summary["successful_corrections"],
    )

    print(
        "Correction success rate  :",
        f"{summary['correction_success_rate']:.2f}%",
    )

    print()

    print(
        "Semantic reviews run      :",
        summary["semantic_reviews_run"],
    )

    print(
        "Semantic rewrites         :",
        summary["semantic_rewrites"],
    )

    print(
        "Successful semantic review:",
        summary["successful_semantic_reviews"],
    )

    print(
        "Semantic review failures  :",
        summary["semantic_review_failures"],
    )

    print(
        "Semantic review success   :",
        f"{summary['semantic_review_success_rate']:.2f}%",
    )

    print()
    print("=" * 80)


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "split",
        nargs="?",
        default="dev",
        choices=[
            "dev",
            "holdout",
        ],
    )

    parser.add_argument(
        "--one",
        action="store_true",
        help=(
            "Evaluate only the first case "
            "for a smoke test."
        ),
    )

    args = parser.parse_args()

    test_set = load_test_set()

    cases = [
        item
        for item in test_set
        if item["split"] == args.split
    ]

    if args.one:
        cases = cases[:1]

    tokenizer, model, device = (
        load_lora_model()
    )

    print("=" * 80)
    print("PHASE 7.8 — LORA + CORRECTION + SEMANTIC REVIEW EVALUATION")
    print("=" * 80)
    print()

    print("Split :", args.split)
    print("Cases :", len(cases))
    print("Mode  :", "ONE CASE" if args.one else "FULL")
    print()

    results = run_evaluation(
        cases,
        tokenizer,
        model,
        device,
    )

    summary = build_summary(
        results
    )

    print_summary(
        args.split,
        summary,
    )

    if not args.one:

        RESULTS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            RESULTS_DIR
            / (
                "phase7_post_lora_"
                f"{args.split}.json"
            )
        )

        output_data = {
            "phase": "7.8",
            "name": "LoRA + Self-Correction + Semantic Review Evaluation",
            "model": BASE_MODEL,
            "adapter": str(ADAPTER_PATH),
            "split": args.split,
            "summary": summary,
            "results": results,
        }

        output_path.write_text(
            json.dumps(
                output_data,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print()
        print(
            "Results saved:",
            output_path,
        )

    print()
    print("=" * 80)
    print(
        "🎯 LORA + CORRECTION + SEMANTIC REVIEW EVALUATION FINISHED"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
