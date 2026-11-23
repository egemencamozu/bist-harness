"""QLoRA fine-tuning of the local explainer/planner model on training/data (Unsloth + TRL).

Runs in a SEPARATE environment (GPU libraries are not in the project venv): see training/README.md.

  # 1) timing pilot (measures seconds/step and prints the full-run estimate)
  python training/train_qlora.py --base unsloth/Qwen3.5-4B --pilot-steps 20
  # 2) full run (checkpoint every --save-steps; after an interruption re-run the same command with --resume)
  python training/train_qlora.py --base unsloth/Qwen3.5-4B --out training/output/bist-4b
  # 3) merge the adapter (16-bit safetensors) + Modelfile; Ollama quantizes it (separate step: an export failure
  #    never costs the training). `--gguf q4_k_m` instead uses Unsloth's llama.cpp route.
  python training/train_qlora.py --out training/output/bist-4b --export-only
  ollama create bist-analist -q q4_K_M -f training/output/bist-4b/Modelfile

Loss is computed on the assistant tokens only (the evidence prompt is context, not a target). Skill mix is sampled
deterministically (seed 42). The validation split (its own as_of dates) is evaluated every epoch.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mix(
    rows: list[dict[str, Any]], caps: dict[str, int], seed: int, upsample_candidates: int = 1
) -> list[dict[str, Any]]:
    """Per-skill caps; explanation examples whose target is a *_CANDIDATE action (rare: strict evidence rules) are
    repeated `upsample_candidates` times so the model still learns when a candidate label is justified."""
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for skill, cap in caps.items():
        part = [r for r in rows if r["skill"] == skill]
        rng.shuffle(part)
        out += part[:cap] if cap >= 0 else part
    rare = [r for r in out if r["skill"] == "explanation" and "CANDIDATE" in str(r.get("action", ""))]
    out += rare * max(0, upsample_candidates - 1)
    rng.shuffle(out)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="unsloth/Qwen3.5-9B")
    p.add_argument("--data", default=str(ROOT / "training" / "data"))
    p.add_argument("--out", default=str(ROOT / "training" / "output" / "run"))
    p.add_argument(
        "--caps", default="explanation=-1,intent=1500,planning=1000", help="max examples per skill (-1 = all)"
    )
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--r", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--max-seq", type=int, default=4096)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=16)
    p.add_argument("--pilot-steps", type=int, default=0)
    p.add_argument("--gguf", default="", help="e.g. q4_k_m: export a GGUF for Ollama after training")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--upsample-candidates", type=int, default=8)
    p.add_argument("--save-steps", type=int, default=50, help="checkpoint interval (optimizer steps)")
    p.add_argument("--resume", action="store_true", help="continue from the latest checkpoint in --out")
    p.add_argument("--export-only", action="store_true", help="skip training; export --gguf from --out/adapter")
    a = p.parse_args(argv)

    import unsloth  # noqa: F401  (must be imported before trl/transformers/peft to apply its patches)
    from datasets import Dataset  # GPU environment only
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    if a.export_only:
        if a.gguf:
            return export_gguf(Path(a.out), a.gguf, a.max_seq)
        return export_merged(Path(a.out), a.max_seq)

    caps = {k: int(v) for k, v in (x.split("=") for x in a.caps.split(","))}
    train_rows = mix(load(Path(a.data) / "train.jsonl"), caps, a.seed, a.upsample_candidates)
    val_rows = mix(
        load(Path(a.data) / "val.jsonl"), {k: (v if v < 0 else max(50, v // 10)) for k, v in caps.items()}, a.seed
    )
    model, tok = FastLanguageModel.from_pretrained(
        model_name=a.base, max_seq_length=a.max_seq, load_in_4bit=True, dtype=None
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=a.r,
        lora_alpha=a.alpha,
        lora_dropout=0.0,
        bias="none",
        random_state=a.seed,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
    )

    def render(rows: list[dict[str, Any]]) -> Dataset:
        texts = [tok.apply_chat_template(r["messages"], tokenize=False) for r in rows]
        return Dataset.from_list([{"text": t} for t in texts])

    train_ds, val_ds = render(train_rows), render(val_rows)
    text_tok = getattr(tok, "tokenizer", tok)  # multimodal checkpoints return a processor wrapping the tokenizer
    n_tokens = sum(len(text_tok(t)["input_ids"]) for t in train_ds["text"])
    print(f"train examples {len(train_ds)} (~{n_tokens / 1e6:.1f}M tokens/epoch), val {len(val_ds)}", flush=True)
    args = SFTConfig(
        output_dir=a.out,
        dataset_text_field="text",
        max_length=a.max_seq,  # TRL >= 1.0 name (was max_seq_length)
        per_device_train_batch_size=a.batch,
        gradient_accumulation_steps=a.grad_accum,
        num_train_epochs=a.epochs,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_steps=0.03,  # transformers 5: a value < 1 is a ratio of the total steps
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.0,
        seed=a.seed,
        report_to="none",
        save_strategy="no" if a.pilot_steps else "steps",
        save_steps=a.save_steps,
        save_total_limit=2,
        eval_strategy="no" if a.pilot_steps else "epoch",
        max_steps=a.pilot_steps or -1,
        bf16=True,
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tok,
        train_dataset=train_ds,
        eval_dataset=None if a.pilot_steps else val_ds,
        args=args,
    )
    trainer = train_on_responses_only(
        trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n"
    )
    t0 = time.perf_counter()
    trainer.train(resume_from_checkpoint=True if a.resume else None)
    secs = time.perf_counter() - t0
    if a.pilot_steps:
        per_step = secs / a.pilot_steps
        steps_full = a.epochs * len(train_ds) / (a.batch * a.grad_accum)
        print(
            f"PILOT: {per_step:.1f} s/step -> full run ~{per_step * steps_full / 3600:.1f} h "
            f"({steps_full:.0f} steps, {a.epochs} epochs)",
            flush=True,
        )
        return 0
    out = Path(a.out)
    model.save_pretrained(out / "adapter")
    tok.save_pretrained(out / "adapter")
    (out / "train_info.json").write_text(
        json.dumps(
            {
                "base": a.base,
                "examples": len(train_ds),
                "tokens_per_epoch": n_tokens,
                "epochs": a.epochs,
                "seconds": secs,
                "lr": a.lr,
                "r": a.r,
                "alpha": a.alpha,
                "caps": caps,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"ADAPTER: {out / 'adapter'}", flush=True)
    if a.gguf:
        return export_gguf(out, a.gguf, a.max_seq, model, tok)
    return 0


def export_merged(out: Path, max_seq: int) -> int:
    """Merge the adapter into the 16-bit base weights (safetensors) and write an Ollama Modelfile.

    Ollama converts + quantizes the safetensors itself (`ollama create -q q4_K_M`), so no llama.cpp build is needed
    on Windows. RENDERER/PARSER qwen3.5 = the same chat format the model was trained on (think block closed)."""
    from unsloth import FastLanguageModel

    model, tok = FastLanguageModel.from_pretrained(
        model_name=str(out / "adapter"), max_seq_length=max_seq, load_in_4bit=True, dtype=None
    )
    model.save_pretrained_merged(str(out / "merged"), tok, save_method="merged_16bit")
    (out / "Modelfile").write_text(
        "FROM ./merged\nRENDERER qwen3.5\nPARSER qwen3.5\n"
        "PARAMETER temperature 0\nPARAMETER seed 42\nPARAMETER num_ctx 4096\n",
        encoding="utf-8",
    )
    print(f"MERGED: {out / 'merged'}\nOllama: ollama create bist-analist -q q4_K_M -f {out / 'Modelfile'}", flush=True)
    return 0


def export_gguf(out: Path, method: str, max_seq: int, model: Any = None, tok: Any = None) -> int:
    """Alternative route: Unsloth's GGUF export (builds llama.cpp; fragile on Windows)."""
    if model is None:
        from unsloth import FastLanguageModel

        model, tok = FastLanguageModel.from_pretrained(
            model_name=str(out / "adapter"), max_seq_length=max_seq, load_in_4bit=True, dtype=None
        )
    model.save_pretrained_gguf(str(out / "gguf"), tok, quantization_method=method)
    gguf = sorted((out / "gguf").rglob("*.gguf"))[-1]
    (out / "Modelfile").write_text(
        f"FROM ./{gguf.relative_to(out).as_posix()}\nPARAMETER temperature 0\nPARAMETER seed 42\nPARAMETER num_ctx 4096\n",
        encoding="utf-8",
    )
    print(f"GGUF: {gguf}\nOllama: ollama create bist-analist -f {out / 'Modelfile'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
