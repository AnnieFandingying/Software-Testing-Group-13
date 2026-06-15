#!/usr/bin/env python3
"""Visualize LLMeLog anomaly scores on log windows."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch


def parse_time(value: str) -> pd.Timestamp:
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT
    try:
        return pd.to_datetime(float(value), unit="s", utc=True, errors="coerce")
    except (TypeError, ValueError):
        return pd.to_datetime(value, utc=True, errors="coerce")


def load_timeline(path: Path) -> dict[str, dict[str, object]]:
    windows = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            windows[row["run_id"]] = {
                "start": parse_time(row["start_ts"]),
                "end": parse_time(row["end_ts"]),
                "fault_type": row.get("fault_type", ""),
                "target_service": row.get("target_service", ""),
            }
    return windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    member_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--llmelog-root", default=r"D:\tmp\member_d_final_rerun_llmelog_run\code")
    parser.add_argument("--prepared-dir", default=str(member_root / "data" / "logs" / "processed" / "llmelog_final_rerun_verify_w5"))
    parser.add_argument("--dataset", default="final_rerun_verify")
    parser.add_argument("--timeline", default=str(member_root / "data" / "labels" / "final_rerun_verify_timeline.csv"))
    parser.add_argument("--out-dir", default=str(member_root / "results" / "visualizations"))
    parser.add_argument("--threshold", type=float, default=0.205)
    parser.add_argument("--hard-device", default="cuda", choices=["cpu", "cuda"])
    parser.add_argument("--gpu-index", default="0")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    llmelog_root = Path(args.llmelog_root).resolve()
    prepared_dir = Path(args.prepared_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target_data = llmelog_root / "data" / args.dataset
    target_data.mkdir(parents=True, exist_ok=True)
    for name in ["all.txt", "all_sequences.csv"]:
        shutil.copy2(prepared_dir / name, target_data / name)

    sys.path.insert(0, str(llmelog_root))
    os.chdir(llmelog_root)

    from src.dataset import ADloader, load_json
    from src.models import LLMeLog

    device = torch.device(f"cuda:{args.gpu_index}" if args.hard_device == "cuda" and torch.cuda.is_available() else "cpu")
    model_args = argparse.Namespace(
        hard_device=str(device),
        gpu_index=int(args.gpu_index),
        model_save_path="checkpoint",
        lr=0.0003,
        warmup_epochs=8,
        dataset=args.dataset,
    )
    embedding_dict = load_json(str(target_data / "emd_dict.json"))
    model = LLMeLog(model_args, embedding_dict).to(device)
    model.load_state_dict(torch.load(llmelog_root / "checkpoint" / "LLMeLog_model.bin", map_location=device))
    model.eval()

    loader = ADloader(str(target_data / "all.txt"), batch_size=args.batch_size, shuffle=False, num_workers=0)
    scores = []
    labels = []
    with torch.no_grad():
        for batch in loader:
            _, batch_labels = batch
            _, logits = model(batch)
            probs = torch.softmax(logits, dim=1)[:, 1].detach().cpu().numpy()
            scores.extend(probs.tolist())
            labels.extend([int(label[1]) for label in batch_labels])

    meta = pd.read_csv(target_data / "all_sequences.csv")
    if len(meta) != len(scores):
        raise SystemExit(f"metadata rows ({len(meta)}) != score count ({len(scores)})")
    meta["score"] = scores
    meta["model_label"] = (meta["score"] >= args.threshold).astype(int)
    meta["start_time"] = meta["start_ts"].apply(parse_time)
    meta["end_time"] = meta["end_ts"].apply(parse_time)
    meta["label"] = labels

    csv_path = out_dir / f"llmelog_{args.dataset}_scores.csv"
    meta.to_csv(csv_path, index=False)

    timeline = load_timeline(Path(args.timeline))
    run_ids = list(timeline)
    rows = len(run_ids)
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(rows, 1, figsize=(13, max(3.0 * rows, 6)), sharex=False)
    if rows == 1:
        axes = [axes]

    for ax, run_id in zip(axes, run_ids):
        data = meta[meta["run_id"] == run_id].sort_values("start_time")
        plot_data = data.dropna(subset=["start_time", "score"])
        window = timeline[run_id]
        if plot_data.empty:
            ax.text(0.5, 0.5, "No parseable timestamps in this run", ha="center", va="center", transform=ax.transAxes)
        else:
            ax.plot(plot_data["start_time"], plot_data["score"], color="#0f766e", linewidth=1.5, label="LLMeLog anomaly score")
            fault_points = plot_data[plot_data["label"] == 1]
            ax.scatter(
                fault_points["start_time"],
                fault_points["score"],
                color="#dc2626",
                s=14,
                label="fault-window log sequence",
                zorder=3,
            )
        ax.axhline(args.threshold, color="#d97706", linestyle="--", linewidth=1.1, label=f"demo threshold {args.threshold:.3f}")
        if pd.notna(window["start"]) and pd.notna(window["end"]):
            ax.axvspan(window["start"], window["end"], color="#ef4444", alpha=0.16)
        ax.set_title(f"{run_id}: {window['fault_type']} / {window['target_service']}")
        ax.set_ylabel("Score")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.legend(loc="upper left", fontsize=8, ncol=3)

    axes[-1].set_xlabel("Time")
    fig.suptitle("LLMeLog detects log anomaly windows from event sequences", y=0.995)
    fig.tight_layout()
    png_path = out_dir / f"llmelog_{args.dataset}_timeline.png"
    fig.savefig(png_path, dpi=180)

    visible_meta = meta.dropna(subset=["start_time"])
    summary = visible_meta.groupby("run_id").agg(
        plotted_windows=("score", "count"),
        true_fault_windows=("label", "sum"),
        predicted_windows=("model_label", "sum"),
        max_score=("score", "max"),
        mean_score=("score", "mean"),
    )
    summary["total_windows"] = meta.groupby("run_id")["score"].count()
    summary["untimed_windows"] = summary["total_windows"] - summary["plotted_windows"]
    summary = summary[
        [
            "total_windows",
            "plotted_windows",
            "untimed_windows",
            "true_fault_windows",
            "predicted_windows",
            "max_score",
            "mean_score",
        ]
    ]
    summary_path = out_dir / f"llmelog_{args.dataset}_summary.csv"
    summary.to_csv(summary_path)

    print(f"wrote {csv_path}")
    print(f"wrote {summary_path}")
    print(f"wrote {png_path}")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
