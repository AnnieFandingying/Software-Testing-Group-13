#!/usr/bin/env python3
"""HTTP fallback load runner for checkout testing.

This runner mirrors the JMeter checkout scenario with only the Python standard
library. It is intended for environments where Java, JMeter, Selenium, or a
browser driver are unavailable, while still producing a JMeter-compatible CSV
JTL that can be analyzed by analyze_jmeter_results.py.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


JTL_FIELDS = [
    "timeStamp",
    "elapsed",
    "label",
    "responseCode",
    "responseMessage",
    "threadName",
    "dataType",
    "success",
    "failureMessage",
    "bytes",
    "sentBytes",
    "grpThreads",
    "allThreads",
    "URL",
    "Latency",
    "IdleTime",
    "Connect",
]

DEFAULT_PRODUCT_ID = "1YMWWN1N4O"


@dataclass
class Sample:
    timeStamp: int
    elapsed: int
    label: str
    responseCode: str
    responseMessage: str
    threadName: str
    dataType: str
    success: bool
    failureMessage: str
    bytes: int
    sentBytes: int
    grpThreads: int
    allThreads: int
    URL: str
    Latency: int
    IdleTime: int
    Connect: int

    def jtl_row(self) -> dict[str, str | int]:
        row = asdict(self)
        row["success"] = "true" if self.success else "false"
        return row


class HttpSession:
    def __init__(self, base_url: str, timeout_seconds: float, thread_name: str, threads: int):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.thread_name = thread_name
        self.threads = threads
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(
        self,
        label: str,
        path: str,
        method: str = "GET",
        data: dict[str, str] | None = None,
        assert_contains: str | None = None,
    ) -> tuple[Sample, bytes, dict[str, Any]]:
        url = urljoin(self.base_url, path.lstrip("/"))
        encoded = urlencode(data or {}).encode("utf-8") if data is not None else None
        headers = {
            "User-Agent": "Checkout-Python-Load/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if encoded is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(url, data=encoded, method=method, headers=headers)
        started_ms = int(time.time() * 1000)
        started = time.perf_counter()
        body = b""
        final_url = url
        code = "ERR"
        message = ""
        success = False
        failure = ""
        metadata: dict[str, Any] = {"request_url": url, "method": method, "label": label}

        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read()
                code = str(response.getcode())
                message = getattr(response, "reason", "") or "OK"
                final_url = response.geturl()
                success = 200 <= int(code) < 400
                metadata["headers"] = dict(response.headers.items())
        except HTTPError as exc:
            body = exc.read()
            code = str(exc.code)
            message = str(exc.reason)
            final_url = exc.geturl()
            failure = f"HTTPError: {exc.reason}"
            metadata["headers"] = dict(exc.headers.items()) if exc.headers else {}
        except URLError as exc:
            message = exc.reason if isinstance(exc.reason, str) else repr(exc.reason)
            failure = f"URLError: {message}"
        except Exception as exc:  # noqa: BLE001 - capture test evidence, do not crash worker.
            message = f"{exc.__class__.__name__}: {exc}"
            failure = message

        elapsed = max(int(round((time.perf_counter() - started) * 1000)), 0)
        if success and assert_contains:
            text = body.decode("utf-8", "replace")
            if assert_contains not in text:
                success = False
                failure = f"assertion failed: response did not contain {assert_contains!r}"

        if not success and not failure:
            failure = f"unexpected response code {code}"

        metadata.update(
            {
                "final_url": final_url,
                "response_code": code,
                "response_message": message,
                "success": success,
                "failure_message": failure,
                "elapsed_ms": elapsed,
                "body_bytes": len(body),
            }
        )
        sample = Sample(
            timeStamp=started_ms,
            elapsed=elapsed,
            label=label,
            responseCode=code,
            responseMessage=message,
            threadName=self.thread_name,
            dataType="text",
            success=success,
            failureMessage=failure,
            bytes=len(body),
            sentBytes=len(encoded or b""),
            grpThreads=self.threads,
            allThreads=self.threads,
            URL=final_url,
            Latency=elapsed,
            IdleTime=0,
            Connect=0,
        )
        return sample, body, metadata


class EvidenceCapture:
    def __init__(self, evidence_dir: Path | None):
        self.evidence_dir = evidence_dir
        self.lock = threading.Lock()
        self.captured = False
        self.manifest: list[dict[str, Any]] = []

    def maybe_capture(self, records: list[tuple[str, bytes, dict[str, Any]]]) -> None:
        if self.evidence_dir is None:
            return
        with self.lock:
            if self.captured:
                return
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            for idx, (label, body, metadata) in enumerate(records, start=1):
                safe_label = re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_").lower()
                filename = f"{idx:02d}_{safe_label}.html"
                path = self.evidence_dir / filename
                path.write_bytes(body)
                item = dict(metadata)
                item["file"] = filename
                self.manifest.append(item)
            (self.evidence_dir / "manifest.json").write_text(
                json.dumps(self.manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._write_index()
            self.captured = True

    def _write_index(self) -> None:
        if self.evidence_dir is None:
            return
        rows = []
        for item in self.manifest:
            status = "PASS" if item.get("success") else "FAIL"
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(item.get('label', '')))}</td>"
                f"<td>{html.escape(str(item.get('method', '')))}</td>"
                f"<td>{html.escape(str(item.get('response_code', '')))}</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{html.escape(str(item.get('elapsed_ms', '')))}</td>"
                f"<td><a href=\"{html.escape(str(item.get('file', '')))}\">HTML</a></td>"
                "</tr>"
            )
        index = """<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<title>Checkout Evidence Index</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:32px;color:#1f2937}
