# 成员 D 交付报告：KPI 与日志异常检测复现

成员 D 负责复现两类异常检测算法，并把代码、数据接口和运行脚本统一放在主仓内，展示项目时只需要克隆 `Software-Testing-Group-13`。

| 方向 | 算法 | 论文 | 主仓代码位置 | 是否需要训练数据 |
|---|---|---|---|---|
| KPI 异常检测 | DADA | ICLR 2025 | `algorithms/member_d/dada/code/` | 不重训主模型，但需要正常初始化段、测试段和标签 |
| 日志异常检测 | LLMeLog | ISSRE 2024 | `algorithms/member_d/llmelog/code/` | 需要日志训练/验证/测试数据；基础 BERT 可自动下载 |

## 目录结构

```text
algorithms/member_d/
  README.md                 # 成员 D 交付报告
  DATA_REQUEST.md           # 给成员 A 的数据需求报告
  dada/code/                # DADA 论文复现代码与预训练权重
  llmelog/code/             # LLMeLog 论文复现代码
  scripts/                  # 数据采集、格式转换、算法启动脚本
  data/                     # 成员 A 数据放置目录，真实数据不提交
  results/                  # 复现实验结果目录，真实结果不提交
```

## 算法简述

DADA 是面向多变量时间序列的通用异常检测方法。这里保留论文代码和预训练权重 `dada/code/DADA/pytorch_model.bin`，复现时走 zero-shot 推理，不需要重新训练主模型；我们只需要把 Prometheus/KPI 指标整理成 DADA 的 `evaluation_dataset` 格式。

LLMeLog 是日志异常检测方法。它先把日志模板做语义增强，再微调 BERT 得到事件向量，最后训练 Transformer 分类日志序列是否异常。`bert-base-uncased` 不直接提交大模型权重，运行脚本支持首次运行时从 Hugging Face 自动下载到 `llmelog/code/bert-base-en/`。

## 环境准备

建议使用 conda 创建 Python 3.9 环境。下面这组版本已经在 Windows + CPU 上跑通过 DADA 和 LLMeLog 检测器训练/评估：

```powershell
cd "D:\作业\软件测试与维护\Software-Testing-Group-13"
conda create -y -n member_d_repro_py39 python=3.9
conda activate member_d_repro_py39
pip install numpy==1.23.5 pandas==1.5.3 scikit-learn==1.3.2 matplotlib tqdm thop transformers==4.33.3 torch==1.13.1 pytorch-lightning==1.1.2 protobuf==3.20.3
```

不强制使用 Docker。CPU 可以跑通流程；有 GPU 时 DADA 和 LLMeLog 训练会更快。

如果 DADA 加载本地 Hugging Face 模型时报用户目录 cache 权限问题，可以把 cache 放到项目本地：

```powershell
$env:HF_HOME="$PWD\.hf_cache"
$env:TRANSFORMERS_CACHE="$PWD\.hf_cache\transformers"
```

## 数据放置

成员 A 交付的数据按下面放入主仓本地目录：

```text
algorithms/member_d/data/
  kpi/raw/<run_id>_metrics.csv
  logs/raw/<run_id>_<service>.log
  labels/<run_id>_timeline.csv
```

数据字段和数量级见 [DATA_REQUEST.md](DATA_REQUEST.md)。

如果需要成员 D 自己采集，也可以用脚本：

```powershell
python algorithms\member_d\scripts\collect_prometheus_metrics.py --prometheus-url http://localhost:9090 --out algorithms\member_d\data\kpi\raw\metrics.csv
python algorithms\member_d\scripts\collect_k8s_logs.py --namespace default --services frontend checkoutservice discountservice --out-dir algorithms\member_d\data\logs\raw
```

## DADA 复现流程

先把成员 A 的 KPI CSV 转成 DADA 输入：

```powershell
python algorithms\member_d\scripts\prepare_dada_dataset.py --input algorithms\member_d\data\kpi\raw\*.csv --dataset-name memberd_online_boutique
```

再运行 DADA：

```powershell
python algorithms\member_d\scripts\run_dada.py --dataset-name memberd_online_boutique
```

默认会调用本仓代码 `algorithms/member_d/dada/code/run.py`。如果有 GPU，可加 `--gpu 0`。

## LLMeLog 复现流程

先把原始日志和故障时间线转成 LLMeLog 数据：

```powershell
python algorithms\member_d\scripts\prepare_llmelog_dataset.py --logs algorithms\member_d\data\logs\raw\*.log --timeline algorithms\member_d\data\labels\fault_timeline.csv
```

再运行 LLMeLog。首次运行如本地没有 BERT 权重，加 `--auto-download-bert`：

```powershell
python algorithms\member_d\scripts\run_llmelog.py --auto-download-bert --hard-device cpu
```

默认执行 `predata -> encoder -> gen -> detector -> eval`。只想快速检查某一步可以指定：

```powershell
python algorithms\member_d\scripts\run_llmelog.py --stages predata gen --hard-device cpu
```

## 输出约定

预处理后的数据默认写入：

```text
algorithms/member_d/data/kpi/processed/
algorithms/member_d/data/logs/processed/
```

实验截图、指标表和最终汇总结果放入：

```text
algorithms/member_d/results/
```

本地已生成的异常识别展示报告见 `algorithms/member_d/results/final_rerun_test_report.md`。答辩展示建议直接打开：

```text
algorithms/member_d/results/visualizations/dada_memberd_ob_20260614_184048_timeline.png
algorithms/member_d/results/visualizations/llmelog_final_rerun_verify_timeline.png
```

`data/`、`results/`、LLMeLog 下载权重和训练 checkpoint 都已加入忽略规则，不会把本地数据或大模型误提交到主仓。
