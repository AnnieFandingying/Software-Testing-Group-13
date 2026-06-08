from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client import ApiException

from app.config import Settings
from app.models import DegradeMode, RestartKind
from app.state import DegradeStateStore


class KubernetesRecoveryClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.available = self._load_config()
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.state_store = DegradeStateStore(self.core_v1, settings)

    def restart(self, namespace: str, kind: RestartKind, target: str, reason: str) -> dict[str, object]:
        self._validate_target(target, allow_pod_prefix=kind == RestartKind.pod)
        if self.settings.dry_run:
            return {"message": f"dry-run: would restart {kind.value} {target}", "changed": False}

        if kind == RestartKind.deployment:
            return self._restart_deployment(namespace, target, reason)
        return self._delete_pod(namespace, target, reason)

    def set_degrade_mode(
        self,
        namespace: str,
        service: str,
        mode: DegradeMode,
        ttl_seconds: int | None,
        reason: str,
    ) -> dict[str, object]:
        self._validate_target(service)
        if self.settings.dry_run:
            return {
                "message": f"dry-run: would set {service} to {mode.value}",
                "changed": False,
                "mode": mode.value,
            }

        data = self.state_store.set_mode(namespace, service, mode, ttl_seconds, reason)
        return {
            "message": f"set {service} degrade mode to {mode.value}",
            "changed": True,
            "mode": mode.value,
            "configmap": self.settings.degraded_configmap,
            "data": data,
        }

    def read_degrade_state(self, namespace: str) -> dict[str, str]:
        return self.state_store.get_modes(namespace)

    def _restart_deployment(self, namespace: str, target: str, reason: str) -> dict[str, object]:
        timestamp = datetime.now(timezone.utc).isoformat()
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "recovery-gateway/restarted-at": timestamp,
                            "recovery-gateway/reason": reason,
                        }
                    }
                }
            }
        }
        self.apps_v1.patch_namespaced_deployment(name=target, namespace=namespace, body=patch)
        return {
            "message": f"deployment {target} rollout restart requested",
            "changed": True,
            "annotation": timestamp,
        }

    def _delete_pod(self, namespace: str, target: str, reason: str) -> dict[str, object]:
        self.core_v1.delete_namespaced_pod(
            name=target,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
        return {"message": f"pod {target} deleted for restart", "changed": True, "reason": reason}

    def _validate_target(self, target: str, allow_pod_prefix: bool = False) -> None:
        if target not in self.settings.allowed_target_set:
            if allow_pod_prefix and any(target.startswith(f"{allowed}-") for allowed in self.settings.allowed_target_set):
                return
            allowed = ", ".join(sorted(self.settings.allowed_target_set))
            raise ValueError(f"target {target!r} is not allowed; allowed targets: {allowed}")

    @staticmethod
    def _load_config() -> bool:
        try:
            config.load_incluster_config()
            return True
        except config.ConfigException:
            try:
                config.load_kube_config()
                return True
            except config.ConfigException:
                return False


def format_api_exception(exc: ApiException) -> str:
    detail = exc.reason or "Kubernetes API error"
    if exc.status:
        detail = f"{exc.status} {detail}"
    return detail
