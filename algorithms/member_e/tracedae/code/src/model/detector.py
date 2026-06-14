# -*- coding: utf-8 -*-
"""
TraceDAE 异常检测器与根因定位
================================
基于论文第 3.6 节的异常检测算法和根因定位方法。

异常检测（Z-score 方法）：
  Anomaly Score(x_i) = |x_i - μ_x| / σ_x
  阈值 γ = μ_x + 3σ_x（30分钟时间窗口）

根因定位（逐节点重构误差）：
  S_i = α ||A_i - Â_i ∘ θ||²_F + (1-α) ||X_i - X̂_i ∘ η||²_F
  Top-k 节点为根因
"""

import torch
import numpy as np
from typing import List, Tuple, Dict, Optional
from collections import deque


class AnomalyDetector:
    """
    基于 Z-score 的异常检测器

    使用滑动窗口维护正常数据的均值和标准差，
    对每个新样本计算 Z-score 判定是否异常。
    """

    def __init__(self, window_size: int = 30, threshold: float = 3.0,
                 method: str = 'zscore'):
        """
        Args:
            window_size: 时间窗口大小（论文使用 30 分钟）
            threshold: Z-score 阈值（论文使用 3σ，即 3.0）
            method: 检测方法 ('zscore' | 'kde' | 'mad')
        """
        self.window_size = window_size
        self.threshold = threshold
        self.method = method

        # 滑动窗口存储正常损失值
        self.normal_losses = deque(maxlen=1000)
        self.anomaly_history = []

    def update_normal(self, loss_values: List[float]) -> None:
        """
        更新正常数据基线

        Args:
            loss_values: 训练集正常样本的重构损失
        """
        self.normal_losses.extend(loss_values)
        # 限制窗口大小
        while len(self.normal_losses) > 10000:
            self.normal_losses.popleft()

    def compute_statistics(self) -> Tuple[float, float]:
        """
        计算正常数据统计量

        Returns:
            mu: 均值
            sigma: 标准差
        """
        if not self.normal_losses:
            return 0.0, 1.0

        normal_array = np.array(list(self.normal_losses))
        mu = np.mean(normal_array)
        sigma = np.std(normal_array)
        return mu, sigma

    def compute_anomaly_score(self, loss_value: float) -> float:
        """
        计算 Z-score 异常分数

        score = |loss - μ| / σ

        Args:
            loss_value: 当前样本的重构损失

        Returns:
            z_score: 异常分数
        """
        mu, sigma = self.compute_statistics()

        if sigma == 0:
            return 0.0

        if self.method == 'zscore':
            score = abs(loss_value - mu) / sigma
        elif self.method == 'mad':
            score = self._compute_mad_score(loss_value)
        elif self.method == 'kde':
            score = self._compute_kde_score(loss_value)
        else:
            score = abs(loss_value - mu) / sigma

        return score

    def _compute_mad_score(self, loss_value: float) -> float:
        """
        使用 MAD（Median Absolute Deviation）计算异常分数

        MAD 对异常值比标准差更鲁棒
        """
        if not self.normal_losses:
            return 0.0

        normal_array = np.array(list(self.normal_losses))
        median = np.median(normal_array)
        mad = np.median(np.abs(normal_array - median))

        if mad == 0:
            return 0.0

        # 使用修正因子 1.4826 使 MAD 与标准差可比
        return abs(loss_value - median) / (mad * 1.4826)

    def _compute_kde_score(self, loss_value: float) -> float:
        """
        使用核密度估计（KDE）计算异常分数

        KDE 不假设数据服从正态分布
        """
        try:
            from scipy.stats import gaussian_kde
            if not self.normal_losses:
                return 0.0
            normal_array = np.array(list(self.normal_losses))
            kde = gaussian_kde(normal_array)
            density = kde.evaluate(loss_value)[0]
            max_density = max(kde.evaluate(normal_array))

            if max_density == 0:
                return 0.0

            # 密度越低，异常分数越高
            score = 1 - (density / max_density)
            return score
        except ImportError:
            return self.compute_anomaly_score(loss_value)

    def detect(self, loss_value: float) -> Tuple[bool, float, float]:
        """
        异常检测判断

        Args:
            loss_value: 重构损失值

        Returns:
            is_anomaly: 是否异常
            score: 异常分数
            threshold_value: 判定阈值
        """
        mu, sigma = self.compute_statistics()
        score = self.compute_anomaly_score(loss_value)

        # 动态阈值：μ + 3σ
        threshold_value = mu + self.threshold * sigma

        if self.method in ('zscore', 'mad'):
            is_anomaly = score > self.threshold
        else:
            is_anomaly = score > 0.5  # KDE 阈值

        # 更新检测历史
        self.anomaly_history.append({
            'loss': loss_value,
            'score': score,
            'threshold': threshold_value,
            'is_anomaly': is_anomaly,
            'mu': mu,
            'sigma': sigma
        })

        return is_anomaly, score, threshold_value

    def detect_batch(self, losses: List[float]) -> List[Dict]:
        """
        批量检测异常

        Args:
            losses: 损失值列表

        Returns:
            results: 检测结果列表
        """
        results = []
        for loss in losses:
            is_anomaly, score, threshold = self.detect(loss)
            results.append({
                'loss': loss,
                'score': score,
                'is_anomaly': is_anomaly,
                'threshold': threshold
            })
        return results


