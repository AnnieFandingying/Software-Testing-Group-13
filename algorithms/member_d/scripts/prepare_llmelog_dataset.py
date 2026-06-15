#!/usr/bin/env python3
"""Prepare LLMeLog files from raw Online Boutique logs.

Generated files:
- enriched.csv
- train.txt
- dev.txt
- test.txt
- event_templates.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import re
from glob import glob
from collections import defaultdict
from pathlib import Path


UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{12,}\b")
NUM_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:ms|s|m|Mi|Gi|MB|GB|%)?(?![A-Za-z])")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TRACE_RE = re.compile(r"(?:trace_id|trace|request_id|session_id|span_id)=([A-Za-z0-9_.:-]+)")
ISO_FRACTION_RE = re.compile(r"(\.\d+)((?:[+-]\d{2}:\d{2})?)$")


def normalize_iso_fraction(match: re.Match[str]) -> str:
    fraction = match.group(1)[1:]
    fraction = (fraction + "000000")[:6]
    return f".{fraction}{match.group(2) or ''}"


def parse_time(value: str) -> int:
    value = value.strip()
    try:
        return int(float(value))
    except ValueError:
        pass
    text = value.replace("Z", "+00:00")
    text = ISO_FRACTION_RE.sub(normalize_iso_fraction, text)
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def load_timeline(path: str | None) -> list[tuple[str, int, int]]:
    if not path:
        return []
    windows: list[tuple[str, int, int]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            run_id = row.get("run_id", "")
            windows.append((run_id, parse_time(row["start_ts"]), parse_time(row["end_ts"])))
    return windows


def expand_log_paths(patterns: list[str]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches = sorted(glob(pattern))
        for path in matches or [pattern]:
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def label_for(run_id: str, timestamp: int | None, windows: list[tuple[str, int, int]]) -> int:
    if timestamp is None:
        return 0
    for window_run_id, start, end in windows:
        if window_run_id and window_run_id != run_id:
            continue
        if start <= timestamp <= end:
            return 1
    return 0


KNOWN_SERVICES = [
    "productcatalogservice",
    "recommendationservice",
    "checkoutservice",
    "discountservice",
    "telemetryservice",
    "currencyservice",
    "shippingservice",
    "paymentservice",
    "emailservice",
    "frontend",
    "adservice",
    "cartservice",
    "redis-cart",
]


def infer_context_from_path(path: str, fallback_run_id: str) -> tuple[str, str]:
    stem = Path(path).stem
    for service in sorted(KNOWN_SERVICES, key=len, reverse=True):
        suffix = f"_{service}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], service
    return fallback_run_id, "unknown"


def detect_log_encoding(path: str) -> str:
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if len(head) >= 2 and head[1] == 0:
        return "utf-16-le"
    return "utf-8"


def read_log_line(line: str, default_run_id: str, default_service: str = "unknown") -> dict[str, object] | None:
    text = ANSI_RE.sub("", line.strip())
    if not text:
        return None

    if text.startswith("{"):
        try:
            data = json.loads(text)
            timestamp_raw = str(data.get("timestamp") or data.get("time") or data.get("@timestamp") or "")
            timestamp = parse_time(timestamp_raw) if timestamp_raw else None
            service = str(data.get("service") or data.get("app") or data.get("container") or default_service)
            pod = str(data.get("pod") or data.get("pod_name") or "")
            message = str(data.get("message") or data.get("msg") or data.get("log") or text)
            run_id = str(data.get("run_id") or default_run_id)
            return {"timestamp": timestamp, "service": service, "pod": pod, "message": message, "run_id": run_id}
        except json.JSONDecodeError:
            pass

    parts = text.split(maxsplit=4)
    if len(parts) >= 5:
        timestamp_raw, service, pod, maybe_run, message = parts
        run_id = default_run_id
        if maybe_run.startswith("run_id="):
            run_id = maybe_run.split("=", 1)[1]
        else:
            message = maybe_run + " " + message
        try:
            timestamp = parse_time(timestamp_raw)
        except ValueError:
            timestamp = None
        return {"timestamp": timestamp, "service": service, "pod": pod, "message": message, "run_id": run_id}

    return {"timestamp": None, "service": default_service, "pod": "", "message": text, "run_id": default_run_id}


def normalize_template(service: str, message: str) -> str:
    message = UUID_RE.sub("<uuid>", message)
    message = HEX_RE.sub("<hex>", message)
    message = NUM_RE.sub("<num>", message)
    message = re.sub(r"\s+", " ", message).strip()
    return f"{service}: {message}"


def event_result_type(template: str, labels: list[int]) -> str:
    lower = template.lower()
    suspicious = any(word in lower for word in ["error", "fail", "exception", "timeout", "unavailable", "refused", "panic", "oom"])
    if suspicious or sum(labels) > max(len(labels) // 2, 0):
        return "probably cause anomalies"
    return "no obvious abnormalities"


def make_enriched_json(template: str, result_type: str) -> str:
    if ":" in template:
        service, action = template.split(":", 1)
    else:
        service, action = "service", template
    payload = {
        template: {
            "Event Subject": service.strip() or "service",
            "Event Action Description": action.strip() or template,
            "Event Result": action.strip() or template,
            "Events Result Type": result_type,
        }
    }
    return json.dumps(payload, ensure_ascii=False)


def group_sequences(
    events: list[dict[str, object]],
    mode: str,
    window_seconds: int,
) -> list[dict[str, object]]:
    groups: dict[tuple[str, object], list[dict[str, object]]] = defaultdict(list)
    for event in events:
        timestamp = event.get("timestamp")
        run_id = str(event["run_id"])
        if mode == "trace":
            match = TRACE_RE.search(str(event["message"]))
            key = match.group(1) if match else f"{timestamp}-{len(groups)}"
        else:
            bucket = int(timestamp // window_seconds) if isinstance(timestamp, int) else len(groups)
            key = bucket
        groups[(run_id, key)].append(event)

    sequences: list[dict[str, object]] = []
    for (run_id, key), group in sorted(groups.items(), key=lambda item: str(item[0])):
        ordered = sorted(group, key=lambda item: item.get("timestamp") or 0)
        ids = [int(item["event_id"]) for item in ordered]
        if not ids:
            continue
        label = max(int(item["label"]) for item in ordered)
        timestamps = [item.get("timestamp") for item in ordered if isinstance(item.get("timestamp"), int)]
        start_ts = min(timestamps) if timestamps else ""
        end_ts = max(timestamps) if timestamps else ""
        sequences.append(
            {
                "run_id": str(run_id),
                "bucket": key,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "label": label,
                "event_ids": ids,
            }
        )
    return sequences


def split_sequences(
    sequences: list[dict[str, object]],
    train_ratio: float,
    dev_ratio: float,
    seed: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    rng = random.Random(seed)
    by_label: dict[int, list[dict[str, object]]] = defaultdict(list)
    for seq in sequences:
        by_label[int(seq["label"])].append(seq)

    train: list[dict[str, object]] = []
    dev: list[dict[str, object]] = []
    test: list[dict[str, object]] = []
    for label, items in by_label.items():
        rng.shuffle(items)
        n_train = max(int(len(items) * train_ratio), 1 if items else 0)
        n_dev = max(int(len(items) * dev_ratio), 1 if len(items) - n_train > 1 else 0)
        train.extend(items[:n_train])
        dev.extend(items[n_train : n_train + n_dev])
        test.extend(items[n_train + n_dev :])

    rng.shuffle(train)
    rng.shuffle(dev)
    rng.shuffle(test)
    return train, dev, test


def write_sequence_file(path: Path, sequences: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for sequence in sequences:
            label = int(sequence["label"])
            event_ids = list(sequence["event_ids"])
            joined = " ".join(str(event_id) for event_id in event_ids)
            fh.write(f"{label}:{joined}\n")


def write_sequence_meta(path: Path, sequences: list[dict[str, object]], split: str) -> None:
    fieldnames = ["split", "run_id", "bucket", "start_ts", "end_ts", "label", "event_count", "sequence"]
    exists = path.exists()
    with path.open("a" if exists else "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for sequence in sequences:
            event_ids = [str(event_id) for event_id in sequence["event_ids"]]
            writer.writerow(
                {
                    "split": split,
                    "run_id": sequence["run_id"],
                    "bucket": sequence["bucket"],
                    "start_ts": sequence["start_ts"],
                    "end_ts": sequence["end_ts"],
                    "label": sequence["label"],
                    "event_count": len(event_ids),
                    "sequence": " ".join(event_ids),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", nargs="+", required=True)
    parser.add_argument("--timeline")
    parser.add_argument("--run-id", default="memberd")
    parser.add_argument("--out-dir", default="algorithms/member_d/data/logs/processed/llmelog_memberd")
    parser.add_argument("--sequence-mode", choices=["window", "trace"], default="window")
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--dev-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    windows = load_timeline(args.timeline)
    raw_events: list[dict[str, object]] = []
    template_to_id: dict[str, int] = {}
    template_labels: dict[int, list[int]] = defaultdict(list)

    for path in expand_log_paths(args.logs):
        default_run_id, default_service = infer_context_from_path(path, args.run_id)
        with open(path, "r", encoding=detect_log_encoding(path), errors="replace") as fh:
            for line in fh:
                event = read_log_line(line, default_run_id, default_service)
                if not event:
                    continue
                timestamp = event.get("timestamp")
                run_id = str(event["run_id"])
                label = label_for(run_id, timestamp if isinstance(timestamp, int) else None, windows)
                template = normalize_template(str(event["service"]), str(event["message"]))
                if template not in template_to_id:
                    template_to_id[template] = len(template_to_id) + 1
                event_id = template_to_id[template]
                event["template"] = template
                event["event_id"] = event_id
                event["label"] = label
                template_labels[event_id].append(label)
                raw_events.append(event)

    if not raw_events:
        raise SystemExit("no log events parsed")

    sequences = group_sequences(raw_events, args.sequence_mode, args.window_seconds)
    if not sequences:
        raise SystemExit("no sequences generated")

    train, dev, test = split_sequences(sequences, args.train_ratio, args.dev_ratio, args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    id_to_template = {event_id: template for template, event_id in template_to_id.items()}
    with (out_dir / "enriched.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["EventId", "EventTemplate"])
        writer.writeheader()
        for event_id in sorted(id_to_template):
            template = id_to_template[event_id]
            result_type = event_result_type(template, template_labels[event_id])
            writer.writerow({"EventId": str(event_id), "EventTemplate": make_enriched_json(template, result_type)})

    with (out_dir / "event_templates.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["event_id", "event_template", "label_hint_count"])
        writer.writeheader()
        for event_id in sorted(id_to_template):
            writer.writerow(
                {
                    "event_id": event_id,
                    "event_template": id_to_template[event_id],
                    "label_hint_count": sum(template_labels[event_id]),
                }
            )

    write_sequence_file(out_dir / "train.txt", train)
    write_sequence_file(out_dir / "dev.txt", dev)
    write_sequence_file(out_dir / "test.txt", test)
    write_sequence_file(out_dir / "all.txt", sequences)
    all_meta_path = out_dir / "all_sequences.csv"
    if all_meta_path.exists():
        all_meta_path.unlink()
    write_sequence_meta(all_meta_path, sequences, "all")
    meta_path = out_dir / "sequences.csv"
    if meta_path.exists():
        meta_path.unlink()
    write_sequence_meta(meta_path, train, "train")
    write_sequence_meta(meta_path, dev, "dev")
    write_sequence_meta(meta_path, test, "test")

    print(f"wrote {out_dir}")
    print(f"events={len(raw_events)} templates={len(template_to_id)} sequences={len(sequences)}")
    print(f"train={len(train)} dev={len(dev)} test={len(test)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
