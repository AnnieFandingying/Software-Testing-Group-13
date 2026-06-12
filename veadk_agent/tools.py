"""
Agent 工具注册与实现模块
======================
定义 Agent 可以调用的所有工具函数，以及对应的 Function Calling Schema。

四个核心工具：
1. execute_promql    - 执行 PromQL 查询获取 Prometheus 监控指标
2. get_service_logs  - 获取指定微服务的 Kubernetes Pod 日志
3. restart_pod       - 通过 recovery-gateway 重启指定的 K8s 服务
4. set_degrade_mode  - 设置服务降级模式（扩展工具）
"""

import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .config import AgentConfig, get_config

logger = logging.getLogger("veadk.tools")

# ============================================================================
# PromQL 预定义查询模板（帮助 LLM 快速选择合适的查询）
# ============================================================================

PROMQL_TEMPLATES: dict[str, dict[str, str]] = {
    "cpu_usage": {
        "description": "各 Pod 的 CPU 使用率（核）",
        "query": 'sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}"}}[5m])) by (pod)',
    },
    "memory_usage": {
        "description": "各 Pod 的内存使用量（字节）",
        "query": 'sum(container_memory_usage_bytes{{namespace="{namespace}"}}) by (pod)',
    },
    "memory_usage_mb": {
        "description": "各 Pod 的内存使用量（MB）",
        "query": 'sum(container_memory_usage_bytes{{namespace="{namespace}"}}) by (pod) / 1024 / 1024',
    },
    "error_rate_5xx": {
        "description": "5xx 错误率",
        "query": 'sum(rate(http_requests_total{{namespace="{namespace}", status_code=~"5.."}}[5m])) by (service)',
    },
    "request_rate": {
        "description": "各服务的请求速率（QPS）",
        "query": 'sum(rate(http_requests_total{{namespace="{namespace}"}}[5m])) by (service)',
    },
    "pod_restarts": {
        "description": "Pod 重启次数",
        "query": 'kube_pod_container_status_restarts_total{{namespace="{namespace}"}}',
    },
    "pod_status": {
        "description": "Pod 运行状态（Running=1, 其他=0）",
        "query": 'sum(kube_pod_status_ready{{namespace="{namespace}"}}) by (pod)',
    },
    "disk_usage": {
        "description": "各 Pod 的文件系统使用率",
        "query": 'sum(container_fs_usage_bytes{{namespace="{namespace}"}}) by (pod) / sum(container_fs_limit_bytes{{namespace="{namespace}"}}) by (pod) * 100',
    },
    "network_rx": {
        "description": "各 Pod 的网络接收速率（bytes/s）",
        "query": 'sum(rate(container_network_receive_bytes_total{{namespace="{namespace}"}}[5m])) by (pod)',
    },
    "network_tx": {
        "description": "各 Pod 的网络发送速率（bytes/s）",
        "query": 'sum(rate(container_network_transmit_bytes_total{{namespace="{namespace}"}}[5m])) by (pod)',
    },
    "boutique_requests": {
        "description": "Online-Boutique 遥测事件总数（telemetryservice 自定义指标）",
        "query": 'boutique_requests_total',
    },
    "boutique_errors": {
        "description": "Online-Boutique 遥测错误事件数（telemetryservice 自定义指标）",
        "query": 'boutique_errors_total',
    },
    "boutique_discount_hits": {
        "description": "折扣规则命中次数（telemetryservice 自定义指标）",
        "query": 'boutique_discount_hits_total',
    },
}


def _build_promql_template_table() -> str:
    """生成 PromQL 模板表格，嵌入工具描述中供 LLM 参考"""
    lines = ["预定义 PromQL 查询模板："]
    for name, info in PROMQL_TEMPLATES.items():
        lines.append(f"  - {name}: {info['description']}")
        lines.append(f"    PromQL: {info['query']}")
    return "\n".join(lines)


# ============================================================================
# 工具 1：execute_promql
# ============================================================================

