# Member C JMeter SLA Summary

- Source JTL: `results/member_c/jmeter/fault_001.jtl`
- Samples: 1217
- Failed samples: 1217
- Duration: 8919.9s
- Overall TPS: 0.14
- Error Rate: 100.00% (FAIL, target <= 5.00%)
- Latency p95: 212998.8 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 85948.3 / 38635.0 / 161501.0 / 437733.2 / 2708745.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 1217 | 100.00% | 0.14 | 85948.3 | 212998.8 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
