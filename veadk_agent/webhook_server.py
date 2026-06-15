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

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .agent import AIOpsAgent, get_agent
from .config import get_config
from .dashboard import render_history, render_detail, render_stats, render_health, render_cluster_health
from .report_store import get_store

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

    # 解析请求体（兼容 UTF-8 和 GBK 编码）
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 降级：手动读取原始字节并尝试 GBK → UTF-8
        try:
            raw = await request.body()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
            body = json.loads(text)
        except Exception:
            raise HTTPException(status_code=400, detail="无效的 JSON 格式（请使用 UTF-8 编码）")

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

    # 告警聚合：多条告警时进行关联分析，识别共同根因
    agent = _get_agent()
    reports = []
    start = time.perf_counter()

    if len(firing_alerts) >= 2:
        # 多条告警 → 聚合推理，识别共同根因
        logger.info("触发聚合诊断: %d 条告警", len(firing_alerts))
        alert_dicts = [
            {
                "alertname": a.get("labels", {}).get("alertname", ""),
                "severity": a.get("labels", {}).get("severity", "info"),
                "service": a.get("labels", {}).get("service", "unknown"),
                "summary": a.get("annotations", {}).get("summary", ""),
                "description": a.get("annotations", {}).get("description", ""),
            }
            for a in firing_alerts[:5]
        ]
        # 生成聚合指纹（合并所有告警名 + 服务名），实现冷却期去重
        agg_fp_parts = sorted(set(
            a.get("alertname", "") + a.get("service", "") for a in alert_dicts
        ))
        agg_fingerprint = hashlib.md5("|".join(agg_fp_parts).encode()).hexdigest()[:12]

        report = agent.bulk_diagnose(alert_dicts, agg_fingerprint)
        elapsed_ms = (time.perf_counter() - start) * 1000
        _diagnosis_count += 1
        reports.append({
            "fingerprint": agg_fingerprint,
            "alertname": f"聚合诊断 ({len(alert_dicts)}条告警)",
            "severity": "critical",
            "report": report,
            "elapsed_ms": elapsed_ms,
        })
        logger.info("聚合诊断完成 (%.0fms)", elapsed_ms)
    else:
        # 单条告警 → 常规处理
        for alert_dict in firing_alerts[:3]:
            alert = AlertItem(**alert_dict)
            fingerprint = _make_fingerprint(alert_dict)
            alert_text = _format_alert_for_agent(alert)

            logger.info("处理告警: fingerprint=%s alertname=%s", fingerprint, alert.labels.alertname)

            single_start = time.perf_counter()
            report = agent.diagnose(alert_text, alert_fingerprint=fingerprint)
            single_elapsed = (time.perf_counter() - single_start) * 1000

            _diagnosis_count += 1

            reports.append({
                "fingerprint": fingerprint,
                "alertname": alert.labels.alertname,
                "severity": alert.labels.severity,
                "report": report,
                "elapsed_ms": single_elapsed,
            })

            logger.info("告警 %s 诊断完成 (%.0fms)", fingerprint, single_elapsed)

    return {
        "ok": True,
        "alerts_received": len(alerts),
        "alerts_processed": len(reports),
        "aggregated": len(firing_alerts) >= 2,
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


@app.post("/simulate")
def simulate_alert(req: DiagnoseRequest):
    """
    🆕 模拟告警 — 仪表盘一键触发诊断（演示用）。
    无需等待 Alertmanager，点按钮即可触发完整诊断流程。
    """
    global _diagnosis_count
    from .report_store import get_store
    agent = _get_agent()
    store = get_store()

    start = time.perf_counter()
    report = agent.diagnose(req.alert_context)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _diagnosis_count += 1

    # 返回最新记录 ID（刚保存的）
    record_id = store.count()

    return {
        "ok": True,
        "record_id": record_id,
        "report": report[:500],
        "elapsed_ms": round(elapsed_ms),
    }


# ============================================================================
# 仪表盘 & 历史查询端点
# ============================================================================

@app.get("/history", response_class=HTMLResponse)
def history_dashboard(view: str = Query(default="list", description="视图类型: list | stats | cluster | health")):
    """
    Web 仪表盘主页。
    - /history → 诊断历史列表
    - /history?view=stats → 统计面板
    - /history?view=cluster → 集群健康评分
    - /history?view=health → 健康检查
    """
    store = get_store()

    if view == "stats":
        return HTMLResponse(render_stats(store.stats()))

    if view == "cluster":
        return HTMLResponse(render_cluster_health(store.get_all(limit=20)))

    if view == "health":
        cfg = get_config()
        return HTMLResponse(render_health(
            uptime=time.time() - _start_time,
            diagnosis_count=_diagnosis_count,
            prometheus_url=cfg.prometheus_url,
            gateway_url=cfg.recovery_gateway_url,
        ))

    records = store.get_all(limit=20)
    stats = store.stats()
    return HTMLResponse(render_history(records, stats))


@app.get("/history/stats")
def history_stats():
    """诊断统计 JSON API"""
    store = get_store()
    return store.stats()


@app.get("/history/{record_id}", response_class=HTMLResponse)
def history_detail(record_id: int):
    """单条诊断详情页"""
    store = get_store()
    record = store.get_by_id(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return HTMLResponse(render_detail(record))


@app.get("/reports/{filename}")
def download_report(filename: str):
    """下载 Markdown 报告文件"""
    from .report_store import REPORTS_DIR
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(str(filepath), media_type="text/markdown", filename=filename)
