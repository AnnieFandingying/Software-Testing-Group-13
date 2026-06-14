# 成员 E 数据需求报告

一句话：请成员 A 提供同一批实验的 Jaeger Trace 数据和 Prometheus 多变量时序指标；时间戳必须能对齐。

## 需要哪些数据

| 数据 | 用途 | 格式 | 必要字段 |
|---|---|---|---|
| Jaeger Trace | TraceDAE | JSON（Jaeger API 导出格式） | `traceID, spans[].operationName, spans[].startTime, spans[].duration, references[].refType` |
| 多变量时序指标 | BARO / TraceDAE attribute | CSV | `timestamp, service, metric, value, run_id` |
| 故障时间线 | 统一打标签（两算法共用） | CSV | `run_id, start_ts, end_ts, fault_type, target_service` |
| 可选：调用链拓扑 | TraceDAE STG构建验证 | JSON/YAML | 服务间调用关系图 |

## 是否需要训练集和测试集

| 算法 | 训练需求 | 测试需求 |
|---|---|---|
| TraceDAE | 需要正常trace训练双自编码器（无监督，仅正常数据） | 需要带标签的异常trace测试集 |
| BARO | **无需训练**（纯统计推断） | 需要带故障时间线的多维时序指标 |

## Trace / TraceDAE 要求

优先导出 Jaeger 中的完整 trace：

- 包含所有 span 的 `operationName`、`startTime`、`duration`、`references`（父子关系）。
- 每次请求一条 trace，traceID 作为唯一标识。
- 导出格式：Jaeger API `/api/traces` 的 JSON 响应格式。
- 重点服务：`frontend`、`checkoutservice`、`cartservice`、`paymentservice`、`shippingservice`、`productcatalogservice`、`currencyservice`、`adservice`、`recommendationservice`、`discountservice`。

最小可跑通：

| 项目 | 最低值 | 建议值 |
|---|---:|---:|
| Trace 总数 | 300 条 | 1000 到 5000 条 |
| 正常 trace | 200 条 | 800 到 4000 条 |
| 异常 trace | 50 条 | 100 到 500 条 |
| 涉及服务数 | 5 个 | 8 到 12 个 |
| 每条trace span数 | 3 个以上 | 5 到 20 个 |

TraceDAE 会将每条 trace 构建为一个 STG（Service Trace Graph），需要 `label` 标注该 trace 是否异常：

```csv
trace_id,label,timestamp
abc123,0,1718253600
def456,1,1718257200
```

## 时序指标 / BARO 要求

优先导出同一时间轴上的多维指标（每个服务 4 个指标维度 × N 个服务）：

- **Latency**（响应延迟）：p50、p95、p99 或 avg
- **Errors**（错误率/错误数）
- **Traffic**（QPS/请求量）
- **CPU / Memory**（资源使用率）

重点服务与 TraceDAE 一致。

BARO 异常检测仅使用 Latency + Errors（论文假设：真正异常反映在延迟和错误率中），根因分析使用全部指标。

最小可跑通：

| 项目 | 最低值 | 建议值 |
|---|---:|---:|
| 指标维度数 | 10（5服务×2指标） | 20到40 |
| 正常时间步 | 300 点 | 1000 到 3000 点 |
| 故障时间步 | 50 点 | 100 到 500 点 |
| 故障案例数 | 3 个 | 10 到 25 个 |
| 采样间隔 | 60s | 10s 到 60s |

示例格式（宽表）：

```csv
timestamp,frontend_latency,frontend_errors,frontend_traffic,frontend_cpu,checkoutservice_latency,checkoutservice_errors,...
1718253600,12.5,0,150,0.31,8.2,0,80,0.25,...
1718253660,13.1,0,145,0.34,9.0,0,78,0.26,...
```

## 故障时间线 / 统一标签

两个算法共用，用于评估：

```csv
run_id,start_ts,end_ts,fault_type,target_service,description
fault_001,1718257200,1718257800,cpu_hog,checkoutservice,CPU stress via ChaosMesh
fault_002,1718258400,1718259000,network_delay,paymentservice,200ms network delay injection
fault_003,1718259600,1718260200,memory_leak,frontend,gradual memory pressure
```

fault_type 建议覆盖：
- `cpu_hog`：CPU 饱和（突变型）
- `memory_leak`：内存泄漏（渐变型）
- `network_delay`：网络延迟注入（突变型）
- `packet_loss`：丢包注入（突变型）
- `pod_kill`：Pod 被杀/重启

## 推荐目录

```text
algorithms/member_e/
  tracedae/data/raw/jaeger/        # Jaeger trace JSON
  tracedae/data/raw/metrics/       # 各服务指标CSV
  tracedae/data/raw/labels.csv     # trace级标签
  baro/data/raw/<run_id>_metrics.csv   # 多维时序宽表
  baro/data/labels/<run_id>_labels.csv # 故障时间线
```

## 验收标准

1. Trace 和指标时间戳能对齐（同一批实验）。
2. 每次实验有唯一 `run_id`。
3. 故障时间线能生成 `label=0/1`。
4. 时序指标维度 ≥ 10（至少覆盖 5 个核心服务 × 2 指标）。
5. 至少包含 3 种不同的故障类型。
6. Jaeger trace 包含完整的 span 父子关系（`references` 字段）。
