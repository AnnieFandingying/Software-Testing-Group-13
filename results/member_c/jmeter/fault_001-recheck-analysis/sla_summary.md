# Member C JMeter SLA Summary

- Source JTL: `results/member_c/jmeter/fault_001.jtl`
- Samples: 1193
- Failed samples: 1188
- Duration: 8935.7s
- Overall TPS: 0.13
- Error Rate: 99.58% (FAIL, target <= 5.00%)
- Latency p95: 22676.8 ms (FAIL, target <= 1500.0 ms)
- Latency avg/p50/p90/p99/max: 16113.7 / 2154.0 / 13114.8 / 76784.0 / 2461361.0 ms

## Per Label

| Label | Samples | Error Rate | TPS | Avg ms | p95 ms |
|---|---:|---:|---:|---:|---:|
| POST Checkout CNY Discount | 1193 | 99.58% | 0.13 | 16113.7 | 22676.8 |

## Interpretation Guide

- Compare the baseline run and each ChaosMesh run with the same thread/ramp/duration settings.
- In the chaos window, expected behavior is a temporary TPS drop or p95 rise, followed by recovery after the experiment is deleted or self-healing completes.
- For telemetry weak-dependency faults, checkout success rate should stay near baseline even when telemetry metrics have gaps.
