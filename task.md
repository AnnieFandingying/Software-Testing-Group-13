# 成员 F（智能体开发与系统集成）任务执行清单

> **项目**：软件测试与维护（2026年春）大作业 — 加分项二：智能体自动运维  
> **小组**：Group 13  
> **GitHub 仓库**：https://github.com/AnnieFandingying/Software-Testing-Group-13  
> **成员 F 职责**：基于 VeADK 框架开发 AIOps Agent + 项目 PM（GitHub 管理、PDF 排版、PPT 美化）

---

## 一、已完成内容概述（成员 A 和 B 的交付物）

通过克隆并分析 GitHub 仓库 `main` 分支，成员 A 和 B 已完成以下工作：

### 1.1 成员 A（平台与可观测性工程师）已完成：
- ✅ 部署 Online-Boutique 微服务系统（基于 Minikube 集群）
- ✅ 配置 Prometheus + Grafana 监控系统
- ✅ **开发微服务3**：`recovery-gateway`（自愈网关）— 提供 REST API 供 Agent 远程调用执行 Pod 重启/服务降级
  - 路径：`src/recoverygateway/`
  - API 端点：`POST /api/v1/restart`、`POST /api/v1/degrade`、`GET /healthz`、`GET /metrics`
  - 认证：Bearer Token（环境变量 `RECOVERY_AUTH_TOKEN`）
  - K8s 清单：`kubernetes-manifests/recoverygateway.yaml`
- ✅ 编写 K8s Deployment/Service/RBAC YAML 清单

### 1.2 成员 B（微服务开发工程师）已完成：
- ✅ **开发微服务1**：`discount-service`（618 满减折扣服务，gRPC）
  - 路径：`src/discountservice/`
  - 满 200 减 50、满 400 减 100、满 700 减 200
  - 仅对 CNY 币种生效
- ✅ **开发微服务2**：`telemetry-service`（遥测聚合服务，HTTP）
  - 路径：`src/telemetryservice/`
  - 接收事件 `POST /events`，暴露 Prometheus 指标 `GET /metrics`
  - 弱依赖语义：遥测挂掉不影响主链路
- ✅ 修改 `checkoutservice`：集成 discount-service gRPC 调用 + 遥测上报
- ✅ 修改 `frontend`：结算页面金额修正 + 遥测上报
- ✅ 编写 Dockerfile、K8s YAML、Helm Chart
- ✅ 编写 `Ability.md`（功能说明）和 `Check.md`（编译自检清单）

### 1.3 系统架构现状（了解 Agent 的工作环境）：

