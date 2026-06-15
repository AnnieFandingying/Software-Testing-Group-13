"""
群聊通知模块
===========
诊断完成后自动推送到飞书/钉钉群机器人。

支持格式:
- 飞书 (Lark): interactive card
- 钉钉 (DingTalk): actionCard markdown

使用方式:
    在 .env 中设置 VEADK_NOTIFY_WEBHOOK_URL 即可自动启用。
    支持飞书或钉钉 webhook URL，自动识别平台。
"""

import json
import logging
from datetime import datetime

import requests

logger = logging.getLogger("veadk.notify")


def _detect_platform(url: str) -> str:
    """根据 URL 自动识别平台"""
    if "feishu" in url or "lark" in url:
        return "feishu"
    if "dingtalk" in url:
        return "dingtalk"
    return "unknown"


def _build_feishu_card(alert_summary: str, root_cause: str, category: str,
                       confidence: float, actions: list, recommendations: list,
                       record_id: int = 0) -> dict:
    """构建飞书卡片消息"""
    conf_pct = f"{confidence:.0%}"
    if confidence >= 0.8:
        color = "green"
        conf_text = f"🟢 {conf_pct}"
    elif confidence >= 0.5:
        color = "yellow"
        conf_text = f"🟡 {conf_pct}"
    else:
        color = "red"
        conf_text = f"🔴 {conf_pct}"

    actions_text = "\n".join(f"• {a}" for a in actions) if actions else "• 未执行操作"
    recs_text = "\n".join(f"• {r}" for r in recommendations[:3]) if recommendations else "• 无"

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🚨 AIOps Agent 诊断报告 #{record_id}"},
                "template": color,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**告警摘要**\n{alert_summary[:200]}"}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**🔍 根因** ({category})\n{root_cause[:300]}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**📊 指标**\n置信度: {conf_text}"}},
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**🔧 执行操作**\n{actions_text}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**📋 建议**\n{recs_text}"}},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"VeADK AIOps Agent v1.1 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                    ],
                },
            ],
        },
    }


def _build_dingtalk_md(alert_summary: str, root_cause: str, category: str,
                       confidence: float, actions: list, recommendations: list,
                       record_id: int = 0) -> dict:
    """构建钉钉 Markdown 消息"""
    conf_pct = f"{confidence:.0%}"
    if confidence >= 0.8:
        conf_emoji = "🟢"
    elif confidence >= 0.5:
        conf_emoji = "🟡"
    else:
        conf_emoji = "🔴"

    actions_text = "  \n".join(f"- {a}" for a in actions) if actions else "- 未执行操作"
    recs_text = "  \n".join(f"- {r}" for r in recommendations[:3]) if recommendations else "- 无"

    md = (
        f"## 🚨 AIOps Agent 诊断报告 #{record_id}\n\n"
        f"---\n\n"
        f"### 📋 告警摘要\n{alert_summary[:200]}\n\n"
        f"---\n\n"
        f"### 🔍 根因分析 ({category})\n"
        f"{root_cause[:300]}\n\n"
        f"**置信度**: {conf_emoji} {conf_pct}\n\n"
        f"---\n\n"
        f"### 🔧 执行操作\n{actions_text}\n\n"
        f"### 📋 建议\n{recs_text}\n\n"
        f"> VeADK AIOps Agent v1.1 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    return {
        "msgtype": "markdown",
        "markdown": {
            "title": f"AIOps 诊断 #{record_id} - {category} - 置信度{conf_pct}",
            "text": md,
        },
    }


def send_notification(
    alert_context: str,
    report_text: str,
    webhook_url: str,
    record_id: int = 0,
    report_json: dict = None,
) -> bool:
    """
    推送诊断通知到群聊。

    Args:
        alert_context: 告警描述
        report_text: LLM 输出的完整报告
        webhook_url: 群机器人 Webhook URL
        record_id: 诊断记录 ID
        report_json: 结构化诊断 JSON

    Returns:
        True = 发送成功
    """
    if not webhook_url:
        return False

    platform = _detect_platform(webhook_url)
    if platform == "unknown":
        logger.warning("无法识别通知平台（URL 需包含 'feishu' 或 'dingtalk'）")
        return False

    # 从 report_text 提取 JSON
    if report_json is None:
        report_json = _extract_json(report_text)

    alert_summary = report_json.get("alert_summary", alert_context[:200])
    root_cause = report_json.get("root_cause", "未知")
    category = report_json.get("root_cause_category", "未知")
    confidence = report_json.get("confidence", 0.0)
    actions = report_json.get("actions_taken", [])
    recommendations = report_json.get("recommendations", [])

    try:
        if platform == "feishu":
            payload = _build_feishu_card(
                alert_summary, root_cause, category, confidence,
                actions, recommendations, record_id,
            )
        else:  # dingtalk
            payload = _build_dingtalk_md(
                alert_summary, root_cause, category, confidence,
                actions, recommendations, record_id,
            )

        resp = requests.post(webhook_url, json=payload, timeout=10)

        if resp.status_code == 200:
            body = resp.json()
            # 飞书返回 code=0，钉钉返回 errcode=0
            code = body.get("code", body.get("errcode", -1))
            if code == 0:
                logger.info("群通知发送成功 (record_id=%d, platform=%s)", record_id, platform)
                return True
            else:
                logger.warning("群通知返回错误: %s", body.get("msg", body.get("errmsg", "")))
                return False
        else:
            logger.warning("群通知 HTTP %d: %s", resp.status_code, resp.text[:200])
            return False

    except requests.exceptions.Timeout:
        logger.warning("群通知发送超时")
        return False
    except Exception as e:
        logger.warning("群通知发送异常: %s", e)
        return False


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON"""
    import re
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{[^{}]*"alert_time"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def is_configured(webhook_url: str = "") -> bool:
    """检查通知是否已配置"""
    return bool(webhook_url and webhook_url not in ("", "https://your-webhook-url"))
