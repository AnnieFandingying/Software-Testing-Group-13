from datetime import datetime, timedelta, timezone

from kubernetes import client
from kubernetes.client import ApiException

from app.config import Settings
from app.models import DegradeMode


class DegradeStateStore:
    def __init__(self, core_v1: client.CoreV1Api, settings: Settings):
        self._core_v1 = core_v1
        self._settings = settings

    def set_mode(
        self,
        namespace: str,
        service: str,
        mode: DegradeMode,
        ttl_seconds: int | None,
        reason: str,
    ) -> dict[str, str]:
        self._ensure_configmap(namespace)
        expires_at = ""
        if mode == DegradeMode.degraded and ttl_seconds:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

        key_prefix = self._safe_key(service)
        patch = {
            "data": {
                f"{key_prefix}.mode": mode.value,
                f"{key_prefix}.reason": reason,
                f"{key_prefix}.expires_at": expires_at,
                f"{key_prefix}.updated_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        self._core_v1.patch_namespaced_config_map(
            name=self._settings.degraded_configmap,
            namespace=namespace,
            body=patch,
        )
        return patch["data"]

    def get_modes(self, namespace: str) -> dict[str, str]:
        try:
            cm = self._core_v1.read_namespaced_config_map(self._settings.degraded_configmap, namespace)
        except ApiException as exc:
            if exc.status == 404:
                return {}
            raise
        return cm.data or {}

    def _ensure_configmap(self, namespace: str) -> None:
        try:
            self._core_v1.read_namespaced_config_map(self._settings.degraded_configmap, namespace)
            return
        except ApiException as exc:
            if exc.status != 404:
                raise

        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=self._settings.degraded_configmap,
                labels={"app": "recovery-gateway"},
            ),
            data={},
        )
        self._core_v1.create_namespaced_config_map(namespace=namespace, body=body)

    @staticmethod
    def _safe_key(value: str) -> str:
        return value.replace("/", "_").replace(".", "_").replace(":", "_")
