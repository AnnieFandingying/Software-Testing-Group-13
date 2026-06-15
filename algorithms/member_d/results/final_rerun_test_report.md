# Member D 异常识别展示报告

本报告不做严格性能排名，只展示两件事：DADA 能根据 KPI 时间序列把异常段打出高分，LLMeLog 能根据日志事件序列把故障窗口识别出来。

## 展示产物

| 方向 | 展示图 | 分数明细 | 说明 |
|---|---|---|---|
| KPI 异常检测 DADA | `algorithms/member_d/results/visualizations/dada_memberd_ob_20260614_184048_timeline.png` | `algorithms/member_d/results/visualizations/dada_memberd_ob_20260614_184048_scores.csv` | 使用本地完整 Online Boutique KPI run，包含正常段、故障段、恢复段 |
| 日志异常检测 LLMeLog | `algorithms/member_d/results/visualizations/llmelog_final_rerun_verify_timeline.png` | `algorithms/member_d/results/visualizations/llmelog_final_rerun_verify_scores.csv` | 使用队员提供的 `final_rerun/verify_*` 日志和 timeline |

## DADA：通过 KPI 识别异常段

DADA 输入多维 KPI 矩阵，例如 pod 内存、服务请求量、重启次数等 Prometheus 指标；模型输出每个时间点的异常分数。展示图中：

1. 红色背景是真实故障时间段。
2. 绿色曲线是 DADA 异常分数，越高表示越异常。
3. 橙色虚线是用初始化正常段得到的 95 分位阈值。

本次展示使用的故障是 `discountservice scale_down`，时间为 `2026-06-14 10:47:49 UTC` 到 `2026-06-14 10:51:16 UTC`。DADA 的异常峰值主要出现在故障结束后，说明故障影响在 KPI 上存在滞后扩散；图上可以直观看到 KPI 从正常状态进入异常状态，并在后续时间段触发高异常分数。

关键数据：

- 处理后 KPI 数据：`algorithms/member_d/data/kpi/processed/dada_evaluation_dataset/data/memberd_ob_20260614_184048.csv`
- 故障时间线：`algorithms/member_d/data/labels/memberd_ob_20260614_184048_timeline.csv`
- 时间点数量：572
- 有 DADA 分数的时间点：345
- 阈值：0.068891
- 超过阈值的时间点：185

队员提供的 `final_rerun/verify_*/prometheus` 可以读入，但它几乎只覆盖故障窗口，且所有标签都是异常，合计只有 133 个时间点；它适合证明接口能跑通，不适合作为 DADA 的展示主图。DADA 展示需要故障前正常段和故障后恢复段。

## LLMeLog：通过日志识别异常窗口

LLMeLog 先把日志模板转成事件序列，再用 BERT 语义向量和检测器判断日志窗口是否异常。展示图中：

1. 每一行对应一个 `final_rerun/verify_*` 故障 run。
2. 红色背景是真实故障时间段。
3. 绿色曲线是 LLMeLog 对 5 秒日志窗口输出的异常概率。
4. 橙色虚线是展示阈值 `0.205`，超过阈值的窗口视为异常。
5. 红点表示该窗口落在故障时间段内。

使用的数据来自队员提供的 5 组有效日志：

- `verify_frontend_cpu_001`
- `verify_checkout_pod_kill_001`
- `verify_productcatalog_pod_failure_001`
- `verify_telemetry_loss_001`
- `verify_checkout_discount_delay_001`

处理后规模：

- 原始日志事件聚合后：84709 条事件
- 日志模板：360 个
- 5 秒日志窗口：4166 个
- 训练集：2499 个窗口，正常 2263，异常 236
- 验证集：832 个窗口，正常 754，异常 78
- 测试集：835 个窗口，正常 755，异常 80
- 可画到时间轴上的展示窗口：1807 个

展示摘要：

| run_id | 可展示窗口 | 故障窗口 | 预测异常窗口 | 最高异常分数 |
|---|---:|---:|---:|---:|
| verify_checkout_discount_delay_001 | 362 | 86 | 279 | 0.3651 |
| verify_checkout_pod_kill_001 | 361 | 45 | 287 | 0.3323 |
| verify_frontend_cpu_001 | 361 | 95 | 275 | 0.3487 |
| verify_productcatalog_pod_failure_001 | 362 | 77 | 288 | 0.3695 |
| verify_telemetry_loss_001 | 361 | 91 | 306 | 0.3651 |

这里的重点不是分数是否达到最优，而是图上可以看到：故障窗口内有大量日志序列被模型赋予较高异常分数，说明 LLMeLog 复现代码已经能基于队员日志数据完成异常段识别展示。同时图中也能看到正常段存在误报点，这部分可解释为当前训练数据较少、阈值只用于展示，没有做正式调参。

## 可复现命令

DADA KPI 展示图：

```powershell
D:\miniconda3\envs\member_d_cuda_py39\python.exe algorithms\member_d\scripts\visualize_dada_scores.py
```

LLMeLog 日志展示图：

```powershell
D:\miniconda3\envs\member_d_cuda_py39\python.exe algorithms\member_d\scripts\visualize_llmelog_scores.py `
  --llmelog-root D:\tmp\member_d_final_rerun_llmelog_run\code `
  --dataset final_rerun_verify `
  --threshold 0.205 `
  --hard-device cuda --gpu-index 0 --batch-size 8
```

LLMeLog 已训练产物在：

- `D:\tmp\member_d_final_rerun_llmelog_run\code\checkpoint\HSFencoder_model.bin`
- `D:\tmp\member_d_final_rerun_llmelog_run\code\checkpoint\LLMeLog_model.bin`
- `D:\tmp\member_d_final_rerun_llmelog_run\code\data\final_rerun_verify\emd_dict.json`

## 答辩讲法

DADA 负责回答：“KPI 指标异常时，模型能不能在时间线上把异常段打出来？”展示 DADA 图，指出红色故障段和异常分数越过阈值即可。

LLMeLog 负责回答：“服务日志出现异常模式时，模型能不能把故障窗口识别出来？”展示 LLMeLog 图，按 5 个故障 run 逐行说明红色故障区间、红点日志窗口和模型异常分数的对应关系即可。
