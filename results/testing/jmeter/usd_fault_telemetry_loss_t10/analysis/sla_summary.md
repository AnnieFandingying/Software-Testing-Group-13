# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_fault_telemetry_loss_t10/run.jtl`
- Samples: 65
- Failed samples: 16
- Duration: 413.0s
- Overall TPS: 0.16
- Error Rate: 24.62% (FAIL, target <= 5.00%)
- Latency p95: 85756.6 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 52160.4 / 51373.0 / 80838.2 / 93549.3 / 105708.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 65 | 24.62% | 0.16 | 52160.4 | 85756.6 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
