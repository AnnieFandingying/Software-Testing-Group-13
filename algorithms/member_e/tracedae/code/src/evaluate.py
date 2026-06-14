# -*- coding: utf-8 -*-
"""
TraceDAE 评估脚本
=====================
评估训练后的 TraceDAE 模型在异常检测和根因定位上的性能。

评估指标：
  异常检测：Precision, Recall, F1, ROC-AUC
  根因定位：A@1, A@2, A@3
  效率评估：训练时间, 推理时间

使用方法：
  python src/evaluate.py --model data/models/tracedae_best.pth --data data/processed/stgs/
"""

import os
import sys
import yaml
import argparse
import numpy as np
import torch
from typing import Dict, List, Tuple, Optional
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix,
    precision_recall_curve, average_precision_score,
    classification_report
)
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.dual_autoencoder import DualAutoencoder
from model.detector import AnomalyDetector, RootCauseLocalizer
from data.dataset import STGDataset, create_dataloader


class TraceDAEEvaluator:
    """
    TraceDAE 综合评估器

    评估异常检测和根因定位性能。
    """

    def __init__(self, model: DualAutoencoder, config: dict,
                 device: torch.device = None):
        """
        Args:
            model: 训练好的 DualAutoencoder 模型
            config: 配置字典
            device: 计算设备
        """
        self.model = model.to(device or torch.device('cpu'))
        self.config = config
        self.device = device or torch.device('cpu')

        # 初始化检测器
        detection_config = config.get('detection', {})
        self.anomaly_detector = AnomalyDetector(
            window_size=detection_config.get('window_size', 30),
            threshold=detection_config.get('z_score_threshold', 3.0)
        )
        self.root_cause_localizer = RootCauseLocalizer(
            alpha=config['model'].get('alpha', 0.1),
            theta=config['model'].get('theta', 40.0),
            eta=config['model'].get('eta', 5.0),
            top_k=detection_config.get('top_k', 5)
        )

    def evaluate_anomaly_detection(
        self,
        test_loader,
        normal_loader
    ) -> Dict[str, float]:
        """
        评估异常检测性能

        Args:
            test_loader: 测试集 DataLoader
            normal_loader: 正常数据 DataLoader（用于建立检测基线）

        Returns:
            评估指标字典
        """
        print("\n[评估] 异常检测性能评估")
        print("-" * 50)

        # Step 1: 收集正常数据的重构损失基线
        print("  收集正常数据损失基线...")
        self.model.eval()
        normal_losses = []

        with torch.no_grad():
            for data in normal_loader:
                data = data.to(self.device)
                _, adj_recon, _, x_recon = self.model(
                    data.x, data.edge_index, data.adj, data.attr_sequences
                )
                total_loss, _, _ = self.model.compute_loss(
                    data.adj, adj_recon, data.x, x_recon
                )
                normal_losses.append(total_loss.item())

        self.anomaly_detector.update_normal(normal_losses)
        mu, sigma = self.anomaly_detector.compute_statistics()
        print(f"  正常基线: μ={mu:.4f}, σ={sigma:.4f}")

        # Step 2: 在测试集上检测异常
        print("  异常检测推理...")
        y_true = []
        y_pred = []
        y_scores = []
        detection_results = []

        with torch.no_grad():
            for data in test_loader:
                data = data.to(self.device)

                _, adj_recon, _, x_recon = self.model(
                    data.x, data.edge_index, data.adj, data.attr_sequences
                )
                total_loss, struct_loss, attr_loss = self.model.compute_loss(
                    data.adj, adj_recon, data.x, x_recon
                )

                loss_value = total_loss.item()
                is_anomaly, score, threshold = self.anomaly_detector.detect(loss_value)

                # 获取真实标签
                true_label = int(data.y.item()) if hasattr(data, 'y') else 0

                y_true.append(true_label)
                y_pred.append(1 if is_anomaly else 0)
                y_scores.append(score)

                detection_results.append({
                    'trace_id': getattr(data, 'trace_id', 'unknown'),
                    'true_label': true_label,
                    'predicted': is_anomaly,
                    'loss': loss_value,
                    'score': score,
                    'struct_loss': struct_loss.item(),
                    'attr_loss': attr_loss.item(),
                })

        # Step 3: 计算评估指标
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        y_scores = np.array(y_scores)

        # 处理异常分数以计算 AUC
        # ROC-AUC 需要正确的分数方向：分数越高越可能是异常
        metrics = self._compute_detection_metrics(y_true, y_pred, y_scores)
        metrics['n_samples'] = len(y_true)
        metrics['n_anomalies'] = int(np.sum(y_true == 1))

        # 打印结果
        self._print_detection_metrics(metrics)

        return metrics, detection_results

    def _compute_detection_metrics(
        self, y_true: np.ndarray, y_pred: np.ndarray, y_scores: np.ndarray
    ) -> Dict[str, float]:
        """计算异常检测指标"""
        metrics = {}

        # 基本指标
        metrics['precision'] = precision_score(y_true, y_pred, zero_division=0)
        metrics['recall'] = recall_score(y_true, y_pred, zero_division=0)
        metrics['f1'] = f1_score(y_true, y_pred, zero_division=0)

        # ROC-AUC（仅当有两类时）
        if len(np.unique(y_true)) > 1:
            try:
                metrics['roc_auc'] = roc_auc_score(y_true, y_scores)
            except Exception:
                metrics['roc_auc'] = 0.0

            try:
                metrics['avg_precision'] = average_precision_score(y_true, y_scores)
            except Exception:
                metrics['avg_precision'] = 0.0
        else:
            metrics['roc_auc'] = 0.0
            metrics['avg_precision'] = 0.0

        # 混淆矩阵
        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        if cm.shape == (2, 2):
            tn, fp, fn, tp = cm.ravel()
            metrics['tp'] = int(tp)
            metrics['fp'] = int(fp)
            metrics['tn'] = int(tn)
            metrics['fn'] = int(fn)
            metrics['fpr'] = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        else:
            metrics['tp'] = metrics['fp'] = metrics['tn'] = metrics['fn'] = 0
            metrics['fpr'] = 0.0

        return metrics

    def _print_detection_metrics(self, metrics: Dict[str, float]):
        """打印异常检测指标"""
        print(f"\n  异常检测结果:")
        print(f"    样本数: {metrics.get('n_samples', 0)}")
        print(f"    异常样本: {metrics.get('n_anomalies', 0)}")
        print(f"    Precision: {metrics.get('precision', 0):.4f}")
        print(f"    Recall:    {metrics.get('recall', 0):.4f}")
        print(f"    F1-Score:  {metrics.get('f1', 0):.4f}")
        print(f"    ROC-AUC:   {metrics.get('roc_auc', 0):.4f}")
        if 'tp' in metrics:
            print(f"    混淆矩阵: TP={metrics['tp']}, FP={metrics['fp']}, "
                  f"TN={metrics['tn']}, FN={metrics['fn']}")

    def evaluate_root_cause_localization(
        self,
        test_loader,
        ground_truth: Dict
    ) -> Dict[str, float]:
        """
        评估根因定位性能

        Args:
            test_loader: 测试集 DataLoader
            ground_truth: {trace_id: [root_cause_node_indices]} 真值

        Returns:
            A@1, A@2, A@3 指标
        """
        print("\n[评估] 根因定位性能评估")
        print("-" * 50)

        self.model.eval()
        all_hits = {'a@1': [], 'a@2': [], 'a@3': [], 'a@5': []}

        with torch.no_grad():
            for data in test_loader:
                data = data.to(self.device)
                trace_id = getattr(data, 'trace_id', 'unknown')

                if trace_id not in ground_truth:
                    continue

                # 根因定位
                node_names = getattr(data, 'node_names', None)
                root_causes = self.root_cause_localizer.localize(
                    self.model, data, node_names
                )

                # 提取预测的节点索引
                predicted_nodes = [rc[0] for rc in root_causes]
                true_nodes = ground_truth[trace_id]

                # 计算命中率
                for k in [1, 2, 3, 5]:
                    if k <= len(predicted_nodes):
                        hits = sum(1 for p in predicted_nodes[:k] if p in true_nodes)
                        all_hits[f'a@{k}'].append(min(hits, 1))  # 二元：命中或未命中

        # 汇总指标
        metrics = {}
        for k, hits in all_hits.items():
            metrics[k] = np.mean(hits) if hits else 0.0

        print(f"\n  根因定位结果:")
        for k, v in metrics.items():
            print(f"    {k}: {v:.4f}")

        return metrics

    def evaluate_efficiency(self, test_loader) -> Dict[str, float]:
        """
        评估模型效率（训练/推理时间）

        Args:
            test_loader: 测试集 DataLoader

        Returns:
            {'avg_train_time_ms': ..., 'avg_inference_time_ms': ...}
        """
        print("\n[评估] 效率评估")
        print("-" * 50)

        self.model.eval()
        inference_times = []

        # 预热
        for data in test_loader:
            data = data.to(self.device)
            _ = self.model(data.x, data.edge_index, data.adj, data.attr_sequences)
            break

        # 测量推理时间
        with torch.no_grad():
            for data in test_loader:
                data = data.to(self.device_t)

                start_time = time.perf_counter()
                _ = self.model(data.x, data.edge_index, data.adj, data.attr_sequences)
                end_time = time.perf_counter()

                inference_times.append((end_time - start_time) * 1000)  # ms

        avg_inference_time = np.mean(inference_times)
        print(f"  平均推理时间: {avg_inference_time:.2f} ms/sample")
        print(f"  最小: {np.min(inference_times):.2f} ms, "
              f"最大: {np.max(inference_times):.2f} ms")

        return {
            'avg_inference_time_ms': avg_inference_time,
            'min_inference_time_ms': np.min(inference_times),
            'max_inference_time_ms': np.max(inference_times),
        }

    def generate_report(
        self,
        detection_metrics: Dict,
        rca_metrics: Dict,
        efficiency_metrics: Dict,
        dataset_name: str = "D1"
    ) -> str:
        """
        生成评估报告

        Args:
            detection_metrics: 异常检测指标
            rca_metrics: 根因定位指标
            efficiency_metrics: 效率指标
            dataset_name: 数据集名称

        Returns:
            报告字符串
        """
        report = f"""
{'='*60}
TraceDAE 评估报告 — {dataset_name} 数据集
{'='*60}

## 异常检测性能
  Precision:  {detection_metrics.get('precision', 0):.4f}
  Recall:     {detection_metrics.get('recall', 0):.4f}
  F1-Score:   {detection_metrics.get('f1', 0):.4f}
  ROC-AUC:    {detection_metrics.get('roc_auc', 0):.4f}

## 根因定位性能
  A@1:        {rca_metrics.get('a@1', 0):.4f}
  A@2:        {rca_metrics.get('a@2', 0):.4f}
  A@3:        {rca_metrics.get('a@3', 0):.4f}

## 效率评估
  推理时间:   {efficiency_metrics.get('avg_inference_time_ms', 0):.2f} ms/sample

## 论文对比（D1 数据集）
  指标          TraceDAE(论文)    TraceDAE(复现目标)
  Precision    0.971            ≥0.90
  Recall       0.935            ≥0.88
  F1           0.953            ≥0.89
  A@1          0.786            ≥0.65
  A@2          0.891            ≥0.78
  A@3          0.943            ≥0.85

{'='*60}
"""
        return report


