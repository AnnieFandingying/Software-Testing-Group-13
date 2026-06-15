# Member C JMeter SLA Summary

- Source JTL: `results/member_c/jmeter/usd_baseline_smoke.jtl`
- Samples: 2
- Failed samples: 1
- Duration: 17.5s
- Overall TPS: 0.11
- Error Rate: 50.00% (FAIL, target <= 5.00%)
- Latency p95: 12218.3 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 8927.0 / 8927.0 / 11852.6 / 12510.9 / 12584.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 2 | 50.00% | 0.11 | 8927.0 | 12218.3 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
