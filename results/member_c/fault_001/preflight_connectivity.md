# Member C Preflight Connectivity Record - fault_001

## Run Metadata

- Run ID: `fault_001`
- Recorded UTC time: `2026-06-13T16:41:55Z`
- Member C machine Tailscale IP: `100.93.93.17`
- Target machine: `100.110.3.67`
- Intended frontend URL: `http://100.110.3.67:18081`

## Checks Executed

| Check | Command target | Result |
|---|---|---|
| Tailscale peer status | `tailscale status` | Target `100.110.3.67 laptop-emri7g68` is `active`, relay `ord` |
| Frontend URL | `http://100.110.3.67:18081/` | Failed: `Connection refused` |
| Prometheus readiness | `http://100.110.3.67:9090/-/ready` | Passed: `Prometheus is Ready.` |
| Recovery Gateway health | `http://100.110.3.67:18080/healthz` | Passed: `status=ok`, `kubernetes=configured`, `namespace=default` |
| Jaeger UI | `http://100.110.3.67:16686/` | Failed: `Connection refused` |
| Prometheus default namespace `up` | `up{namespace="default"}` | Empty result |

## Evidence

Recovery Gateway health response:

```json
{
  "status": "ok",
  "namespace": "default",
  "dry_run": false,
  "kubernetes": "configured",
  "allowed_targets": [
    "adservice",
    "cartservice",
    "checkoutservice",
    "currencyservice",
    "discountservice",
    "emailservice",
    "frontend",
    "paymentservice",
    "productcatalogservice",
    "recommendationservice",
    "recovery-gateway",
    "redis-cart",
    "shippingservice",
    "telemetryservice"
  ]
}
```

Prometheus readiness response:

```text
Prometheus is Ready.
```

Prometheus query:

```promql
up{namespace="default"}
```

Result:

```json
{"status":"success","data":{"resultType":"vector","result":[]}}
```

## Current Blocker

Member C cannot start Selenium or JMeter against the frontend yet because
`http://100.110.3.67:18081` is refusing TCP connections. This is not a local
test-script issue: Prometheus and recovery-gateway are reachable through the
same Tailscale peer, so the Tailscale path works.

The most likely cause is that the frontend port-forward on the target machine
is not running or is bound only to `127.0.0.1` on the Windows host.

## Required Action On Member A Machine

Run one of the following on the machine `100.110.3.67`.

Preferred, bind the port-forward to all interfaces so Tailscale peers can reach
it:

```bash
kubectl port-forward --address 0.0.0.0 svc/frontend 18081:80
```

If using PowerShell:

```powershell
kubectl port-forward --address 0.0.0.0 svc/frontend 18081:80
```

Also expose Jaeger if trace screenshots are required:

```bash
kubectl port-forward --address 0.0.0.0 -n observability svc/jaeger 16686:16686
```

## Member C Commands To Run After Frontend Is Reachable

Selenium functional checkout test:

```bash
FRONTEND_URL=http://100.110.3.67:18081 \
pytest -q tests/member_c/selenium/checkout_discount_test.py
```

JMeter baseline:

```bash
jmeter -n \
  -t tests/member_c/jmeter/online_boutique_checkout_pressure.jmx \
  -l results/member_c/jmeter/fault_001.jtl \
  -JRESULTS_FILE=results/member_c/jmeter/fault_001.jtl \
  -JFRONTEND_HOST=100.110.3.67 \
  -JFRONTEND_PORT=18081 \
  -JTHREADS=50 \
  -JRAMP_SECONDS=60 \
  -JDURATION_SECONDS=600
```

Analyze JMeter results:

```bash
python3 tests/member_c/scripts/analyze_jmeter_results.py \
  --jtl results/member_c/jmeter/fault_001.jtl \
  --out-dir results/member_c/jmeter/fault_001-analysis \
  --label-filter "E2E Browse And Checkout"
```
