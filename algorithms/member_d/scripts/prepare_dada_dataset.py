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
    args = parser.parse_args()

    values, labels = read_rows(args.input)
    if not values:
        raise SystemExit("no metric values found")

    common_timestamps = None
    for metric_values in values.values():
        timestamps = set(metric_values)
        common_timestamps = timestamps if common_timestamps is None else common_timestamps & timestamps
    timestamps_sorted = sorted(common_timestamps or [])
    if not timestamps_sorted:
        raise SystemExit("no common timestamps across metrics")

    train_lens = args.train_lens or infer_train_lens(timestamps_sorted, labels)
    if train_lens >= len(timestamps_sorted):
        raise SystemExit("train_lens must be smaller than total time points")

    out_root = Path(args.out_root)
    data_dir = out_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = f"{args.dataset_name}.csv"
    dataset_path = data_dir / dataset_file

    with dataset_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "value", "cols"])
        writer.writeheader()
        for metric in sorted(values):
            for timestamp in timestamps_sorted:
                writer.writerow(
                    {
                        "date": format_date(timestamp),
                        "value": values[metric][timestamp],
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

