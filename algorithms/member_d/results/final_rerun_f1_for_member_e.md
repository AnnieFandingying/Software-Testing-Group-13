# Member D final_rerun F1-score

给成员 E 做对比表时，建议使用 `best_threshold` 口径，因为 DADA 现有输出就是扫描阈值后的 best F1。

| 算法 | 方向 | final_rerun 数据 | 阈值口径 | Precision | Recall | F1-score | 说明 |
|---|---|---|---|---:|---:|---:|---|
| DADA | KPI 异常检测 | `final_rerun_verify_repeat3` | best threshold | 1.0000 | 1.0000 | 1.0000 | KPI 数据为了满足 DADA 窗口长度做了 3 倍重复，且标签几乎全异常，只适合作为 final_rerun 跑通/对比值 |
| LLMeLog | 日志异常检测 | `final_rerun_verify` test split | best threshold | 0.2158 | 0.9875 | 0.3543 | 推荐给成员 E 的日志算法对比值 |
| LLMeLog | 日志异常检测 | `final_rerun_verify` test split | fixed threshold 0.205 | 0.2026 | 0.7875 | 0.3223 | 这是展示图使用的阈值，不是最佳 F1 |

对应 CSV：`algorithms/member_d/results/final_rerun_f1_for_member_e.csv`

注意：DADA 和 LLMeLog 使用的是不同模态数据，分别是 KPI 和日志；如果成员 E 要横向比较算法性能，最好在表格里保留“数据类型”和“阈值口径”两列。