class RootCauseLocalizer:
    """
    根因定位器

    对异常 STG 的每个节点计算结构和属性的重构误差，
    异常分数最高的 Top-k 个节点为根因。

    节点异常分数：
      S_i = α Σ (A_{i,j} - Â_{i,j})²·θ_{i,j} + (1-α) Σ (X_i - X̂_i)²·η
    """

    def __init__(self, alpha: float = 0.1, theta: float = 40.0,
                 eta: float = 5.0, top_k: int = 5):
        """
        Args:
            alpha: 结构/属性平衡参数
            theta: 结构非零惩罚权重
            eta: 属性非零惩罚权重
            top_k: 返回 Top-k 根因节点
        """
        self.alpha = alpha
        self.theta = theta
        self.eta = eta
        self.top_k = top_k

    def localize(
        self,
        model,
        stg_data,
        node_names: Optional[List[str]] = None
    ) -> List[Tuple[int, float, str]]:
        """
        定位根因微服务

        对每个节点计算重构误差，返回 Top-k 异常分数最高的节点。

        Args:
            model: DualAutoencoder 模型实例
            stg_data: STG 图数据
            node_names: 节点名称列表（可选）

        Returns:
            root_causes: [(node_index, score, name), ...] 按分数降序
        """
        model.eval()

        with torch.no_grad():
            # 获取重构结果
            x = stg_data.x.cuda() if next(model.parameters()).is_cuda else stg_data.x
            edge_index = stg_data.edge_index.cuda() if next(model.parameters()).is_cuda else stg_data.edge_index
            adj = stg_data.adj.cuda() if next(model.parameters()).is_cuda else stg_data.adj
            attr_seq = stg_data.attr_sequences.cuda() if next(model.parameters()).is_cuda else stg_data.attr_sequences

            z_v, adj_recon, z_a, x_recon = model(x, edge_index, adj, attr_seq)

            num_nodes = x.size(0)
            node_scores = []

            for i in range(num_nodes):
                # 结构误差（该节点的邻接行）
                adj_original_row = adj[i]
                adj_recon_row = adj_recon[i]

                weight = torch.where(adj_original_row > 0, self.theta, torch.ones_like(adj_original_row))
                struct_err = torch.sum(weight * (adj_original_row - adj_recon_row) ** 2).item()

                # 属性误差（该节点的属性重构误差）
                # 注意：需要从原始属性和重构属性中提取该节点的部分
                if x.dim() == 2:
                    attr_err = torch.sum((x[i] - x_recon[0, -1, i * 4:(i+1) * 4].unsqueeze(0)) ** 2).item() if x_recon.dim() == 3 else 0.0
                else:
                    attr_err = 0.0

                # 简化属性误差：使用 GAT 嵌入的重构差
                if not hasattr(stg_data, 'x_recon'):
                    # 使用节点嵌入的 L2 距离作为代理
                    attr_err = torch.norm(z_v[i], p=2).item() * 0.01

                # 加权异常分数
                # S_i = α * struct_err + (1-α) * attr_err
                score = self.alpha * struct_err + (1 - self.alpha) * attr_err

                node_name = node_names[i] if node_names and i < len(node_names) else f"node_{i}"
                node_scores.append((i, score, node_name))

        # 按分数降序排列
        node_scores.sort(key=lambda x: x[1], reverse=True)

        return node_scores[:self.top_k]

    def localize_batch(
        self,
        model,
        stg_batch,
        node_names: Optional[List[str]] = None
    ) -> Dict[str, List]:
        """
        批量根因定位

        Args:
            model: 模型实例
            stg_batch: STG 数据批次
            node_names: 节点名称

        Returns:
            results: {'trace_id': [...root_causes...]}
        """
        results = {}
        for idx in range(len(stg_batch)):
            data = stg_batch[idx] if isinstance(stg_batch, list) else stg_batch
            trace_id = getattr(data, 'trace_id', str(idx))
            root_causes = self.localize(model, data, node_names)
            results[trace_id] = root_causes
        return results

    def evaluate_hits(
        self,
        predicted: List[int],  # 预测的根因节点索引
        ground_truth: List[int]  # 真实的根因节点索引
    ) -> Dict[str, float]:
        """
        评估根因定位命中率

        Args:
            predicted: 预测的 Top-k 节点索引列表
            ground_truth: 真实的根因节点索引列表

        Returns:
            {'a@1', 'a@2', 'a@3', 'a@5'}: 各 Top-k 命中率
        """
        gt_set = set(ground_truth)

        metrics = {}
        for k in [1, 2, 3, 5, 10]:
            if k <= len(predicted):
                hits = sum(1 for p in predicted[:k] if p in gt_set)
                metrics[f'a@{k}'] = hits / min(k, len(gt_set))

        return metrics