```
┌─────────────────────────────────────────────────────────────┐
│                    Minikube 集群 (成员A电脑)                    │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Online-Boutique 微服务                     │    │
│  │  frontend → checkoutservice → discountservice (NEW)    │    │
│  │     ↓                         → telemetryservice (NEW) │    │
│  │  cartservice, paymentservice, shippingservice, ...     │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐     │
│  │ Prometheus  │  │   Grafana    │  │ recovery-gateway │     │
│  │ (采集指标)   │  │  (可视化)     │  │  (自愈网关 :8080)  │     │
│  └──────┬──────┘  └──────────────┘  └────────▲─────────┘     │
│         │                                     │               │
│  ┌──────┴─────────────────────────────────────┴──────┐       │
│  │              Alertmanager (告警 Webhook)            │       │
│  └──────────────────────────┬───────────────────────┘       │
└─────────────────────────────┼─────────────────────────────┘
                              │ HTTP POST (告警 JSON)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              成员 F 电脑（Agent 运行环境）                       │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               VeADK Agent (veadk_agent.py)             │    │
│  │                                                        │    │
│  │  ① 接收 Alertmanager Webhook 告警                       │    │
│  │  ② ReAct 推理循环（LLM 分析 → 工具调用 → 综合分析）      │    │
│  │  ③ 工具1：execute_promql → 查询 Prometheus API         │    │
│  │  ④ 工具2：get_service_logs → 获取 K8s Pod 日志         │    │
│  │  ⑤ 工具3：restart_pod → 调用 recovery-gateway 重启服务  │    │
│  │  ⑥ 输出诊断报告 + 执行自愈动作                           │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、详细任务分解（总计约 40 小时）

### 📋 阶段一：环境准备与大模型 API 打通（约 8 小时）

#### 任务 1.1：Python 开发环境准备
- [ ] 确认 Python 3.8+ 已安装（`python --version`）
- [ ] 创建项目虚拟环境：`python -m venv venv`
- [ ] 激活虚拟环境并安装依赖：
  ```bash
  pip install openai requests fastapi uvicorn pyyaml kubernetes
  ```
- [ ] 创建项目目录结构：
  ```
  cs-final-test/
  ├── task.md                          # 本任务清单
  ├── veadk_agent/
  │   ├── __init__.py
  │   ├── agent.py                     # Agent 核心逻辑（ReAct Loop）
  │   ├── tools.py                     # 工具注册与实现
  │   ├── config.py                    # 配置管理（环境变量读取）
  │   ├── webhook_server.py            # Alertmanager Webhook 接收服务
  │   ├── prometheus_client.py         # Prometheus API 查询客户端
  │   └── requirements.txt             # Python 依赖清单
  ├── tests/
  │   ├── test_tools.py                # 工具函数单测
  │   ├── test_agent.py                # Agent 推理链单测
  │   └── test_integration.py          # 端到端集成测试
  ├── config/
  │   └── agent_config.yaml            # Agent 配置文件
  └── docs/
      └── agent_design.md              # Agent 设计文档
  ```

#### 任务 1.2：大模型 API 配置
- [ ] 注册/获取大模型 API Key（推荐使用火山引擎豆包 API 或其他国产大模型）
  - 建议 API：DeepSeek API、通义千问 API、火山引擎豆包 API
  - 参考 VeADK 教程：`https://nankai.feishu.cn/wiki/AuPtwvDlKinPaskYVubcWoLancd`
- [ ] 配置环境变量：
  ```bash
  export OPENAI_API_KEY="sk-xxxxxxxxxxxxx"
  export OPENAI_BASE_URL="https://api.deepseek.com"  # 或其他兼容 OpenAI API 的地址
  ```
- [ ] 编写简单的 API 连通性测试脚本，确认可以正常调用大模型

#### 任务 1.3：克隆仓库并理解现有代码
- [x] 已克隆 GitHub 仓库：`git clone https://github.com/AnnieFandingying/Software-Testing-Group-13.git`
- [x] 已阅读 `Ability.md`（微服务功能说明）
- [x] 已阅读 `Check.md`（编译自检清单）
- [x] 已阅读 `recovery-gateway` 源码（理解 Agent 自愈 API）
- [ ] 与成员 A 确认以下连接信息：
  - Prometheus 地址（Minikube 暴露的 URL）
  - recovery-gateway 的 Service 地址和 Bearer Token
  - Alertmanager Webhook 配置状态
- [ ] 阅读 VeADK 教程原文（飞书文档链接）

---

### 📋 阶段二：Agent 核心逻辑开发（约 15 小时）

#### 任务 2.1：编写 Agent 配置管理模块 (`config.py`)
- [ ] 实现从环境变量读取配置：
  - `PROMETHEUS_URL`：Prometheus 查询地址
  - `RECOVERY_GATEWAY_URL`：recovery-gateway API 地址
  - `RECOVERY_AUTH_TOKEN`：自愈网关认证 Token
  - `LLM_API_KEY`：大模型 API Key
  - `LLM_BASE_URL`：大模型 API 地址
  - `LLM_MODEL`：模型名称（默认 `gpt-4o` 或 `deepseek-chat`）
  - `ALERTMANAGER_WEBHOOK_PORT`：Webhook 监听端口（默认 `5000`）
  - `SOCK_SHOP_NAMESPACE`：K8s 命名空间（默认 `sock-shop`）
- [ ] 支持从 `.env` 文件加载配置

#### 任务 2.2：实现工具函数模块 (`tools.py`)
按照 VeADK 教程中定义的三个核心工具：

