import argparse
import json
import random

from pathlib import Path

import torch

from torch.utils.data import Dataset

from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

from peft import (
    LoraConfig,
    get_peft_model,
)


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = (
    "Qwen/Qwen2.5-Coder-0.5B-Instruct"
)

BASE_DIR = Path(__file__).resolve().parent

DATA_PATH = (
    BASE_DIR
    / "data"
    / "querypilot_lora_train.jsonl"
)

OUTPUT_DIR = (
    BASE_DIR
    / "outputs"
    / "querypilot_qwen_lora"
)

MAX_LENGTH = 1024

SEED = 42


# ============================================================
# LOAD JSONL
# ============================================================

def load_records(path):

    records = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            if not line.strip():
                continue

            record = json.loads(line)

            required = {
                "database_name",
                "instruction",
                "input",
                "output",
            }

            if not required.issubset(record):
                raise ValueError(
                    "Invalid training record at "
                    f"line {line_number}"
                )

            records.append(record)

    return records


# ============================================================
# DATASET
# ============================================================

class QueryPilotDataset(Dataset):

    def __init__(
        self,
        records,
        tokenizer,
        max_length,
    ):

        self.records = records
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):

        return len(self.records)

    def __getitem__(
        self,
        index,
    ):

        record = self.records[index]

        prompt_messages = [
            {
                "role": "system",
                "content": record["instruction"],
            },
            {
                "role": "user",
                "content": record["input"],
            },
        ]

        full_messages = [
            *prompt_messages,
            {
                "role": "assistant",
                "content": record["output"],
            },
        ]

        prompt_encoding = (
            self.tokenizer.apply_chat_template(
                prompt_messages,
                tokenize=True,
                add_generation_prompt=True,
            )
        )

        full_encoding = (
            self.tokenizer.apply_chat_template(
                full_messages,
                tokenize=True,
                add_generation_prompt=False,
            )
        )

        prompt_ids = prompt_encoding[
            "input_ids"
        ]

        input_ids = full_encoding[
            "input_ids"
        ]

        if len(input_ids) > self.max_length:
            raise ValueError(
                "Training example exceeds "
                f"MAX_LENGTH={self.max_length}. "
                f"Index={index}, "
                f"tokens={len(input_ids)}"
            )

        labels = input_ids.copy()

        prompt_length = len(
            prompt_ids
        )

        if prompt_length >= len(labels):
            raise ValueError(
                "No assistant response tokens "
                f"found at index={index}"
            )

        for token_index in range(
            prompt_length
        ):
            labels[token_index] = -100

        attention_mask = [
            1
            for _ in input_ids
        ]

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        }


# ============================================================
# DATA COLLATOR
# ============================================================

class QueryPilotDataCollator:

    def __init__(
        self,
        tokenizer,
    ):

        self.tokenizer = tokenizer

    def __call__(
        self,
        features,
    ):

        max_length = max(
            len(item["input_ids"])
            for item in features
        )

        batch_input_ids = []
        batch_attention_mask = []
        batch_labels = []

        pad_token_id = (
            self.tokenizer.pad_token_id
        )

        for item in features:

            padding_length = (
                max_length
                - len(item["input_ids"])
            )

            batch_input_ids.append(
                item["input_ids"]
                + [pad_token_id]
                * padding_length
            )

            batch_attention_mask.append(
                item["attention_mask"]
                + [0]
                * padding_length
            )

            batch_labels.append(
                item["labels"]
                + [-100]
                * padding_length
            )

        return {
            "input_ids": torch.tensor(
                batch_input_ids,
                dtype=torch.long,
            ),
            "attention_mask": torch.tensor(
                batch_attention_mask,
                dtype=torch.long,
            ),
            "labels": torch.tensor(
                batch_labels,
                dtype=torch.long,
            ),
        }


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Use a tiny dataset and one "
            "training step."
        ),
    )

    args = parser.parse_args()

    random.seed(SEED)
    torch.manual_seed(SEED)

    print("=" * 80)
    print("QUERYPILOT — QWEN LORA TRAINING")
    print("=" * 80)

    print()
    print("Model      :", MODEL_NAME)
    print("Data       :", DATA_PATH)
    print("Output     :", OUTPUT_DIR)
    print("Max length :", MAX_LENGTH)
    print("Smoke test :", args.smoke_test)
    print()

    # --------------------------------------------------------
    # TOKENIZER
    # --------------------------------------------------------

    print("Loading tokenizer...")

    tokenizer = (
        AutoTokenizer.from_pretrained(
            MODEL_NAME
        )
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = (
            tokenizer.eos_token
        )

    print("✅ Tokenizer loaded")

    # --------------------------------------------------------
    # DATA
    # --------------------------------------------------------

    print()
    print("Loading training records...")

    records = load_records(
        DATA_PATH
    )

    print(
        "Training records:",
        len(records),
    )

    if len(records) != 298:
        raise RuntimeError(
            "Expected exactly 298 "
            f"training records, got "
            f"{len(records)}"
        )

    if args.smoke_test:

        records = records[:4]

        print(
            "Smoke-test records:",
            len(records),
        )

    dataset = QueryPilotDataset(
        records=records,
        tokenizer=tokenizer,
        max_length=MAX_LENGTH,
    )

    # --------------------------------------------------------
    # MODEL
    # --------------------------------------------------------

    print()
    print("Loading base model...")

    model = (
        AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype="auto",
        )
    )

    print("✅ Base model loaded")

    # --------------------------------------------------------
    # LORA
    # --------------------------------------------------------

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=[
            "q_proj",
            "v_proj",
        ],
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(
        model,
        lora_config,
    )

    print()
    print("LoRA configuration:")
    print("  r              : 8")
    print("  alpha          : 16")
    print("  dropout        : 0.05")
    print("  target modules : q_proj, v_proj")
    print()

    model.print_trainable_parameters()

    # --------------------------------------------------------
    # TRAINING CONFIG
    # --------------------------------------------------------

    if args.smoke_test:

        epochs = 1
        max_steps = 1

    else:

        epochs = 3
        max_steps = -1

    training_args = TrainingArguments(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=epochs,
        max_steps=max_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        weight_decay=0.01,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        remove_unused_columns=False,
        seed=SEED,
        dataloader_num_workers=0,
        use_cpu=False,
    )

    collator = QueryPilotDataCollator(
        tokenizer
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=collator,
    )

    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

    print()
    print("=" * 80)

    if args.smoke_test:
        print(
            "STARTING ONE-STEP SMOKE TRAINING"
        )
    else:
        print(
            "STARTING FULL LORA TRAINING"
        )

    print("=" * 80)
    print()

    train_result = trainer.train()

    print()
    print("=" * 80)
    print("TRAINING COMPLETE")
    print("=" * 80)

    print(
        "Training loss:",
        train_result.training_loss,
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_directory = OUTPUT_DIR

    if args.smoke_test:
        save_directory = (
            OUTPUT_DIR
            / "smoke_test"
        )

    save_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    model.save_pretrained(
        save_directory
    )

    tokenizer.save_pretrained(
        save_directory
    )

    print()
    print(
        "Adapter saved:",
        save_directory,
    )

    print()
    print(
        "🎯 QUERYPILOT LORA RUN "
        "FINISHED SUCCESSFULLY"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()
