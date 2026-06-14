# 成员 E 交付报告：Trace异常检测与故障诊断算法复现

成员 E 负责复现两类微服务 AIOps 算法——Trace异常检测（TraceDAE）和故障诊断（BARO）——并把代码、合成数据和运行脚本统一放在主仓内，展示项目时只需要克隆 `Software-Testing-Group-13`。

| 方向 | 算法 | 论文 | 主仓代码位置 | 是否需要训练数据 |
|---|---|---|---|---|
| Trace异常检测 | TraceDAE | TNSM 2025 | `algorithms/member_e/tracedae/code/` | 不重训也可直接用合成数据跑集成测试；完整训练需真实trace |
| 故障诊断 | BARO | ESEC/FSE 2024 | `algorithms/member_e/baro/code/` | 无需训练（纯统计方法）；合成数据可直接运行 |

## 目录结构

```text
algorithms/member_e/
  README.md                 # 成员 E 交付报告
  DATA_REQUEST.md           # 给成员 A 的数据需求报告
  .gitignore
  tracedae/
    code/                   # TraceDAE 论文复现代码
    data/raw/               # 合成数据集（460条trace + 8服务metric）
    experiments/            # 集成测试结果
  baro/
    code/                   # BARO 论文复现代码
    results/                # 复现实验结果与报告
```

## 算法简述

**TraceDAE** 将每条分布式trace建模为Service Trace Graph (STG)，使用双自编码器联合检测异常：
- 结构自编码器（GAT）：重建邻接矩阵，检测服务调用异常（SIA）
- 属性自编码器（LSTM）：重建节点属性序列，检测服务响应异常（SRA）
- 联合损失 `L = α·L_struct + (1-α)·L_attr`（α=0.1）

**BARO** 是纯统计方法，无需训练、无需标注、无需GPU：
- 多变量BOCPD（贝叶斯在线变点检测）：联合建模Latency+Errors，检测分布变化
- RobustScorer（鲁棒根因评分）：median + IQR 非参数排序，对检测时间偏差具有鲁棒性

## 环境准备

两个算法依赖版本不同，建议分别建虚拟环境。**TraceDAE 需要 PyTorch + PyG（GPU 推荐但非必须）**，**BARO 仅需 numpy/scipy/scikit-learn（纯 CPU）**。

TraceDAE：

```powershell
cd "D:\作业\软件测试与维护\Software-Testing-Group-13"
python -m venv .venv-tracedae
.\.venv-tracedae\Scripts\activate
pip install -r algorithms\member_e\tracedae\code\requirements.txt
```

BARO：

```powershell
cd "D:\作业\软件测试与维护\Software-Testing-Group-13"
python -m venv .venv-baro
.\.venv-baro\Scripts\activate
pip install -r algorithms\member_e\baro\code\requirements.txt
```

不强制使用 Docker。BARO 完全在 CPU 上运行；TraceDAE 集成测试可在 CPU 上完成，完整训练建议使用 GPU。

## 数据放置

成员 A 交付的数据按下面放入主仓本地目录：

```text
algorithms/member_e/tracedae/data/
  raw/jaeger/                  # 从Jaeger导出的真实trace JSON
  raw/metrics/<service>.csv    # 各服务的Prometheus指标

algorithms/member_e/baro/data/
  raw/<run_id>_metrics.csv     # 多维时序指标（列：服务×指标）
  labels/<run_id>_labels.csv   # 故障时间线标注
```

数据字段和数量级见 [DATA_REQUEST.md](DATA_REQUEST.md)。

## TraceDAE 复现流程

### 1. 集成测试（合成数据，端到端验证流水线）

```powershell
cd algorithms\member_e\tracedae\code
python src/integration_test.py
```

输出 `../experiments/integration_test_result.json`，验证全部6阶段流水线是否通过。

### 2. 使用真实数据

将成员A交付的Jaeger trace JSON放入 `../data/raw/jaeger/`，指标CSV放入 `../data/raw/metrics/`：

```powershell
python src/generate_synthetic_data.py --mode real --jaeger-dir ../data/raw/jaeger/ --metrics-dir ../data/raw/metrics/
```

### 3. 完整训练

```powershell
python src/train.py --config configs/default.yaml --data ../data/processed/stgs_clean/ --output ../data/models/
```

### 4. 评估

```powershell
python src/evaluate.py --config configs/default.yaml --model ../data/models/tracedae_best.pth --data ../data/processed/stgs_clean/
```

### 5. 消融实验（7变体）

```powershell
python src/experiments.py --config configs/default.yaml --data ../data/processed/stgs_clean/ --output ../experiments/ --epochs 100
```

## BARO 复现流程

### 1. 完整实验流水线（合成数据，直接运行）

```powershell
cd algorithms\member_e\baro\code
python run_experiments.py
```

自动完成：合成数据生成 → BOCPD + 基线检测 → 鲁棒评分 → 评估 → 输出JSON结果。

### 2. 学术评估套件（含统计检验、参数敏感性）

```powershell
python run_academic_experiments.py
```

### 3. 使用真实数据

将成员A的指标CSV放入 `../data/raw/`，编辑 `configs/default.yaml` 中的 `data.use_synthetic: false` 和 `data.raw_path`，再重新运行。

## 输出约定

TraceDAE 输出：

```text
algorithms/member_e/tracedae/
  data/processed/     # 预处理后的STG数据
  data/models/        # 训练好的模型权重（.pth）
  experiments/        # 消融实验结果和对比图表
```

BARO 输出：

```text
algorithms/member_e/baro/
  results/            # 实验JSON、报告MD、图表PNG
```

`data/processed/`、`data/models/` 和图表文件已加入忽略规则，不会误提交到主仓。

## 四算法横向对比

成员 E 已完成 TraceDAE 和 BARO 的独立评估，并与成员 D 约定统一对比框架。待成员 D 交付 DADA 和 LLMeLog 结果后，在统一数据集上完成四算法统计对比。

> 详细复现报告见本地文件：`成员E_算法复现与对比分析报告.md`
