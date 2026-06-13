# Member C - Automated Testing And Chaos Engineering

Role C deliverables for Group 13:

- Selenium functional tests for the Online Boutique checkout path and 618 discount contract.
- JMeter pressure test plan for concurrent browse/cart/checkout traffic.
- ChaosMesh experiments for CPU pressure, pod failure/kill, network delay and telemetry packet loss.
- JTL analysis script that produces SLA summaries and TPS/Error Rate/p95 curves.

## Handoff Decisions

The AB handoff PDF says Member C should design cases around the `200/400/700`
discount thresholds. The repository code is the source of truth:

- `src/discountservice/service.go`: `200-50`, `400-100`, `700-200`
- `Ability.md`: `200-50`, `400-100`, `700-200`
- `kubernetes-manifests/*`: telemetry event URL is `http://telemetryservice:8080/events`
- AB public ACR images:
  `crpi-3qhk4rm49tlwivvp.cn-hangzhou.personal.cr.aliyuncs.com/vowit/{checkoutservice,discountservice,frontend,telemetryservice}:618-v1`

The PDF also contains older text saying `200-20`, `400-50`, `700-100` and a
`/v1/metrics` telemetry URL. These are treated as stale handoff notes.

## Selenium Functional Test

Install dependencies:

```bash
python3 -m venv .venv-member-c
. .venv-member-c/bin/activate
pip install -r tests/member_c/selenium/requirements.txt
```

Run against Member A's exposed frontend:

```bash
FRONTEND_URL=http://127.0.0.1:8080 \
pytest -q tests/member_c/selenium/checkout_discount_test.py
```

Optional telemetry assertion:

```bash
FRONTEND_URL=http://127.0.0.1:8080 \
TELEMETRY_METRICS_URL=http://127.0.0.1:18080/metrics \
pytest -q tests/member_c/selenium/checkout_discount_test.py
```

The Selenium script writes interaction metrics to:

```text
results/member_c/selenium/checkout_discount_results.jsonl
```

## JMeter Baseline Pressure Test

Run a no-chaos baseline:

```bash
mkdir -p results/member_c/jmeter
jmeter -n \
  -t tests/member_c/jmeter/online_boutique_checkout_pressure.jmx \
  -l results/member_c/jmeter/baseline.jtl \
  -JRESULTS_FILE=results/member_c/jmeter/baseline.jtl \
  -JFRONTEND_HOST=127.0.0.1 \
  -JFRONTEND_PORT=8080 \
  -JTHREADS=50 \
  -JRAMP_SECONDS=60 \
  -JDURATION_SECONDS=600
```

Analyze the JTL:

```bash
python3 tests/member_c/scripts/analyze_jmeter_results.py \
  --jtl results/member_c/jmeter/baseline.jtl \
  --out-dir results/member_c/jmeter/baseline-analysis \
  --label-filter "E2E Browse And Checkout"
```

Generated artifacts:

- `sla_summary.md`
- `sla_timeseries.csv`
- `sla_tps_error_rate.svg`

## Chaos + Load Coupled Run

Example with checkoutservice -> discountservice network delay:

```bash
FRONTEND_HOST=127.0.0.1 \
FRONTEND_PORT=8080 \
THREADS=50 \
RAMP_SECONDS=60 \
DURATION_SECONDS=600 \
CHAOS_DELAY_SECONDS=120 \
CHAOS_FILE=tests/member_c/chaosmesh/network-delay-checkout-to-discount.yaml \
bash tests/member_c/scripts/run_chaos_load_test.sh
```

Repeat the same command with:

- `tests/member_c/chaosmesh/stress-frontend-cpu.yaml`
- `tests/member_c/chaosmesh/network-loss-telemetry-weak-dependency.yaml`
- `tests/member_c/chaosmesh/pod-failure-productcatalogservice.yaml`
- `tests/member_c/chaosmesh/pod-kill-checkoutservice.yaml`

## Suggested SLA Gate

Use the same thread/ramp/duration settings for baseline and chaos runs.

| Metric | Baseline target | Chaos acceptance |
|---|---:|---:|
| Checkout success rate | >= 99% | >= 95% except hard productcatalog failure |
| p95 latency | <= 1500 ms | temporary spike allowed; should recover after chaos ends |
| Recovery time | N/A | <= 120 s after experiment deletion or Agent action |
| Telemetry-loss checkout error rate | <= baseline + 1% | should remain close to baseline |
