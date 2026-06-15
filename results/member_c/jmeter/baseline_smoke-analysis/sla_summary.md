# Member C JMeter SLA Summary

- Source JTL: `results/member_c/jmeter/baseline_smoke.jtl`
- Samples: 4
- Failed samples: 4
- Duration: 25.7s
- Overall TPS: 0.16
- Error Rate: 100.00% (FAIL, target <= 5.00%)
- Latency p95: 5941.7 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 4830.8 / 4462.0 / 5689.4 / 6143.5 / 6194.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 4 | 100.00% | 0.16 | 4830.8 | 5941.7 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
