# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_baseline_t10/run.jtl`
- Samples: 58
- Failed samples: 53
- Duration: 899.4s
- Overall TPS: 0.06
- Error Rate: 91.38% (FAIL, target <= 5.00%)
- Latency p95: 180057.3 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 143594.7 / 180032.0 / 180047.3 / 201617.3 / 207453.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 58 | 91.38% | 0.06 | 143594.7 | 180057.3 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
