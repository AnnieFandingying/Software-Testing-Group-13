#!/usr/bin/env python3
"""Collect Kubernetes pod logs for Member D LLMeLog experiments."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def find_pods(service: str, namespace: str) -> list[str]:
    cmd = [
        "kubectl",
        "get",
        "pods",
        "-n",
        namespace,
        "-l",
        f"app={service}",
        "-o",
        "json",
    ]
    data = json.loads(run(cmd))
    pods = []
    for item in data.get("items", []):
        phase = item.get("status", {}).get("phase")
        if phase == "Running":
            pods.append(item["metadata"]["name"])
    return pods


def collect_pod_logs(pod: str, namespace: str, since: str | None, tail: str | None) -> str:
    cmd = ["kubectl", "logs", pod, "-n", namespace, "--timestamps"]
    if since:
        cmd.append(f"--since={since}")
    if tail:
        cmd.append(f"--tail={tail}")
    return run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--services", nargs="+", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-dir", default="algorithms/member_d/data/logs/raw")
    parser.add_argument("--since", help="kubectl logs --since value, e.g. 30m or 2h")
    parser.add_argument("--tail", help="kubectl logs --tail value")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for service in args.services:
        pods = find_pods(service, args.namespace)
        if not pods:
            print(f"warn: no running pods found for service={service}")
            continue
        out_path = out_dir / f"{args.run_id}_{service}.log"
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            for pod in pods:
                logs = collect_pod_logs(pod, args.namespace, args.since, args.tail)
                for line in logs.splitlines():
                    if not line.strip():
                        continue
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        timestamp, message = parts
                    else:
                        timestamp, message = "", parts[0]
                    fh.write(f"{timestamp} {service} {pod} run_id={args.run_id} {message}\n")
        print(f"wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

