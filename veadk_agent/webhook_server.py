"""
Alertmanager Webhook 接收服务
=============================
接收 Prometheus Alertmanager 发送的告警 Webhook，
解析告警内容，触发 Agent 诊断流程。

同时提供：
- GET  /healthz  — 健康检查
- GET  /metrics  — Agent 自身 Prometheus 指标
- POST /alert    — Alertmanager Webhook 接收端点
- POST /diagnose — 手动触发诊断（调试用）
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .agent import AIOpsAgent, get_agent
from .config import get_config

logger = logging.getLogger("veadk.webhook")

# ============================================================================
# Pydantic 模型
# ============================================================================


class AlertLabel(BaseModel):
    alertname: str = ""
    severity: str = ""
    service: str = ""
    namespace: str = ""
    instance: str = ""


class AlertAnnotation(BaseModel):
    summary: str = ""
    description: str = ""


class AlertItem(BaseModel):
    status: str = ""
    labels: AlertLabel = Field(default_factory=AlertLabel)
    annotations: AlertAnnotation = Field(default_factory=AlertAnnotation)
    startsAt: str = ""
    endsAt: str = ""


class AlertmanagerWebhook(BaseModel):
    receiver: str = ""
    status: str = ""
    alerts: list[AlertItem] = Field(default_factory=list)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""


class DiagnoseRequest(BaseModel):
    alert_context: str
    fingerprint: Optional[str] = None


class DiagnoseResponse(BaseModel):
    ok: bool
    fingerprint: Optional[str] = None
    report: str
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    diagnosis_count: int


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(
    title="VeADK AIOps Agent Webhook",
    description="Alertmanager Webhook 接收服务，负责唤醒 AIOps Agent 进行故障诊断。",
    version="1.0.0",
)

# Agent 单例 + 统计
_agent: Optional[AIOpsAgent] = None
_start_time = time.time()
_diagnosis_count = 0


def _get_agent() -> AIOpsAgent:
    global _agent
    if _agent is None:
        config = get_config()
        _agent = AIOpsAgent(config)
    return _agent


def _make_fingerprint(alert: dict) -> str:
    """生成告警指纹（用于去重和冷却期判断）"""
    raw = json.dumps({
        "alertname": alert.get("labels", {}).get("alertname", ""),
        "service": alert.get("labels", {}).get("service", ""),
        "instance": alert.get("labels", {}).get("instance", ""),
    }, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _format_alert_for_agent(alert: AlertItem) -> str:
    """
    将 Alertmanager 告警格式化为 Agent 可理解的文本。

    Args:
        alert: Alertmanager Webhook 中的单条告警

    Returns:
        格式化的告警描述文本
    """
    labels = alert.labels
    annotations = alert.annotations

    parts = [
        "═══════════════════════════════════",
        f"🔴 告警名称: {labels.alertname}",
        f"   严重程度: {labels.severity}",
        f"   涉及服务: {labels.service}",
        f"   命名空间: {labels.namespace}",
        f"   实例:     {labels.instance}",
        f"   状态:     {alert.status}",
        f"   开始时间: {alert.startsAt}",
        "",
        f"📋 摘要: {annotations.summary}",
        f"📝 描述: {annotations.description}",
        "═══════════════════════════════════",
    ]
    return "\n".join(parts)


# ============================================================================
# API 端点
# ============================================================================


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """健康检查端点"""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_seconds=time.time() - _start_time,
        diagnosis_count=_diagnosis_count,
    )


@app.get("/metrics")
def metrics():
    """暴露 Agent 自身运行指标（Prometheus 文本格式）"""
    uptime = time.time() - _start_time
    return {
        "content": (
            "# HELP veadk_agent_uptime_seconds Agent 运行时间\n"
            "# TYPE veadk_agent_uptime_seconds gauge\n"
            f"veadk_agent_uptime_seconds {uptime:.0f}\n"
            "# HELP veadk_agent_diagnosis_total Agent 诊断次数\n"
            "# TYPE veadk_agent_diagnosis_total counter\n"
            f"veadk_agent_diagnosis_total {_diagnosis_count}\n"
        ),
        "media_type": "text/plain; version=0.0.4",
    }


@app.post("/alert")
async def handle_alert(request: Request):
    """
    接收 Alertmanager Webhook 告警。

    处理流程：
    1. 解析 Webhook JSON
    2. 过滤 firing 状态的告警
    3. 按严重程度排序，优先处理 critical
    4. 调用 Agent 进行诊断
    5. 返回诊断报告
    """
    global _diagnosis_count

    # 解析请求体
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="无效的 JSON 格式")

    logger.info("收到 Alertmanager Webhook: status=%s alerts=%d", body.get("status"), len(body.get("alerts", [])))

    # 只处理 firing 状态的告警
    alerts = body.get("alerts", [])
    firing_alerts = [a for a in alerts if a.get("status") == "firing"]

    if not firing_alerts:
        logger.info("无 firing 告警，跳过诊断")
        return {"ok": True, "message": "无 firing 告警", "alerts_processed": 0}

    # 按严重程度排序：critical > warning > info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    firing_alerts.sort(key=lambda a: severity_order.get(a.get("labels", {}).get("severity", "info"), 99))

    # 处理每个告警（有冷却期保护）
    agent = _get_agent()
    reports = []

    for alert_dict in firing_alerts[:3]:  # 最多处理 3 个告警
        alert = AlertItem(**alert_dict)
        fingerprint = _make_fingerprint(alert_dict)
        alert_text = _format_alert_for_agent(alert)

        logger.info("处理告警: fingerprint=%s alertname=%s", fingerprint, alert.labels.alertname)

        start = time.perf_counter()
        report = agent.diagnose(alert_text, alert_fingerprint=fingerprint)
        elapsed_ms = (time.perf_counter() - start) * 1000

        _diagnosis_count += 1

        reports.append({
            "fingerprint": fingerprint,
            "alertname": alert.labels.alertname,
            "severity": alert.labels.severity,
            "report": report,
            "elapsed_ms": elapsed_ms,
        })

        logger.info("告警 %s 诊断完成 (%.0fms)", fingerprint, elapsed_ms)

    return {
        "ok": True,
        "alerts_received": len(alerts),
        "alerts_processed": len(reports),
        "diagnosis_results": reports,
    }


@app.post("/diagnose", response_model=DiagnoseResponse)
def manual_diagnose(req: DiagnoseRequest):
    """
    手动触发诊断（调试用）。

    可以直接 POST 一段告警描述，触发 Agent 诊断。
    """
    global _diagnosis_count
    agent = _get_agent()

    start = time.perf_counter()
    report = agent.diagnose(req.alert_context, alert_fingerprint=req.fingerprint)
    elapsed_ms = (time.perf_counter() - start) * 1000

    _diagnosis_count += 1

    return DiagnoseResponse(
        ok=True,
        fingerprint=req.fingerprint,
        report=report,
        elapsed_ms=elapsed_ms,
    )
