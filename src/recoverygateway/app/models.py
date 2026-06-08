from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RestartKind(StrEnum):
    deployment = "deployment"
    pod = "pod"


class DegradeMode(StrEnum):
    normal = "normal"
    degraded = "degraded"


class RestartRequest(BaseModel):
    target: str = Field(..., min_length=1, description="Deployment or Pod name.")
    namespace: str | None = Field(default=None, description="Override namespace.")
    kind: RestartKind = Field(default=RestartKind.deployment)
    reason: str = Field(default="agent_recovery", max_length=256)


class DegradeRequest(BaseModel):
    service: str = Field(..., min_length=1, description="Service/deployment name.")
    mode: DegradeMode = Field(..., description="normal clears degradation; degraded enables it.")
    namespace: str | None = Field(default=None, description="Override namespace.")
    ttl_seconds: int | None = Field(default=900, ge=60, le=86400)
    reason: str = Field(default="agent_recovery", max_length=256)


class CommandResult(BaseModel):
    ok: bool
    action: str
    namespace: str
    target: str
    message: str
    dry_run: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthResponse(BaseModel):
    status: str
    namespace: str
    dry_run: bool
    kubernetes: str
    allowed_targets: list[str]
