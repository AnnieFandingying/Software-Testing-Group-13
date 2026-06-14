# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_fault_frontend_cpu_t10/run.jtl`
- Samples: 132
- Failed samples: 29
- Duration: 779.1s
- Overall TPS: 0.17
- Error Rate: 21.97% (FAIL, target <= 5.00%)
- Latency p95: 82393.2 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 52277.3 / 51038.0 / 71542.7 / 101233.3 / 103115.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 132 | 21.97% | 0.17 | 52277.3 | 82393.2 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
