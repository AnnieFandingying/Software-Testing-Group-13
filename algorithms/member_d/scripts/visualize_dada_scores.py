#!/usr/bin/env python3
"""Visualize DADA anomaly scores on a KPI timeline."""

from __future__ import annotations

import argparse
import csv
import os
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
    text = str(value).strip()
    try:
        return pd.to_datetime(float(text), unit="s", utc=True)
    except ValueError:
        return pd.to_datetime(text, utc=True)


def load_timeline(path: Path) -> list[dict[str, object]]:
    windows = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            windows.append(
                {
                    "run_id": row.get("run_id", ""),
                    "start": parse_time(row["start_ts"]),
                    "end": parse_time(row["end_ts"]),
                    "fault_type": row.get("fault_type", ""),
                    "target_service": row.get("target_service", ""),
                }
            )
    return windows


def normalize(values: pd.Series) -> pd.Series:
    values = values.astype(float)
    min_value = values.min()
    max_value = values.max()
    if max_value == min_value:
        return values * 0
    return (values - min_value) / (max_value - min_value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    member_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--dada-root", default=str(member_root / "dada" / "code"))
    parser.add_argument("--root-path", default=str(member_root / "data" / "kpi" / "processed" / "dada_evaluation_dataset"))
    parser.add_argument("--dataset-name", default="memberd_ob_20260614_184048")
    parser.add_argument("--timeline", default=str(member_root / "data" / "labels" / "memberd_ob_20260614_184048_timeline.csv"))
    parser.add_argument("--out-dir", default=str(member_root / "results" / "visualizations"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seq-len", type=int, default=100)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--gpu", default="0")
    args = parser.parse_args()

    dada_root = Path(args.dada_root).resolve()
    root_path = Path(args.root_path).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(member_root / ".hf_cache"))
    os.environ.setdefault("HF_MODULES_CACHE", str(member_root / ".hf_cache" / "modules"))
    sys.path.insert(0, str(dada_root))

    from data_provider.data_provider import data_provider, read_data, read_meta
    from transformers import AutoModel

    file_path, train_lens = read_meta(str(root_path), args.dataset_name)
    df = read_data(file_path)
    timeline = load_timeline(Path(args.timeline))

    device = torch.device(f"cuda:{args.gpu}" if torch.cuda.is_available() else "cpu")
    model = AutoModel.from_pretrained(str(dada_root / "DADA"), trust_remote_code=True).to(device)
    model.eval()

    _, init_loader = data_provider(
        root_path=str(root_path),
        datasets=args.dataset_name,
        batch_size=args.batch_size,
        win_size=args.seq_len,
        step=args.stride,
        flag="init",
        num_workers=0,
    )
    _, test_loader = data_provider(
        root_path=str(root_path),
        datasets=args.dataset_name,
        batch_size=args.batch_size,
        win_size=args.seq_len,
        step=args.stride,
        flag="test",
        num_workers=0,
    )

    init_scores = []
    test_scores = []
    test_labels = []
    with torch.no_grad():
        for batch_x, _ in init_loader:
            score = model.infer(batch_x.float().to(device), norm=0).detach().cpu().numpy()
            init_scores.append(score.reshape(-1))
        for batch_x, batch_y in test_loader:
            score = model.infer(batch_x.float().to(device), norm=0).detach().cpu().numpy()
            test_scores.append(score)
            test_labels.append(batch_y.numpy())

    threshold = float(np.quantile(np.concatenate(init_scores), 0.95)) if init_scores else 0.0
    test_scores_np = np.concatenate(test_scores, axis=0)
    test_labels_np = np.concatenate(test_labels, axis=0).squeeze(-1)

    score_sum = np.zeros(len(df), dtype=float)
    score_count = np.zeros(len(df), dtype=float)
    label_max = np.zeros(len(df), dtype=int)
    for window_idx in range(test_scores_np.shape[0]):
        start = int(train_lens) + window_idx * args.stride
        end = min(start + args.seq_len, len(df))
        width = end - start
        if width <= 0:
            continue
        score_sum[start:end] += test_scores_np[window_idx, :width]
        score_count[start:end] += 1
        label_max[start:end] = np.maximum(label_max[start:end], test_labels_np[window_idx, :width].astype(int))

    valid = score_count > 0
    score = np.full(len(df), np.nan)
    score[valid] = score_sum[valid] / score_count[valid]

    score_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(df.index, utc=True),
            "dada_score": score,
            "threshold_p95_init": threshold,
            "label": label_max,
        }
    )
    csv_path = out_dir / f"dada_{args.dataset_name}_scores.csv"
    score_df.to_csv(csv_path, index=False)

    metric_columns = [col for col in df.columns if col != "label"]
    variances = df[metric_columns].astype(float).var().sort_values(ascending=False)
    top_metrics = list(variances.head(4).index)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1.4]})
    ax = axes[0]
    ax.plot(score_df["timestamp"], score_df["dada_score"], color="#2454a6", linewidth=1.8, label="DADA anomaly score")
    ax.axhline(threshold, color="#d97706", linestyle="--", linewidth=1.2, label="95% init threshold")
    for window in timeline:
        ax.axvspan(window["start"], window["end"], color="#ef4444", alpha=0.18)
        ax.text(
            window["start"],
            ax.get_ylim()[1],
            f"{window['fault_type']} / {window['target_service']}",
            color="#991b1b",
            fontsize=9,
            va="top",
        )
    ax.set_ylabel("Anomaly score")
    ax.set_title("DADA detects KPI anomaly during injected fault")
    ax.legend(loc="upper left")

    ax2 = axes[1]
    for metric in top_metrics:
        ax2.plot(pd.to_datetime(df.index, utc=True), normalize(df[metric]), linewidth=1.1, label=metric)
    for window in timeline:
        ax2.axvspan(window["start"], window["end"], color="#ef4444", alpha=0.18)
    ax2.set_ylabel("Normalized KPI")
    ax2.set_xlabel("Time")
    ax2.legend(loc="upper left", fontsize=8, ncol=2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    fig.tight_layout()
    png_path = out_dir / f"dada_{args.dataset_name}_timeline.png"
    fig.savefig(png_path, dpi=180)
    print(f"wrote {csv_path}")
    print(f"wrote {png_path}")
    print(f"threshold_p95_init={threshold:.6f} top_metrics={', '.join(top_metrics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
