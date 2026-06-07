# Recovery Gateway

`recovery-gateway` is the Agent-facing self-healing gateway for the group project. It accepts authenticated recovery commands and uses the Kubernetes API to restart workloads or write service degradation state.

## APIs

All `/api/v1/*` endpoints require:

```http
Authorization: Bearer <RECOVERY_AUTH_TOKEN>
```

Restart a deployment:

```bash
curl -X POST http://recovery-gateway:8080/api/v1/restart \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target":"checkoutservice","kind":"deployment","reason":"5xx_rate_high"}'
```

Set degradation mode:

```bash
curl -X POST http://recovery-gateway:8080/api/v1/degrade \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"service":"checkoutservice","mode":"degraded","ttl_seconds":900,"reason":"payment_dependency_unstable"}'
```

Useful endpoints:

- `GET /healthz`
- `GET /metrics`
- `GET /api/v1/degrade-state`
