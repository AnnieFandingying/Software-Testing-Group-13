<p align="center">
  <img src="/docs/img/architecture-diagram.png" width="650" alt="Architecture" />
</p>

# 融合异常检测算法的微服务智能运维平台

**Software Testing Group 13 — 软件测试与维护（2026年春）大作业**

> **评分等级：第三档（微服务开发）+ 加分点一（多算法复现对比）+ 加分点二（智能体自动运维）**

---

## 项目简介

本项目基于 **Online-Boutique** 微服务示范系统，围绕微服务部署、自动化测试、性能监控与智能运维展开。在原有 11 个微服务基础上，新增 **3 个自研微服务**，复现 **4 篇异常检测与故障诊断论文算法**，并开发了基于大语言模型的 **AIOps 智能运维 Agent**，打通"告警触发→迭代分析→自愈执行"全闭环。

---

## 基础系统：Online-Boutique

Online-Boutique 是一款云优先的微服务演示应用程序，由 Google Cloud 开源。用户可以在其中浏览商品、将其添加到购物车并购买。Google 使用此应用程序来演示如何使用 GKE、gRPC、Cloud Service Mesh、Cloud Operations 等云产品对企业应用进行现代化改造。此应用程序适用于任何 Kubernetes 集群。

### 原有微服务（11个）

| 服务 | 语言 | 描述 |
|------|------|------|
| [frontend](/src/frontend) | Go | 用户无需注册/登录，自动生成会话 ID |
| [cartservice](/src/cartservice) | C# | 购物车，数据存储在 Redis |
| [productcatalogservice](/src/productcatalogservice) | Go | 商品列表、搜索和详情 |
| [currencyservice](/src/currencyservice) | Node.js | 货币转换（使用欧洲央行实际汇率） |
| [paymentservice](/src/paymentservice) | Node.js | 信用卡模拟支付 |
| [shippingservice](/src/shippingservice) | Go | 运费估算和模拟发货 |
| [emailservice](/src/emailservice) | Python | 订单确认邮件（模拟） |
| [checkoutservice](/src/checkoutservice) | Go | 订单结算编排（**已被本组改造**） |
| [recommendationservice](/src/recommendationservice) | Python | 商品推荐 |
| [adservice](/src/adservice) | Java | 文字广告 |
| [loadgenerator](/src/loadgenerator) | Python/Locust | 模拟用户流量生成 |

---

## 自研微服务（本组新增，第三档核心）

| 微服务 | 开发者 | 技术栈 | 功能 |
|--------|--------|--------|------|
| **DiscountService** | Group 13 | Go + gRPC | 梯度满减折扣引擎（满200减20/满400减50/满700减100），后端唯一可信折扣数据源 |
| **TelemetryService** | Group 13 | Python + FastAPI | 全链路指标统一采集中枢，通用事件指标 + 折扣专项指标，异步非阻塞上报 |
| **Recovery-Gateway** | Group 13 | Python + FastAPI | 自愈网关微服务，K8s 操作 REST API（Pod 重启/服务降级），Token 鉴权 |

---

## 系统架构

```
用户 (Browser)
  │
  ▼
frontend ──────────────────────────────────────────────────┐
  │                                                         │
  ├─► productcatalogservice ─► 商品数据                      │
  ├─► currencyservice       ─► 货币转换                      │
  ├─► cartservice           ─► Redis 购物车                  │
  ├─► recommendationservice ─► 推荐                          │
  ├─► adservice             ─► 广告                          │
  │                                                         │
  └─► checkoutservice ──────┬─► paymentservice  ─► 支付      │
                             ├─► shippingservice  ─► 物流    │
                             ├─► emailservice     ─► 邮件    │
                             ├─► DiscountService  ─► 折扣 ★  │
                             └─► TelemetryService ─► 指标 ★  │
                                                         │
监控与智能运维层:                                            │
  Prometheus ─► Grafana ─► Alertmanager ─► Jaeger           │
       │                          │                          │
       └────────── VeADK Agent ◄──┘                         │
                       │                                     │
                       └──► Recovery-Gateway ─► K8s 自愈 ★  │
                       └──► 飞书通知                         │
                       └──► Web 仪表盘                       │
```

---

## 可观测性建设

### 监控栈
- **Prometheus v2.26**：指标采集与告警规则（PodDown、HighRestartRate、HighCPU、HighMemory）
- **Grafana 7.5.5**：集群资源概览 + Pod 级别指标可视化面板
- **Alertmanager**：Webhook 推送告警至 VeADK Agent
- **Jaeger + OpenTelemetry**：分布式调用链追踪

