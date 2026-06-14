# -*- coding: utf-8 -*-
"""
TraceDAE PyTorch Dataset
===========================
将预处理后的 STG 数据封装为 PyTorch Dataset，
支持 train/val/test 划分。

每个样本包含：
  - x: 节点特征 [num_nodes, input_dim]
  - edge_index: 边索引 [2, num_edges]
  - adj: 原始邻接矩阵 [num_nodes, num_nodes]
  - attr_sequences: 属性时间序列 [1, seq_len, embed_dim]
  - label: 异常标签（0=正常, 1=异常）
  - trace_id: 追踪 ID
"""

import os
import glob
import torch
import numpy as np
from typing import Dict, List, Tuple, Optional
from torch.utils.data import Dataset
from torch_geometric.data import Data


class STGDataset(Dataset):
    """
    Service Trace Graph 数据集

    从预处理后的 STG 文件加载图数据。
    """

    def __init__(self, data_dir: str, split: str = 'train',
                 train_ratio: float = 0.6, val_ratio: float = 0.1,
                 test_ratio: float = 0.3, seed: int = 42,
                 use_labels: bool = True):
        """
        初始化 STG 数据集

        Args:
            data_dir: STG 数据目录（.pt 文件）
            split: 数据集划分 ('train' | 'val' | 'test' | 'all')
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            test_ratio: 测试集比例
            seed: 随机种子
            use_labels: 是否加载标签
        """
        super().__init__()
        self.data_dir = data_dir
        self.split = split
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.seed = seed
        self.use_labels = use_labels

        # 加载所有 STG 文件
        self.stg_files = self._find_stg_files()
        self.labels = {}  # trace_id -> label

        # 数据集划分
        self.indices = self._split_data()

        print(f"[STGDataset] {split} 集加载完成:")
        print(f"  数据目录: {data_dir}")
        print(f"  总文件数: {len(self.stg_files)}")
        print(f"  {split} 样本数: {len(self.indices)}")

    def _find_stg_files(self) -> List[str]:
        """查找所有 STG 文件"""
        # 支持 .pt（PyTorch 序列化）和 .pkl 格式
        files = []
        for ext in ['*.pt', '*.pkl', '*.pth']:
            files.extend(glob.glob(os.path.join(self.data_dir, ext)))

        if not files:
            # 尝试递归搜索
            for ext in ['*.pt', '*.pkl', '*.pth']:
                files.extend(glob.glob(os.path.join(self.data_dir, '**', ext), recursive=True))

        return sorted(files)

    def load_labels(self, label_path: str) -> None:
        """
        加载异常标签

        Args:
            label_path: CSV 标签文件路径 (trace_id,label)
        """
        import pandas as pd
        df = pd.read_csv(label_path)
        for _, row in df.iterrows():
            self.labels[str(row['trace_id'])] = int(row['label'])
        print(f"[STGDataset] 加载 {len(self.labels)} 条标签")

    def _split_data(self) -> List[int]:
        """
        数据集划分

        Returns:
            当前 split 对应的文件索引列表
        """
        n = len(self.stg_files)
        if n == 0:
            return []

        rng = np.random.default_rng(self.seed)
        perm = rng.permutation(n)

        train_end = int(n * self.train_ratio)
        val_end = train_end + int(n * self.val_ratio)

        if self.split == 'train':
            indices = perm[:train_end]
        elif self.split == 'val':
            indices = perm[train_end:val_end]
        elif self.split == 'test':
            indices = perm[val_end:]
        elif self.split == 'all':
            indices = np.arange(n)
        else:
            raise ValueError(f"不支持的数据集划分: {self.split}")

        return list(indices)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, idx: int) -> Data:
        """
        获取单个 STG 样本

        Args:
            idx: 样本索引

        Returns:
            PyG Data 对象
        """
        file_idx = self.indices[idx]
        file_path = self.stg_files[file_idx]

        data = torch.load(file_path, weights_only=False)

        # 确保必要属性存在
        if not hasattr(data, 'adj'):
            # 从 edge_index 构建邻接矩阵
            num_nodes = data.x.size(0)
            adj = torch.zeros((num_nodes, num_nodes), dtype=torch.float32)
            if data.edge_index.numel() > 0:
                adj[data.edge_index[0], data.edge_index[1]] = 1.0
            data.adj = adj

        if not hasattr(data, 'attr_sequences'):
            # 创建默认属性序列
            seq_len = 30  # 30分钟窗口
            data.attr_sequences = data.x.unsqueeze(0).repeat(1, seq_len, 1)

        if not hasattr(data, 'trace_id'):
            data.trace_id = os.path.basename(file_path).split('.')[0]

        # 添加标签
        if self.use_labels and data.trace_id in self.labels:
            data.y = torch.tensor([self.labels[data.trace_id]], dtype=torch.float32)
        else:
            data.y = torch.tensor([0.0])

        # 添加文件路径（用于调试）
        data.file_path = file_path

        return data

    def get_normal_losses(self) -> List[float]:
        """
        获取训练集中正常样本的损失值
        用于 Z-score 异常检测的基线计算
        """
        losses = []
        for i in range(len(self)):
            data = self[i]
            if data.y.item() == 0:
                losses.append(0.0)  # 占位，实际需要模型推理后填充
        return losses


