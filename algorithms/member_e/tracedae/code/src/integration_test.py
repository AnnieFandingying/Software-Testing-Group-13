# -*- coding: utf-8 -*-
"""
TraceDAE 端到端集成测试
=========================
使用合成数据验证完整流水线。合成数据和真实数据的加载路径完全一致 —
真实数据到达后只需替换 data/raw/ 下的文件即可。

流水线:
  生成合成数据 → Trace/Metric 加载 → STG 构建(含异常感知属性序列)
  → DBSCAN 降噪 → 双自编码器训练 → 异常检测评估 → 消融实验

运行: python src/integration_test.py
"""

import os, sys, json, time, argparse
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.trace_collector import TraceCollector
from data.metric_collector import MetricCollector
from data.stg_builder import STGBuilder
from data.dbscan_denoise import DBSCANDenoiser
from data.dataset import STGDataset, create_dataloader
from model.dual_autoencoder import DualAutoencoder
from model.detector import AnomalyDetector
from sklearn.metrics import f1_score, precision_score, recall_score


def load_labels(label_path="data/raw/labels.csv"):
    """加载 trace_id → label 映射"""
    labels = {}
    if os.path.exists(label_path):
        with open(label_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("trace_id") or not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    labels[parts[0]] = int(parts[1])
    return labels


def build_stgs(traces, metrics, labels):
    """构建 Service Trace Graphs — 异常感知"""
    builder = STGBuilder(traces, metrics)
    stgs = builder.build_all_stgs(labels=labels)
    stats = builder.get_stg_statistics()
    print(f"[STG] 构建 {stats['total_stgs']} 个 STG, "
          f"avg_nodes={stats['avg_nodes']:.1f}, avg_edges={stats['avg_edges']:.1f}")
    return stgs


def denoise_stgs(stgs, labels):
    """DBSCAN 降噪"""
    features = []
    stg_ids = []
    for tid, stg in stgs.items():
        feat = stg.x.numpy().flatten()
        if len(feat) < 8:
            feat = np.pad(feat, (0, 8 - len(feat)))
        features.append(feat[:8])
        stg_ids.append(tid)

    features = np.array(features)
    # 合成数据 eps 放宽到 1.5 避免把异常样本当噪声剔除
    # 真实数据可调回默认 0.5 (数据本身有噪声)
    denoiser = DBSCANDenoiser(eps=1.5, min_samples=2)
    valid_idx, _ = denoiser.denoise(features)

    valid_stgs = {}
    valid_labels = {}
    for i in valid_idx:
        tid = stg_ids[i]
        valid_stgs[tid] = stgs[tid]
        valid_labels[tid] = labels.get(tid, 0)

    n_anomaly_kept = sum(1 for tid in valid_stgs if labels.get(tid, 0) == 1)
    n_anomaly_orig = sum(1 for tid in stgs if labels.get(tid, 0) == 1)
    print(f"[DBSCAN] {len(stgs)} -> {len(valid_stgs)} STGs "
          f"(异常: {n_anomaly_kept}/{n_anomaly_orig} 保留)")
    return valid_stgs, valid_labels


def get_config():
    """训练配置 — 合成数据使用较小模型加速"""
    return {
        "model": {"input_dim": 4, "hidden_dim": 96, "num_heads": 2,
                  "num_lstm_layers": 1, "alpha": 0.1, "theta": 5.0,
                  "eta": 2.0, "dropout": 0.1},
        "training": {"epochs": 80, "learning_rate": 0.001,
                     "weight_decay": 1e-5, "seed": 42},
        "data": {"train_ratio": 0.7, "val_ratio": 0.0, "test_ratio": 0.3},
    }


def train_model(train_stgs, train_labels, config, device):
    """训练双自编码器"""
    model = DualAutoencoder(
        input_dim=config["model"]["input_dim"],
        hidden_dim=config["model"]["hidden_dim"],
        num_heads=config["model"]["num_heads"],
        num_lstm_layers=config["model"]["num_lstm_layers"],
        alpha=config["model"]["alpha"],
        theta=config["model"]["theta"],
        eta=config["model"]["eta"],
    ).to(device)

    opt = torch.optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
    stg_list = list(train_stgs.values())
    epochs = config["training"]["epochs"]
    best_loss = float("inf")

    model.train()
    for epoch in range(epochs):
        epoch_loss = 0.0
        n = 0
        for stg in stg_list:
            x = stg.x.to(device)
            ei = stg.edge_index.to(device)
            adj = stg.adj.to(device)
            aseq = stg.attr_sequences.to(device)

            opt.zero_grad()
            _, arec, _, xrec = model(x, ei, adj, aseq)
            total, sl, al = model.compute_loss(adj, arec, aseq, xrec)
            total.backward()
            opt.step()
            epoch_loss += total.item()
            n += 1

        avg_loss = epoch_loss / max(n, 1)
        if avg_loss < best_loss:
            best_loss = avg_loss

        if (epoch + 1) % 15 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1:3d}: loss={avg_loss:.4f}")

    model.eval()
    print(f"[Train] Done. best_loss={best_loss:.4f}")

    # 用正常样本建立检测基线
    detector = AnomalyDetector(threshold=2.0)
    normal_losses = []
    with torch.no_grad():
        for stg in stg_list:
            tid = stg.trace_id
            if train_labels.get(tid, 0) == 0:
                x = stg.x.to(device)
                ei = stg.edge_index.to(device)
                adj = stg.adj.to(device)
                aseq = stg.attr_sequences.to(device)
                _, arec, _, xrec = model(x, ei, adj, aseq)
                loss, _, _ = model.compute_loss(adj, arec, aseq, xrec)
                normal_losses.append(loss.item())
    detector.update_normal(normal_losses)
    mu, sigma = detector.compute_statistics()
    print(f"  Normal baseline: mu={mu:.1f}, sigma={sigma:.1f}")

    return model, detector


