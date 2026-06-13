#!/usr/bin/env python3
"""Export Prometheus KPI series to member D's long-form CSV format.

Output columns:
  timestamp,metric,value,label,run_id

The script uses only the Python standard library. It queries Prometheus
/api/v1/query_range for a fixed set of Kubernetes metrics and labels each point
from a timeline CSV.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_SERVICES = [
    "frontend",
    "checkoutservice",
    "discountservice",
    "telemetryservice",
]

# Prometheus queries are formatted with {service}. Each query should return a
# single time series for that service in a healthy kube-state/cAdvisor setup.
PROM_QUERIES = {
    "{service}_cpu": (
        'sum(rate(container_cpu_usage_seconds_total{namespace="default",pod=~"{service}-.*",container!="",container!="POD"}[1m]))'
    ),
    "{service}_memory_bytes": (
        'sum(container_memory_usage_bytes{namespace="default",pod=~"{service}-.*",container!="",container!="POD"})'
    ),
    "{service}_restarts": (
        'sum(kube_pod_container_status_restarts_total{namespace="default",pod=~"{service}-.*"})'
    ),
    "{service}_available_replicas": (
        'sum(kube_deployment_status_replicas_available{namespace="default",deployment="{service}"})'
    ),
}


def parse_time(value: str) -> dt.datetime:
    value = value.strip()
    if value.isdigit():
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        # Accept common human-readable CSV values.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = dt.datetime.strptime(value, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            raise
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def to_unix_seconds(value: str) -> int:
    return int(parse_time(value).timestamp())


def iso_utc(ts: float | int) -> str:
    return dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_timeline(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"timeline file not found: {path}")
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"run_id", "start_ts", "end_ts", "fault_type", "target_service", "chaos_file"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"timeline missing required columns: {sorted(missing)}")
        for row in reader:
            rows.append({
                "run_id": row["run_id"].strip(),
                "start": parse_time(row["start_ts"]),
                "end": parse_time(row["end_ts"]),
                "fault_type": row["fault_type"].strip().lower(),
            })
    if not rows:
        raise ValueError("timeline has no rows")
    return rows


def label_for(ts: float, timeline: list[dict[str, object]]) -> int:
    point = dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc)
    for row in timeline:
        if row["start"] <= point <= row["end"]:
            fault_type = str(row["fault_type"])
            if fault_type in {"normal", "none", "recovery"}:
                return 0
            return 1
    return 0


def query_range(prometheus_url: str, query: str, start: int, end: int, step: str) -> dict:
    base = prometheus_url.rstrip("/") + "/api/v1/query_range"
    params = urllib.parse.urlencode({
        "query": query,
        "start": str(start),
        "end": str(end),
        "step": step,
    })
    url = f"{base}?{params}"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload


def iter_values(payload: dict) -> list[tuple[float, float]]:
    result = payload.get("data", {}).get("result", [])
    values: list[tuple[float, float]] = []
    for series in result:
        for ts, value in series.get("values", []):
            try:
                values.append((float(ts), float(value)))
            except (TypeError, ValueError):
                continue
    # If a query accidentally returns multiple series, collapse by timestamp sum.
    collapsed: dict[float, float] = {}
    for ts, value in values:
        collapsed[ts] = collapsed.get(ts, 0.0) + value
    return sorted(collapsed.items())


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Prometheus KPI CSV for member D")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--timeline", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start", help="Override start time, ISO/Z or Unix seconds")
    parser.add_argument("--end", help="Override end time, ISO/Z or Unix seconds")
    parser.add_argument("--step", default="15s")
    parser.add_argument("--services", default=",".join(DEFAULT_SERVICES), help="Comma-separated deployment names")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    timeline = load_timeline(args.timeline)
    run_rows = [row for row in timeline if row["run_id"] == args.run_id]
    if not run_rows:
        raise ValueError(f"run_id {args.run_id!r} not found in timeline")

    start = to_unix_seconds(args.start) if args.start else int(min(row["start"] for row in run_rows).timestamp())
    end = to_unix_seconds(args.end) if args.end else int(max(row["end"] for row in run_rows).timestamp())
    services = [s.strip() for s in args.services.split(",") if s.strip()]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "metric", "value", "label", "run_id"])
        writer.writeheader()
        for service in services:
            for metric_template, query_template in PROM_QUERIES.items():
                metric = metric_template.format(service=service)
                query = query_template.format(service=service)
                print(f"querying {metric} ...", file=sys.stderr)
                payload = query_range(args.prometheus_url, query, start, end, args.step)
                for ts, value in iter_values(payload):
                    writer.writerow({
                        "timestamp": iso_utc(ts),
                        "metric": metric,
                        "value": value,
                        "label": label_for(ts, run_rows),
                        "run_id": args.run_id,
                    })
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
