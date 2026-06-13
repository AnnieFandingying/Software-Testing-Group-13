#!/usr/bin/env python3
"""Export Prometheus range-query results for Member D KPI experiments.

Output schema:
timestamp,metric,value,label,run_id,source_labels
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_QUERIES = [
    {
        "metric": "pod_cpu",
        "query": 'sum(rate(container_cpu_usage_seconds_total{namespace="{namespace}"}[1m])) by (pod)',
    },
    {
        "metric": "pod_memory",
        "query": 'sum(container_memory_usage_bytes{namespace="{namespace}"}) by (pod)',
    },
    {
        "metric": "pod_restarts",
        "query": 'kube_pod_container_status_restarts_total{namespace="{namespace}"}',
    },
    {"metric": "boutique_requests", "query": "boutique_requests_total"},
    {"metric": "boutique_errors", "query": "boutique_errors_total"},
    {"metric": "boutique_duration_sum", "query": "boutique_request_duration_ms_sum"},
    {"metric": "boutique_discount_hits", "query": "boutique_discount_hits_total"},
]


def parse_time(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        pass
    text = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value.strip("_") or "unknown"


def load_timeline(path: str | None, run_id: str) -> list[tuple[int, int]]:
    if not path:
        return []
    windows: list[tuple[int, int]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("run_id") and row["run_id"] != run_id:
                continue
            start = parse_time(row["start_ts"])
            end = parse_time(row["end_ts"])
            windows.append((start, end))
    return windows


def label_for(timestamp: int, windows: list[tuple[int, int]], default_label: int) -> int:
    if not windows:
        return default_label
    return int(any(start <= timestamp <= end for start, end in windows))


def load_queries(path: str | None) -> list[dict[str, str]]:
    if not path:
        return DEFAULT_QUERIES
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise SystemExit("query config must be a JSON list")
    return data


def query_range(prometheus_url: str, query: str, start: int, end: int, step: str) -> list[dict]:
    base = prometheus_url.rstrip("/") + "/api/v1/query_range"
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(base + "?" + params, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(payload)
    return payload.get("data", {}).get("result", [])


def metric_name(base: str, labels: dict[str, str]) -> str:
    suffix_parts = []
    for key in ("service", "pod", "deployment", "container", "rule", "action", "status", "error_type"):
        if labels.get(key):
            suffix_parts.append(slug(labels[key]))
    if suffix_parts:
        return slug(base + "_" + "_".join(suffix_parts))
    return slug(base)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", required=True, help="Prometheus base URL, e.g. http://127.0.0.1:9090")
    parser.add_argument("--start", required=True, help="Unix seconds or ISO timestamp")
    parser.add_argument("--end", required=True, help="Unix seconds or ISO timestamp")
    parser.add_argument("--step", default="15s", help="Prometheus query_range step, e.g. 15s or 1m")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace for templated queries")
    parser.add_argument("--queries-json", help="Optional JSON list of {metric, query}")
    parser.add_argument("--timeline", help="Fault timeline CSV with run_id,start_ts,end_ts")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--default-label", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    start = parse_time(args.start)
    end = parse_time(args.end)
    windows = load_timeline(args.timeline, args.run_id)
    queries = load_queries(args.queries_json)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["timestamp", "metric", "value", "label", "run_id", "source_labels"],
        )
        writer.writeheader()
        for spec in queries:
            query = spec["query"].format(namespace=args.namespace)
            results = query_range(args.prometheus_url, query, start, end, args.step)
            for series in results:
                labels = series.get("metric", {})
                name = metric_name(spec["metric"], labels)
                for ts, value in series.get("values", []):
                    timestamp = int(float(ts))
                    writer.writerow(
                        {
                            "timestamp": timestamp,
                            "metric": name,
                            "value": value,
                            "label": label_for(timestamp, windows, args.default_label),
                            "run_id": args.run_id,
                            "source_labels": json.dumps(labels, ensure_ascii=False, sort_keys=True),
                        }
                    )

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