def evaluate_standalone(config_path: str, model_path: str, data_dir: str):
    """
    独立评估脚本入口

    直接调用此函数进行端到端评估。
    """
    # 加载配置
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 加载模型
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
    model = DualAutoencoder(
        input_dim=config['model']['input_dim'],
        hidden_dim=config['model']['hidden_dim'],
        num_heads=config['model']['num_heads'],
        num_lstm_layers=config['model']['num_lstm_layers'],
    )
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # 加载数据
    test_dataset = STGDataset(data_dir, split='test', seed=config['training']['seed'])
    normal_dataset = STGDataset(data_dir, split='train', seed=config['training']['seed'],
                                 use_labels=False)

    test_loader = create_dataloader(test_dataset, batch_size=1, shuffle=False)
    normal_loader = create_dataloader(normal_dataset, batch_size=1, shuffle=False)

    # 评估
    evaluator = TraceDAEEvaluator(model, config, device)
    detection_metrics, _ = evaluator.evaluate_anomaly_detection(test_loader, normal_loader)
    efficiency_metrics = evaluator.evaluate_efficiency(test_loader)

    return detection_metrics, efficiency_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='TraceDAE 模型评估')
    parser.add_argument('--config', type=str, default='configs/default.yaml')
    parser.add_argument('--model', type=str, required=True, help='模型路径')
    parser.add_argument('--data', type=str, default='data/processed/stgs/')
    parser.add_argument('--dataset', type=str, default='D1', help='数据集名称')

    args = parser.parse_args()

    metrics, eff = evaluate_standalone(args.config, args.model, args.data)
    print(f"\n评估完成！F1-Score: {metrics.get('f1', 0):.4f}")
