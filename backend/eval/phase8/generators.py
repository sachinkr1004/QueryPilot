from llm.baseline_client import (
    client,
    clean_sql,
    format_examples,
)


# ============================================================
# PHASE-8 BASELINE GENERATOR
# ============================================================

def generate_phase8_baseline_sql(
    question,
    context,
):
    """
    Phase-8 production-style baseline generator.

    Important:
    - Does NOT accept gold SQL.
    - Uses only inference-time information.
    - Supports configurable retrieved schema.
    - Supports value grounding ON/OFF.
    - Supports RAG examples ON/OFF.
    """

    schema_text = context["schema_text"]
    value_text = context["value_text"]
    examples = context["examples"]

    example_text = format_examples(
        examples
    )

    value_section = (
        value_text
        if value_text
        else (
            "No relevant database values "
            "were provided."
        )
    )

    prompt = f"""
You are an expert PostgreSQL SQL generator.

Your job is to generate a PostgreSQL query that correctly
answers the user's question using ONLY the provided
retrieved database schema, relevant database values,
and safe RAG examples.

The examples are references only.
Do NOT blindly copy them.
Adapt them to the current question and schema.


IMPORTANT OUTPUT RULES:

- Return ONLY the SQL query.
- Do NOT use markdown.
- Do NOT provide explanations.
- Do NOT include comments.
- Return one executable PostgreSQL query only.


SCHEMA RULES:

- Use ONLY tables present in the provided schema.
- Use ONLY columns present in the provided schema.
- Do NOT invent tables or columns.
- Use exact table and column names.
- Quote PostgreSQL mixed-case identifiers correctly.
- Use schema-qualified table names.


VALUE RULES:

- Use provided relevant database values only when they
  are actually required by the user's question.
- Do NOT invent database values.
- Do NOT force a retrieved value into the SQL when it
  does not match the user's intent.


POSTGRESQL DATA TYPE RULES:

- Respect declared PostgreSQL data types.
- Do NOT introduce unnecessary numeric casts.
- Preserve text semantics for text columns.
- Treat textual 'null' as text when appropriate.


JOIN RULES:

- Use JOIN when multiple related tables are required.
- Prefer relationships explicitly shown in the schema.
- Every JOIN must contain a complete boolean ON condition.
- Do NOT invent relationships.


AGGREGATION RULES:

- Use COUNT, MIN, MAX, AVG, SUM and GROUP BY according
  to the user's requested semantics.
- Use HAVING for aggregate conditions.
- Use WHERE for row-level conditions.


DISTINCT RULES:

- Do NOT add DISTINCT unless the question explicitly
  requires distinct/unique results or it is logically
  necessary.


ORDERING RULES:

- Use ORDER BY / LIMIT only when required by the question.
- Preserve the declared data type while ordering.
- Do NOT invent unnecessary tie-breakers.


FINAL VERIFICATION:

Before returning SQL, silently verify:

1. Every table exists in the provided schema.
2. Every column exists in the provided schema.
3. JOIN conditions are valid.
4. Requested output fields are present and ordered correctly.
5. Aggregation/grouping matches the question.
6. Comparison directions match the question.
7. The SQL is executable PostgreSQL.
8. Return SQL only.


DATABASE SCHEMA:

{schema_text}


RELEVANT DATABASE VALUES:

{value_section}


SAFE RAG EXAMPLES:

{example_text}


USER QUESTION:

{question}


POSTGRESQL SQL:
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        max_completion_tokens=1000,
        temperature=0,
        seed=42,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    sql = (
        response
        .choices[0]
        .message
        .content
    )

    return clean_sql(sql)

# ============================================================
# LOCAL MODEL COMPARISON SUPPORT
# ============================================================

from pathlib import Path

import torch
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)


BASE_QWEN_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"

ADAPTER_PATH = (
    Path(__file__).resolve().parents[2]
    / "finetuning"
    / "outputs"
    / "querypilot_qwen_lora"
)

LOCAL_INSTRUCTION = (
    "Generate the correct PostgreSQL SQL query "
    "for the user's question using only the "
    "provided database schema, relevant database "
    "values, and safe RAG examples. "
    "Return only one executable PostgreSQL query."
)

MAX_NEW_TOKENS = 256

_LOCAL_TOKENIZER = None
_LOCAL_MODEL = None
_LOCAL_DEVICE = None
_LOCAL_GENERATOR = None


def load_phase8_local_generator(generator_name):
    global _LOCAL_TOKENIZER
    global _LOCAL_MODEL
    global _LOCAL_DEVICE
    global _LOCAL_GENERATOR

    if generator_name not in {
        "base_qwen",
        "qwen_lora",
    }:
        raise ValueError(
            f"Unsupported local generator: {generator_name}"
        )

    if (
        _LOCAL_MODEL is not None
        and _LOCAL_GENERATOR == generator_name
    ):
        return

    print("=" * 80)
    print("LOADING PHASE-8 LOCAL MODEL")
    print("=" * 80)
    print()
    print("Generator:", generator_name)
    print("Base model:", BASE_QWEN_MODEL)

    if generator_name == "qwen_lora":
        print("Adapter   :", ADAPTER_PATH)

    print()

    tokenizer_source = (
        ADAPTER_PATH
        if generator_name == "qwen_lora"
        else BASE_QWEN_MODEL
    )

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_source
    )

    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_QWEN_MODEL,
        torch_dtype="auto",
    )

    if generator_name == "qwen_lora":
        model = PeftModel.from_pretrained(
            base_model,
            ADAPTER_PATH,
        )
    else:
        model = base_model

    if torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    model = model.to(device)
    model.eval()

    _LOCAL_TOKENIZER = tokenizer
    _LOCAL_MODEL = model
    _LOCAL_DEVICE = device
    _LOCAL_GENERATOR = generator_name

    print("Device    :", device)
    print()
    print("✅ PHASE-8 LOCAL MODEL READY")
    print("=" * 80)
    print()


def generate_phase8_local_sql(
    question,
    context,
):
    if (
        _LOCAL_TOKENIZER is None
        or _LOCAL_MODEL is None
        or _LOCAL_DEVICE is None
    ):
        raise RuntimeError(
            "Local model has not been loaded."
        )

    messages = [
        {
            "role": "system",
            "content": LOCAL_INSTRUCTION,
        },
        {
            "role": "user",
            "content": context["input_context"],
        },
    ]

    inputs = _LOCAL_TOKENIZER.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )

    inputs = {
        key: value.to(_LOCAL_DEVICE)
        for key, value in inputs.items()
    }

    prompt_length = inputs["input_ids"].shape[1]

    with torch.no_grad():
        generated = _LOCAL_MODEL.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=_LOCAL_TOKENIZER.eos_token_id,
        )

    generated_tokens = generated[
        0,
        prompt_length:,
    ]

    sql = _LOCAL_TOKENIZER.decode(
        generated_tokens,
        skip_special_tokens=True,
    ).strip()

    return clean_sql(sql)


def prepare_phase8_generator(generator_name):
    if generator_name == "phase8_baseline":
        return

    load_phase8_local_generator(
        generator_name
    )


def generate_phase8_sql(
    generator_name,
    question,
    context,
):
    if generator_name == "phase8_baseline":
        return generate_phase8_baseline_sql(
            question=question,
            context=context,
        )

    if generator_name in {
        "base_qwen",
        "qwen_lora",
    }:
        return generate_phase8_local_sql(
            question=question,
            context=context,
        )

    raise ValueError(
        f"Unknown Phase-8 generator: {generator_name}"
    )
