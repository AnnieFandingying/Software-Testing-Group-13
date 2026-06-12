# VeADK AIOps Agent 设计文档

> **成员 F — 智能体开发与系统集成**  
> **Software Testing Group 13**

---

## 1. 概述

### 1.1 背景

在微服务系统中，传统运维依赖人工查看监控面板、分析日志、手动执行恢复操作。这种方式响应慢、依赖专家经验、无法 7×24 值守。

本 Agent 基于 **VeADK (Volcengine Agent Development Kit)** 范式，利用大语言模型 (LLM) 的推理能力，实现：

- **自主监控**：定时查询 Prometheus 指标，或在 Alertmanager 触发告警时被唤醒
- **智能诊断**：通过 ReAct 推理循环，交叉分析多项指标和日志，定位根因
- **自动恢复**：通过 recovery-gateway API 远程执行 Pod 重启、服务降级等自愈操作
- **自然语言报告**：每次诊断输出结构化报告，便于事后审计

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **证据驱动** | 不凭单一指标下结论，必须交叉验证多项数据 |
| **安全第一** | 自愈操作限制在白名单内，诊断-操作分离 |
| **弱依赖** | Agent 自身的故障不影响微服务主链路 |
| **可观测** | Agent 暴露自身运行指标，可被 Prometheus 抓取 |
| **渐进式** | 先查宏观指标 → 定位异常服务 → 深入日志 → 执行操作 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                    Alertmanager (成员A)                        │
│                    发送告警 Webhook                             │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP POST /alert
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                  Webhook Server (FastAPI)                      │
│  - 接收告警 JSON                                              │
│  - 告警去重 & 冷却期管理                                       │
│  - 格式化告警为 Agent 可读文本                                  │
└──────────────────────────┬───────────────────────────────────┘
                           │ 触发诊断
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     AIOpsAgent (ReAct Loop)                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ 1. LLM 分析告警 + 历史上下文                          │     │
│  │ 2. LLM 决定是否调用工具                              │     │
│  │ 3. 执行工具 (PromQL / Logs / Restart)                │     │
│  │ 4. 工具结果反馈给 LLM                                │     │
│  │ 5. 重复 1-4 直到 LLM 输出最终诊断报告                │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────┬──────────┬──────────┬──────────────────────┘
                   │          │          │
          ┌────────▼──┐ ┌────▼───┐ ┌───▼────────────┐
          │ Prometheus │ │kubectl │ │recovery-gateway│
          │  (查询指标) │ │(读日志) │ │  (重启/降级)    │
          └────────────┘ └────────┘ └────────────────┘
```

### 2.2 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| `config` | `config.py` | 从环境变量读取所有配置，提供全局配置单例 |
| `tools` | `tools.py` | 四个工具的实现 + Function Calling Schema 生成 |
| `agent` | `agent.py` | ReAct Loop 实现、System Prompt、LLM 交互 |
| `webhook_server` | `webhook_server.py` | FastAPI 服务器，接收 Alertmanager Webhook |
| `main` | `main.py` | 主入口，支持 webhook/patrol/once 三种模式 |

---

## 3. ReAct 推理循环

### 3.1 循环流程

```
输入: 告警上下文 alert_context
  │
  ▼
初始化 messages = [System Prompt, User(告警)]
  │
  ▼