def evaluate_model(model, detector, test_stgs, test_labels, device):
    """异常检测评估"""
    y_true, y_pred, y_scores = [], [], []
    inference_times = []

    model.eval()
    with torch.no_grad():
        for tid, stg in test_stgs.items():
            x = stg.x.to(device)
            ei = stg.edge_index.to(device)
            adj = stg.adj.to(device)
            aseq = stg.attr_sequences.to(device)

            t0 = time.perf_counter()
            _, arec, _, xrec = model(x, ei, adj, aseq)
            loss, _, _ = model.compute_loss(adj, arec, aseq, xrec)
            t1 = time.perf_counter()
            inference_times.append((t1 - t0) * 1000)

            loss_val = loss.item()
            is_anomaly, score, _ = detector.detect(loss_val)
            true_label = test_labels.get(tid, 0)

            y_true.append(true_label)
            y_pred.append(1 if is_anomaly else 0)
            y_scores.append(score)

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    p = precision_score(y_true, y_pred, zero_division=0)
    r = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    avg_inf = np.mean(inference_times) if inference_times else 0

    print(f"\n[Eval] 异常检测:")
    print(f"  Samples={len(y_true)}, Anomalies={int(y_true.sum())}")
    print(f"  Precision={p:.4f}, Recall={r:.4f}, F1={f1:.4f}")
    print(f"  Avg inference: {avg_inf:.2f} ms/sample")

    return {"precision": p, "recall": r, "f1": f1,
            "inference_ms": avg_inf, "n_samples": len(y_true),
            "n_anomalies": int(y_true.sum())}


