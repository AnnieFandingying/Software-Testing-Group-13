"""
Agent 核心推理模块
================
实现 AIOps Agent 的核心推理循环（ReAct Loop），包括：

1. System Prompt 设计（定义 Agent 人设与专家知识）
2. ReAct 循环：思考 → 工具调用 → 观察 → 再思考
3. 诊断报告生成（结构化 JSON 输出）
4. 与 LLM API 的交互封装
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from openai import OpenAI

from .config import AgentConfig, get_config
from .tools import execute_tool, get_tool_schemas

logger = logging.getLogger("veadk.agent")

# 延迟导入避免循环依赖
_report_store_imported = False


def _save_to_history(alert_context: str, report_text: str):
    """诊断完成后自动保存到 SQLite + Markdown 文件 + 群聊通知"""
    global _report_store_imported
    try:
        if not _report_store_imported:
            from .report_store import save_diagnosis  # noqa: F811
            _report_store_imported = True
        from .report_store import save_diagnosis
        record_id = save_diagnosis(alert_context, report_text)
        logger.info("诊断已归档: id=%d", record_id)

        # 群聊通知（如果配置了 webhook URL）
        try:
            from .config import get_config
            from .notify import send_notification, is_configured
            cfg = get_config()
            if is_configured(cfg.notify_webhook_url):
                send_notification(alert_context, report_text, cfg.notify_webhook_url, record_id)
        except Exception:
            pass

        # 知识库提取
        try:
            from .report_store import _extract_json
            from .knowledge import extract_and_store
            report_json = _extract_json(report_text)
            extract_and_store(record_id, alert_context, report_json)
        except Exception:
            pass
    except Exception as e:
        logger.warning("诊断归档失败（不影响主流程）: %s", e)

# ============================================================================
# System Prompt — Agent 人设与专家知识
# ============================================================================

SYSTEM_PROMPT = """你是一个资深的云原生 AIOps 专家 Agent，运行在 VeADK (Volcengine Agent Development Kit) 框架之上。

## 你的能力
你可以自主调用以下工具来收集信息和执行操作：
1. **execute_promql** — 查询 Prometheus 监控指标（CPU、内存、网络、错误率等）
2. **get_service_logs** — 获取微服务的容器日志
3. **restart_pod** — 重启异常服务（需确认后再执行）
4. **set_degrade_mode** — 设置服务降级模式（熔断保护）

## 你的运维哲学
- **证据驱动诊断**：不能仅凭单一指标下结论。必须交叉验证多项指标（CPU + 内存 + 错误率 + 日志）。
- **区分正常波动与真异常**：流量突增导致的 CPU 升高是正常现象，不应重启。只有确认底层组件出现不可逆故障（死锁、OOM、连接池耗尽）时才执行自愈。
- **渐进式排查**：先查宏观指标（CPU/内存/错误率）→ 定位异常服务 → 查看该服务日志 → 综合判断 → 执行操作。

## 诊断决策路径
当收到告警时，请严格遵循以下步骤：
1. **初步分析**：解析告警内容，确定涉及的服务和指标
2. **数据收集**：调用 execute_promql 获取更多维度的指标（至少检查 CPU + 内存 + 错误率）
3. **深入排查**：如果指标异常，调用 get_service_logs 查看日志确认根因
4. **交叉验证**：对比多个指标和日志，给出根因判断
5. **决策与行动**：
   - 如果确认为死锁/连接池耗尽/内存泄漏等不可逆故障 → 调用 restart_pod
   - 如果是数据库/依赖服务故障 → 调用 set_degrade_mode 触发降级保护
   - 如果是正常流量突增 → 仅输出诊断报告，不执行操作
6. **输出报告**：给出一份包含根因、证据链、置信度、执行操作的结构化报告

## 严禁行为
- ❌ 在未查询任何指标和日志的情况下直接重启服务
- ❌ 仅因为 CPU 暂时升高就重启服务
- ❌ 同时重启多个服务（可能引发连锁故障）
- ❌ 对非白名单中的服务执行操作

## 输出格式
诊断结束后，请用以下 JSON 格式输出报告（方便后续自动化处理）：
```json
{
  "alert_time": "ISO 8601 时间戳",
  "alert_summary": "告警简要描述",
  "root_cause": "根因判断",
  "root_cause_category": "死锁/连接池耗尽/内存泄漏/流量突增/依赖故障/配置错误/未知",
  "confidence": 0.0-1.0,
  "supporting_evidence": ["证据1", "证据2", ...],
  "actions_taken": ["执行的操作"],
  "recommendations": ["后续建议"]
}
```

