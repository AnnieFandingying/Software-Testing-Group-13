# -*- coding: utf-8 -*-
"""
TraceDAE Service Trace Graph (STG) 构建器
=============================================
实现论文 Algorithm 1：基于 trace 和 metric 数据构建 Service Trace Graph。

STG = {V, E, X}
  V: 服务节点（以 Span ID 标识）
  E: 服务调用边（有向边，从源服务到目标服务）
  X: 服务属性矩阵 [timestamp, avg_response_time, cpu_usage, memory_usage]

与 TraceCRL 的区别：
  - TraceCRL: 节点=服务操作, 边=操作状态+属性
  - TraceDAE:  节点=整个服务, 边=调用关系, 属性附在节点上
"""

import numpy as np
import torch
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from torch_geometric.data import Data


class STGBuilder:
    """
    Service Trace Graph 构建器

    将分布式追踪数据 + 性能指标数据转换为图结构表示。
    每个 STG 对应一条 trace，节点为微服务，边为调用依赖。
    """

    def __init__(self, trace_data: Dict[str, Dict], metric_data: Dict[str, np.ndarray]):
        """
        初始化 STG 构建器

        Args:
            trace_data: {trace_id: trace_dict} 字典
            metric_data: {service_name: np.array} 字典
        """
        self.trace_data = trace_data
        self.metric_data = metric_data
        self.stgs: Dict[str, Data] = {}  # trace_id -> PyG Data object
        self.meta: Dict[str, Dict] = {}  # 元数据

    def build_all_stgs(self, labels: Dict[str, int] = None) -> Dict[str, Data]:
        """为所有 trace 构建 STG.

        Args:
            labels: {trace_id: 0/1} 异常标签字典, None 则全部按正常处理
        """
        labels = labels or {}
        for trace_id in self.trace_data:
            is_anomaly = labels.get(trace_id, 0) == 1
            stg = self.build_stg(trace_id, is_anomaly=is_anomaly)
            if stg is not None:
                self.stgs[trace_id] = stg
        print(f"[STGBuilder] 成功构建 {len(self.stgs)}/{len(self.trace_data)} 个 STG")
        return self.stgs

    def build_stg(self, trace_id: str, is_anomaly: bool = False) -> Optional[Data]:
        """
        为单条 trace 构建 STG（Algorithm 1）

        Args:
            trace_id: 追踪 ID
            is_anomaly: 是否为异常 trace（影响属性序列生成）

        Returns:
            PyG Data 对象:
              - x: 节点特征 [num_nodes, feature_dim]
              - edge_index: 边索引 [2, num_edges]
              - trace_id: 追踪 ID
              - adj: 原始邻接矩阵 [num_nodes, num_nodes]
              - node_names: 节点服务名列表
        """
        trace = self.trace_data.get(trace_id)
        if not trace:
            return None

        spans = trace.get('spans', [])
        if not spans:
            return None

        # 构建节点映射 span_id -> node_index
        nodes: Dict[str, int] = {}
        node_features: List[np.ndarray] = []
        node_names: List[str] = []
        edges: List[Tuple[int, int]] = []

        for span in spans:
            span_id = span.get('spanId', '')
            service_name = span.get('serviceName', '')

            if span_id not in nodes:
                idx = len(nodes)
                nodes[span_id] = idx
                node_names.append(service_name)

                # 提取节点特征
                feature = self._build_feature(span)
                node_features.append(feature)

        # 构建边（基于 parentSpanId 的调用关系）
        for span in spans:
            parent_id = span.get('parentSpanId')
            span_id = span.get('spanId', '')
            if parent_id and parent_id in nodes and span_id in nodes:
                src_idx = nodes[parent_id]
                dst_idx = nodes[span_id]
                edges.append((src_idx, dst_idx))

        # 转换为 PyG Data
        num_nodes = len(nodes)
        x = torch.tensor(np.array(node_features), dtype=torch.float32)

        if edges:
            edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
        else:
            edge_index = torch.zeros((2, 0), dtype=torch.long)

        # 构建邻接矩阵（用于结构自编码器重构）
        adj = torch.zeros((num_nodes, num_nodes), dtype=torch.float32)
        for src, dst in edges:
            adj[src, dst] = 1.0

        # 构建属性序列（为每个节点收集时间序列数据）
        attr_sequences = self._build_attribute_sequences(spans, nodes, num_nodes, is_anomaly=is_anomaly)

        stg = Data(
            x=x,
            edge_index=edge_index,
            adj=adj,
            attr_sequences=attr_sequences,
        )
        stg.trace_id = trace_id
        stg.num_nodes = num_nodes
        stg.node_names = node_names

        # 保存元数据
        self.meta[trace_id] = {
            'num_nodes': num_nodes,
            'num_edges': len(edges),
            'node_names': node_names
        }

        return stg

    def _build_feature(self, span: Dict) -> np.ndarray:
        """
        构建节点特征向量

        特征维度 [4]:
          [0] timestamp: 标准化时间戳
          [1] avg_response_time: 响应时间 (ms)
          [2] cpu_usage: CPU 使用率 (%)
          [3] memory_usage: 内存使用率 (%)

        Args:
            span: 单条 span 数据

        Returns:
            feature vector [4]
        """
        service_name = span.get('serviceName', '')
        span_id = span.get('spanId', '')

        # 从 metric 数据获取性能指标
        metrics = self._get_metrics(span_id, service_name)

        # 提取特征
        timestamp = span.get('startTime', 0) / 1e9  # 纳秒转秒（归一化用）
        duration = span.get('duration', 0) / 1000.0  # 微秒转毫秒

        cpu_usage = np.mean(metrics[:, 2]) if len(metrics) > 0 else 50.0
        memory_usage = np.mean(metrics[:, 3]) if len(metrics) > 0 else 40.0

        feature = np.array([
            timestamp,
            duration,
            cpu_usage,
            memory_usage,
        ], dtype=np.float32)

        return feature

    def _get_metrics(self, span_id: str, service_name: str) -> np.ndarray:
        """
        获取服务的性能指标数据

        Args:
            span_id: Span ID
            service_name: 服务名称

        Returns:
            np.array [N, 4] 时间序列指标数据
        """
        # 优先用 span_id 查找
        if span_id in self.metric_data:
            return self.metric_data[span_id]
        # 回退到 service_name
        if service_name in self.metric_data:
            return self.metric_data[service_name]
        # 返回默认值
        return np.zeros((1, 4))

    def _build_attribute_sequences(
        self,
        spans: List[Dict],
        nodes: Dict[str, int],
        num_nodes: int,
        seq_length: int = 30,
        is_anomaly: bool = False
    ) -> torch.Tensor:
        """
        构建属性时间序列（用于 LSTM 属性自编码器）

        Args:
            spans: span 列表
            nodes: span_id -> node_index 映射
            num_nodes: 节点总数
            seq_length: 时间序列长度（论文使用30分钟窗口）
            is_anomaly: 是否为异常 trace

        Returns:
            [batch=1, seq_length, input_dim] 属性序列
        """
        input_dim = 4  # [timestamp, response_time, cpu, memory]

        # 为每个节点构建时间序列
        node_sequences = []
        for span in spans:
            span_id = span.get('spanId', '')
            if span_id in nodes:
                feature = self._build_feature(span)
                # 复制特征 seq_length 次形成序列
                node_seq = np.tile(feature, (seq_length, 1)).astype(np.float32)

                if is_anomaly:
                    # 异常 trace: 注入明显的时序异常模式
                    anomaly_start = seq_length // 3  # 异常从前 1/3 处开始
                    # 响应时间递增趋势
                    trend = np.linspace(0, 2.0, seq_length - anomaly_start)
                    node_seq[anomaly_start:, 1] += trend * feature[1] * 0.8
                    # CPU 在后半段尖峰
                    spike_start = seq_length // 2
                    node_seq[spike_start:, 2] += feature[2] * 0.6
                    # 加中等噪声模拟真实异常的不稳定性
                    anomaly_noise = np.random.randn(seq_length, input_dim) * feature * 0.05
                else:
                    # 正常 trace: 微弱波动模拟稳态运行
                    anomaly_noise = np.random.randn(seq_length, input_dim) * feature * 0.005

                node_sequences.append(node_seq + anomaly_noise)

        if not node_sequences:
            node_sequences.append(np.zeros((seq_length, input_dim)))

        # 按节点取均值得到图级属性序列 [seq_length, input_dim]
        attr_seq = np.mean(np.stack(node_sequences), axis=0)  # [seq_length, input_dim]

        return torch.tensor(attr_seq, dtype=torch.float32).unsqueeze(0)  # [1, seq_length, input_dim]

    def save_stg(self, trace_id: str, output_path: str) -> None:
        """
        保存单个 STG 到文件

        Args:
            trace_id: 追踪 ID
            output_path: 输出路径
        """
        import os
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        stg = self.stgs.get(trace_id)
        if stg:
            torch.save(stg, output_path)

    def save_all_stgs(self, output_dir: str) -> None:
        """保存所有 STG 到目录"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        for trace_id, stg in self.stgs.items():
            path = os.path.join(output_dir, f"{trace_id}.pt")
            torch.save(stg, path)
        print(f"[STGBuilder] 所有 STG 已保存至: {output_dir}")

    def load_stg(self, path: str) -> Data:
        """加载单个 STG 从文件"""
        return torch.load(path, weights_only=False)

    def get_stg_statistics(self) -> Dict[str, Any]:
        """获取 STG 统计信息"""
        if not self.stgs:
            return {}

        num_nodes_list = [s.num_nodes for s in self.stgs.values()]
        num_edges_list = [s.edge_index.size(1) if s.edge_index.numel() > 0 else 0
                          for s in self.stgs.values()]

        return {
            'total_stgs': len(self.stgs),
            'avg_nodes': np.mean(num_nodes_list),
            'avg_edges': np.mean(num_edges_list),
            'max_nodes': max(num_nodes_list),
            'min_nodes': min(num_nodes_list),
            'max_edges': max(num_edges_list),
            'min_edges': min(num_edges_list),
        }


if __name__ == "__main__":
    # 测试 STG 构建
    print("STGBuilder 初始化完成")
    print("\n使用示例：")
    print("  from data.stg_builder import STGBuilder")
    print("  builder = STGBuilder(trace_data, metric_data)")
    print("  stg = builder.build_stg(trace_id)")
    print("  print(stg)")