def execute_promql(query_str: str, config: Optional[AgentConfig] = None) -> str:
    """
    执行 PromQL 查询，从 Prometheus 获取监控指标数据。

    Args:
        query_str: 要执行的 PromQL 查询语句
        config: Agent 配置（可选，默认使用全局配置）

    Returns:
        格式化的查询结果字符串
    """
    if config is None:
        config = get_config()

    logger.info("执行 PromQL 查询: %s", query_str[:120])

    try:
        response = requests.get(
            config.prometheus_query_url,
            params={"query": query_str},
            timeout=config.prometheus_timeout,
        )

        if response.status_code != 200:
            return (
                f"Prometheus 查询失败 (HTTP {response.status_code}): "
                f"{response.text[:500]}"
            )

        data = response.json()
        result_type = data.get("data", {}).get("resultType", "unknown")
        results = data.get("data", {}).get("result", [])

        if not results:
            return f"查询结果为空 (resultType={result_type})。可能原因：指标不存在、时间范围内无数据、或 label 过滤条件不匹配。"

        # 格式化输出
        output_lines = [f"查询成功 (resultType={result_type}, 共 {len(results)} 条结果):"]
        for item in results[:20]:  # 最多展示 20 条
            metric = item.get("metric", {})
            value = item.get("value", [None, "N/A"])
            metric_labels = ", ".join(f"{k}={v}" for k, v in metric.items())
            if metric_labels:
                output_lines.append(f"  {metric_labels} => {value[1]}")
            else:
                output_lines.append(f"  value => {value[1]}")

        if len(results) > 20:
            output_lines.append(f"  ... 还有 {len(results) - 20} 条结果未显示")

        return "\n".join(output_lines)

    except requests.exceptions.Timeout:
        return f"Prometheus 查询超时 (timeout={config.prometheus_timeout}s)。请检查 Prometheus 是否在线。"
    except requests.exceptions.ConnectionError as e:
        return f"无法连接到 Prometheus ({config.prometheus_url}): {e}"
    except Exception as e:
        logger.exception("PromQL 查询异常")
        return f"PromQL 查询异常: {type(e).__name__}: {e}"


# ============================================================================
# 工具 2：get_service_logs
# ============================================================================