现在，请开始分析以下告警。记住：诊断质量 > 诊断速度，宁可多调用一次工具确认，也不要盲目下结论。"""


# ============================================================================
# Agent 核心类
# ============================================================================

class AIOpsAgent:
    """
    基于 VeADK 范式的 AIOps 智能运维 Agent。

    核心工作流程（ReAct Loop）：
    1. 接收告警上下文
    2. 调用 LLM 分析 → LLM 决定是否调用工具
    3. 执行工具 → 将结果反馈给 LLM
    4. LLM 综合分析 → 输出诊断报告
    5. 最多循环 max_rounds 次

    Usage:
        agent = AIOpsAgent()
        report = agent.diagnose("frontend 服务 CPU 突增至 85%")
        print(report)
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        """
        初始化 Agent。

        Args:
            config: Agent 配置。如果为 None，使用全局配置。
        """
        self.config = config or get_config()
        self._validate_config()

        # 初始化 OpenAI 兼容客户端
        self.client = OpenAI(
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
        )

        # 加载工具 Schema
        self.tools_schema = get_tool_schemas(self.config)

        # 诊断历史（用于冷却期判断）
        self._diagnosis_history: dict[str, float] = {}

        logger.info(
            "AIOpsAgent 初始化完成: model=%s base_url=%s",
            self.config.llm_model,
            self.config.llm_base_url,
        )

    def _validate_config(self):
        """验证配置完整性"""
        if not self.config.llm_api_key:
            raise ValueError(
                "LLM_API_KEY 未配置。请设置环境变量 VEADK_LLM_API_KEY 或 OPENAI_API_KEY。"
            )
        logger.info(
            "配置验证通过: prometheus=%s gateway=%s",
            self.config.prometheus_url,
            self.config.recovery_gateway_url,
        )

    def _is_in_cooldown(self, alert_fingerprint: str) -> bool:
        """检查告警是否在冷却期内"""
        last_time = self._diagnosis_history.get(alert_fingerprint)
        if last_time is None:
            return False
        elapsed = time.time() - last_time
        return elapsed < self.config.diagnosis_cooldown_seconds

    def _record_diagnosis(self, alert_fingerprint: str):
        """记录诊断时间"""
        self._diagnosis_history[alert_fingerprint] = time.time()
        # 清理过大的历史记录
        if len(self._diagnosis_history) > self.config.dedup_cache_size:
            oldest = sorted(self._diagnosis_history.items(), key=lambda x: x[1])
            self._diagnosis_history = dict(oldest[-self.config.dedup_cache_size // 2 :])

    def diagnose(self, alert_context: str, alert_fingerprint: Optional[str] = None) -> str:
        """
        对告警执行完整诊断流程。

        Args:
            alert_context: 告警上下文描述（将发送给 LLM 进行分析）
            alert_fingerprint: 告警指纹（用于冷却期判断，可选）

        Returns:
            LLM 生成的诊断报告（文本 + JSON）
        """
        # 冷却期检查
        if alert_fingerprint and self._is_in_cooldown(alert_fingerprint):
            remaining = self.config.diagnosis_cooldown_seconds - int(
                time.time() - self._diagnosis_history[alert_fingerprint]
            )
            logger.info("告警 %s 在冷却期内，跳过诊断（剩余 %ds）", alert_fingerprint, remaining)
            return f"[冷却期] 告警 '{alert_fingerprint}' 在 {remaining} 秒前已诊断过，跳过重复诊断。"

        logger.info("=" * 60)
        logger.info("[Agent 唤醒] 接收告警: %s", alert_context[:200])

        # 检索知识库中的历史相似案例
        knowledge_context = ""
        try:
            from .knowledge import get_knowledge_context
            knowledge_context = get_knowledge_context(alert_context)
        except Exception:
            pass

        # 构建消息上下文（注入知识库案例）
        system_content = SYSTEM_PROMPT + knowledge_context
        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"系统出现以下异常，请按照诊断决策路径进行排查：\n\n"
                    f"{alert_context}\n\n"
                    f"当前时间: {datetime.now(timezone.utc).isoformat()}\n"
                    f"目标命名空间: {self.config.k8s_namespace}\n"
                    f"请开始诊断。"
                ),
            },
        ]

        # ReAct 循环
        final_report = ""
        for round_num in range(1, self.config.max_tool_calls_per_diagnosis + 1):
            logger.info("[Agent 思考 - 第 %d/%d 轮]", round_num, self.config.max_tool_calls_per_diagnosis)

            try:
                response = self.client.chat.completions.create(
                    model=self.config.llm_model,
                    messages=messages,
                    tools=self.tools_schema,
                    tool_choice="auto",
                    max_tokens=self.config.llm_max_tokens,
                    temperature=self.config.llm_temperature,
                )
            except Exception as e:
                logger.exception("LLM API 调用失败 (第 %d 轮)", round_num)
                error_report = (
                    f"## Agent 诊断异常\n\n"
                    f"LLM API 调用失败 (第 {round_num} 轮): {e}\n\n"
                    f"告警内容: {alert_context}\n"
                )
                if alert_fingerprint:
                    self._record_diagnosis(alert_fingerprint)
                _save_to_history(alert_context, error_report)
                return error_report

            response_message = response.choices[0].message
            messages.append(response_message)  # 加入记忆

            # 检查是否调用了工具
            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}

                    logger.info(
                        "  工具调用: %s(%s)",
                        function_name,
                        json.dumps(function_args, ensure_ascii=False)[:200],
                    )

                    # 执行工具
                    tool_result = execute_tool(function_name, function_args, self.config)

                    # 将工具执行结果（Observation）反馈给 LLM
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    })

                    logger.info(
                        "  工具结果: %s(...) => %s",
                        function_name,
                        tool_result[:150].replace("\n", " "),
                    )
            else:
                # LLM 没有调用工具 → 诊断完成，输出最终报告
                final_report = response_message.content or ""
                logger.info("[Agent 诊断完成]")
                break
        else:
            # 达到最大循环次数，强制总结
            logger.warning(
                "[Agent] 达到最大工具调用轮数 (%d)，强制要求 LLM 总结",
                self.config.max_tool_calls_per_diagnosis,
            )
            messages.append({
                "role": "user",
                "content": "已达到最大工具调用次数限制。请基于当前收集到的所有信息，输出最终的诊断报告（JSON 格式）。",
            })
            try:
                response = self.client.chat.completions.create(
                    model=self.config.llm_model,
                    messages=messages,
                    max_tokens=self.config.llm_max_tokens,
                    temperature=self.config.llm_temperature,
                )
                final_report = response.choices[0].message.content or ""
            except Exception as e:
                final_report = f"诊断超限后 LLM 总结失败: {e}"

        # 记录诊断时间
        if alert_fingerprint:
            self._record_diagnosis(alert_fingerprint)

        # 输出最终报告
        logger.info("=" * 60)
        logger.info("[Agent 最终诊断报告]")
        for line in final_report.split("\n"):
            logger.info("  %s", line)
        logger.info("=" * 60)

        # 自动保存到 SQLite + 生成 Markdown 报告
        _save_to_history(alert_context, final_report)

        return final_report

    def quick_check(self, query: str) -> str:
        """
        轻量级快速咨询（不使用工具，直接问答）。

        Args:
            query: 问题描述

        Returns:
            LLM 回复
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.config.llm_model,
                messages=messages,
                max_tokens=1024,
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"快速咨询失败: {e}"

    def bulk_diagnose(self, alerts: list[dict]) -> str:
        """
        告警聚合推理：同时分析多条告警，识别共同根因。

        当 Alertmanager 在短时间内触发多条告警时，
        不逐一处理，而是打包发送给 LLM 进行关联分析。

        Args:
            alerts: 告警列表，每个元素含 {alertname, severity, service, summary}

        Returns:
            聚合诊断报告
        """
        if not alerts:
            return "无告警需要分析"

        if len(alerts) == 1:
            a = alerts[0]
            svc = a.get("service", "unknown")
            return self.diagnose(
                f"[{a.get('severity', 'warning')}] {a.get('alertname', 'Alert')}: "
                f"{a.get('summary', '')} (服务: {svc})"
            )

        # 构建聚合告警描述
        alert_lines = ["## 批量告警聚合分析", "", f"共收到 {len(alerts)} 条告警，请进行关联分析，识别共同根因：", ""]
        for i, a in enumerate(alerts, 1):
            alert_lines.append(
                f"{i}. **[{a.get('severity', 'warning').upper()}] {a.get('alertname', 'Alert')}**\n"
                f"   服务: `{a.get('service', 'unknown')}`\n"
                f"   摘要: {a.get('summary', 'N/A')}\n"
                f"   描述: {a.get('description', 'N/A')}"
            )

        alert_lines.append("")
        alert_lines.append("请分析：")
        alert_lines.append("1. 这些告警是否由同一个根因引起？")
        alert_lines.append("2. 如果是，真正的根因是什么？哪条告警是根源，哪些是连锁反应？")
        alert_lines.append("3. 应该优先修复哪个服务？")
        alert_lines.append("4. 是否需要重启操作的组合，还是只需修复根源即可？")

        aggregated_context = "\n".join(alert_lines)
        return self.diagnose(aggregated_context)


# ============================================================================
# 便捷函数
# ============================================================================

_global_agent: Optional[AIOpsAgent] = None


def get_agent(config: Optional[AgentConfig] = None) -> AIOpsAgent:
    """获取全局 Agent 单例"""
    global _global_agent
    if _global_agent is None:
        _global_agent = AIOpsAgent(config)
    return _global_agent


def reset_agent():
    """重置全局 Agent 单例（用于测试）"""
    global _global_agent
    _global_agent = None