table{border-collapse:collapse;width:100%;max-width:1080px}
th,td{border:1px solid #d1d5db;padding:8px 10px;text-align:left}
th{background:#f3f4f6}
</style>
<h1>Checkout HTTP Evidence</h1>
<p>These HTML files are raw frontend responses captured during the first
successful test iteration.</p>
<table>
<thead><tr><th>Label</th><th>Method</th><th>HTTP</th><th>Status</th><th>Elapsed ms</th><th>Evidence</th></tr></thead>
<tbody>
""" + "\n".join(rows) + """
</tbody>
</table>
</html>
"""
        (self.evidence_dir / "index.html").write_text(index, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HTTP checkout load and write JTL.")
    parser.add_argument("--frontend-url", required=True, help="Frontend base URL")
    parser.add_argument("--out-jtl", required=True, help="Output CSV JTL path")
    parser.add_argument("--summary-json", required=True, help="Output JSON summary path")
    parser.add_argument("--evidence-dir", help="Directory for captured HTML evidence")
    parser.add_argument("--product-id", default=DEFAULT_PRODUCT_ID)
    parser.add_argument("--quantity", default="2")
    parser.add_argument("--currency-code", default="USD")
    parser.add_argument("--threads", type=int, default=5)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--iterations-per-thread", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--think-min-ms", type=int, default=300)
    parser.add_argument("--think-max-ms", type=int, default=1200)
    return parser.parse_args()


def checkout_fields() -> dict[str, str]:
    return {
        "email": f"checkout-test-{uuid.uuid4()}@example.com",
        "street_address": "1600 Amphitheatre Parkway",
        "zip_code": "94043",
        "city": "Mountain View",
        "state": "CA",
        "country": "United States",
        "credit_card_number": "4432801561520454",
        "credit_card_expiration_month": "12",
        "credit_card_expiration_year": "2030",
        "credit_card_cvv": "672",
    }


def run_transaction(
    worker_id: int,
    iteration: int,
    args: argparse.Namespace,
    evidence: EvidenceCapture,
) -> list[Sample]:
    thread_name = f"Checkout Concurrent Users {worker_id + 1}-{iteration + 1}"
    session = HttpSession(args.frontend_url, args.timeout_seconds, thread_name, args.threads)
    all_samples: list[Sample] = []
    evidence_records: list[tuple[str, bytes, dict[str, Any]]] = []
    txn_started_ms = int(time.time() * 1000)
    txn_started = time.perf_counter()

    steps = [
        ("GET Home", "/", "GET", None, "Online Boutique"),
        (
            "POST Set Currency",
            "/setCurrency",
            "POST",
            {"currency_code": args.currency_code},
            None,
        ),
        ("GET Product Detail", f"/product/{args.product_id}", "GET", None, args.product_id),
        (
            "POST Add To Cart",
            "/cart",
            "POST",
            {"product_id": args.product_id, "quantity": args.quantity},
            None,
        ),
        ("GET Cart", "/cart", "GET", None, "Place Order"),
        ("POST Checkout", "/cart/checkout", "POST", checkout_fields(), "Your order is complete!"),
    ]

    for label, path, method, data, assertion in steps:
        sample, body, metadata = session.request(label, path, method, data, assertion)
        all_samples.append(sample)
        evidence_records.append((label, body, metadata))
        if label == "GET Cart":
            time.sleep(random.uniform(args.think_min_ms, args.think_max_ms) / 1000.0)

    evidence.maybe_capture(evidence_records)
    elapsed = max(int(round((time.perf_counter() - txn_started) * 1000)), 0)
    failed_steps = [sample for sample in all_samples if not sample.success]
    parent = Sample(
        timeStamp=txn_started_ms,
        elapsed=elapsed,
        label="E2E Browse And Checkout",
        responseCode="200" if not failed_steps else failed_steps[0].responseCode,
        responseMessage="OK" if not failed_steps else failed_steps[0].responseMessage,
        threadName=thread_name,
        dataType="text",
        success=not failed_steps,
        failureMessage="; ".join(
            f"{sample.label}: {sample.failureMessage}" for sample in failed_steps
        ),
        bytes=sum(sample.bytes for sample in all_samples),
        sentBytes=sum(sample.sentBytes for sample in all_samples),
        grpThreads=args.threads,
        allThreads=args.threads,
        URL=args.frontend_url.rstrip("/") + "/cart/checkout",
        Latency=elapsed,
        IdleTime=0,
        Connect=0,
    )
    all_samples.append(parent)
    return all_samples


def worker(worker_id: int, args: argparse.Namespace, evidence: EvidenceCapture) -> list[Sample]:
    samples: list[Sample] = []
    deadline = time.monotonic() + args.duration_seconds
    iteration = 0
    while True:
        if args.iterations_per_thread > 0:
            if iteration >= args.iterations_per_thread:
                break
        elif time.monotonic() >= deadline:
            break

        samples.extend(run_transaction(worker_id, iteration, args, evidence))
        iteration += 1
    return samples


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(samples: list[Sample], args: argparse.Namespace) -> dict[str, Any]:
    by_label: dict[str, list[Sample]] = {}
    for sample in samples:
        by_label.setdefault(sample.label, []).append(sample)

    label_summary: dict[str, Any] = {}
    for label, label_samples in sorted(by_label.items()):
        elapsed = [sample.elapsed for sample in label_samples]
        failed = sum(1 for sample in label_samples if not sample.success)
        label_summary[label] = {
            "samples": len(label_samples),
            "failed": failed,
            "error_rate": failed / len(label_samples),
            "avg_ms": round(statistics.mean(elapsed), 2),
            "p95_ms": round(percentile(elapsed, 0.95), 2),
            "max_ms": max(elapsed),
        }

    e2e = by_label.get("E2E Browse And Checkout", [])
    start = min((sample.timeStamp for sample in e2e), default=int(time.time() * 1000))
    end = max((sample.timeStamp for sample in e2e), default=start)
    measured_seconds = max((end - start) / 1000.0, 1.0)
    failed_e2e = sum(1 for sample in e2e if not sample.success)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "frontend_url": args.frontend_url.rstrip("/"),
        "product_id": args.product_id,
        "quantity": args.quantity,
        "currency_code": args.currency_code,
        "threads": args.threads,
        "duration_seconds_arg": args.duration_seconds,
        "iterations_per_thread": args.iterations_per_thread,
        "total_samples": len(samples),
        "e2e_transactions": len(e2e),
        "e2e_failed": failed_e2e,
        "e2e_error_rate": failed_e2e / len(e2e) if e2e else 1.0,
        "e2e_tps": len(e2e) / measured_seconds,
        "label_summary": label_summary,
    }


def write_jtl(path: Path, samples: list[Sample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = sorted(samples, key=lambda sample: (sample.timeStamp, sample.threadName, sample.label))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=JTL_FIELDS)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample.jtl_row())


def main() -> int:
    args = parse_args()
    if args.threads <= 0:
        raise SystemExit("--threads must be positive")
    if args.iterations_per_thread <= 0 and args.duration_seconds <= 0:
        raise SystemExit("--duration-seconds must be positive unless --iterations-per-thread is set")

    evidence = EvidenceCapture(Path(args.evidence_dir) if args.evidence_dir else None)
    all_samples: list[Sample] = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = [executor.submit(worker, worker_id, args, evidence) for worker_id in range(args.threads)]
        for future in as_completed(futures):
            all_samples.extend(future.result())

    write_jtl(Path(args.out_jtl), all_samples)
    summary = summarize(all_samples, args)
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["e2e_error_rate"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
