"""
Agent 配置管理模块
---------------
从环境变量或 .env 文件读取所有配置项。
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional


@dataclass
class AgentConfig:
    """Agent 全局配置"""

    # --- 大模型 API 配置 ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.1  # 低温度，保证诊断一致性

    # --- Prometheus 配置 ---
    prometheus_url: str = "http://localhost:9090"
    prometheus_timeout: int = 10  # 秒

    # --- recovery-gateway 配置 ---
    recovery_gateway_url: str = "http://localhost:8080"
    recovery_auth_token: str = "change-me"

    # --- Kubernetes 配置 ---
    k8s_namespace: str = "sock-shop"
    kube_config_path: Optional[str] = None  # None = 使用默认 kubeconfig

    # --- Webhook 服务器配置 ---
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 5000

    # --- Agent 行为配置 ---
    max_tool_calls_per_diagnosis: int = 5  # 单次诊断最大工具调用轮数
    cpu_alert_threshold: float = 0.5  # CPU 告警阈值
    memory_alert_threshold_mb: float = 512  # 内存告警阈值
    patrol_interval_seconds: int = 10  # 轮询模式巡检间隔
    diagnosis_cooldown_seconds: int = 60  # 同一告警冷却期

    # --- 自愈白名单（仅允许操作这些服务） ---
    allowed_services: list[str] = field(default_factory=lambda: [
        "frontend",
        "checkoutservice",
        "cartservice",
        "productcatalogservice",
        "paymentservice",
        "shippingservice",
        "currencyservice",
        "emailservice",
        "recommendationservice",
        "adservice",
        "redis-cart",
        "discountservice",
        "telemetryservice",
        "recovery-gateway",
    ])

    # --- 告警指纹去重（内存缓存） ---
    dedup_cache_size: int = 100

    def __post_init__(self):
        """从环境变量覆盖默认值"""
        self._load_from_env()

    def _load_from_env(self):
        """读取环境变量（前缀 VEADK_）"""
        env_map = {
            "VEADK_LLM_API_KEY": "llm_api_key",
            "VEADK_LLM_BASE_URL": "llm_base_url",
            "VEADK_LLM_MODEL": "llm_model",
            "VEADK_LLM_MAX_TOKENS": ("llm_max_tokens", int),
            "VEADK_LLM_TEMPERATURE": ("llm_temperature", float),
            "VEADK_PROMETHEUS_URL": "prometheus_url",
            "VEADK_PROMETHEUS_TIMEOUT": ("prometheus_timeout", int),
            "VEADK_RECOVERY_GATEWAY_URL": "recovery_gateway_url",
            "VEADK_RECOVERY_AUTH_TOKEN": "recovery_auth_token",
            "VEADK_K8S_NAMESPACE": "k8s_namespace",
            "VEADK_WEBHOOK_PORT": ("webhook_port", int),
            "VEADK_MAX_TOOL_CALLS": ("max_tool_calls_per_diagnosis", int),
            "VEADK_CPU_THRESHOLD": ("cpu_alert_threshold", float),
            "VEADK_PATROL_INTERVAL": ("patrol_interval_seconds", int),
            "VEADK_COOLDOWN_SECONDS": ("diagnosis_cooldown_seconds", int),
        }

        for env_key, attr_info in env_map.items():
            value = os.getenv(env_key, "")
            if not value:
                continue
            if isinstance(attr_info, tuple):
                attr_name, converter = attr_info
                try:
                    setattr(self, attr_name, converter(value))
                except (ValueError, TypeError):
                    pass
            else:
                setattr(self, attr_info, value)

        # 也支持 OPENAI_API_KEY 作为后备
        if not self.llm_api_key:
            self.llm_api_key = os.getenv("OPENAI_API_KEY", "")

        # 读取 allowed_services 环境变量（逗号分隔）
        allowed_env = os.getenv("VEADK_ALLOWED_SERVICES", "")
        if allowed_env:
            self.allowed_services = [s.strip() for s in allowed_env.split(",") if s.strip()]

    @property
    def prometheus_query_url(self) -> str:
        """Prometheus 即时查询 API 地址"""
        return f"{self.prometheus_url.rstrip('/')}/api/v1/query"

    @property
    def prometheus_range_url(self) -> str:
        """Prometheus 范围查询 API 地址"""
        return f"{self.prometheus_url.rstrip('/')}/api/v1/query_range"

    @property
    def recovery_restart_url(self) -> str:
        """自愈网关重启 API 地址"""
        return f"{self.recovery_gateway_url.rstrip('/')}/api/v1/restart"

    @property
    def recovery_degrade_url(self) -> str:
        """自愈网关降级 API 地址"""
        return f"{self.recovery_gateway_url.rstrip('/')}/api/v1/degrade"

    @property
    def recovery_health_url(self) -> str:
        """自愈网关健康检查地址"""
        return f"{self.recovery_gateway_url.rstrip('/')}/healthz"


@lru_cache()
def get_config() -> AgentConfig:
    """获取全局配置单例"""
    return AgentConfig()


def load_dotenv_if_exists() -> None:
    """加载 .env 文件（如果存在）"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass
