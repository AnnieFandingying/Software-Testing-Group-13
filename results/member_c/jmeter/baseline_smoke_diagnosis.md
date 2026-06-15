# Member C Baseline Smoke Diagnosis

## Conclusion

JMeter is working correctly. The baseline smoke run can reach the frontend,
set CNY, load product detail, add the product to cart, and open the cart page.
The failure is concentrated at `POST /cart/checkout`.

Root cause observed from the frontend 500 page:

```text
rpc error: code = Internal desc = failed to get discount:
rpc error: code = Unavailable desc = connection error:
transport: Error while dialing: dial tcp 10.96.179.221:50051: connect: connection refused
```

This points to `discountservice` inside Kubernetes, not to the JMeter script.

## JMeter Evidence

- Source: `results/member_c/jmeter/baseline_smoke.jtl`
- Run window: `2026-06-14 03:53:10 CST` to `2026-06-14 03:53:44 CST`
- Effective rows: 44
- E2E transactions: 4
- E2E failures: 4

Per-step result:

| Label | Total | Failed | Main status |
|---|---:|---:|---|
| GET Home | 4 | 0 | 200 |
| POST Set Currency CNY | 4 | 0 | 200 |
| GET Product Detail | 4 | 0 | 200 |
| POST Add To Cart | 4 | 0 | 200 |
| GET Cart | 4 | 0 | 200 |
| POST Checkout CNY Discount | 4 | 4 | 500 |

Generated analysis:

- `results/member_c/jmeter/baseline_smoke-analysis/sla_summary.md`
- `results/member_c/jmeter/baseline_smoke-checkout-analysis/sla_summary.md`

## Direct HTTP Reproduction

Direct one-transaction reproduction saved the failed checkout page at:

```text
results/member_c/jmeter/baseline_smoke_http_evidence/06_post_checkout_cny_discount.html
```

All previous steps returned 200. Checkout returned:

```text
HTTP 500 Internal Server Error
failed to get discount
connect: connection refused
```

## Prometheus / kube-state Evidence

Prometheus could query kube-state-metrics and showed:

```text
discountservice pod: discountservice-b96d45868-zxfdf
phase: Running
container ready: 0
container restarts: 11
waiting reason: CrashLoopBackOff
last terminated reason: Error
deployment replicas: 1
available replicas: 0
unavailable replicas: 1
```

The image reported by kube-state-metrics was:

```text
crpi-3qhk4rm49t1wiwvp.cn-hangzhou.personal.cr.aliyuncs.com/vowit/discountservice:618-v1
```

The handoff document says the expected ACR domain is:

```text
crpi-3qhk4rm49tlwivvp.cn-hangzhou.personal.cr.aliyuncs.com/vowit/discountservice:618-v1
```

The actual deployed domain contains `t1...` while the expected domain contains
`tl...`. Member A should verify and redeploy the discountservice image.

## Commands For Member A

```bash
kubectl -n default get pods -l app=discountservice -o wide
kubectl -n default describe pod -l app=discountservice
kubectl -n default logs deploy/discountservice -c server --tail=100
kubectl -n default logs deploy/discountservice -c server --previous --tail=100
```

If the image URL is wrong, redeploy with the handoff image:

```bash
kubectl -n default set image deployment/discountservice \
  server=crpi-3qhk4rm49tlwivvp.cn-hangzhou.personal.cr.aliyuncs.com/vowit/discountservice:618-v1

kubectl -n default rollout status deployment/discountservice
kubectl -n default get pods -l app=discountservice
```

After `discountservice` is ready, rerun:

```bash
jmeter -n \
  -t tests/member_c/jmeter/online_boutique_checkout_pressure.jmx \
  -l results/member_c/jmeter/baseline_smoke.jtl \
  -JRESULTS_FILE=results/member_c/jmeter/baseline_smoke.jtl \
  -JFRONTEND_SCHEME=http \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=1 \
  -JRAMP_SECONDS=1 \
  -JDURATION_SECONDS=60 \
  -JCONNECT_TIMEOUT_MS=5000 \
  -JRESPONSE_TIMEOUT_MS=30000 \
  -Jsummariser.interval=10
```

Expected smoke result after repair: `POST Checkout CNY Discount` returns 200
and the response contains `Your order is complete!`.
