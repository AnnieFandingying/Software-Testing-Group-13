"""
RobustScorer: Robust non-parametric hypothesis test for root cause analysis.
Uses median and IQR instead of mean and std for robustness.
"""

import numpy as np


class RobustScorer:
    """
    鲁棒非参数假设检验根因定位
    - 使用 median 和 IQR 替代 mean 和 std
    - 对异常检测时间不精确具有鲁棒性
    """

    def __init__(self, use_median_iqr=True):
        """
        - use_median_iqr: True 使用 median+IQR (BARO), False 使用 mean+std (基线)
        """
        self.use_median_iqr = use_median_iqr

    def _compute_location_scale(self, normal_data):
        """计算位置和尺度统计量"""
        if self.use_median_iqr:
            location = np.median(normal_data, axis=0)
            q75 = np.percentile(normal_data, 75, axis=0)
            q25 = np.percentile(normal_data, 25, axis=0)
            scale = q75 - q25  # IQR
            # 避免零 IQR
            scale = np.where(scale == 0, 1e-8, scale)
        else:
            location = np.mean(normal_data, axis=0)
            scale = np.std(normal_data, axis=0)
            scale = np.where(scale == 0, 1e-8, scale)
        return location, scale

    def score(self, metric_data, anomaly_time, window_before=60, window_after=60):
        """
        计算每个指标的根因分数
        - metric_data: [T, mn] 所有指标的完整时间序列
        - anomaly_time: 异常检测时间点 t̂_A
        - window_before: 正常期间窗口大小
        - window_after: 异常期间窗口大小
        返回: 排序后的根因排名列表 [(metric_idx, score), ...]
        """
        T, mn = metric_data.shape

        # 正常期间
        t_start = max(0, anomaly_time - window_before)
        normal_data = metric_data[t_start:anomaly_time]

        # 异常期间
        t_end = min(T, anomaly_time + window_after)
        anomaly_data = metric_data[anomaly_time:t_end]

        if len(normal_data) == 0 or len(anomaly_data) == 0:
            return [(i, 0.0) for i in range(mn)]

        # 学习正常分布
        location, scale = self._compute_location_scale(normal_data)

        # 计算每个指标的异常分数
        scores = np.zeros(mn)
        for j in range(mn):
            deviations = np.abs(anomaly_data[:, j] - location[j]) / scale[j]
            scores[j] = np.max(deviations)

        # 按 ρ 降序排列
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked

    def hypothesis_test(self, metric_data, anomaly_time, alpha=0.05):
        """
        假设检验版本
        - H0: 指标 x^(i,j) 不是根因指标
        """
        ranked_scores = self.score(metric_data, anomaly_time)

        n_metrics = len(ranked_scores)
        threshold = 1.0 - alpha / n_metrics

        significant = []
        for idx, score in ranked_scores:
            if score > threshold:
                significant.append((idx, score))
            else:
                break

        return significant
