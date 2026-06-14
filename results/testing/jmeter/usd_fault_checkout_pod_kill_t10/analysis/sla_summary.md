# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_fault_checkout_pod_kill_t10/run.jtl`
- Samples: 95
- Failed samples: 19
- Duration: 547.7s
- Overall TPS: 0.17
- Error Rate: 20.00% (FAIL, target <= 5.00%)
- Latency p95: 82125.4 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 50278.8 / 47757.0 / 77970.6 / 87121.4 / 92000.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 95 | 20.00% | 0.17 | 50278.8 | 82125.4 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
