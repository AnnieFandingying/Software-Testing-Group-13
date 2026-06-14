"""
Synthetic data generator for BARO validation.
Generates microservice metric data with injected faults for testing.
"""

import numpy as np


class SyntheticDataGenerator:
    """
    模拟微服务指标数据生成器
    生成包含正常期和故障期的多元时间序列数据
    """

    def __init__(self, n_services=5, metrics_per_service=4, seed=None):
        """
        - n_services: 服务数量
        - metrics_per_service: 每个服务的指标数（latency, error, traffic, cpu）
        """
        self.n_services = n_services
        self.metrics_per_service = metrics_per_service
        self.n_metrics = n_services * metrics_per_service
        self.rng = np.random.RandomState(seed)

    def generate_normal_data(self, n_steps, base_mean=0.0, noise_std=0.02):
        """生成正常期间的指标数据（均值为0，低噪声，符合BOCPD模型假设）"""
        data = np.zeros((n_steps, self.n_metrics))
        for i in range(self.n_metrics):
            data[:, i] = self.rng.normal(base_mean, noise_std, n_steps)
        return data

    def inject_fault(self, data, fault_type, target_service, fault_start, fault_duration):
        """
        向数据中注入故障（数据均值为0，故障导致显著偏离）
        - fault_type: 'cpu_hog', 'memory_leak', 'network_delay', 'packet_loss'
        - target_service: 目标服务索引 (0-based)
        - fault_start: 故障开始时间步
        - fault_duration: 故障持续时间
        """
        faulty_data = data.copy()
        end = min(fault_start + fault_duration, len(data))

        # 目标服务的指标索引范围
        svc_start = target_service * self.metrics_per_service
        latency_idx = svc_start
        error_idx = svc_start + 1
        traffic_idx = svc_start + 2
        cpu_idx = svc_start + 3

        if fault_type == 'cpu_hog':
            # CPU飙升，延迟增加，错误率上升
            faulty_data[fault_start:end, cpu_idx] += self.rng.uniform(1.5, 3.0, end - fault_start)
            faulty_data[fault_start:end, latency_idx] += self.rng.uniform(1.0, 2.5, end - fault_start)
            faulty_data[fault_start:end, error_idx] += self.rng.uniform(0.5, 1.5, end - fault_start)

        elif fault_type == 'memory_leak':
            # 内存泄漏导致延迟逐渐增加，错误率上升
            for t in range(fault_start, end):
                progress = (t - fault_start) / max(1, fault_duration)
                faulty_data[t, latency_idx] += progress * self.rng.uniform(1.0, 2.5)
                faulty_data[t, error_idx] += progress * self.rng.uniform(0.5, 1.5)

        elif fault_type == 'network_delay':
            # 网络延迟显著增加
            faulty_data[fault_start:end, latency_idx] += self.rng.uniform(2.0, 4.0, end - fault_start)
            faulty_data[fault_start:end, error_idx] += self.rng.uniform(0.3, 1.0, end - fault_start)

        elif fault_type == 'packet_loss':
            # 丢包导致错误率飙升
            faulty_data[fault_start:end, error_idx] += self.rng.uniform(1.5, 3.5, end - fault_start)
            faulty_data[fault_start:end, latency_idx] += self.rng.uniform(0.5, 1.5, end - fault_start)

        # 故障传播：相邻服务受影响（简化模型）
        if target_service > 0:
            prev_svc_start = (target_service - 1) * self.metrics_per_service
            faulty_data[fault_start:end, prev_svc_start] += 0.5
            faulty_data[fault_start:end, prev_svc_start + 1] += 0.3

        if target_service < self.n_services - 1:
            next_svc_start = (target_service + 1) * self.metrics_per_service
            faulty_data[fault_start:end, next_svc_start] += 0.5
            faulty_data[fault_start:end, next_svc_start + 1] += 0.3

        return faulty_data

    def generate_case(self, n_steps=300, fault_type='cpu_hog', target_service=0,
                      fault_start=150, fault_duration=60):
        """生成一个完整的故障案例（故障前稳定，故障后显著偏离）"""
        data = self.generate_normal_data(n_steps)
        data = self.inject_fault(data, fault_type, target_service, fault_start, fault_duration)

        # 标注根因指标（故障目标服务的所有指标）
        svc_start = target_service * self.metrics_per_service
        ground_truth = list(range(svc_start, svc_start + self.metrics_per_service))

        return data, ground_truth, fault_start

    def generate_simple_case(self, n_steps=200, target_service=0, fault_start=100):
        """生成简单明确的故障案例（用于验证BOCPD）"""
        data = np.zeros((n_steps, self.n_metrics))
        # 正常期间：均值为0，低噪声
        for i in range(self.n_metrics):
            data[:, i] = self.rng.normal(0, 0.02, n_steps)

        # 故障期间：目标服务的latency和error显著增加
        svc_start = target_service * self.metrics_per_service
        end = min(fault_start + 60, n_steps)
        data[fault_start:end, svc_start] += self.rng.uniform(3.0, 5.0, end - fault_start)
        data[fault_start:end, svc_start + 1] += self.rng.uniform(2.0, 4.0, end - fault_start)

        ground_truth = list(range(svc_start, svc_start + self.metrics_per_service))
        return data, ground_truth, fault_start

    def generate_dataset(self, n_cases=20, n_services=5, fault_types=None):
        """生成多个故障案例的数据集"""
        if fault_types is None:
            fault_types = ['cpu_hog', 'memory_leak', 'network_delay', 'packet_loss']

        dataset = []
        for i in range(n_cases):
            fault_type = fault_types[i % len(fault_types)]
            target_service = i % n_services
            data, gt, fault_start = self.generate_case(
                fault_type=fault_type,
                target_service=target_service
            )
            dataset.append({
                'data': data,
                'ground_truth': gt,
                'fault_type': fault_type,
                'target_service': target_service,
                'fault_start': fault_start
            })

        return dataset
