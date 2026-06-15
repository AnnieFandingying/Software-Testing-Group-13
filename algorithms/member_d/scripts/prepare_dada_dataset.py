#!/usr/bin/env python3
"""Convert Member A KPI CSV exports into DADA evaluation_dataset format."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path


def parse_timestamp(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        text = value.strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp())


def format_date(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def read_rows(paths: list[str]) -> tuple[dict[str, dict[int, float]], dict[int, int]]:
    values: dict[str, dict[int, float]] = defaultdict(dict)
    labels: dict[int, int] = defaultdict(int)
    for path in paths:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                timestamp = parse_timestamp(row["timestamp"])
                metric = row["metric"].strip()
                if not metric:
                    continue
                try:
                    value = float(row["value"])
                except ValueError:
                    continue
                values[metric][timestamp] = value
                labels[timestamp] = max(labels[timestamp], int(float(row.get("label", "0") or 0)))
    return values, labels


def infer_train_lens(timestamps: list[int], labels: dict[int, int], fallback_ratio: float = 0.6) -> int:
    for idx, timestamp in enumerate(timestamps):
        if labels.get(timestamp, 0) == 1:
            return max(idx, 1)
    return max(int(len(timestamps) * fallback_ratio), 1)


def align_series(metric_values: dict[int, float], timestamps: list[int]) -> dict[int, float]:
    points = sorted(metric_values.items())
    first_value = points[0][1]
    last_value = first_value
    idx = 0
    aligned: dict[int, float] = {}
    for timestamp in timestamps:
        while idx < len(points) and points[idx][0] <= timestamp:
            last_value = points[idx][1]
            idx += 1
        aligned[timestamp] = last_value if idx > 0 else first_value
    return aligned


def write_meta(path: Path, dataset_file: str, dataset_name: str, train_lens: int, n_points: int) -> None:
    fieldnames = [
        "file_name",
        "trend",
        "seasonal",
        "stationary",
        "pattern",
        "shifting",
        "dataset_name",
        "type_value",
        "train_lens",
        "time_steps",
        "if_univariate",
        "size",
    ]
    exists = path.exists()
    rows = []
    if exists:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = [row for row in csv.DictReader(fh) if row.get("file_name") != dataset_file]
    rows.append(
        {
            "file_name": dataset_file,
            "trend": "",
            "seasonal": "",
            "stationary": "",
            "pattern": "",
            "shifting": "",
            "dataset_name": dataset_name,
            "type_value": "Multi",
            "train_lens": str(train_lens),
            "time_steps": str(n_points),
            "if_univariate": "FALSE",
            "size": "small",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, help="Raw KPI CSV files")
    parser.add_argument("--dataset-name", default="memberd_online_boutique")
    parser.add_argument(
        "--out-root",
        default="algorithms/member_d/data/kpi/processed/dada_evaluation_dataset",
        help="Directory containing DETECT_META.csv and data/",
    )
    parser.add_argument("--train-lens", type=int, help="Number of initial normal time points")
    parser.add_argument(
        "--repeat-points",
        type=int,
        default=1,
        help="Repeat each observed timestamp this many times with one-second offsets.",
    )
    args = parser.parse_args()

    values, labels = read_rows(args.input)
    if not values:
        raise SystemExit("no metric values found")

    timestamps_sorted = sorted({timestamp for metric_values in values.values() for timestamp in metric_values})
    if not timestamps_sorted:
        raise SystemExit("no timestamps found across metrics")
    if args.repeat_points < 1:
        raise SystemExit("repeat-points must be >= 1")

    if args.repeat_points > 1:
        original_timestamps = timestamps_sorted
        timestamps_sorted = [
            timestamp + offset
            for timestamp in original_timestamps
            for offset in range(args.repeat_points)
        ]
        labels = {
            timestamp + offset: labels.get(timestamp, 0)
            for timestamp in original_timestamps
            for offset in range(args.repeat_points)
        }

    train_lens = args.train_lens or infer_train_lens(timestamps_sorted, labels)
    if train_lens >= len(timestamps_sorted):
        raise SystemExit("train_lens must be smaller than total time points")

    aligned_values = {metric: align_series(metric_values, timestamps_sorted) for metric, metric_values in values.items()}

    out_root = Path(args.out_root)
    data_dir = out_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = f"{args.dataset_name}.csv"
    dataset_path = data_dir / dataset_file

    with dataset_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "value", "cols"])
        writer.writeheader()
        for metric in sorted(aligned_values):
            for timestamp in timestamps_sorted:
                writer.writerow(
                    {
                        "date": format_date(timestamp),
                        "value": aligned_values[metric][timestamp],
                        "cols": metric,
                    }
                )
        for timestamp in timestamps_sorted:
            writer.writerow(
                {
                    "date": format_date(timestamp),
                    "value": labels.get(timestamp, 0),
                    "cols": "label",
                }
            )

    write_meta(out_root / "DETECT_META.csv", dataset_file, args.dataset_name, train_lens, len(timestamps_sorted))
    print(f"wrote {dataset_path}")
    print(f"wrote {out_root / 'DETECT_META.csv'}")
    print(f"dataset_name={args.dataset_name} train_lens={train_lens} points={len(timestamps_sorted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
