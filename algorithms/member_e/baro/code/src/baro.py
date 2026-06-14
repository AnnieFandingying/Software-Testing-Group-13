"""
BARO: Robust Root Cause Analysis for Microservices
Main algorithm integrating Multivariate BOCPD and RobustScorer.
"""

import numpy as np
from src.bocpd.multivariate import MultivariateBOCPD
from src.scorer.robust_scorer import RobustScorer


class BARO:
    """
    BARO: 端到端异常检测 + 根因分析
    Algorithm 1:
      1. Multivariate BOCPD → 异常检测 + 异常时间
      2. RobustScorer → 根因排名
    """

    def __init__(self, n_metrics, hazard_rate=100, N0=None,
                 sigma_hat=None, use_robust_scorer=True):
        self.detector = MultivariateBOCPD(
            n_metrics=n_metrics,
            hazard_rate=hazard_rate,
            N0=N0,
            sigma_hat=sigma_hat
        )
        self.scorer = RobustScorer(use_median_iqr=use_robust_scorer)

    def analyze(self, metric_data, latency_error_indices):
        """
        端到端分析
        - metric_data: [T, total_metrics] 所有指标的时间序列
        - latency_error_indices: Latency 和 Errors 指标的列索引
        返回: (is_anomaly, anomaly_time, root_cause_ranking)
        """
        # Step 1: 异常检测（仅使用 Latency 和 Errors 指标）
        le_data = metric_data[:, latency_error_indices]
        is_anomaly, anomaly_time = self.detector.detect_anomaly(le_data)

        if not is_anomaly:
            return False, -1, []

        # Step 2: 根因定位（使用全部指标）
        root_causes = self.scorer.score(
            metric_data, anomaly_time
        )

        return True, anomaly_time, root_causes

    def top_k_accuracy(self, prediction_ranking, ground_truth, k=1):
        """计算 Top-k Accuracy"""
        top_k_predicted = set(idx for idx, _ in prediction_ranking[:k])
        gt_set = set(ground_truth)
        return len(top_k_predicted & gt_set) / len(gt_set) if gt_set else 0

    def reset(self):
        """重置模型状态"""
        self.detector.reset()