**工具 1：`execute_promql(query_str: str) -> str`**
- [ ] 实现 Prometheus HTTP API 查询：
  - 调用 `GET {PROMETHEUS_URL}/api/v1/query?query={query_str}`
  - 支持即时查询（instant query）
  - 解析 JSON 响应并格式化返回
  - 错误处理：超时、连接失败、无数据
- [ ] 预定义常用 PromQL 查询模板（方便 LLM 选择）：
  - CPU 使用率：`sum(rate(container_cpu_usage_seconds_total{namespace="sock-shop"}[5m])) by (pod)`
  - 内存使用率：`sum(container_memory_usage_bytes{namespace="sock-shop"}) by (pod)`
  - 请求错误率：`sum(rate(http_requests_total{status_code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))`
  - 请求延迟 P99：`histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
  - Pod 重启次数：`kube_pod_container_status_restarts_total{namespace="sock-shop"}`
  - 文件系统使用率：`sum(container_fs_usage_bytes{namespace="sock-shop"}) by (pod)`

**工具 2：`get_service_logs(service_name: str, tail_lines: int = 50) -> str`**
- [ ] 实现通过 kubectl 获取 Pod 日志：
  - 使用 `kubectl logs` 命令（通过 subprocess 或 kubernetes Python 客户端）
  - 自动查找服务对应的 Pod 名称
  - 支持 `--tail` 参数限制行数
  - 支持 `--timestamps` 获取时间戳
- [ ] 备选方案：如果 kubectl 不可用，通过 Kubernetes Python 客户端读取
- [ ] 日志格式化输出，方便 LLM 理解

**工具 3：`restart_pod(service_name: str, namespace: str = "sock-shop") -> str`**
- [ ] 调用 recovery-gateway REST API：
  ```python
  POST {RECOVERY_GATEWAY_URL}/api/v1/restart
  Headers:
    Authorization: Bearer {RECOVERY_AUTH_TOKEN}
    Content-Type: application/json
  Body:
    {
      "target": "{service_name}",
      "namespace": "{namespace}",
      "kind": "deployment",
      "reason": "agent_auto_recovery"
    }
  ```
- [ ] 验证 API 响应，确认重启操作是否成功
- [ ] 如果 recovery-gateway 不可用，降级使用 kubectl 命令执行 `kubectl rollout restart deployment/{service_name}`
- [ ] 增加安全检查：仅允许重启白名单中的服务

**工具 4（扩展，加分项）：`set_degrade_mode(service_name: str, mode: str, ttl_seconds: int = 900) -> str`**
- [ ] 调用 recovery-gateway 的 `/api/v1/degrade` 端点
- [ ] 支持将服务设置为 `degraded` 或 `normal` 模式
- [ ] 在诊断出部分服务压力过大时，可自动执行降级

#### 任务 2.3：实现 Agent 核心推理循环 (`agent.py`)
- [ ] 设计 Agent System Prompt（系统人设）：
  ```
  你是一个资深的云原生 AIOps 专家。
  当收到告警时，你不能盲目判断。你需要通过调用工具来收集证据，
  区分这是正常的流量突增，还是底层组件发生了不可见的老化与
  Fail-Slow 劣化（例如死锁、连接池耗尽、慢查询）。
  
  请遵循以下思考路径：
  ① 分析当前告警信息
  ② 决定是否需要更多数据（调用工具获取）
  ③ 交叉分析多项指标和日志
  ④ 得出根因诊断结论 + 给出置信度
  ⑤ 如果确认为可自愈故障，执行恢复操作
  ⑥ 输出结构化诊断报告
  ```
- [ ] 实现 ReAct Loop（推理-行动循环）：
  - 最多允许 5 轮工具调用（防止无限循环）
  - 每轮将用户告警 + 工具返回结果加入 messages 上下文
  - 支持多工具并行调用（当多个查询不互相依赖时）
- [ ] 实现诊断报告结构化输出：
  ```json
  {
    "alert_time": "2026-06-12T14:30:00",
    "alert_summary": "catalogue 服务 CPU 突增至 85%",
    "root_cause": "数据库连接池耗尽，导致请求堆积",
    "confidence": 0.85,
    "supporting_evidence": [
      "PromQL 查询显示 catalogue CPU 持续 >80% 已达 5 分钟",
      "日志中频繁出现 'DB Pool exhausted' 错误",
      "数据库连接数指标显示连接池使用率 100%"
    ],
    "actions_taken": [
      "已通过 recovery-gateway 重启 catalogue 服务",
      "建议检查数据库最大连接数配置"
    ],
    "recovery_result": "catalogue 服务已成功重启，CPU 恢复正常"
  }
  ```

#### 任务 2.4：定义工具 Schema（供 LLM Function Calling 使用）
- [ ] 按照 OpenAI Function Calling 格式定义每个工具：
  ```python
  TOOLS_SCHEMA = [
      {
          "type": "function",
          "function": {
              "name": "execute_promql",
              "description": "执行 PromQL 查询获取 Prometheus 监控指标。常用查询："
                             "1) CPU: sum(rate(container_cpu_usage_seconds_total{namespace='sock-shop'}[5m])) by (pod)"
                             "2) 内存: sum(container_memory_usage_bytes{namespace='sock-shop'}) by (pod)"
                             "3) 错误率: sum(rate(http_requests_total{status_code=~'5..'}[5m])) by (pod)",
              "parameters": {
                  "type": "object",
                  "properties": {
                      "query_str": {
                          "type": "string",
                          "description": "要执行的 PromQL 查询语句"
                      }
                  },
                  "required": ["query_str"]
              }
          }
      },
      {
          "type": "function",
          "function": {
              "name": "get_service_logs",
              "description": "获取指定微服务的最新 Kubernetes Pod 日志",
              "parameters": {
                  "type": "object",
                  "properties": {
                      "service_name": {"type": "string", "description": "服务名称，如 catalogue, frontend"},
                      "tail_lines": {"type": "integer", "description": "返回最后 N 行日志，默认 50"}
                  },
                  "required": ["service_name"]
              }
          }
      },
      {
          "type": "function",
          "function": {
              "name": "restart_pod",
              "description": "当确认服务处于死锁或内存泄漏等无法恢复的僵死状态时，通过 recovery-gateway 重启该服务。仅限白名单中的服务。",
              "parameters": {
                  "type": "object",
                  "properties": {
                      "service_name": {"type": "string", "description": "要重启的服务名称"},
                      "namespace": {"type": "string", "description": "K8s 命名空间，默认 sock-shop"}
                  },
                  "required": ["service_name"]
              }
          }
      }
  ]
  ```
- [ ] 确保工具描述中包含足够的提示信息（示例 PromQL），帮助 LLM 做出正确的工具选择

---

### 📋 阶段三：Webhook 接收与告警触发（约 8 小时）

#### 任务 3.1：实现 Alertmanager Webhook 接收服务 (`webhook_server.py`)
- [ ] 使用 FastAPI/Flask 创建 HTTP 服务器，接收 Alertmanager 发送的告警 JSON
- [ ] 解析 Alertmanager Webhook 格式：
  ```json
  {
    "receiver": "agent-webhook",
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HighCPUUsage",
          "severity": "critical",
          "service": "catalogue",
          "namespace": "sock-shop"
        },
        "annotations": {
          "summary": "catalogue service CPU usage is above 80%",
          "description": "CPU usage has been above 80% for 5 minutes"
        },
        "startsAt": "2026-06-12T14:25:00Z",
        "endsAt": "0001-01-01T00:00:00Z"
      }
    ],
    "groupLabels": {},
    "commonLabels": {},
    "externalURL": "http://prometheus:9093"
  }
  ```
- [ ] 告警去重：同一告警在 firing/resolved 周期内只触发一次 Agent 诊断
- [ ] 告警优先级过滤：根据 severity 标签决定是否触发 Agent
- [ ] 添加 `/healthz` 健康检查端点
- [ ] 添加 `/metrics` 端点，暴露 Agent 自身运行指标（诊断次数、成功率等）

#### 任务 3.2：告警格式化与上下文构建
- [ ] 将 Alertmanager 告警转换为 Agent 可理解的文本描述：
  ```python
  def format_alert_for_agent(alert: dict) -> str:
      return f"""
  [告警名称] {alert['labels']['alertname']}
  [严重程度] {alert['labels']['severity']}
  [涉及服务] {alert['labels'].get('service', 'unknown')}
  [告警摘要] {alert['annotations']['summary']}
  [详细描述] {alert['annotations']['description']}
  [开始时间] {alert['startsAt']}
  [当前状态] {alert['status']}
  """
  ```
- [ ] 支持多告警聚合：将同一时间窗口内的多个相关告警打包发送给 Agent

#### 任务 3.3：轮询模式（备选方案，当 Alertmanager 不可用时）
- [ ] 实现定时巡检函数 `fetch_basic_cpu()`：
  - 每 10 秒查询一次关键服务的 CPU 使用率
  - 超过阈值（如 CPU > 0.5 或 80%）时主动触发 Agent 诊断
- [ ] 参考教程中的 `main()` 函数实现守护进程模式

---

### 📋 阶段四：闭环联调与端到端验证（约 5 小时）

#### 任务 4.1：与成员 A 的系统打通
- [ ] 确认 Prometheus URL 连通性（从 F 电脑可访问 A 电脑的 Prometheus）
- [ ] 确认 recovery-gateway API 连通性（从 F 电脑可调用 A 电脑的 K8s 集群内的 recovery-gateway）
  - 可能需要 Minikube tunnel 或 NodePort 暴露服务
- [ ] 确认 kubectl 可远程操作 A 电脑的 K8s 集群（或通过 recovery-gateway 代理所有操作）
- [ ] 测试工具函数是否正常工作：
  ```bash
  # 测试 PromQL 查询
  curl "http://<A_IP>:<PROMETHEUS_PORT>/api/v1/query?query=up"
  # 测试 recovery-gateway
  curl -X POST "http://<A_IP>:<GATEWAY_PORT>/api/v1/restart" \
    -H "Authorization: Bearer <TOKEN>" \
    -H "Content-Type: application/json" \
    -d '{"target":"frontend","kind":"deployment","reason":"test"}'
  ```

#### 任务 4.2：模拟故障场景测试
- [ ] **场景 1：CPU 飙升触发诊断**
  - 使用 `kubectl exec` 进入某 Pod 执行 `stress --cpu 2`
  - 观察 Agent 是否检测到 CPU 异常
  - 验证 Agent 能否正确分析并给出建议
- [ ] **场景 2：服务 Crash 自动重启**
  - 手动删除一个 Pod（模拟 Crash）
  - 观察 Agent 是否检测到服务不可用
  - 验证 Agent 是否调用 recovery-gateway 执行恢复
- [ ] **场景 3：日志异常检测**
  - 注入数据库连接错误（通过 ChaosMesh 网络分区）
  - 观察 Agent 是否查询日志并识别 `Connection refused` 错误
- [ ] **场景 4：多告警并发**
  - 同时触发多个告警
  - 验证 Agent 能否正确聚合分析
- [ ] 记录每个场景的 Agent 输出日志，作为演示素材

#### 任务 4.3：端到端闭环验证
- [ ] 完整链路测试：ChaosMesh 注入故障 → Prometheus 采集异常 → Alertmanager 触发 Webhook → Agent 唤醒 → 工具查询 → 根因诊断 → 调用 recovery-gateway 自愈 → 验证恢复
- [ ] 记录端到端延迟（从故障注入到 Agent 完成诊断的总时间）
- [ ] 记录自愈成功率（注入 10 次故障，统计成功自愈次数）

---

### 📋 阶段五：文档撰写与项目管理（约 4 小时）

#### 任务 5.1：撰写大作业报告 — Agent 章节
- [ ] 撰写报告章节：**"基于 VeADK 的智能自愈运维 Agent 实现"**（约 5-8 页）
- [ ] 内容大纲：
  1. 智能运维 Agent 背景与意义
  2. Agent 架构设计（附架构图）
  3. 工具注册与实现细节（PromQL 查询、日志抓取、远程重启）
  4. ReAct 推理循环设计（附流程图）
  5. 与 Alertmanager 和 recovery-gateway 的集成方案
  6. 故障场景测试结果（附诊断报告截图）
  7. 自愈效果评估（成功率、响应时间等指标）
  8. 总结与改进方向

#### 任务 5.2：项目管理（PM 职责）
- [ ] GitHub 仓库管理：
  - 创建 `agent` 分支用于 Agent 代码开发
  - 定期 Review 成员提交的 PR（关注代码质量和合并冲突）
  - 合并前确保所有测试通过
  - 维护 `.gitignore` 和 `README.md`
- [ ] 收集各成员撰写的报告章节：
  - 成员 A：集群架构部署与可观测性监控
  - 成员 B：微服务开发（discount-service、telemetry-service）
  - 成员 C：Selenium 功能测试与 JMeter 并发性能测试
  - 成员 D：KPI 异常检测与日志异常分类算法实现
  - 成员 E：Trace 异常定位与根因分类算法、多算法横向对比
  - 成员 F（自己）：智能运维 Agent 实现
- [ ] PDF 报告排版：
  - 统一字体、行距、页眉页脚
  - 添加目录（含页码）
  - 统一图表编号（图 1-1、表 1-1 等）
  - 添加参考文献列表
  - 导出为 PDF
- [ ] 答辩 PPT 制作：
  - 封面（项目名称、组号、成员名单）
  - 项目概述（1 页）
  - 系统架构（1 页）
  - 各成员贡献展示（每人 1-2 页）
  - 测试结果（2-3 页）
  - 算法对比（2-3 页）
  - Agent 演示（2-3 页，含自愈日志截图）
  - 总结与展望（1 页）
  - 总页数控制在 20-25 页

#### 任务 5.3：录制演示视频
- [ ] 与各成员协调录制多机联合演示视频：
  - 屏幕 1：压测屏（JMeter 并发压测界面）
  - 屏幕 2：监控自愈屏（Grafana 仪表盘 + Prometheus 界面）
  - 屏幕 3：Agent 运行屏（Agent 诊断日志 + 自愈动作输出）
- [ ] 视频时长控制在 5-8 分钟
- [ ] 添加字幕说明关键步骤

---

## 三、技术关键点与注意事项

### 3.1 网络连通性
- **核心挑战**：成员 F 的 Agent 运行在本地电脑，需要跨网络访问成员 A 电脑上的 Prometheus 和 recovery-gateway
- **解决方案**：
  1. 如果成员 A 使用 Minikube，通过 `minikube service recovery-gateway --url` 获取可访问的 URL
  2. 如果成员 A 和 F 在同一局域网，直接使用 IP:端口访问
  3. 如果不在同一网络，使用内网穿透工具（如 frp、ngrok）暴露服务

### 3.2 大模型选择建议
- **推荐方案**（按优先级）：
  1. **DeepSeek API**（`deepseek-chat`）：性价比高，支持 Function Calling，中文理解能力强
  2. **通义千问 API**（`qwen-plus`）：阿里云生态，兼容 OpenAI SDK
  3. **火山引擎豆包 API**（`doubao-lite`）：VeADK 教程推荐
- **关键要求**：必须支持 Function Calling / Tool Use 能力

### 3.3 安全注意事项
- [ ] recovery-gateway 的 Bearer Token 不要硬编码在代码中，使用环境变量
- [ ] Agent 不会自动重启未在白名单中的服务
- [ ] Agent 的 API Key 不提交到 Git 仓库（加入 `.gitignore`）
- [ ] 所有外部调用（Prometheus、recovery-gateway）需要超时控制（默认 10 秒）

### 3.4 容错设计
- [ ] Prometheus 不可用时，Agent 应降级为纯日志分析模式
- [ ] recovery-gateway 不可用时，Agent 应降级为仅诊断模式（不执行自愈）
- [ ] LLM API 调用失败时，实现重试机制（最多 3 次，指数退避）
- [ ] Webhook 服务崩溃时，Alertmanager 可自动重试（利用其内置重试机制）

---

## 四、交付物清单

| 序号 | 交付物 | 格式 | 说明 |
|------|--------|------|------|
| 1 | `veadk_agent/` 完整源码 | Python | Agent 核心代码，含 agent.py, tools.py, config.py, webhook_server.py |
| 2 | `requirements.txt` | 文本 | Python 依赖清单 |
| 3 | `agent_config.yaml` | YAML | Agent 配置文件模板 |
| 4 | `docs/agent_design.md` | Markdown | Agent 设计文档（含架构图、流程图） |
| 5 | 诊断日志截图 | PNG | 至少 3 个故障场景的 Agent 诊断输出截图 |
| 6 | 自愈验证日志 | 文本 | 端到端自愈闭环的日志输出 |
| 7 | 报告章节 PDF | PDF | "基于 VeADK 的智能自愈运维 Agent 实现" 章节（5-8 页） |
| 8 | 合并后的完整报告 | PDF | 各组员章节合并排版后的最终报告 |
| 9 | 答辩 PPT | PPTX | 20-25 页展示用幻灯片 |
| 10 | 演示视频 | MP4 | 5-8 分钟多机联合演示 |

---

## 五、时间规划（四周）

```
📅 第一周（6/12 - 6/18）：环境搭建 + Agent 基础框架
├── Day 1-2：阅读文档，克隆仓库，理解现有代码 [已完成]
├── Day 3-4：Python 环境准备，大模型 API 申请与测试
├── Day 5-6：编写 config.py + tools.py（四个工具实现）
└── Day 7：编写 agent.py（ReAct Loop 框架 + System Prompt）

