#!/usr/bin/env python3
"""Analyze JMeter JTL output for checkout SLA reporting.

The script reads the CSV JTL produced by online_boutique_checkout_pressure.jmx
and writes:
  - sla_summary.md
  - sla_timeseries.csv
  - sla_tps_error_rate.svg

It intentionally uses only the Python standard library so it can run on a
fresh testing machine without scientific Python packages.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class Sample:
    timestamp_ms: int
    elapsed_ms: float
    label: str
    response_code: str
    success: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze JMeter CSV JTL results.")
    parser.add_argument("--jtl", required=True, help="Path to JMeter .jtl CSV file")
    parser.add_argument(
        "--out-dir",
        default="results/testing/jmeter",
        help="Output directory for summary, CSV and SVG",
    )
    parser.add_argument(
        "--bucket-seconds",
        type=int,
        default=10,
        help="Bucket size for time-series metrics",
    )
    parser.add_argument(
        "--label-filter",
        default="",
        help="Optional exact JMeter label to analyze, e.g. E2E Browse And Checkout",
    )
    parser.add_argument(
        "--sla-p95-ms",
        type=float,
        default=1500.0,
        help="p95 latency target in milliseconds",
    )
    parser.add_argument(
        "--sla-error-rate",
        type=float,
        default=0.05,
        help="Error-rate target as a decimal fraction",
    )
    parser.add_argument(
        "--fail-on-sla",
        action="store_true",
        help="Exit with code 2 when p95 or error-rate exceeds target",
    )
    return parser.parse_args()


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"true", "1", "yes"}


def read_samples(path: Path, label_filter: str) -> list[Sample]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        samples: list[Sample] = []
        for row in reader:
            label = row.get("label", "")
            if label_filter and label != label_filter:
                continue
            try:
                samples.append(
                    Sample(
                        timestamp_ms=int(float(row["timeStamp"])),
                        elapsed_ms=float(row["elapsed"]),
                        label=label,
                        response_code=row.get("responseCode", ""),
                        success=parse_bool(row.get("success", "false")),
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
    if not samples:
        raise SystemExit(f"no samples found in {path} for label_filter={label_filter!r}")
    return samples


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def summarize(samples: list[Sample]) -> dict[str, float]:
    elapsed = [s.elapsed_ms for s in samples]
    failed = [s for s in samples if not s.success]
    start = min(s.timestamp_ms for s in samples)
    end = max(s.timestamp_ms for s in samples)
    duration = max((end - start) / 1000.0, 1.0)
    return {
        "samples": float(len(samples)),
        "failed": float(len(failed)),
        "duration_seconds": duration,
        "tps": len(samples) / duration,
        "error_rate": len(failed) / len(samples),
        "avg_ms": mean(elapsed),
        "min_ms": min(elapsed),
        "p50_ms": percentile(elapsed, 0.50),
        "p90_ms": percentile(elapsed, 0.90),
        "p95_ms": percentile(elapsed, 0.95),
        "p99_ms": percentile(elapsed, 0.99),
        "max_ms": max(elapsed),
    }


def bucketize(samples: list[Sample], bucket_seconds: int) -> list[dict[str, float]]:
    start = min(s.timestamp_ms for s in samples)
    buckets: dict[int, list[Sample]] = defaultdict(list)
    for sample in samples:
        bucket = int((sample.timestamp_ms - start) // (bucket_seconds * 1000))
        buckets[bucket].append(sample)

    rows: list[dict[str, float]] = []
    for bucket in sorted(buckets):
        bucket_samples = buckets[bucket]
        elapsed = [s.elapsed_ms for s in bucket_samples]
        errors = sum(1 for s in bucket_samples if not s.success)
        rows.append(
            {
                "offset_seconds": float(bucket * bucket_seconds),
                "samples": float(len(bucket_samples)),
                "tps": len(bucket_samples) / bucket_seconds,
                "error_rate": errors / len(bucket_samples),
                "avg_ms": mean(elapsed),
                "p95_ms": percentile(elapsed, 0.95),
            }
        )
    return rows


def label_summary(samples: list[Sample]) -> list[tuple[str, dict[str, float]]]:
    by_label: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_label[sample.label].append(sample)
    return sorted(
        ((label, summarize(values)) for label, values in by_label.items()),
        key=lambda item: item[0],
    )


def write_timeseries(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["offset_seconds", "samples", "tps", "error_rate", "avg_ms", "p95_ms"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def scale(values: list[float], height: int, top: int, bottom: int) -> tuple[float, float]:
    usable = height - top - bottom
    low = 0.0
    high = max(values) if values else 1.0
    if high <= 0:
        high = 1.0
    return low, high / usable


def polyline(points: list[tuple[float, float]], color: str) -> str:
    if not points:
        return ""
    encoded = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (
        f'<polyline points="{encoded}" fill="none" stroke="{color}" '
        'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
    )


def write_svg(path: Path, rows: list[dict[str, float]]) -> None:
    width = 1040
    panel_height = 210
    margin_left = 74
    margin_right = 24
    top = 42
    bottom = 42
    total_height = panel_height * 3 + 40
    max_x = max((row["offset_seconds"] for row in rows), default=1.0) or 1.0

    metrics = [
        ("TPS", "tps", "#1f77b4", "requests/sec"),
        ("Error Rate", "error_rate", "#d62728", "fraction"),
        ("p95 Latency", "p95_ms", "#555555", "ms"),
    ]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_height}" viewBox="0 0 {width} {total_height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;font-size:13px}.title{font-size:18px;font-weight:700}.axis{stroke:#999;stroke-width:1}.grid{stroke:#e5e7eb;stroke-width:1}</style>',
        '<text class="title" x="24" y="26">Checkout Chaos Load Test SLA Curves</text>',
    ]

    plot_width = width - margin_left - margin_right
    for panel_idx, (title, key, color, unit) in enumerate(metrics):
        y0 = 36 + panel_idx * panel_height
        values = [row[key] for row in rows]
        _, unit_scale = scale(values, panel_height, top, bottom)
        max_value = max(values) if values else 1.0
        if max_value <= 0:
            max_value = 1.0
        y_base = y0 + panel_height - bottom
        y_top = y0 + top

        lines.extend(
            [
                f'<text x="24" y="{y0 + 24}" font-weight="700">{html.escape(title)} ({html.escape(unit)})</text>',
                f'<line class="axis" x1="{margin_left}" y1="{y_base}" x2="{width - margin_right}" y2="{y_base}"/>',
                f'<line class="axis" x1="{margin_left}" y1="{y_top}" x2="{margin_left}" y2="{y_base}"/>',
                f'<line class="grid" x1="{margin_left}" y1="{y_top}" x2="{width - margin_right}" y2="{y_top}"/>',
                f'<text x="12" y="{y_top + 4}">{max_value:.2f}</text>',
                f'<text x="34" y="{y_base + 4}">0</text>',
            ]
        )
        points = []
        for row in rows:
            x = margin_left + (row["offset_seconds"] / max_x) * plot_width
            y = y_base - row[key] / unit_scale
            points.append((x, max(min(y, y_base), y_top)))
        lines.append(polyline(points, color))
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary(
    path: Path,
    jtl_path: Path,
    overall: dict[str, float],
    per_label: list[tuple[str, dict[str, float]]],
    sla_p95_ms: float,
    sla_error_rate: float,
) -> None:
    p95_ok = overall["p95_ms"] <= sla_p95_ms
    error_ok = overall["error_rate"] <= sla_error_rate
    lines = [
        "# Checkout JMeter SLA Summary",
        "",
        f"- Source JTL: `{jtl_path}`",
        f"- Samples: {int(overall['samples'])}",
        f"- Failed samples: {int(overall['failed'])}",
        f"- Duration: {overall['duration_seconds']:.1f}s",
        f"- Overall TPS: {overall['tps']:.2f}",
        f"- Error Rate: {overall['error_rate'] * 100:.2f}% ({'PASS' if error_ok else 'FAIL'}, target <= {sla_error_rate * 100:.2f}%)",
        f"- Latency p95: {overall['p95_ms']:.1f} ms ({'PASS' if p95_ok else 'FAIL'}, target <= {sla_p95_ms:.1f} ms)",
        f"- Latency avg/p50/p90/p99/max: {overall['avg_ms']:.1f} / {overall['p50_ms']:.1f} / {overall['p90_ms']:.1f} / {overall['p99_ms']:.1f} / {overall['max_ms']:.1f} ms",
        "",
        "## Per Label",
        "",
        "| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, item in per_label:
        lines.append(
            f"| {label} | {int(item['samples'])} | {item['error_rate'] * 100:.2f}% | "
            f"{item['tps']:.2f} | {item['avg_ms']:.1f} | {item['p95_ms']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Guide",
            "",
            "- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.",
            "- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.",
            "- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    jtl_path = Path(args.jtl)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = read_samples(jtl_path, args.label_filter)
    overall = summarize(samples)
    rows = bucketize(samples, args.bucket_seconds)
    per_label = label_summary(samples)

    write_timeseries(out_dir / "sla_timeseries.csv", rows)
    write_svg(out_dir / "sla_tps_error_rate.svg", rows)
    write_summary(
        out_dir / "sla_summary.md",
        jtl_path,
        overall,
        per_label,
        args.sla_p95_ms,
        args.sla_error_rate,
    )

    sla_failed = overall["p95_ms"] > args.sla_p95_ms or overall["error_rate"] > args.sla_error_rate
    if sla_failed and args.fail_on_sla:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
