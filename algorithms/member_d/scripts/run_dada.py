#!/usr/bin/env python3
"""Run the bundled DADA code on a prepared Member D dataset."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    member_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--dada-root", default=str(member_root / "dada" / "code"))
    parser.add_argument(
        "--root-path",
        default=str(member_root / "data" / "kpi" / "processed" / "dada_evaluation_dataset"),
        help="Prepared DADA evaluation_dataset directory",
    )
    parser.add_argument("--dataset-name", default="memberd_online_boutique")
    parser.add_argument("--batch-size", default="32")
    parser.add_argument("--metric", nargs="+", default=["affiliation", "auc", "best_f1"])
    parser.add_argument("--thresholds", nargs="+", default=["0.20", "0.25", "0.30"])
    parser.add_argument("--gpu", default=None, help="GPU id. Omit to force CPU.")
    args = parser.parse_args()

    dada_root = Path(args.dada_root).resolve()
    if not (dada_root / "run.py").exists():
        raise SystemExit(f"DADA root not found: {dada_root}")

    root_path = Path(args.root_path).resolve()
    if not (root_path / "DETECT_META.csv").exists():
        raise SystemExit(f"prepared DADA root missing DETECT_META.csv: {root_path}")

    cmd = [
        "python",
        "-u",
        "run.py",
        "--metric",
        *args.metric,
        "--t",
        *args.thresholds,
        "--norm",
        "0",
        "--root_path",
        str(root_path),
        "--data",
        args.dataset_name,
        "--model",
        "./DADA",
        "--des",
        "zero_shot",
        "--batch_size",
        args.batch_size,
    ]
    if args.gpu is None:
        cmd.extend(["--use_gpu", "False"])
    else:
        cmd.extend(["--use_gpu", "True", "--gpu", args.gpu])

    print(" ".join(cmd))
    subprocess.run(cmd, cwd=dada_root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
