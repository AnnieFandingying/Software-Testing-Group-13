from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECOVERY_", env_file=".env", extra="ignore")

    namespace: str = Field(default="default", description="Default Kubernetes namespace.")
    auth_token: str = Field(default="change-me", description="Bearer token accepted from the Agent.")
    dry_run: bool = Field(default=False, description="Simulate Kubernetes writes when true.")
    allowed_targets: str = Field(
        default="frontend,checkoutservice,cartservice,productcatalogservice,paymentservice,shippingservice,"
        "currencyservice,emailservice,recommendationservice,adservice,redis-cart,discountservice,"
        "telemetryservice,recovery-gateway",
        description="Comma-separated deployment/service names that may be changed.",
    )
    degraded_configmap: str = Field(
        default="recovery-gateway-degrade-state",
        description="ConfigMap storing service degrade switches.",
    )

    @property
    def allowed_target_set(self) -> set[str]:
        return {item.strip() for item in self.allowed_targets.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
