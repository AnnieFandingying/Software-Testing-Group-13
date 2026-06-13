# 成员 D 数据需求报告

一句话：请成员 A 提供同一批实验的 KPI、容器日志和故障时间线；时间戳必须能对齐。

## 需要哪些数据

| 数据 | 用途 | 格式 | 必要字段 |
|---|---|---|---|
| 多变量 KPI 时序 | DADA | CSV | `timestamp,metric,value,label,run_id` |
| 原始容器日志 | LLMeLog | `.log` 或 `.jsonl` | `timestamp,service,pod,message,run_id` |
| 故障时间线 | 统一打标签 | CSV | `run_id,start_ts,end_ts,fault_type,target_service,chaos_file` |
| 可选：日志模板 | 减少解析工作 | CSV | `event_id,event_template,service,count,example_message` |

## 是否需要训练集和测试集

| 算法 | 训练需求 | 测试需求 |
|---|---|---|
| DADA | 不重训主模型；需要一段正常 KPI 作为初始化/参考段 | 需要带标签的 KPI 测试段 |
| LLMeLog | 需要正常/异常日志序列训练编码器和检测器；基础 BERT 可自动下载 | 需要带标签的日志序列测试集 |

## KPI / DADA 要求

优先导出同一时间轴上的多维指标：

- CPU、内存、QPS、错误率、p95/p99 响应时间、Pod 重启次数。
- 重点服务：`frontend`、`checkoutservice`、`discountservice`、`telemetryservice`、故障目标服务。
- 自定义指标可包含：`boutique_requests_total`、`boutique_errors_total`、`boutique_request_duration_ms_sum`、`boutique_discount_hits_total`。

最小可跑通：

| 项目 | 最低值 | 建议值 |
|---|---:|---:|
| 指标维度 | 5 到 10 个 | 10 到 30 个 |
| 正常点数 | 300 个 | 1000 到 3000 个 |
| 测试点数 | 300 个 | 1000 到 3000 个 |
| 每种故障窗口 | 50 个点以上 | 100 到 500 个点 |

示例：

```csv
timestamp,metric,value,label,run_id
1718253600,frontend_cpu,0.31,0,normal_001
1718253660,frontend_cpu,0.34,0,normal_001
1718257200,frontend_cpu,0.91,1,fault_001
```

## 日志 / LLMeLog 要求

原始日志要求：

- UTF-8 编码。
- 每行有时间戳和服务名。
- 保留 `trace_id`、`request_id`、`session_id` 等字段，如果有的话。
- 去掉终端颜色控制符。

重点服务：

- `frontend`
- `checkoutservice`
- `discountservice`
- `telemetryservice`
- 故障目标服务

最小可跑通：

| 项目 | 最低值 | 建议值 |
|---|---:|---:|
| 原始日志行数 | 5000 行 | 20000 到 100000 行 |
| 唯一事件模板数 | 20 个 | 50 到 300 个 |
| 正常训练序列 | 500 条 | 2000 到 10000 条 |
| 测试序列 | 300 条 | 1000 到 5000 条 |
| 异常序列 | 50 条以上 | 200 条以上 |

示例：

```text
1718253600 checkoutservice trace_id=abc event=checkout_completed status=ok duration_ms=135
1718253601 discountservice trace_id=abc event=discount_calculated status=ok rule=FULL_700_MINUS_200
```

## 推荐目录

```text
algorithms/member_d/data/
  kpi/raw/<run_id>_metrics.csv
  logs/raw/<run_id>_<service>.log
  labels/<run_id>_timeline.csv
```

## 验收标准

1. KPI 和日志时间戳能对齐。
2. 每次实验有唯一 `run_id`。
3. 故障时间线能生成 `label=0/1`。
4. KPI 至少 5 个指标维度。
5. 日志至少包含 `frontend`、`checkoutservice`、`discountservice`。
