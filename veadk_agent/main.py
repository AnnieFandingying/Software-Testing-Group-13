"""
VeADK AIOps Agent — 主入口
==========================
支持两种运行模式：

1. **Webhook 模式**（推荐）：
   python -m veadk_agent.main --mode webhook
   启动 FastAPI 服务器，接收 Alertmanager Webhook。

2. **轮询模式**（备用，无需 Alertmanager）：
   python -m veadk_agent.main --mode patrol
   定时查询 Prometheus，指标超过阈值时自动触发诊断。

Usage:
    # Webhook 模式（默认）
    python -m veadk_agent.main --mode webhook --port 5000

    # 轮询模式
    python -m veadk_agent.main --mode patrol --interval 10

    # 单次诊断（调试）
    python -m veadk_agent.main --mode once --alert "CPU usage high on frontend"
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

# 确保项目根目录在 Python path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veadk_agent.config import AgentConfig, get_config, load_dotenv_if_exists

# 加载 .env 文件
load_dotenv_if_exists()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("veadk.main")


def run_webhook_mode(config: AgentConfig):
    """Webhook 模式：启动 FastAPI 服务器接收 Alertmanager 告警"""
    import uvicorn

    from veadk_agent.webhook_server import app  # noqa: F811

    logger.info("=" * 60)
    logger.info("VeADK AIOps Agent — Webhook 模式")
    logger.info("=" * 60)
    logger.info("监听地址: %s:%d", config.webhook_host, config.webhook_port)
    logger.info("Prometheus: %s", config.prometheus_url)
    logger.info("Recovery Gateway: %s", config.recovery_gateway_url)
    logger.info("LLM 模型: %s (%s)", config.llm_model, config.llm_base_url)
    logger.info("K8s 命名空间: %s", config.k8s_namespace)
    logger.info("=" * 60)
    logger.info("Alertmanager Webhook URL: http://<host>:%d/alert", config.webhook_port)
    logger.info("健康检查: http://<host>:%d/healthz", config.webhook_port)
    logger.info("手动诊断: POST http://<host>:%d/diagnose", config.webhook_port)
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=config.webhook_host,
        port=config.webhook_port,
        log_level="info",
    )


def run_patrol_mode(config: AgentConfig):
    """轮询模式：定时查询 Prometheus，超过阈值时触发 Agent 诊断"""
    from veadk_agent.agent import AIOpsAgent
    from veadk_agent.tools import execute_promql

    logger.info("=" * 60)
    logger.info("VeADK AIOps Agent — 轮询模式")
    logger.info("巡检间隔: %ds", config.patrol_interval_seconds)
    logger.info("CPU 告警阈值: %.2f", config.cpu_alert_threshold)
    logger.info("Prometheus: %s", config.prometheus_url)
    logger.info("LLM 模型: %s (%s)", config.llm_model, config.llm_base_url)
    logger.info("=" * 60)

    agent = AIOpsAgent(config)
    namespace = config.k8s_namespace

    # 预定义的巡检 PromQL
    cpu_query = (
        f'sum(rate(container_cpu_usage_seconds_total'
        f'{{namespace="{namespace}"}}[5m])) by (pod)'
    )
    memory_query = (
        f'sum(container_memory_usage_bytes'
        f'{{namespace="{namespace}"}}) by (pod) / 1024 / 1024'
    )

    logger.info("智能监控守护进程已启动...")

    while True:
        try:
            # 查询 CPU
            cpu_result = execute_promql(cpu_query, config)
            # 查询内存
            mem_result = execute_promql(memory_query, config)

            timestamp = datetime.now().strftime("%H:%M:%S")
            cpu_summary = cpu_result[:120].replace("\n", " | ")
            mem_summary = mem_result[:120].replace("\n", " | ")
            logger.info("[%s] 日常巡检 | CPU: %s", timestamp, cpu_summary)
            logger.info("[%s] 日常巡检 | MEM: %s", timestamp, mem_summary)

            # 检查是否超过阈值（简化版：检查结果中是否有异常值）
            # 这里用文本匹配方式检查；更严谨的做法是解析 Prometheus 返回值
            alert_triggered = False

            # 解析 CPU 值
            for line in cpu_result.split("\n"):
                if "=>" in line:
                    try:
                        value_str = line.rsplit("=>", 1)[-1].strip()
                        cpu_value = float(value_str)
                        if cpu_value > config.cpu_alert_threshold:
                            pod_name = line.split("{")[0].strip() if "{" in line else "unknown"
                            alert_context = (
                                f"[自动巡检告警] Pod '{pod_name}' CPU 使用率 {cpu_value:.4f} "
                                f"超过阈值 {config.cpu_alert_threshold}。\n\n"
                                f"CPU 查询结果:\n{cpu_result}\n\n"
                                f"内存查询结果:\n{mem_result}"
                            )
                            logger.warning("⚠ 触发告警: %s CPU=%.4f", pod_name, cpu_value)
                            agent.diagnose(alert_context, alert_fingerprint=f"patrol-cpu-{pod_name}")
                            alert_triggered = True
                            break
                    except (ValueError, IndexError):
                        pass

            if alert_triggered:
                time.sleep(config.diagnosis_cooldown_seconds)
            else:
                time.sleep(config.patrol_interval_seconds)

        except KeyboardInterrupt:
            logger.info("收到退出信号，Agent 守护进程停止。")
            break
        except Exception as e:
            logger.exception("巡检循环异常")
            time.sleep(config.patrol_interval_seconds)


def run_once_mode(alert_context: str, config: AgentConfig):
    """单次诊断模式（调试用）"""
    from veadk_agent.agent import AIOpsAgent

    logger.info("=" * 60)
    logger.info("VeADK AIOps Agent — 单次诊断模式")
    logger.info("告警内容: %s", alert_context[:200])
    logger.info("=" * 60)

    agent = AIOpsAgent(config)
    report = agent.diagnose(alert_context)

    print("\n" + "=" * 60)
    print("[Agent 最终诊断报告]")
    print("=" * 60)
    print(report)
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="VeADK AIOps Agent - 智能运维 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["webhook", "patrol", "once"],
        default="webhook",
        help="运行模式: webhook(接收告警), patrol(主动巡检), once(单次诊断)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Webhook 模式监听端口（默认 5000）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="轮询模式巡检间隔（秒，默认 10）",
    )
    parser.add_argument(
        "--alert",
        type=str,
        default="",
        help="单次诊断模式的告警描述",
    )

    args = parser.parse_args()

    # 获取配置
    config = get_config()

    # 命令行参数覆盖
    if args.port is not None:
        config.webhook_port = args.port
    if args.interval is not None:
        config.patrol_interval_seconds = args.interval

    # 运行对应模式
    if args.mode == "webhook":
        run_webhook_mode(config)
    elif args.mode == "patrol":
        run_patrol_mode(config)
    elif args.mode == "once":
        run_once_mode(args.alert, config)


if __name__ == "__main__":
    main()
