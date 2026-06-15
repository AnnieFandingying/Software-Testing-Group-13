"""
Evaluation module for BARO and baseline methods.
Computes anomaly detection and root cause analysis metrics.
"""

import numpy as np


class Evaluator:
    """
    评估器：计算异常检测和根因分析指标
    """

    def __init__(self):
        pass

    @staticmethod
    def anomaly_detection_metrics(predictions, labels):
        """
        计算异常检测指标
        - predictions: 列表，每个元素为 (is_anomaly, anomaly_time)
        - labels: 列表，每个元素为 (true_is_anomaly, true_anomaly_time)
        返回: dict with precision, recall, f1
        """
        tp = fp = fn = 0

        for (pred_anomaly, pred_time), (true_anomaly, true_time) in zip(predictions, labels):
            if pred_anomaly and true_anomaly:
                # 允许一定时间窗口内的偏移
                if abs(pred_time - true_time) <= 10:
                    tp += 1
                else:
                    fp += 1
                    fn += 1
            elif pred_anomaly and not true_anomaly:
                fp += 1
            elif not pred_anomaly and true_anomaly:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return {
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'tp': tp,
            'fp': fp,
            'fn': fn
        }

    @staticmethod
    def rca_top_k_accuracy(predictions, ground_truths, k_values=[1, 2, 3]):
        """
        计算根因分析 Top-k Accuracy
        - predictions: 列表，每个元素为根因排名 [(metric_idx, score), ...]
        - ground_truths: 列表，每个元素为真实根因指标索引列表
        返回: dict with A@k for each k
        """
        results = {}

        for k in k_values:
            correct = 0
            total = 0

            for ranking, gt in zip(predictions, ground_truths):
                if len(ranking) == 0 or len(gt) == 0:
                    continue

                top_k_predicted = set(idx for idx, _ in ranking[:k])
                gt_set = set(gt)

                # 如果预测命中了任何真实根因指标，则计为正确
                if len(top_k_predicted & gt_set) > 0:
                    correct += 1
                total += 1

            results[f'A@{k}'] = correct / total if total > 0 else 0.0

        return results

    @staticmethod
    def robustness_test(baro_model, data_cases, time_shifts=[-3, -2, -1, 0, 1, 2, 3]):
        """
        测试 RobustScorer 对异常检测时间偏移的鲁棒性
        - time_shifts: 模拟异常检测时间的偏移量
        返回: dict with A@k for each time shift
        """
        results = {}

        for shift in time_shifts:
            rankings = []
            for case in data_cases:
                data = case['data']
                true_time = case['fault_start']
                shifted_time = max(0, true_time + shift)

                ranking = baro_model.scorer.score(data, shifted_time)
                rankings.append(ranking)

            gt_list = [case['ground_truth'] for case in data_cases]
            acc = Evaluator.rca_top_k_accuracy(rankings, gt_list, k_values=[1, 2, 3])
            results[shift] = acc

        return results
