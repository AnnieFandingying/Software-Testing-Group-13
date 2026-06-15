# Member C JMeter SLA Summary

- Source JTL: `results/member_c/jmeter/usd_fault_frontend_cpu_t10.jtl`
- Samples: 139
- Failed samples: 139
- Duration: 194.3s
- Overall TPS: 0.72
- Error Rate: 100.00% (FAIL, target <= 5.00%)
- Latency p95: 22404.9 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 5921.6 / 4019.0 / 10691.2 / 30251.2 / 31498.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| E2E Browse And Checkout | 139 | 100.00% | 0.72 | 5921.6 | 22404.9 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