┌──────────────────────────────────┐
│ 第 N 轮 (最多 5 轮)              │
│                                  │
│ 1. LLM(messages) → response     │
│ 2. messages.append(response)     │
│ 3. if response.tool_calls:       │
│      for each tool_call:         │
│        result = execute_tool()   │
│        messages.append(result)   │
│      goto 下一轮                  │
│    else:                         │
│      输出最终报告 → 结束           │
└──────────────────────────────────┘
```

### 3.2 System Prompt 设计

System Prompt 包含以下要素：

1. **角色定义**：资深的云原生 AIOps 专家
2. **能力说明**：四个工具的用途和使用场景
3. **运维哲学**：证据驱动、区分正常波动与真异常、渐进式排查
4. **决策路径**：6 步结构化诊断流程
5. **禁止行为**：明确列出不可执行的操作
6. **输出格式**：要求输出 JSON 结构化报告

### 3.3 工具选择策略

LLM 根据告警类型自主选择工具组合：

| 告警类型 | 典型工具调用序列 |
|----------|----------------|
| CPU 突增 | execute_promql(CPU) → execute_promql(Error Rate) → get_service_logs |
| 内存泄漏 | execute_promql(Memory) → get_service_logs → restart_pod |
| 5xx 错误率 | execute_promql(Error Rate) → get_service_logs → set_degrade_mode |
| Pod Crash | execute_promql(Pod Restarts) → get_service_logs → restart_pod |

---

## 4. 工具实现

### 4.1 execute_promql

- **输入**：PromQL 查询字符串
- **实现**：HTTP GET `{PROMETHEUS_URL}/api/v1/query?query={query_str}`
- **输出**：格式化的指标值列表
- **模板**：内置 12 个常用 PromQL 模板（CPU、内存、错误率、QPS 等）

### 4.2 get_service_logs

- **输入**：service_name, tail_lines
- **实现**：`kubectl logs deployment/{service_name} -n {namespace} --tail={tail_lines}`
- **备选**：通过 label 查找 Pod → 直接读 Pod 日志
- **输出**：带时间戳的容器日志

### 4.3 restart_pod

- **输入**：service_name, reason
- **实现**（优先级）：
  1. 通过 recovery-gateway REST API
  2. 降级到 `kubectl rollout restart`
- **安全**：仅操作白名单中的服务
- **输出**：操作结果（成功/失败 + 详情）

### 4.4 set_degrade_mode

- **输入**：service_name, mode, ttl_seconds
- **实现**：调用 recovery-gateway 的 `/api/v1/degrade` 端点
- **模式**：`degraded`（降级）/ `normal`（恢复）
- **输出**：操作结果

---

## 5. 运行模式

### 5.1 Webhook 模式（推荐）

```bash
python -m veadk_agent.main --mode webhook --port 5000
```

- 启动 FastAPI 服务器
- Alertmanager 配置 webhook URL: `http://<agent_host>:5000/alert`
- 收到告警后自动触发 Agent 诊断

### 5.2 轮询模式（备用）

```bash
python -m veadk_agent.main --mode patrol --interval 10
```

- 每 N 秒查询一次 Prometheus CPU 指标
- 超过阈值时触发 Agent 诊断
- 不依赖 Alertmanager

### 5.3 单次诊断模式（调试）

```bash
python -m veadk_agent.main --mode once --alert "frontend CPU 突增至 85%"
```

---

## 6. 故障场景覆盖

### 6.1 CPU 飙升

1. Agent 收到 CPU 告警
2. 查询 CPU 变化趋势 + 错误率 + QPS
3. 如果 QPS 也同步升高 → 正常流量突增，不操作
4. 如果 QPS 不变但 CPU 高 → 查日志定位死循环/GC 问题
5. 确认是代码级故障 → 重启服务

### 6.2 服务 Crash

1. 检测到 Pod 重启次数增加
2. 查询最近日志中的错误信息
3. 如果是 OOM → 重启服务 + 建议增加内存限制
4. 如果是 Panic → 重启服务 + 标记 degraded

### 6.3 依赖故障

1. checkoutservice 出现大量 Connection Refused
2. 检查下游服务（discountservice/cartservice）状态
3. 如果下游服务故障 → 调用 set_degrade_mode 触发降级
4. 等待下游服务恢复后恢复 normal 模式

---

## 7. 容错设计

| 组件 | 故障类型 | 降级策略 |
|------|---------|---------|
| LLM API | 超时/限流/不可用 | 重试 3 次（指数退避），失败后返回错误状态 |
| Prometheus | 不可达 | 跳过指标查询，仅依赖日志分析 |
| recovery-gateway | 不可达 | 降级到 kubectl 命令 |
| kubectl | 未安装 | 仅输出诊断报告，不执行自愈操作 |
| Webhook Server | 崩溃 | Alertmanager 自动重试 |

---

## 8. 安全设计

1. **Token 认证**：recovery-gateway 使用 Bearer Token 认证 Agent 请求
2. **白名单**：只有 `allowed_services` 中的服务可被重启或降级
3. **冷却期**：同一告警 60 秒内不会重复触发诊断
4. **环境变量**：所有敏感信息（API Key、Token）通过环境变量注入，不硬编码
5. **操作审计**：所有自愈操作记录在 Deployment annotation 中

---

## 9. 集成点

### 9.1 Alertmanager → Agent

Alertmanager 配置示例：

```yaml
receivers:
  - name: 'veadk-agent-webhook'
    webhook_configs:
      - url: 'http://<agent_host>:5000/alert'
        send_resolved: false
```

### 9.2 Agent → Prometheus

直接 HTTP GET 查询 Prometheus HTTP API。

### 9.3 Agent → recovery-gateway

```
POST http://<gateway_host>:8080/api/v1/restart
Authorization: Bearer <token>
Content-Type: application/json

{
  "target": "frontend",
  "namespace": "sock-shop",
  "kind": "deployment",
  "reason": "agent_auto_recovery"
}
```

---

> **文档版本**：1.0  
> **最后更新**：2026-06-12
