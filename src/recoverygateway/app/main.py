import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException
from kubernetes.client import ApiException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.auth import require_agent_token
from app.config import Settings, get_settings
from app.k8s_client import KubernetesRecoveryClient, format_api_exception
from app.metrics import COMMAND_LATENCY_SECONDS, COMMANDS_TOTAL, DEGRADE_STATE
from app.models import CommandResult, DegradeRequest, HealthResponse, RestartRequest

logger = logging.getLogger("recovery-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.recovery = KubernetesRecoveryClient(settings)
    yield


app = FastAPI(
    title="Recovery Gateway",
    description="Agent-facing gateway for Kubernetes self-healing operations.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_recovery_client() -> KubernetesRecoveryClient:
    return app.state.recovery


@app.get("/healthz", response_model=HealthResponse)
def healthz(
    settings: Settings = Depends(get_settings),
    recovery: KubernetesRecoveryClient = Depends(get_recovery_client),
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        namespace=settings.namespace,
        dry_run=settings.dry_run,
        kubernetes="configured" if recovery.available else "not-configured",
        allowed_targets=sorted(settings.allowed_target_set),
    )


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post(
    "/api/v1/restart",
    response_model=CommandResult,
    dependencies=[Depends(require_agent_token)],
)
def restart_workload(
    request: RestartRequest,
    settings: Settings = Depends(get_settings),
    recovery: KubernetesRecoveryClient = Depends(get_recovery_client),
) -> CommandResult:
    namespace = request.namespace or settings.namespace
    start = perf_counter()
    try:
        details = recovery.restart(namespace, request.kind, request.target, request.reason)
        COMMANDS_TOTAL.labels("restart", request.target, "ok").inc()
        logger.info("restart command accepted target=%s namespace=%s kind=%s", request.target, namespace, request.kind)
        return CommandResult(
            ok=True,
            action="restart",
            namespace=namespace,
            target=request.target,
            message=str(details["message"]),
            dry_run=settings.dry_run,
            details=details,
        )
    except ValueError as exc:
        COMMANDS_TOTAL.labels("restart", request.target, "rejected").inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApiException as exc:
        COMMANDS_TOTAL.labels("restart", request.target, "k8s_error").inc()
        raise HTTPException(status_code=502, detail=format_api_exception(exc)) from exc
    finally:
        COMMAND_LATENCY_SECONDS.labels("restart").observe(perf_counter() - start)


@app.post(
    "/api/v1/degrade",
    response_model=CommandResult,
    dependencies=[Depends(require_agent_token)],
)
def set_degrade_mode(
    request: DegradeRequest,
    settings: Settings = Depends(get_settings),
    recovery: KubernetesRecoveryClient = Depends(get_recovery_client),
) -> CommandResult:
    namespace = request.namespace or settings.namespace
    start = perf_counter()
    try:
        details = recovery.set_degrade_mode(
            namespace=namespace,
            service=request.service,
            mode=request.mode,
            ttl_seconds=request.ttl_seconds,
            reason=request.reason,
        )
        COMMANDS_TOTAL.labels("degrade", request.service, "ok").inc()
        DEGRADE_STATE.labels(request.service, request.mode.value).inc()
        logger.info("degrade command accepted service=%s namespace=%s mode=%s", request.service, namespace, request.mode)
        return CommandResult(
            ok=True,
            action="degrade",
            namespace=namespace,
            target=request.service,
            message=str(details["message"]),
            dry_run=settings.dry_run,
            details=details,
        )
    except ValueError as exc:
        COMMANDS_TOTAL.labels("degrade", request.service, "rejected").inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApiException as exc:
        COMMANDS_TOTAL.labels("degrade", request.service, "k8s_error").inc()
        raise HTTPException(status_code=502, detail=format_api_exception(exc)) from exc
    finally:
        COMMAND_LATENCY_SECONDS.labels("degrade").observe(perf_counter() - start)


@app.get(
    "/api/v1/degrade-state",
    dependencies=[Depends(require_agent_token)],
)
def get_degrade_state(
    namespace: str | None = None,
    settings: Settings = Depends(get_settings),
    recovery: KubernetesRecoveryClient = Depends(get_recovery_client),
) -> dict[str, object]:
    effective_namespace = namespace or settings.namespace
    try:
        return {
            "namespace": effective_namespace,
            "configmap": settings.degraded_configmap,
            "data": recovery.read_degrade_state(effective_namespace),
        }
    except ApiException as exc:
        raise HTTPException(status_code=502, detail=format_api_exception(exc)) from exc
