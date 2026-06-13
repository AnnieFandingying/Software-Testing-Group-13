#!/usr/bin/env python3
"""Copy prepared LLMeLog data into the bundled code directory and run selected stages."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


DEFAULT_BERT_MODEL_ID = "google-bert/bert-base-uncased"


def ensure_base_bert(llmelog_root: Path, model_id: str) -> None:
    target = llmelog_root / "bert-base-en"
    if (target / "pytorch_model.bin").exists() or (target / "model.safetensors").exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {model_id} to {target}")
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id)
    tokenizer.save_pretrained(target)
    model.save_pretrained(target)


def copy_dataset(prepared_dir: Path, llmelog_root: Path, dataset: str) -> None:
    target = llmelog_root / "data" / dataset
    target.mkdir(parents=True, exist_ok=True)
    required = ["enriched.csv", "train.txt", "dev.txt", "test.txt"]
    for name in required:
        src = prepared_dir / name
        if not src.exists():
            raise SystemExit(f"missing prepared file: {src}")
        shutil.copy2(src, target / name)
    print(f"copied dataset to {target}")


def run(cmd: list[str], cwd: Path) -> None:
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    member_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--llmelog-root", default=str(member_root / "llmelog" / "code"))
    parser.add_argument(
        "--prepared-dir",
        default=str(member_root / "data" / "logs" / "processed" / "llmelog_memberd"),
    )
    parser.add_argument("--dataset", default="memberd")
    parser.add_argument(
        "--stages",
        nargs="+",
        default=["predata", "encoder", "gen", "detector", "eval"],
        choices=["predata", "encoder", "gen", "detector", "eval"],
    )
    parser.add_argument("--hard-device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--gpu-index", default="0")
    parser.add_argument("--auto-download-bert", action="store_true")
    parser.add_argument("--bert-model-id", default=DEFAULT_BERT_MODEL_ID)
    args = parser.parse_args()

    llmelog_root = Path(args.llmelog_root).resolve()
    if not (llmelog_root / "main.py").exists():
        raise SystemExit(f"LLMeLog root not found: {llmelog_root}")
    prepared_dir = Path(args.prepared_dir).resolve()
    copy_dataset(prepared_dir, llmelog_root, args.dataset)

    if args.auto_download_bert:
        ensure_base_bert(llmelog_root, args.bert_model_id)

    common = ["--dataset", args.dataset, "--hard_device", args.hard_device, "--gpu_index", args.gpu_index]

    if "predata" in args.stages:
        run(["python", "predata.py", "--dataset", args.dataset], llmelog_root)
    if "encoder" in args.stages:
        run(["python", "main.py", "--mode", "train", "--encoder", "1", "--lr", "0.0002", *common], llmelog_root)
    if "gen" in args.stages:
        run(["python", "main.py", "--mode", "gen", "--encoder", "1", "--lr", "0.0002", *common], llmelog_root)
    if "detector" in args.stages:
        run(["python", "main.py", "--mode", "train", "--batch_size", "256", "--lr", "0.0003", *common], llmelog_root)
    if "eval" in args.stages:
        run(
            [
                "python",
                "main.py",
                "--mode",
                "eval",
                "--batch_size",
                "256",
                "--lr",
                "0.0003",
                "--load_checkpoint",
                "True",
                *common,
            ],
            llmelog_root,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