class STGDatasetSimple(Dataset):
    """
    简化版 STG 数据集

    适用于数据格式不一致的情况，支持从原始数据直接构建。
    数据目录结构：
      data_dir/
        trace_id_001.pt    # PyG Data 对象
        trace_id_002.pt
        ...
        labels.csv         # 可选标签文件
    """

    def __init__(self, data_dir: str, config: Optional[dict] = None):
        """
        Args:
            data_dir: 数据目录
            config: 配置字典
        """
        self.data_dir = data_dir
        self.config = config or {}

        self.files = glob.glob(os.path.join(data_dir, '*.pt'))
        if not self.files:
            self.files = glob.glob(os.path.join(data_dir, '**/*.pt'), recursive=True)

        self.labels = self._load_labels()
        print(f"[STGDatasetSimple] 加载 {len(self.files)} 个 STG 文件")

    def _load_labels(self) -> Dict[str, int]:
        """加载标签文件"""
        label_file = os.path.join(self.data_dir, 'labels.csv')
        if os.path.exists(label_file):
            import pandas as pd
            df = pd.read_csv(label_file)
            return {str(row['trace_id']): int(row['label'])
                    for _, row in df.iterrows()}
        return {}

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> Data:
        file_path = self.files[idx]
        data = torch.load(file_path, weights_only=False)
        trace_id = os.path.basename(file_path).split('.')[0]
        data.trace_id = trace_id
        if trace_id in self.labels:
            data.y = torch.tensor([self.labels[trace_id]], dtype=torch.float32)
        else:
            data.y = torch.tensor([0.0])
        return data


def create_dataloader(dataset: Dataset, batch_size: int = 1,
                      shuffle: bool = True, num_workers: int = 0):
    """
    创建 DataLoader

    注意：PyG Data 对象的 batch 处理需要使用 torch_geometric.loader.DataLoader

    Args:
        dataset: STGDataset 实例
        batch_size: 批大小（图数据通常用 1 或小 batch）
        shuffle: 是否打乱
        num_workers: 数据加载线程数
    """
    try:
        from torch_geometric.loader import DataLoader
        return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle,
                          num_workers=num_workers)
    except ImportError:
        from torch.utils.data import DataLoader
        return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle,
                          num_workers=num_workers)


if __name__ == "__main__":
    print("STGDataset 初始化完成")
    print("\n使用示例：")
    print("  from data.dataset import STGDataset, create_dataloader")
    print("  dataset = STGDataset('data/processed/stgs/', split='train')")
    print("  loader = create_dataloader(dataset, batch_size=1)")
    print("  for batch in loader:")
    print("      print(batch)")