📅 第二周（6/19 - 6/25）：Agent 完善 + Webhook 集成
├── Day 1-3：完善 Agent 推理链 + 工具 Schema 定义
├── Day 4-5：编写 webhook_server.py（Alertmanager 对接）
├── Day 6：编写轮询模式备用方案
└── Day 7：单元测试（pytest）

📅 第三周（6/26 - 7/2）：联调 + 故障测试
├── Day 1-2：与成员 A 打通网络（Prometheus + recovery-gateway）
├── Day 3-4：模拟故障场景测试（4 个场景）
├── Day 5：端到端闭环验证 + 性能记录
└── Day 6-7：修复问题 + 优化 Agent 诊断准确率

📅 第四周（7/3 - 7/9）：文档 + PPT + 演示
├── Day 1-2：撰写报告章节
├── Day 3：收集各成员报告，合并排版 PDF
├── Day 4-5：制作答辩 PPT
├── Day 6：录制演示视频
└── Day 7：最终检查，提交到 GitHub
```

---

## 六、检查点与风险应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 大模型 API 申请延迟 | 高 | 提前申请，准备多个备选 API（DeepSeek + 通义千问 + 豆包） |
| 成员 A 电脑网络不可达 | 高 | 使用内网穿透（frp/ngrok），或让 Agent 也部署到 A 电脑的 Minikube 中 |
| recovery-gateway 尚未就绪 | 中 | Agent 先使用 kubectl 直接操作，后续再切换到 recovery-gateway |
| LLM 诊断准确率低 | 中 | 优化 System Prompt，添加 Few-shot 示例，增加工具描述详细度 |
| 时间不足 | 中 | 优先保证核心 Agent 功能可用，PM 工作（PPT 排版）可简化为模板 |

---

## 七、参考资料

1. **VeADK 智能运维教程**：[使用智能体进行智能运维](https://nankai.feishu.cn/wiki/AuPtwvDlKinPaskYVubcWoLancd)
2. **Online-Boutique 官方仓库**：[GoogleCloudPlatform/microservices-demo](https://github.com/GoogleCloudPlatform/microservices-demo)
3. **小组 GitHub 仓库**：[Software-Testing-Group-13](https://github.com/AnnieFandingying/Software-Testing-Group-13)
4. **Prometheus HTTP API 文档**：[Prometheus Querying API](https://prometheus.io/docs/prometheus/latest/querying/api/)
5. **Alertmanager Webhook 配置**：[Alertmanager Webhook](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
6. **OpenAI Function Calling 文档**：[Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
7. **Kubernetes Python Client**：[kubernetes-client/python](https://github.com/kubernetes-client/python)
8. **ChaosMesh 官方文档**：[Chaos Mesh](https://chaos-mesh.org/docs/)

---

> **最后更新**：2026-06-12  
> **状态**：阶段一进行中 — 已完成文档阅读和仓库分析，下一步进行 Agent 代码开发
