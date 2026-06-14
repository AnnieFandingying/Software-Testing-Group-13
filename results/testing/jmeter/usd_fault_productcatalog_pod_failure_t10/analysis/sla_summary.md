# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_fault_productcatalog_pod_failure_t10/run.jtl`
- Samples: 154
- Failed samples: 86
- Duration: 754.5s
- Overall TPS: 0.20
- Error Rate: 55.84% (FAIL, target <= 5.00%)
- Latency p95: 85082.7 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 41245.2 / 34433.5 / 71566.7 / 95924.8 / 111770.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 154 | 55.84% | 0.20 | 41245.2 | 85082.7 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
