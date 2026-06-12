"""
工具函数单元测试
===============
测试四个核心工具的功能正确性。
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veadk_agent.config import AgentConfig
from veadk_agent.tools import (
    AVAILABLE_TOOLS,
    PROMQL_TEMPLATES,
    execute_promql,
    execute_tool,
    get_service_logs,
    get_tool_schemas,
    restart_pod,
    set_degrade_mode,
)


@pytest.fixture
def test_config():
    """创建测试用配置"""
    return AgentConfig()


class TestPromQLTemplates:
    """PromQL 模板测试"""

    def test_all_templates_have_description(self):
        """所有模板都有描述"""
        for name, info in PROMQL_TEMPLATES.items():
            assert "description" in info, f"模板 {name} 缺少 description"
            assert "query" in info, f"模板 {name} 缺少 query"

    def test_templates_contain_namespace(self):
        """模板中包含 namespace 占位符（自定义指标除外）"""
        boutique_custom = {"boutique_requests", "boutique_errors", "boutique_discount_hits"}
        for name, info in PROMQL_TEMPLATES.items():
            if name in boutique_custom:
                continue  # 自定义指标不需要 namespace 过滤
            assert "{namespace}" in info["query"], f"模板 {name} 缺少 namespace 占位符"


class TestExecutePromQL:
    """PromQL 查询工具测试"""

    @patch("veadk_agent.tools.requests.get")
    def test_successful_query(self, mock_get, test_config):
        """正常查询返回格式化结果"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"pod": "frontend-abc123"},
                        "value": [1700000000, "0.45"],
                    }
                ],
            },
        }
        mock_get.return_value = mock_response

        result = execute_promql("up", test_config)
        assert "查询成功" in result
        assert "frontend-abc123" in result
        assert "0.45" in result

    @patch("veadk_agent.tools.requests.get")
    def test_empty_result(self, mock_get, test_config):
        """空结果"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"resultType": "vector", "result": []},
        }
        mock_get.return_value = mock_response

        result = execute_promql("nonexistent_metric", test_config)
        assert "查询结果为空" in result

    @patch("veadk_agent.tools.requests.get")
    def test_connection_error(self, mock_get, test_config):
        """连接失败"""
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("拒绝连接")

        result = execute_promql("up", test_config)
        assert "无法连接到 Prometheus" in result

    @patch("veadk_agent.tools.requests.get")
    def test_timeout(self, mock_get, test_config):
        """查询超时"""
        mock_get.side_effect = __import__("requests").exceptions.Timeout()

        result = execute_promql("up", test_config)
        assert "超时" in result


class TestGetServiceLogs:
    """日志获取工具测试"""

    @patch("veadk_agent.tools.subprocess.run")
    def test_successful_logs(self, mock_run, test_config):
        """正常获取日志"""
        # 第一次调用：查找 Pod
        mock_find = MagicMock()
        mock_find.returncode = 0
        mock_find.stdout = "frontend-abc123"

        # 第二次调用：获取日志
        mock_logs = MagicMock()
        mock_logs.returncode = 0
        mock_logs.stdout = "2026-06-12T10:00:00Z INFO Request processed"

        mock_run.side_effect = [mock_find, mock_logs]

        result = get_service_logs("frontend", tail_lines=20, config=test_config)
        assert "frontend" in result
        assert "Request processed" in result

    @patch("veadk_agent.tools.subprocess.run")
    def test_service_not_found(self, mock_run, test_config):
        """服务不存在"""
        mock_find = MagicMock()
        mock_find.returncode = 1
        mock_find.stdout = ""

        # 第二次：列出所有 Pod
        mock_list = MagicMock()
        mock_list.returncode = 0
        mock_list.stdout = "frontend-abc123   1/1   Running"

        mock_run.side_effect = [mock_find, mock_list]

        result = get_service_logs("nonexistent", config=test_config)
        assert "未找到服务" in result


class TestRestartPod:
    """重启工具测试"""

    def test_not_in_whitelist(self, test_config):
        """非白名单服务被拒绝"""
        result = restart_pod("malicious-service", config=test_config)
        assert "白名单" in result
        assert "malicious-service" in result

    @patch("veadk_agent.tools.requests.post")
    def test_successful_restart_via_gateway(self, mock_post, test_config):
        """通过 recovery-gateway 成功重启"""
        test_config.recovery_auth_token = "test-token-123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "action": "restart",
            "message": "deployment frontend rollout restart requested",
            "details": {"annotation": "2026-06-12T10:00:00Z"},
        }
        mock_post.return_value = mock_response

        result = restart_pod("frontend", reason="test", config=test_config)
        assert "✅" in result
        assert "frontend" in result

    @patch("veadk_agent.tools.subprocess.run")
    def test_restart_fallback_to_kubectl(self, mock_run, test_config):
        """recovery-gateway 不可用时降级到 kubectl"""
        # 降级路径：check deployment 是否存在
        mock_check = MagicMock()
        mock_check.returncode = 0

        # 执行重启
        mock_restart = MagicMock()
        mock_restart.returncode = 0

        mock_run.side_effect = [mock_check, mock_restart]

        result = restart_pod("frontend", reason="gateway_down", config=test_config)
        assert "kubectl" in result.lower()


class TestSetDegradeMode:
    """降级模式工具测试"""

    def test_invalid_mode(self, test_config):
        """无效的降级模式"""
        result = set_degrade_mode("frontend", mode="invalid", config=test_config)
        assert "无效的降级模式" in result

    @patch("veadk_agent.tools.requests.post")
    def test_successful_degrade(self, mock_post, test_config):
        """成功设置降级"""
        test_config.recovery_auth_token = "test-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "message": "set frontend degrade mode to degraded",
            "changed": True,
        }
        mock_post.return_value = mock_response

        result = set_degrade_mode("frontend", mode="degraded", config=test_config)
        assert "✅" in result


class TestGetToolSchemas:
    """工具 Schema 测试"""

    def test_all_tools_have_schemas(self):
        """所有注册的工具都有 Schema"""
        schemas = get_tool_schemas()
        schema_names = [s["function"]["name"] for s in schemas]
        for tool_name in AVAILABLE_TOOLS:
            assert tool_name in schema_names, f"工具 {tool_name} 缺少 Schema"

    def test_schema_format(self):
        """Schema 符合 OpenAI Function Calling 格式"""
        schemas = get_tool_schemas()
        for schema in schemas:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]


class TestExecuteTool:
    """工具调度器测试"""

    def test_execute_known_tool(self, test_config):
        """执行已知工具"""
        with patch.dict("veadk_agent.tools.AVAILABLE_TOOLS", {"execute_promql": lambda **kw: "mocked result"}):
            result = execute_tool("execute_promql", {"query_str": "up"}, test_config)
            assert result == "mocked result"

    def test_execute_unknown_tool(self, test_config):
        """执行未知工具抛出异常"""
        with pytest.raises(ValueError, match="未知工具"):
            execute_tool("hack_the_planet", {}, test_config)
