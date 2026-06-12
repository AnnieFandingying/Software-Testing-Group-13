"""
Agent 核心逻辑单元测试
=====================
测试 AIOpsAgent 的初始化、ReAct 循环、诊断流程。
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veadk_agent.agent import AIOpsAgent, SYSTEM_PROMPT, get_agent, reset_agent
from veadk_agent.config import AgentConfig


@pytest.fixture
def test_config():
    """创建测试用配置"""
    return AgentConfig()
    # 注意：实际 API Key 通过环境变量注入，测试中 mock LLM 调用


@pytest.fixture
def mock_llm_client():
    """Mock OpenAI 客户端"""
    with patch("veadk_agent.agent.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        yield mock_client


class TestAgentInit:
    """Agent 初始化测试"""

    def test_config_validation_no_api_key(self):
        """无 API Key 时抛出错误"""
        config = AgentConfig()
        config.llm_api_key = ""
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            AIOpsAgent(config)

    @patch("veadk_agent.agent.OpenAI")
    def test_successful_init(self, mock_openai, test_config):
        """正常初始化"""
        test_config.llm_api_key = "test-key-123"
        agent = AIOpsAgent(test_config)
        assert agent.config == test_config
        assert len(agent.tools_schema) == 4


class TestSystemPrompt:
    """System Prompt 测试"""

    def test_prompt_contains_key_sections(self):
        """System Prompt 包含关键部分"""
        assert "AIOps" in SYSTEM_PROMPT
        assert "execute_promql" in SYSTEM_PROMPT
        assert "get_service_logs" in SYSTEM_PROMPT
        assert "restart_pod" in SYSTEM_PROMPT
        assert "set_degrade_mode" in SYSTEM_PROMPT
        assert "严禁" in SYSTEM_PROMPT  # 禁止行为
        assert "JSON" in SYSTEM_PROMPT  # 要求结构化输出


class TestDiagnose:
    """诊断流程测试"""

    @patch("veadk_agent.agent.OpenAI")
    def test_simple_diagnosis(self, mock_openai, test_config):
        """简单诊断流程"""
        test_config.llm_api_key = "test-key"

        # Mock LLM 响应：第一轮不调用工具，直接返回报告
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = "## 诊断报告\n根因：CPU正常波动\n置信度：0.95"
        mock_message.tool_calls = None  # 无工具调用

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create.return_value = mock_response

        agent = AIOpsAgent(test_config)
        report = agent.diagnose("frontend CPU 突增至 85%")

        assert "诊断报告" in report
        assert "CPU" in report

    @patch("veadk_agent.agent.OpenAI")
    def test_diagnosis_with_tool_call(self, mock_openai, test_config):
        """包含工具调用的诊断流程"""
        test_config.llm_api_key = "test-key"

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # 第一轮：LLM 决定调用工具
        tool_call_msg = MagicMock()
        tool_call = MagicMock()
        tool_call.id = "call_001"
        tool_call.function.name = "execute_promql"
        tool_call.function.arguments = '{"query_str": "up"}'
        tool_call_msg.tool_calls = [tool_call]
        tool_call_msg.content = None

        # 第二轮：LLM 输出报告
        final_msg = MagicMock()
        final_msg.content = "## 诊断报告\n根因：服务正常运行\n置信度：1.0"
        final_msg.tool_calls = None

        mock_choice_1 = MagicMock()
        mock_choice_1.message = tool_call_msg
        mock_choice_2 = MagicMock()
        mock_choice_2.message = final_msg

        mock_client.chat.completions.create.side_effect = [
            MagicMock(choices=[mock_choice_1]),
            MagicMock(choices=[mock_choice_2]),
        ]

        with patch("veadk_agent.agent.execute_tool") as mock_execute:
            mock_execute.return_value = "查询成功: up => 1"

            agent = AIOpsAgent(test_config)
            report = agent.diagnose("检查服务状态")

            assert "诊断报告" in report
            mock_execute.assert_called_once()

    def test_cooldown_respected(self, test_config):
        """冷却期检查"""
        test_config.llm_api_key = "test-key"
        test_config.diagnosis_cooldown_seconds = 60

        with patch("veadk_agent.agent.OpenAI"):
            agent = AIOpsAgent(test_config)
            # 第一次诊断
            agent._record_diagnosis("alert-001")

            # 立即再次诊断同一告警 → 应被冷却
            report = agent.diagnose("test alert", alert_fingerprint="alert-001")
            assert "冷却期" in report


class TestGetAgent:
    """Agent 单例测试"""

    def teardown_method(self):
        reset_agent()

    def test_singleton(self, test_config):
        """测试 Agent 单例模式"""
        test_config.llm_api_key = "test-key"
        with patch("veadk_agent.agent.OpenAI"):
            agent1 = get_agent(test_config)
            agent2 = get_agent(test_config)
            assert agent1 is agent2

    def test_reset(self, test_config):
        """测试重置 Agent"""
        test_config.llm_api_key = "test-key"
        with patch("veadk_agent.agent.OpenAI"):
            agent1 = get_agent(test_config)
            reset_agent()
            agent2 = get_agent(test_config)
            assert agent1 is not agent2