### ChaosMesh 故障注入实验

| 场景 | 故障类型 | 目标服务 | 参数 | 影响 |
|------|----------|----------|------|------|
| 1 | CPU 压力 | frontend | 85%, 2 workers, 2min | 页面响应变慢 |
| 2 | Pod Kill | checkoutservice | 随机 1 个 Pod | 服务中断（K8s ~10s 自愈） |
| 3 | Pod Failure | productcatalogservice | 2min 持续崩溃 | RESTARTS 持续增长 |
| 4 | 网络丢包 | telemetryservice | 50%, Egress | 弱依赖隔离验证（主链路正常） |
| 5 | 网络延迟 | checkout→discount | 800ms, jitter 120ms | 结算延迟 ~10x（100ms→984ms） |

---

## 算法复现（加分项一）

| 算法 | 数据模态 | 任务 | 核心指标 |
|------|----------|------|----------|
| **DADA** | KPI 时序指标 | 异常检测（自适应性瓶颈+双对抗解码器） | Zero-shot 推理，345 测试点 |
| **LLMeLog** | 日志事件 | 异常检测（LLM 增强日志事件 + BERT + Transformer） | 84,709 条日志，360 模板 |
| **TraceDAE** | 分布式 Trace | 异常检测 + 服务级根因定位（GAT+LSTM 双自编码器） | Precision 0.893，F1 0.695 |
| **BARO** | 多维指标 | 异常检测 + 指标级根因定位（多变量贝叶斯变点检测） | F1 0.82（25 案例） |

---

## AIOps 智能运维 Agent（加分项二）

基于 VeADK 框架与 DeepSeek V4 Pro 大语言模型，实现自主异常检测、根因诊断与自动恢复。

### 核心能力
- **ReAct 推理循环**：LLM 自主决策调用工具，最多 5 轮渐进式排查
- **四大运维工具**：PromQL 查询、K8s 日志读取、Pod 重启、服务降级
- **告警聚合**：30 条告警 → 5 条核心 → 1 个根因服务
- **根因知识库**（简化版 RAG）：SQLite 存储，历史案例检索，诊断准确率持续提升（30%→59%）
- **飞书实时通知**：Interactive Card 诊断卡片推送
- **Web 仪表盘**：5 页暗色主题（诊断历史、统计分析、集群健康评分）
- **Markdown 报告自动生成**：21 份诊断报告

### 运行统计
- 累计 **63 次**诊断，自愈率 **59%**
- 诊断耗时约 **45 秒**（vs 人工 30 分钟，效率提升 40 倍）
- 覆盖 CrashLoopBackOff、配置错误、依赖故障、流量突增（混沌实验）等故障类型
- 25 个 pytest 单元测试全部通过

---

## 自动化测试

### Selenium 功能测试
- 模拟用户完整结账流程（首页→币种设置→商品加购→购物车→结账）
- USD 单用户场景 7 样本全部成功，完整事务耗时 8.011s
- 多浏览器兼容性验证

### JMeter 性能压测
- 10 并发线程，120s 递增，持续 1800s
- 覆盖注入前、故障期间全流程
- 统计 TPS、错误率、平均时延、p95/p99

| 场景 | 错误率 | TPS | p95/s |
|------|--------|-----|-------|
| Frontend CPU | 21.97% | 0.169 | 82.39 |
| Checkout Pod Kill | 20.62% | 0.172 | 81.68 |
| ProductCatalog Failure | 51.45% | 0.206 | 89.40 |
| Telemetry Loss | 25.33% | 0.162 | 85.52 |
| Checkout-Discount Delay | 23.16% | 0.157 | 98.41 |

---

## 项目结构

