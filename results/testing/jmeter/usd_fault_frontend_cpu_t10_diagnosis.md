# USD 10-Thread JMeter Failure Diagnosis

## Symptom

The checked USD frontend CPU run produced 172 `E2E Browse And Checkout`
transaction samples, and all 172 transaction samples failed. The failures are
not limited to checkout or to the discount assertion.

## Evidence From JTL

Representative failing sub-requests:

| Request label | Observed failure |
|---|---|
| `GET Home` | many HTTP 500 responses from `/` |
| `POST Set Currency` | redirected request often lands on HTTP 500 from `/` |
| `GET Product Detail` | many HTTP 500 responses from `/product/1YMWWN1N4O` |
| `POST Add To Cart` | many HTTP 500 responses from `/cart` |
| `GET Cart` | many HTTP 500 responses from `/cart` |
| `POST Checkout` | many HTTP 500 responses from `/cart/checkout` |

This means the JMeter plan is able to reach the frontend, but the deployed
application was already unhealthy during the run. A JMeter assertion mismatch
would only fail `POST Checkout`; it would not make home, product, and cart pages
return HTTP 500.

## Code-Side Fix Applied

The previous single-currency discount gate has been removed from the active code
path. The discount-enabled UI currencies are now:

```text
EUR, USD, JPY, GBP, TRY, CAD
```

Affected code:

- `src/checkoutservice/discount.go`
- `src/discountservice/service.go`
- `src/frontend/pricing.go`

The formal JMeter/Selenium test paths now use `PRODUCT_QUANTITY=2` and
`CURRENCY_CODE=USD`, so the default watch product crosses the 200 threshold and
exercises `checkoutservice -> discountservice`.

## Required Platform Recovery

Ask the deployment owner to run this on the cluster machine before collecting
formal chaos data:

```bash
kubectl -n default get stresschaos,podchaos,networkchaos
kubectl -n default delete stresschaos --all
kubectl -n default delete podchaos --all
kubectl -n default delete networkchaos --all

kubectl -n default rollout restart deployment/frontend
kubectl -n default rollout restart deployment/checkoutservice
kubectl -n default rollout restart deployment/discountservice
kubectl -n default rollout restart deployment/productcatalogservice

kubectl -n default rollout status deployment/frontend
kubectl -n default rollout status deployment/checkoutservice
kubectl -n default rollout status deployment/discountservice
kubectl -n default rollout status deployment/productcatalogservice
kubectl -n default get pods
```

Then rebuild and redeploy images containing the updated code for at least:

```text
frontend
checkoutservice
discountservice
```

## Smoke Test After Recovery

Run one-thread USD smoke before asking A to inject chaos:

```bash
jmeter -n \
  -t tests/performance/online_boutique_checkout_pressure.jmx \
  -l results/testing/jmeter/usd_discount_smoke_t1.jtl \
  -JRESULTS_FILE=results/testing/jmeter/usd_discount_smoke_t1.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=1 \
  -JRAMP_SECONDS=1 \
  -JDURATION_SECONDS=60 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -JPRODUCT_QUANTITY=2 \
  -JCURRENCY_CODE=USD \
  -Jsummariser.interval=10
```

Analyze:

```bash
python3 tests/performance/scripts/analyze_jmeter_results.py \
  --jtl results/testing/jmeter/usd_discount_smoke_t1.jtl \
  --out-dir results/testing/jmeter/usd_discount_smoke_t1-analysis \
  --label-filter "E2E Browse And Checkout"
```

Proceed to the 10-thread chaos run only if the one-thread smoke has zero
checkout transaction failures.