def _find_pod_by_service(service_name: str, namespace: str, config: AgentConfig) -> Optional[str]:
    """根据服务名查找 Pod 名称"""
    try:
        result = subprocess.run(
            [
                "kubectl", "get", "pods",
                "-n", namespace,
                "-l", f"app={service_name}",
                "-o", "jsonpath={.items[0].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # 备选：使用更宽松的标签匹配
    try:
        result = subprocess.run(
            [
                "kubectl", "get", "pods",
                "-n", namespace,
                "--field-selector", "status.phase=Running",
                "-o", "jsonpath={.items[?(@.metadata.labels.app)].metadata.name}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            pod_names = result.stdout.strip().split()
            for pod_name in pod_names:
                if service_name.lower() in pod_name.lower():
                    return pod_name
    except Exception:
        pass

    return None


def get_service_logs(
    service_name: str,
    tail_lines: int = 50,
    namespace: Optional[str] = None,
    config: Optional[AgentConfig] = None,
) -> str:
    """
    获取指定微服务的最新 Kubernetes Pod 日志。

    Args:
        service_name: 服务名称（如 frontend, catalogue, checkoutservice）
        tail_lines: 返回最后 N 行日志
        namespace: K8s 命名空间
        config: Agent 配置

    Returns:
        格式化的日志内容
    """
    if config is None:
        config = get_config()
    if namespace is None:
        namespace = config.k8s_namespace

    logger.info("获取服务日志: service=%s namespace=%s tail=%d", service_name, namespace, tail_lines)

    # 1. 查找 Pod
    pod_name = _find_pod_by_service(service_name, namespace, config)

    if pod_name is None:
        # 尝试列出所有 Pod 帮助 LLM 定位
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "--no-headers"],
                capture_output=True, text=True, timeout=10,
            )
            pod_list = result.stdout.strip() or "(无 Pod 或 kubectl 不可用)"
        except Exception:
            pod_list = "(kubectl 不可用)"

        return (
            f"未找到服务 '{service_name}' 对应的 Running Pod。\n"
            f"命名空间 '{namespace}' 中的 Pod 列表:\n{pod_list}\n"
            f"请确认服务名称是否正确。"
        )

    # 2. 获取日志
    try:
        result = subprocess.run(
            [
                "kubectl", "logs",
                f"deployment/{service_name}",
                "-n", namespace,
                f"--tail={tail_lines}",
                "--timestamps",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            # 回退到直接使用 Pod 名称
            result = subprocess.run(
                ["kubectl", "logs", pod_name, "-n", namespace, f"--tail={tail_lines}", "--timestamps"],
                capture_output=True, text=True, timeout=15,
            )

        if result.returncode != 0:
            return f"获取日志失败: {result.stderr[:500]}"

        logs = result.stdout.strip()
        if not logs:
            return f"服务 '{service_name}' (Pod: {pod_name}) 的日志为空。"

        return (
            f"服务 '{service_name}' (Pod: {pod_name}) 最后 {tail_lines} 行日志:\n"
            f"{'─' * 60}\n"
            f"{logs}\n"
            f"{'─' * 60}"
        )

    except subprocess.TimeoutExpired:
        return f"获取日志超时: 服务 '{service_name}'"
    except Exception as e:
        logger.exception("获取日志异常")
        return f"获取日志异常: {type(e).__name__}: {e}"


# ============================================================================
# 工具 3：restart_pod（通过 recovery-gateway）
# ============================================================================

def restart_pod(
    service_name: str,
    namespace: Optional[str] = None,
    reason: str = "agent_auto_recovery",
    config: Optional[AgentConfig] = None,
) -> str:
    """
    通过 recovery-gateway 重启指定的 K8s 服务（Deployment）。

    执行前会校验服务是否在白名单中。

    Args:
        service_name: 要重启的服务名称（如 frontend, checkoutservice）
        namespace: K8s 命名空间
        reason: 重启原因（记录在 Deployment annotation 中）
        config: Agent 配置

    Returns:
        操作结果描述
    """
    if config is None:
        config = get_config()
    if namespace is None:
        namespace = config.k8s_namespace

    logger.info("重启服务: service=%s namespace=%s reason=%s", service_name, namespace, reason)

    # 安全检查：是否在白名单中
    if service_name not in config.allowed_services:
        return (
            f"⛔ 重启操作被拒绝: '{service_name}' 不在自愈白名单中。\n"
            f"允许操作的服务: {', '.join(sorted(config.allowed_services))}"
        )

    # 方式 1：通过 recovery-gateway REST API
    if config.recovery_auth_token and config.recovery_auth_token != "change-me":
        try:
            response = requests.post(
                config.recovery_restart_url,
                json={
                    "target": service_name,
                    "namespace": namespace,
                    "kind": "deployment",
                    "reason": reason,
                },
                headers={
                    "Authorization": f"Bearer {config.recovery_auth_token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                return (
                    f"✅ 服务重启成功 (via recovery-gateway):\n"
                    f"  服务: {service_name}\n"
                    f"  命名空间: {namespace}\n"
                    f"  方式: deployment rollout restart\n"
                    f"  详情: {data.get('message', 'OK')}\n"
                    f"  时间: {data.get('details', {}).get('annotation', 'N/A')}"
                )
            elif response.status_code == 401:
                logger.error("recovery-gateway 认证失败，Token 不匹配")
                return _restart_via_kubectl(service_name, namespace, reason)
            else:
                error_detail = response.json().get("detail", response.text[:300])
                logger.warning("recovery-gateway 返回 %d: %s", response.status_code, error_detail)
                return _restart_via_kubectl(service_name, namespace, reason)

        except requests.exceptions.ConnectionError:
            logger.warning("recovery-gateway 不可达，降级使用 kubectl")
            return _restart_via_kubectl(service_name, namespace, reason)
        except Exception as e:
            logger.exception("recovery-gateway 调用异常")
            return _restart_via_kubectl(service_name, namespace, reason)

    # 方式 2：降级为 kubectl 命令
    return _restart_via_kubectl(service_name, namespace, reason)


def _restart_via_kubectl(service_name: str, namespace: str, reason: str) -> str:
    """使用 kubectl 命令执行滚动重启（降级方案）"""
    try:
        # 先检查 deployment 是否存在
        check = subprocess.run(
            ["kubectl", "get", "deployment", service_name, "-n", namespace],
            capture_output=True, text=True, timeout=10,
        )

        if check.returncode != 0:
            return (
                f"⛔ 无法重启: Deployment '{service_name}' 在命名空间 '{namespace}' 中不存在。\n"
                f"kubectl 错误: {check.stderr[:200]}"
            )

        # 执行滚动重启
        result = subprocess.run(
            ["kubectl", "rollout", "restart", f"deployment/{service_name}", "-n", namespace],
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode == 0:
            return (
                f"✅ 服务重启成功 (via kubectl):\n"
                f"  服务: {service_name}\n"
                f"  命名空间: {namespace}\n"
                f"  方式: kubectl rollout restart deployment/{service_name}\n"
                f"  原因: {reason}\n"
                f"  时间: {datetime.now(timezone.utc).isoformat()}"
            )
        else:
            return (
                f"⛔ kubectl 重启失败: {result.stderr[:500]}\n"
                f"  服务: {service_name}\n"
                f"  命名空间: {namespace}"
            )

    except subprocess.TimeoutExpired:
        return f"⛔ kubectl 命令超时: 重启 '{service_name}' 未在 30s 内完成"
    except FileNotFoundError:
        return (
            f"⛔ kubectl 未安装或不在 PATH 中。\n"
            f"  请确认 recovery-gateway 已运行并配置 VEADK_RECOVERY_AUTH_TOKEN 环境变量。"
        )
    except Exception as e:
        logger.exception("kubectl 重启异常")
        return f"⛔ kubectl 重启异常: {type(e).__name__}: {e}"


# ============================================================================
# 工具 4：set_degrade_mode（扩展工具，加分项）
# ============================================================================

def set_degrade_mode(
    service_name: str,
    mode: str = "degraded",
    ttl_seconds: int = 900,
    namespace: Optional[str] = None,
    reason: str = "agent_auto_degrade",
    config: Optional[AgentConfig] = None,
) -> str:
    """
    设置服务的降级模式。

    当诊断出某服务压力过大但不需要完全重启时，
    可将其标记为 degraded 模式，触发上游熔断或降级逻辑。

    Args:
        service_name: 服务名称
        mode: "degraded" 或 "normal"
        ttl_seconds: 降级持续时间（秒），默认 900s (15分钟)
        namespace: K8s 命名空间
        reason: 降级原因
        config: Agent 配置

    Returns:
        操作结果描述
    """
    if config is None:
        config = get_config()
    if namespace is None:
        namespace = config.k8s_namespace

    logger.info("设置降级模式: service=%s mode=%s ttl=%ds", service_name, mode, ttl_seconds)

    if mode not in ("degraded", "normal"):
        return f"⛔ 无效的降级模式: '{mode}'。仅支持 'degraded' 或 'normal'。"

    try:
        response = requests.post(
            config.recovery_degrade_url,
            json={
                "service": service_name,
                "mode": mode,
                "namespace": namespace,
                "ttl_seconds": ttl_seconds,
                "reason": reason,
            },
            headers={
                "Authorization": f"Bearer {config.recovery_auth_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )

        if response.status_code == 200:
            data = response.json()
            return (
                f"{'✅' if data.get('ok') else '⛔'} 降级模式设置:\n"
                f"  服务: {service_name}\n"
                f"  模式: {mode}\n"
                f"  TTL: {ttl_seconds}s\n"
                f"  详情: {data.get('message', 'OK')}"
            )
        else:
            return f"⛔ 降级模式设置失败 (HTTP {response.status_code}): {response.text[:300]}"

    except requests.exceptions.ConnectionError:
        return "⛔ recovery-gateway 不可达，无法设置降级模式。"
    except Exception as e:
        logger.exception("设置降级模式异常")
        return f"⛔ 设置降级模式异常: {type(e).__name__}: {e}"


# ============================================================================
# 工具注册表
# ============================================================================

# 工具函数映射表
AVAILABLE_TOOLS: dict[str, callable] = {
    "execute_promql": execute_promql,
    "get_service_logs": get_service_logs,
    "restart_pod": restart_pod,
    "set_degrade_mode": set_degrade_mode,
}


def get_tool_schemas(config: Optional[AgentConfig] = None) -> list[dict[str, Any]]:
    """
    生成 OpenAI Function Calling 格式的工具 Schema 列表。

    工具描述中嵌入 PromQL 模板和允许的服务列表，帮助 LLM
    在没有额外训练的情况下做出正确的工具选择。
    """
    if config is None:
        config = get_config()

    promql_table = _build_promql_template_table()
    allowed_services_str = ", ".join(sorted(config.allowed_services))

    return [
        {
            "type": "function",
            "function": {
                "name": "execute_promql",
                "description": (
                    "执行 PromQL 查询语句，从 Prometheus 获取实时监控指标数据。\n\n"
                    "使用场景：\n"
                    "- 需要查看服务的 CPU、内存、网络等资源使用情况\n"
                    "- 需要查看请求速率、错误率、延迟等应用指标\n"
                    "- 需要检查 Pod 运行状态和重启次数\n\n"
                    f"{promql_table}\n\n"
                    "⚠️ 注意：PromQL 中的 namespace 默认使用 sock-shop。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query_str": {
                            "type": "string",
                            "description": (
                                "要执行的 PromQL 查询语句。"
                                "可使用上面列出的预定义模板名称，"
                                "也可以编写自定义 PromQL。"
                            ),
                        }
                    },
                    "required": ["query_str"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_service_logs",
                "description": (
                    "获取指定微服务的最新 Kubernetes Pod 日志。\n\n"
                    "使用场景：\n"
                    "- 收到 CPU/内存异常告警后，查看对应服务的日志确认根因\n"
                    "- 发现错误率上升后，查看日志中的具体错误信息\n"
                    "- 检查服务是否出现 'Connection refused'、'OOM'、'timeout' 等异常\n\n"
                    f"可选的服务名称: {allowed_services_str}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": f"要查询日志的服务名称。可选值: {allowed_services_str}",
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "返回日志的最后 N 行，默认 50。如果错误信息较多，可增加到 100-200。",
                        },
                    },
                    "required": ["service_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "restart_pod",
                "description": (
                    "重启指定的 Kubernetes 服务（Deployment 滚动重启）。\n\n"
                    "⚠️ 重要：仅当以下条件全部满足时才可调用此工具：\n"
                    "1. 已通过 PromQL 和日志确认服务确实处于异常状态\n"
                    "2. 异常不是由正常流量突增引起的\n"
                    "3. 服务处于死锁、内存泄漏、连接池耗尽等无法自行恢复的状态\n\n"
                    "⚠️ 严禁对以下情况调用重启：\n"
                    "- 尚未查询监控指标和日志就直接重启\n"
                    "- 仅因为 CPU 暂时升高就重启\n"
                    "- 同时重启多个服务\n\n"
                    f"允许操作的服务（白名单）: {allowed_services_str}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": f"要重启的服务名称。仅限白名单中的服务: {allowed_services_str}",
                        },
                        "reason": {
                            "type": "string",
                            "description": "重启原因，会记录在 Deployment annotation 中用于事后分析。",
                        },
                    },
                    "required": ["service_name", "reason"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_degrade_mode",
                "description": (
                    "设置服务的降级模式（degraded/normal）。\n\n"
                    "使用场景：\n"
                    "- 当服务压力过大但不需要完全重启时，标记为 degraded 触发上游熔断\n"
                    "- 当服务恢复正常后，恢复为 normal 模式\n\n"
                    "⚠️ 此工具需要 recovery-gateway 已部署并正确配置。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "要设置降级模式的服务名称",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["degraded", "normal"],
                            "description": "降级模式: 'degraded'=触发降级, 'normal'=恢复正常",
                        },
                        "ttl_seconds": {
                            "type": "integer",
                            "description": "降级持续时间（秒），默认 900 (15分钟)。超时后自动恢复 normal。",
                        },
                    },
                    "required": ["service_name", "mode"],
                },
            },
        },
    ]


# ============================================================================
# 工具调度器
# ============================================================================

def execute_tool(function_name: str, arguments: dict[str, Any], config: Optional[AgentConfig] = None) -> str:
    """
    根据函数名和参数执行对应的工具函数。

    Args:
        function_name: 工具函数名
        arguments: 函数参数（从 LLM function_call 解析）
        config: Agent 配置

    Returns:
        工具执行结果字符串

    Raises:
        ValueError: 未知的工具名称
    """
    if function_name not in AVAILABLE_TOOLS:
        raise ValueError(f"未知工具: '{function_name}'。可用工具: {list(AVAILABLE_TOOLS.keys())}")

    func = AVAILABLE_TOOLS[function_name]
    start = time.perf_counter()

    try:
        result = func(**arguments, config=config)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("工具 %s 执行完成 (%.0fms)", function_name, elapsed_ms)
        return str(result)
    except TypeError as e:
        logger.error("工具 %s 参数错误: %s (传入: %s)", function_name, e, arguments)
        return f"工具调用参数错误: {e}。请检查参数名和类型是否正确，然后重试。"
    except Exception as e:
        logger.exception("工具 %s 执行异常", function_name)
        return f"工具执行异常 ({function_name}): {type(e).__name__}: {e}"