def compute_node_anomaly_scores(
    model,
    stg_data,
    alpha: float = 0.1,
    theta: float = 40.0,
    eta: float = 5.0
) -> np.ndarray:
    """
    独立计算节点的异常分数（不依赖 RootCauseLocalizer 类）

    Args:
        model: DualAutoencoder 模型
        stg_data: 单个 STG 数据
        alpha: 结构权重
        theta: 结构惩罚
        eta: 属性惩罚

    Returns:
        scores: 节点异常分数 [num_nodes]
    """
    model.eval()
    device = next(model.parameters()).device

    x = stg_data.x.to(device)
    edge_index = stg_data.edge_index.to(device)
    adj = stg_data.adj.to(device)

    with torch.no_grad():
        # 结构重构
        z_v, adj_recon = model.structure_ae(x, edge_index)

        num_nodes = x.size(0)
        scores = np.zeros(num_nodes)

        for i in range(num_nodes):
            # 结构误差
            weight = torch.where(adj[i] > 0, theta, torch.ones_like(adj[i]))
            struct_err = torch.mean(weight * (adj[i] - adj_recon[i]) ** 2).item()

            # 属性误差（节点嵌入变化）
            attr_err = torch.norm(z_v[i], p=2).item() * 0.01

            scores[i] = alpha * struct_err + (1 - alpha) * attr_err

    return scores


if __name__ == "__main__":
    print("AnomalyDetector 与 RootCauseLocalizer 测试")
    print("=" * 60)

    # 测试异常检测
    detector = AnomalyDetector(window_size=30, threshold=3.0)

    # 模拟正常数据
    normal_losses = [0.5 + np.random.randn() * 0.1 for _ in range(100)]
    detector.update_normal(normal_losses)

    # 测试正常样本
    normal_score = detector.compute_anomaly_score(0.55)
    is_anomaly, score, threshold = detector.detect(0.55)
    print(f"正常样本: score={score:.3f}, threshold={threshold:.3f}, anomaly={is_anomaly}")

    # 测试异常样本
    anomaly_score = detector.compute_anomaly_score(2.0)
    is_anomaly, score, threshold = detector.detect(2.0)
    print(f"异常样本: score={score:.3f}, threshold={threshold:.3f}, anomaly={is_anomaly}")

    # 测试 MAD 方法
    mad_detector = AnomalyDetector(window_size=30, threshold=3.0, method='mad')
    mad_detector.update_normal(normal_losses)
    mad_score = mad_detector.compute_anomaly_score(2.0)
    print(f"MAD 异常分数: {mad_score:.3f}")

    print("\nRootCauseLocalizer 初始化完成")
