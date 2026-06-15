# Checkout JMeter SLA Summary

- Source JTL: `results/testing/jmeter/usd_fault_checkout_discount_delay_t10/run.jtl`
- Samples: 92
- Failed samples: 21
- Duration: 578.5s
- Overall TPS: 0.16
- Error Rate: 22.83% (FAIL, target <= 5.00%)
- Latency p95: 98501.2 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 55522.1 / 53169.0 / 88343.4 / 115815.6 / 118653.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 92 | 22.83% | 0.16 | 55522.1 | 98501.2 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
