# -*- coding: utf-8 -*-
"""
TraceDAE DBSCAN 降噪模块
============================
使用 DBSCAN 聚类过滤离群噪声数据，提高后续异常检测准确性。

原理：
  1. 将 STG 特征展平为向量
  2. 使用 DBSCAN 聚类识别离群点
  3. 移除 label = -1（噪声点）
"""

import numpy as np
from typing import List, Optional, Tuple
from sklearn.cluster import DBSCAN
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


class DBSCANDenoiser:
    """
    DBSCAN 降噪器

    对 Service Trace Graph 的特征矩阵进行聚类降噪，
    过滤掉远离主聚类的离群噪声数据点。
    """

    def __init__(self, eps: float = 0.5, min_samples: int = 5,
                 metric: str = 'euclidean', n_jobs: int = -1):
        """
        初始化 DBSCAN 降噪器

        Args:
            eps: DBSCAN 邻域半径（论文未给出具体值，默认 0.5）
            min_samples: 核心点最少邻域样本数（论文未给出，默认 5）
            metric: 距离度量方式
            n_jobs: 并行线程数（-1 表示全部）
        """
        self.eps = eps
        self.min_samples = min_samples
        self.metric = metric
        self.n_jobs = n_jobs
        self.scaler = StandardScaler()
        self.labels_: Optional[np.ndarray] = None
        self.n_clusters_: int = 0
        self.noise_ratio_: float = 0.0

    def denoise(self, features: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        对特征矩阵进行 DBSCAN 降噪

        Args:
            features: 特征矩阵 [num_samples, feature_dim]
                      可以是 STG 的展平特征或图级别嵌入

        Returns:
            valid_indices: 保留的样本索引 (非噪声点)
            labels: 聚类标签 (-1 表示噪声点)

        Raises:
            ValueError: 如果输入特征为空
        """
        if len(features) == 0:
            raise ValueError("输入特征为空")

        # 标准化
        features_scaled = self.scaler.fit_transform(features)

        # DBSCAN 聚类
        clustering = DBSCAN(
            eps=self.eps,
            min_samples=self.min_samples,
            metric=self.metric,
            n_jobs=self.n_jobs,
        )
        self.labels_ = clustering.fit_predict(features_scaled)

        # 统计噪声比例
        noise_mask = self.labels_ == -1
        self.noise_ratio_ = np.mean(noise_mask)
        self.n_clusters_ = len(set(self.labels_)) - (1 if -1 in self.labels_ else 0)

        # 保留非噪声点
        valid_indices = np.where(~noise_mask)[0]

        print(f"[DBSCANDenoiser] 降噪完成:")
        print(f"  原始样本数: {len(features)}")
        print(f"  保留样本数: {len(valid_indices)}")
        print(f"  噪声比例: {self.noise_ratio_:.2%}")
        print(f"  聚类数: {self.n_clusters_}")

        return valid_indices, self.labels_

    def optimize_eps(self, features: np.ndarray,
                     eps_range: Optional[List[float]] = None) -> float:
        """
        使用 k-distance graph 方法优化 eps 参数

        通过在特征空间中计算 k-近邻距离来选择合适的 eps 值。

        Args:
            features: 特征矩阵
            eps_range: eps 候选范围，None 则自动生成

        Returns:
            最优 eps 值
        """
        from sklearn.neighbors import NearestNeighbors

        features_scaled = self.scaler.fit_transform(features)

        if eps_range is None:
            # 基于数据分布自动生成范围
            neigh = NearestNeighbors(n_neighbors=self.min_samples)
            neigh.fit(features_scaled)
            distances, _ = neigh.kneighbors(features_scaled)
            k_distances = np.sort(distances[:, -1])

            # 在 k-distance 曲线拐点附近采样
            candidate_indices = np.linspace(
                int(len(k_distances) * 0.1),
                int(len(k_distances) * 0.9),
                20
            ).astype(int)
            eps_range = k_distances[candidate_indices]

        best_eps = self.eps
        best_score = -1

        for eps in eps_range:
            try:
                clustering = DBSCAN(
                    eps=eps,
                    min_samples=self.min_samples,
                    metric=self.metric,
                    n_jobs=self.n_jobs,
                )
                labels = clustering.fit_predict(features_scaled)

                # 过滤单聚类（全噪声）情况
                unique_labels = set(labels)
                n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)

                if n_clusters >= 2 and len(unique_labels) > 1:
                    # 计算轮廓系数
                    valid_mask = labels != -1
                    if valid_mask.sum() > n_clusters:
                        score = silhouette_score(
                            features_scaled[valid_mask],
                            labels[valid_mask]
                        )
                    else:
                        score = 0

                    # 目标：高轮廓系数 + 低噪声比
                    noise_ratio = np.mean(labels == -1)
                    combined_score = score * (1 - noise_ratio)

                    if combined_score > best_score:
                        best_score = combined_score
                        best_eps = eps
            except Exception:
                continue

        self.eps = best_eps
        print(f"[DBSCANDenoiser] 优化 eps = {best_eps:.4f}")
        return best_eps

    def optimize_min_samples(self, features: np.ndarray,
                              sample_range: Optional[List[int]] = None) -> int:
        """
        优化 min_samples 参数

        Args:
            features: 特征矩阵
            sample_range: min_samples 候选范围

        Returns:
            最优 min_samples 值
        """
        if sample_range is None:
            # 经验规则：min_samples ≥ 特征维度 + 1 且 ≥ 2 * 特征维度
            dim = features.shape[1]
            sample_range = list(range(max(2, dim + 1), max(5, 2 * dim + 1)))

        best_ms = self.min_samples
        best_score = -1

        features_scaled = self.scaler.fit_transform(features)

        for ms in sample_range:
            if ms >= len(features):
                continue
            try:
                clustering = DBSCAN(
                    eps=self.eps,
                    min_samples=ms,
                    metric=self.metric,
                    n_jobs=self.n_jobs,
                )
                labels = clustering.fit_predict(features_scaled)

                unique_labels = set(labels)
                n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)

                if n_clusters >= 2:
                    valid_mask = labels != -1
                    if valid_mask.sum() > n_clusters:
                        score = silhouette_score(
                            features_scaled[valid_mask],
                            labels[valid_mask]
                        )
                    else:
                        score = 0

                    noise_ratio = np.mean(labels == -1)
                    combined_score = score * (1 - noise_ratio)

                    if combined_score > best_score:
                        best_score = combined_score
                        best_ms = ms
            except Exception:
                continue

        self.min_samples = best_ms
        print(f"[DBSCANDenoiser] 优化 min_samples = {best_ms}")
        return best_ms

    def get_statistics(self) -> dict:
        """获取降噪统计信息"""
        if self.labels_ is None:
            return {}
        noise_count = int(np.sum(self.labels_ == -1))
        cluster_counts = []
        for label in set(self.labels_):
            if label != -1:
                cluster_counts.append(int(np.sum(self.labels_ == label)))
        return {
            'n_clusters': self.n_clusters_,
            'noise_ratio': self.noise_ratio_,
            'noise_count': noise_count,
            'cluster_sizes': cluster_counts,
            'avg_cluster_size': np.mean(cluster_counts) if cluster_counts else 0,
        }


class KDistanceOptimizer:
    """
    k-distance graph 方法辅助 eps 选择

    论文未给出具体 eps 值，建议使用 k-distance graph 方法确定。
    """

    @staticmethod
    def compute_k_distance_graph(features: np.ndarray, k: int = 5) -> np.ndarray:
        """
        计算 k-distance graph

        Args:
            features: 特征矩阵
            k: 近邻数

        Returns:
            排序后的第 k 近邻距离
        """
        from sklearn.neighbors import NearestNeighbors

        neigh = NearestNeighbors(n_neighbors=k)
        neigh.fit(features)
        distances, _ = neigh.kneighbors(features)
        return np.sort(distances[:, -1])

    @staticmethod
    def find_elbow_point(sorted_distances: np.ndarray) -> int:
        """
        在 k-distance 曲线上找到拐点

        Args:
            sorted_distances: 排序后的 k-近邻距离

        Returns:
            拐点索引
        """
        n = len(sorted_distances)
        if n < 3:
            return n // 2

        # 使用二阶差分找拐点
        line = np.linspace(sorted_distances[0], sorted_distances[-1], n)
        distances_from_line = sorted_distances - line
        return np.argmax(distances_from_line)


if __name__ == "__main__":
    # 测试 DBSCAN 降噪
    np.random.seed(42)

    # 生成正常聚类数据 + 噪声
    X_normal = np.random.randn(800, 4) * 0.5
    X_noise = np.random.randn(50, 4) * 3  # 离群噪声
    X = np.vstack([X_normal, X_noise])

    denoiser = DBSCANDenoiser(eps=0.5, min_samples=5)
    valid_indices, labels = denoiser.denoise(X)
    print(f"\n降噪统计: {denoiser.get_statistics()}")
    print(f"保留样本: {len(valid_indices)}/{len(X)}")
