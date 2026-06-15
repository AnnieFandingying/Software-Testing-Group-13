# ChaosMesh Test Scenarios

These experiments target the Online Boutique services deployed in the `default`
namespace. If the platform deployment uses another namespace, replace both
`metadata.namespace` and `spec.selector.namespaces`.

## Scenarios

| File | Purpose | Expected system behavior |
|---|---|---|
| `stress-frontend-cpu.yaml` | CPU saturation on one frontend pod | p95 latency rises; Prometheus CPU alert should fire; traffic should recover after experiment ends. |
| `network-delay-checkout-to-discount.yaml` | Delay checkoutservice -> discountservice gRPC calls | Checkout p95 increases; error rate should stay low if timeouts remain within budget. |
| `network-loss-telemetry-weak-dependency.yaml` | Drop telemetryservice traffic | Business checkout should keep succeeding; telemetry curves may show gaps. |
| `pod-failure-productcatalogservice.yaml` | Simulate a stuck productcatalog pod | Product browsing error rate rises until Kubernetes/Agent recovery. |
| `pod-kill-checkoutservice.yaml` | Delete one checkoutservice pod | Short failure spike; deployment should recreate pod and recover. |

## Manual Run

```bash
kubectl apply -f tests/chaosmesh/network-delay-checkout-to-discount.yaml
kubectl get networkchaos -n default
kubectl delete -f tests/chaosmesh/network-delay-checkout-to-discount.yaml
```

## Coupled Load Run

```bash
FRONTEND_HOST=<frontend-ip> FRONTEND_PORT=80 \
THREADS=10 RAMP_SECONDS=120 DURATION_SECONDS=1800 \
PRODUCT_QUANTITY=2 CURRENCY_CODE=USD \
CHAOS_FILE=tests/chaosmesh/network-delay-checkout-to-discount.yaml \
bash tests/performance/scripts/run_chaos_load_test.sh
```
