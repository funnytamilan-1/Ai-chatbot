"""Train a small Qwen adapter from validated JustAI chat examples.

Run this only in a dedicated training environment. It is intentionally separate
from the FastAPI/Render web process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


class ChatDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, max_length: int = 1024):
        self.items = []
        for row in rows:
            messages = row.get("messages", [])
            if not messages or messages[-1].get("role") != "assistant":
                continue
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
            )
            encoded = tokenizer(
                rendered,
                truncation=True,
                max_length=max_length,
                add_special_tokens=False,
            )
            if len(encoded["input_ids"]) >= 2:
                self.items.append(encoded)
        if not self.items:
            raise ValueError("No valid chat examples were found in the dataset.")

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(row.get("messages"), list):
                raise ValueError(f"Line {line_number} must contain a messages array.")
            rows.append(row)
    if len(rows) < 2:
        raise ValueError("At least two training examples are required.")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--rank", type=int, choices=[8, 16, 32], default=8)
    args = parser.parse_args()

    if args.model != DEFAULT_MODEL:
        raise ValueError("This first release only supports the configured Qwen 0.5B base model.")

    rows = read_jsonl(args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    use_4bit = torch.cuda.is_available()
    quantization = None
    if use_4bit:
        try:
            import bitsandbytes  # noqa: F401
            quantization = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
        except ImportError:
            use_4bit = False

    model_kwargs = {"device_map": "auto"} if torch.cuda.is_available() else {}
    if quantization:
        model_kwargs["quantization_config"] = quantization
    else:
        model_kwargs["torch_dtype"] = torch.float16 if torch.cuda.is_available() else torch.float32

    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    if use_4bit:
        model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    adapter_config = LoraConfig(
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, adapter_config)
    model.print_trainable_parameters()

    dataset = ChatDataset(rows, tokenizer)
    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=1,
        fp16=bool(torch.cuda.is_available()),
        gradient_checkpointing=True,
        report_to="none",
        remove_unused_columns=False,
        optim="adamw_torch",
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    trainer.train()
    model.save_pretrained(args.output / "adapter")
    tokenizer.save_pretrained(args.output / "adapter")
    with (args.output / "training-summary.json").open("w", encoding="utf-8") as handle:
        json.dump({
            "base_model": args.model,
            "method": "LoRA",
            "epochs": args.epochs,
            "rank": args.rank,
            "examples": len(dataset),
            "adapter": "adapter",
        }, handle, indent=2)
    print(f"TRAINING_COMPLETE output={args.output / 'adapter'}")


if __name__ == "__main__":
    main()