```
Software-Testing-Group-13/
├── src/
│   ├── discountservice/      # 折扣服务（★★★）
│   ├── telemetryservice/     # 遥测服务（★★★）
│   ├── recoverygateway/      # 自愈网关（★★★）
│   ├── checkoutservice/      # 改造后的结算服务（★★★）
│   ├── frontend/             # 前端（改造：Metadata 解码）
│   └── ...                   # 其余 Online-Boutique 原有服务
├── veadk_agent/              # AIOps Agent（★★★ 加分项二）
│   ├── agent.py              # ReAct 推理循环 + 聚合诊断（~470行）
│   ├── tools.py              # 4个工具 + 12个PromQL模板（~690行）
│   ├── webhook_server.py     # FastAPI Webhook 服务（~410行）
│   ├── dashboard.py          # Web 仪表盘 5 页面（~420行）
│   ├── knowledge.py          # 根因知识库 RAG（~200行）
│   ├── notify.py             # 飞书通知（~180行）
│   ├── config.py             # 16项环境变量配置
│   ├── report_store.py       # SQLite + Markdown 报告
│   └── tests/                # 25 个单元测试
├── algorithms/               # 算法复现（★★★ 加分项一）
│   ├── AnomalyDetection/     # DADA + LLMeLog
│   └── TraceDAE_BARO/        # TraceDAE + BARO
├── tests/
│   ├── functional/           # Selenium 脚本
│   ├── performance/          # JMeter 测试计划
│   └── chaosmesh/            # 故障注入 YAML
├── kubernetes-manifests/     # K8s 部署文件（含自研服务）
├── results/                  # 实验数据
└── docs/                     # 报告与文档
```

---

## 快速开始（Minikube）

### 环境要求

- **Docker Desktop** ≥ 29.4
- **Minikube** ≥ 1.38, **Kubernetes** ≥ 1.35
- **Python** 3.9–3.11（推荐 3.11）
- **LLM API Key**（DeepSeek V4 Pro 或兼容 OpenAI SDK 的模型）
- **Helm** 3.x

### 1. 启动 Minikube

```bash
minikube start --cpus=4 --memory=8192 --disk-size=20g --driver=docker
minikube addons enable ingress
minikube addons enable metrics-server
```

### 2. 部署 Online-Boutique + 自研服务

```bash
# 配置镜像加速（国内推荐）
# Docker Desktop → Settings → Docker Engine → 添加 registry-mirrors

# 部署全部服务
kubectl apply -f kubernetes-manifests/

# 注入环境变量（打通自研服务）
kubectl set env deployment/checkoutservice \
  DISCOUNT_SERVICE_ADDR=discountservice:50051 \
  TELEMETRY_SERVICE_URL=http://telemetryservice:8080/v1/metrics

# 等待所有 Pod Running
kubectl get pods
```

### 3. 部署监控栈

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace

# 端口转发访问 Prometheus / Grafana
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090 --address=0.0.0.0 &
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80 --address=0.0.0.0 &
```

### 4. 启动 AIOps Agent

```bash
cd veadk_agent
pip install -r requirements.txt

# 配置环境变量（.env 或环境变量）
#   LLM_API_KEY=sk-xxx
#   LLM_BASE_URL=https://api.deepseek.com/v1
#   PROMETHEUS_URL=http://192.168.43.136:9090
#   RECOVERY_GATEWAY_URL=http://192.168.43.136:18080
#   RECOVERY_GATEWAY_TOKEN=xxx
#   FEISHU_WEBHOOK_URL=https://open.feishu.cn/...

# 启动（Webhook 模式）
python main.py --mode webhook

# 或一次性诊断
python main.py --mode once

# 或定时巡检
python main.py --mode patrol
```

### 5. 运行测试

```bash
# Selenium 功能测试
cd tests/functional
python checkout_discount_test.py

# JMeter 性能压测（需安装 JMeter）
jmeter -n -t tests/performance/online_boutique_checkout_pressure.jmx -l results.jtl

# 故障注入
kubectl apply -f tests/chaosmesh/stress-frontend-cpu.yaml
kubectl apply -f tests/chaosmesh/pod-kill-checkoutservice.yaml
```

### 6. 访问前端

```bash
minikube service frontend --url
```

---

## 参考论文

1. **DADA** — Q. Shentu et al., *Towards a General Time Series Anomaly Detector with Adaptive Bottlenecks and Dual Adversarial Decoders*. ICLR 2025.
2. **LLMeLog** — M. He et al., *LLMeLog: An Approach for Anomaly Detection based on LLM-enriched Log Events*. ISSRE 2024.
3. **TraceDAE** — J. Li et al., *TraceDAE: Trace-Based Anomaly Detection in Microservice Systems via Dual Autoencoder*. IEEE TNSM 2025.
4. **BARO** — L. Pham et al., *BARO: Robust Root Cause Analysis for Microservices via Multivariate Bayesian Online Change Point Detection*. ESEC/FSE 2024.

---

*基础系统基于 [Online-Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) by Google Cloud Platform.*
