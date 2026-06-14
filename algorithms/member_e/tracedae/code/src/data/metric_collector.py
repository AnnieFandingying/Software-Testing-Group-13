# -*- coding: utf-8 -*-
"""
TraceDAE Metric 数据采集器
==============================
负责从 cAdvisor 和 Prometheus 采集容器/服务级别的性能指标。
复现环境中支持两种模式：
  1. 模拟模式：生成符合真实分布的模拟 metric 数据
  2. 实时模式：通过 Prometheus API 采集（需要实际 K8s 集群）

指标维度：
  - timestamp: 时间戳
  - avg_response_time: 平均响应时间 (ms)
  - cpu_usage: CPU 使用率 (%)
  - memory_usage: 内存使用率 (%)
"""

import os
import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class MetricCollector:
    """
    Metric 数据采集器

    从 cAdvisor（容器级）和 Prometheus（持久化）采集性能指标。
    复现时优先使用模拟模式生成 synthetic 数据。
    """

    # 正常状态下的指标范围 [min, max]
    NORMAL_METRIC_RANGES = {
        'avg_response_time': (5.0, 100.0),    # ms
        'cpu_usage': (10.0, 60.0),            # %
        'memory_usage': (20.0, 70.0),         # %
    }

    # 异常状态下的指标范围
    ANOMALY_METRIC_RANGES = {
        'avg_response_time': (200.0, 5000.0),
        'cpu_usage': (85.0, 100.0),
        'memory_usage': (85.0, 100.0),
    }

    def __init__(self, data_source: str = "simulate", data_path: Optional[str] = None,
                 prometheus_url: Optional[str] = None, cadvisor_url: Optional[str] = None):
        """
        初始化 Metric 采集器

        Args:
            data_source: 数据源类型 ("simulate" | "csv" | "prometheus")
            data_path: 数据文件路径
            prometheus_url: Prometheus API 地址
            cadvisor_url: cAdvisor API 地址
        """
        self.data_source = data_source
        self.data_path = data_path
        self.prometheus_url = prometheus_url
        self.cadvisor_url = cadvisor_url
        self.metrics: Dict[str, np.ndarray] = {}  # span_id -> [timestamps, values]

    def generate_synthetic_metrics(
        self,
        service_names: List[str],
        num_timepoints: int = 100,
        sample_interval_sec: int = 15,
        anomaly_ratio: float = 0.11,  # 11.04% 论文数据
        seed: int = 42
    ) -> Dict[str, np.ndarray]:
        """
        生成模拟 metric 数据

        Args:
            service_names: 微服务名称列表
            num_timepoints: 每个服务的时间点数
            sample_interval_sec: 采样间隔（秒）
            anomaly_ratio: 异常数据占比
            seed: 随机种子

        Returns:
            {service_name: np.array([timestamp, response_time, cpu, memory])}
        """
        rng = np.random.default_rng(seed)
        base_time = datetime(2025, 6, 1).timestamp()

        for service in service_names:
            # 正常数据
            normal_count = int(num_timepoints * (1 - anomaly_ratio))
            normal_data = self._generate_normal_metrics(normal_count, base_time, sample_interval_sec, rng)

            # 异常数据
            anomaly_count = num_timepoints - normal_count
            anomaly_data = self._generate_anomaly_metrics(anomaly_count, base_time + normal_count * sample_interval_sec, sample_interval_sec, rng)

            self.metrics[service] = np.vstack([normal_data, anomaly_data])

        print(f"[MetricCollector] 生成 {len(service_names)} 个服务的模拟数据，"
              f"共 {num_timepoints} 个时间点/服务，异常占比 {anomaly_ratio:.1%}")
        return self.metrics

    def _generate_normal_metrics(self, count: int, start_time: float,
                                  interval: int, rng: np.random.Generator) -> np.ndarray:
        """生成正常指标数据"""
        timestamps = np.arange(start_time, start_time + count * interval, interval)
        data = np.zeros((count, 4))
        data[:, 0] = timestamps

        for i, key in enumerate(['avg_response_time', 'cpu_usage', 'memory_usage'], 1):
            low, high = self.NORMAL_METRIC_RANGES[key]
            # 添加时间趋势（小幅波动）
            trend = rng.normal(0, (high - low) * 0.05, count)
            base_values = rng.uniform(low, high, count)
            data[:, i] = np.clip(base_values + trend, low, high)

        return data

    def _generate_anomaly_metrics(self, count: int, start_time: float,
                                   interval: int, rng: np.random.Generator) -> np.ndarray:
        """生成异常指标数据"""
        timestamps = np.arange(start_time, start_time + count * interval, interval)
        data = np.zeros((count, 4))
        data[:, 0] = timestamps

        for i, key in enumerate(['avg_response_time', 'cpu_usage', 'memory_usage'], 1):
            low, high = self.ANOMALY_METRIC_RANGES[key]
            # 异常数据波动更大
            data[:, i] = rng.uniform(low, high, count)

        return data

    def load_metrics(self, path: Optional[str] = None) -> Dict[str, np.ndarray]:
        """从文件加载 metric 数据（CSV/JSON格式）"""
        target_path = path or self.data_path
        if not target_path:
            raise ValueError("必须提供数据路径")

        import pandas as pd
        if os.path.isdir(target_path):
            for f in os.listdir(target_path):
                if f.endswith('.csv'):
                    service_name = f.replace('.csv', '')
                    df = pd.read_csv(os.path.join(target_path, f))
                    self.metrics[service_name] = df.values
        else:
            df = pd.read_csv(target_path)
            self.metrics['default'] = df.values

        print(f"[MetricCollector] 成功加载 {len(self.metrics)} 个服务的 metric 数据")
        return self.metrics

    def fetch_prometheus_metrics(
        self,
        query: str = "container_cpu_usage_seconds_total",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        step: str = "15s"
    ) -> np.ndarray:
        """
        通过 Prometheus API 获取指标数据

        注意：需要实际部署的 Prometheus 环境。复现时优先使用模拟模式。
        """
        try:
            import requests

            if not self.prometheus_url:
                raise ValueError("未配置 Prometheus URL")

            params = {
                'query': query,
                'start': start_time.timestamp() if start_time else None,
                'end': end_time.timestamp() if end_time else None,
                'step': step,
            }
            params = {k: v for k, v in params.items() if v is not None}

            resp = requests.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            result = resp.json()
            values = result['data']['result']
            if values:
                return np.array([[float(v[0]), float(v[1])] for v in values[0]['values']])
            return np.array([])
        except ImportError:
            print("[警告] requests 库未安装，跳过 Prometheus 采集")
            return np.array([])
        except Exception as e:
            print(f"[错误] Prometheus 采集失败: {e}")
            return np.array([])

    def get_metrics(self, span_id: str) -> np.ndarray:
        """获取指定 span 的指标数据"""
        return self.metrics.get(span_id, np.zeros((1, 4)))

    def save_metrics(self, output_dir: str) -> None:
        """保存 metric 数据到 CSV 文件"""
        os.makedirs(output_dir, exist_ok=True)
        import pandas as pd
        for service, data in self.metrics.items():
            df = pd.DataFrame(data, columns=['timestamp', 'avg_response_time', 'cpu_usage', 'memory_usage'])
            df.to_csv(os.path.join(output_dir, f"{service}.csv"), index=False)
        print(f"[MetricCollector] Metric 数据已保存至: {output_dir}")

    def add_anomaly_labels(self, metrics: np.ndarray,
                            anomaly_indices: List[int]) -> np.ndarray:
        """
        为指标数据添加异常标签列

        Args:
            metrics: [N, 4] 指标矩阵
            anomaly_indices: 异常时间点索引列表

        Returns:
            [N, 5] 添加了标签的指标矩阵
        """
        labels = np.zeros((metrics.shape[0], 1))
        labels[anomaly_indices] = 1
        return np.hstack([metrics, labels])


if __name__ == "__main__":
    # 示例：生成模拟数据
    collector = MetricCollector(data_source="simulate")
    services = ["ts-travel-service", "ts-order-service", "ts-user-service",
                 "ts-station-service", "ts-train-service"]
    metrics = collector.generate_synthetic_metrics(services, num_timepoints=500)
    print(f"生成了 {len(metrics)} 个服务的模拟 metric 数据")
    for svc, data in metrics.items():
        print(f"  {svc}: shape={data.shape}")
