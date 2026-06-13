# Checkout USD Chaos Test Runbook - 10 Concurrent Users

## Purpose

This runbook is the formal checkout test operation record for the current deployed
environment exposed through Tailscale:

```text
Frontend: http://100.110.3.67:18081
Currency: USD
JMeter threads: 10
Ramp-up: 120 seconds
```

The 30-thread pre-run produced high error rates before any ChaosMesh injection.
Therefore, the formal chaos runs use 10 concurrent users to keep the baseline
comparable and avoid overloading the service before the fault starts.

The frontend exposes `EUR/USD/JPY/GBP/TRY/CAD`. The discount logic has been
updated so these UI currencies all call `discountservice`. This runbook uses
`USD` with `PRODUCT_QUANTITY=2`, which crosses the `200` threshold for the
default watch product and exercises the promotion API.

## Common Rules

- Use the same JMX file for every run:
  `tests/performance/online_boutique_checkout_pressure.jmx`
- Use a separate `.jtl` file per scenario.
- Do not mix multiple chaos scenarios into the same `.jtl`.
- Start JMeter first, keep 3-5 minutes of no-chaos baseline, then ask Member A
  to inject the fault.
- Member A must record UTC timestamps immediately before injection and cleanup.
- After cleanup, keep JMeter running for another 3-5 minutes to capture recovery.
- Analyze every `.jtl` with `analyze_jmeter_results.py`.

## 0. Preparation

Test runner:

```bash
cd "/Users/imnort/Library/Mobile Documents/com~apple~CloudDocs/大学/大三下/软件测试/Software-Testing-Group-13"
mkdir -p results/testing/jmeter
```

Member A:

```bash
cd /path/to/Software-Testing-Group-13
kubectl -n default get pods
kubectl -n default get stresschaos,podchaos,networkchaos
```

## 1. No-Chaos Baseline

Test runner runs:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_baseline_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_baseline_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=900 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_baseline_t10.jtl \
  --out-dir results/testing/jmeter/usd_baseline_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## 2. Scenario 1 - Frontend CPU Pressure

Test runner starts JMeter:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_fault_frontend_cpu_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_fault_frontend_cpu_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=1800 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

After 3-5 minutes, Member A injects:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl apply -f tests/chaosmesh/stress-frontend-cpu.yaml
kubectl -n default get stresschaos
kubectl -n default describe stresschaos checkout-frontend-cpu-pressure
```

After about 5 minutes, Member A cleans up:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl delete -f tests/chaosmesh/stress-frontend-cpu.yaml --ignore-not-found
kubectl -n default get stresschaos
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_fault_frontend_cpu_t10.jtl \
  --out-dir results/testing/jmeter/usd_fault_frontend_cpu_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## 3. Scenario 2 - Checkoutservice Pod Kill

Test runner starts JMeter:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_fault_checkout_pod_kill_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_fault_checkout_pod_kill_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=1800 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

After 3-5 minutes, Member A injects:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl apply -f tests/chaosmesh/pod-kill-checkoutservice.yaml
kubectl -n default get podchaos
kubectl -n default get pods -l app=checkoutservice
```

After 3-5 minutes of recovery observation, Member A cleans up:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl delete -f tests/chaosmesh/pod-kill-checkoutservice.yaml --ignore-not-found
kubectl -n default get pods -l app=checkoutservice
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_fault_checkout_pod_kill_t10.jtl \
  --out-dir results/testing/jmeter/usd_fault_checkout_pod_kill_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## 4. Scenario 3 - Productcatalogservice Pod Failure

Test runner starts JMeter:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_fault_productcatalog_pod_failure_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_fault_productcatalog_pod_failure_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=1800 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

After 3-5 minutes, Member A injects:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl apply -f tests/chaosmesh/pod-failure-productcatalogservice.yaml
kubectl -n default get podchaos
kubectl -n default describe podchaos checkout-productcatalog-pod-failure
kubectl -n default get pods -l app=productcatalogservice
```

After about 2-3 minutes, Member A cleans up:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl delete -f tests/chaosmesh/pod-failure-productcatalogservice.yaml --ignore-not-found
kubectl -n default get pods -l app=productcatalogservice
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_fault_productcatalog_pod_failure_t10.jtl \
  --out-dir results/testing/jmeter/usd_fault_productcatalog_pod_failure_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## 5. Scenario 4 - Telemetry Network Loss

Test runner starts JMeter:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_fault_telemetry_loss_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_fault_telemetry_loss_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=1800 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

After 3-5 minutes, Member A injects:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl apply -f tests/chaosmesh/network-loss-telemetry-weak-dependency.yaml
kubectl -n default get networkchaos
kubectl -n default describe networkchaos checkout-telemetry-loss-weak-dependency
```

After about 5 minutes, Member A cleans up:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl delete -f tests/chaosmesh/network-loss-telemetry-weak-dependency.yaml --ignore-not-found
kubectl -n default get networkchaos
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_fault_telemetry_loss_t10.jtl \
  --out-dir results/testing/jmeter/usd_fault_telemetry_loss_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## 6. Scenario 5 - Checkout To Discount Network Delay

Precondition: Member A has redeployed the updated `checkoutservice`,
`discountservice`, and `frontend` images, and `discountservice` is Ready.

Test runner starts JMeter:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_fault_checkout_discount_delay_t10.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_fault_checkout_discount_delay_t10.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=10 \
  -JRAMP_SECONDS=120 \
  -JDURATION_SECONDS=1800 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

After 3-5 minutes, Member A injects:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl apply -f tests/chaosmesh/network-delay-checkout-to-discount.yaml
kubectl -n default get networkchaos
kubectl -n default describe networkchaos checkout-to-discount-delay
```

After about 5 minutes, Member A cleans up:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
kubectl delete -f tests/chaosmesh/network-delay-checkout-to-discount.yaml --ignore-not-found
kubectl -n default get networkchaos
```

Test runner analyzes:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_fault_checkout_discount_delay_t10.jtl \
  --out-dir results/testing/jmeter/usd_fault_checkout_discount_delay_t10-analysis \
  --label-filter "E2E Browse And Checkout"
```

## Timeline Template

Record one row per scenario:

| Scenario | JMeter file | JMeter start CST | Fault inject UTC | Fault cleanup UTC | JMeter stop CST | Notes |
|---|---|---|---|---|---|---|
| baseline | `usd_baseline_t10.jtl` |  | N/A | N/A |  | No chaos |
| frontend CPU | `usd_fault_frontend_cpu_t10.jtl` |  |  |  |  |  |
| checkout pod kill | `usd_fault_checkout_pod_kill_t10.jtl` |  |  |  |  |  |
| productcatalog pod failure | `usd_fault_productcatalog_pod_failure_t10.jtl` |  |  |  |  |  |
| telemetry loss | `usd_fault_telemetry_loss_t10.jtl` |  |  |  |  |  |
| checkout-discount delay | `usd_fault_checkout_discount_delay_t10.jtl` |  |  |  |  | Requires updated images |