def run_ablation(stgs, labels, config, device):
    """消融实验: 5 个变体"""
    print(f"\n[Ablation] 消融实验")
    print("-" * 50)

    stg_list = list(stgs.values())
    split = int(len(stg_list) * 0.7)

    variants = [
        ("Full TraceDAE",       0.1),
        ("w/o Attribute-AE",    1.0),
        ("w/o Structure-AE",    0.0),
        ("alpha = 0",           0.0),
        ("alpha = 1",           1.0),
    ]

    results = {}
    for vname, alpha in variants:
        print(f"\n  --- {vname} (alpha={alpha}) ---")
        try:
            m = DualAutoencoder(
                input_dim=config["model"]["input_dim"],
                hidden_dim=config["model"]["hidden_dim"],
                num_heads=config["model"]["num_heads"],
                num_lstm_layers=config["model"]["num_lstm_layers"],
                alpha=alpha, theta=config["model"]["theta"],
                eta=config["model"]["eta"],
            ).to(device)
            opt = torch.optim.Adam(m.parameters(), lr=0.001)

            m.train()
            for epoch in range(30):
                for stg in stg_list[:split]:
                    x = stg.x.to(device)
                    ei = stg.edge_index.to(device)
                    adj = stg.adj.to(device)
                    aseq = stg.attr_sequences.to(device)
                    opt.zero_grad()
                    _, arec, _, xrec = m(x, ei, adj, aseq)
                    loss, _, _ = m.compute_loss(adj, arec, aseq, xrec)
                    loss.backward()
                    opt.step()

            m.eval()
            det = AnomalyDetector(threshold=2.0)
            # 收集正常样本的损失基线
            normal_losses = []
            with torch.no_grad():
                for stg in stg_list[:split]:
                    if labels.get(stg.trace_id, 0) == 0:
                        x = stg.x.to(device)
                        ei = stg.edge_index.to(device)
                        adj = stg.adj.to(device)
                        aseq = stg.attr_sequences.to(device)
                        _, arec, _, xrec = m(x, ei, adj, aseq)
                        lo, _, _ = m.compute_loss(adj, arec, aseq, xrec)
                        normal_losses.append(lo.item())
            det.update_normal(normal_losses)

            yt, yp = [], []
            with torch.no_grad():
                for stg in stg_list[split:]:
                    x = stg.x.to(device)
                    ei = stg.edge_index.to(device)
                    adj = stg.adj.to(device)
                    aseq = stg.attr_sequences.to(device)
                    _, arec, _, xrec = m(x, ei, adj, aseq)
                    lo, _, _ = m.compute_loss(adj, arec, aseq, xrec)
                    is_a, _, _ = det.detect(lo.item())
                    yt.append(labels.get(stg.trace_id, 0))
                    yp.append(1 if is_a else 0)

            f1 = f1_score(np.array(yt), np.array(yp), zero_division=0)
            results[vname] = {"f1": f1}
            print(f"  F1={f1:.4f}")

        except Exception as e:
            results[vname] = {"error": str(e)}
            print(f"  Error: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="TraceDAE 集成测试")
    parser.add_argument("--generate", action="store_true", default=True,
                        help="生成合成数据 (默认). 使用 --no-generate 跳过生成")
    parser.add_argument("--raw-dir", default="data/raw",
                        help="原始数据目录")
    parser.add_argument("--no-generate", dest="generate", action="store_false",
                        help="跳过数据生成, 使用已有 data/raw/ 文件")
    parser.add_argument("--output", default="experiments/integration_test_result.json",
                        help="结果输出路径")
    args = parser.parse_args()

    print("=" * 60)
    print("TraceDAE 端到端集成测试")
    print("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ---- Phase 1: 生成/加载数据 ----
    if args.generate:
        print("\n[Phase 1] 生成合成数据")
        from generate_synthetic_data import generate_all
        generate_all(output_dir=args.raw_dir, seed=42)

    # ---- Phase 2: 加载 Trace ----
    print("\n[Phase 2] 加载 Trace 数据")
    trace_collector = TraceCollector(data_source="json")
    traces = trace_collector.load_traces(os.path.join(args.raw_dir, "traces"))
    print(f"  {trace_collector.get_statistics()}")

    # ---- Phase 3: 加载 Metric ----
    print("\n[Phase 3] 加载 Metric 数据")
    metric_collector = MetricCollector(data_source="csv")
    metrics = metric_collector.load_metrics(os.path.join(args.raw_dir, "metrics"))
    print(f"  {len(metrics)} 个服务")

    # ---- Phase 4: 加载标签 ----
    labels = load_labels(os.path.join(args.raw_dir, "labels.csv"))
    n_anomaly = sum(labels.values())
    print(f"\n[Labels] {len(labels)} 条标签, {n_anomaly} 异常")

    # ---- Phase 5: 构建 STG + 降噪 ----
    print("\n[Phase 5] STG 构建 & DBSCAN 降噪")
    config = get_config()
    stgs = build_stgs(traces, metrics, labels)
    stgs_clean, labels_clean = denoise_stgs(stgs, labels)

    # ---- Phase 6: 划分数据 ----
    stg_items = list(stgs_clean.items())
    np.random.seed(42)
    perm = np.random.permutation(len(stg_items))
    split = int(len(stg_items) * 0.7)
    train_stgs = {stg_items[i][0]: stg_items[i][1] for i in perm[:split]}
    test_stgs = {stg_items[i][0]: stg_items[i][1] for i in perm[split:]}

    # ---- Phase 7: 训练 ----
    print("\n[Phase 7] 模型训练")
    model, detector = train_model(train_stgs, labels_clean, config, device)

    # ---- Phase 8: 评估 ----
    print("\n[Phase 8] 异常检测评估")
    det_metrics = evaluate_model(model, detector, test_stgs, labels_clean, device)

    # ---- Phase 9: 消融实验 ----
    print("\n[Phase 9] 消融实验")
    ablation_results = run_ablation(stgs_clean, labels_clean, config, device)

    # ---- 总结 ----
    print("\n" + "=" * 60)
    print("集成测试总结")
    print("=" * 60)
    print(f"  Traces: {len(traces)} -> STGs: {len(stgs)} -> Clean: {len(stgs_clean)}")
    print(f"  Model params: {sum(p.numel() for p in model.parameters()):,}")
    print(f"  Full TraceDAE F1: {det_metrics['f1']:.4f}")

    f1_full = det_metrics["f1"]
    verdict = "PASS" if f1_full >= 0.70 else ("PARTIAL PASS" if f1_full >= 0.50 else "NEEDS TUNING")
    print(f"\n  Verdict: {verdict}")
    print(f"  (合成数据 F1>=0.70 即验证流水线正确)")
    print("=" * 60)

    # ---- 保存结果 ----
    result = {
        "config": config,
        "data": {"n_traces": len(traces), "n_stgs": len(stgs),
                 "n_clean": len(stgs_clean)},
        "detection": {k: (float(v) if isinstance(v, (float, np.floating))
                           else v) for k, v in det_metrics.items()},
        "ablation": {k: {k2: (float(v2) if isinstance(v2, (float, np.floating))
                              else str(v2)) for k2, v2 in v.items()}
                     for k, v in ablation_results.items()},
        "verdict": verdict,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n[Result] -> {args.output}")

    return result


if __name__ == "__main__":
    main()
