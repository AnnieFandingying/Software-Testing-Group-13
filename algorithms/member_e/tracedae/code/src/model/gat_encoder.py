# -*- coding: utf-8 -*-
"""
TraceDAE GAT 结构自编码器 (Structure Autoencoder)
======================================================
使用图注意力网络（GAT）编码服务间调用依赖关系，捕获结构调用异常（SIA）。

架构：
  编码器：Linear → GATConv × 2（多头注意力）
  解码器：内积重构邻接矩阵 Â = σ(Z^V · (Z^V)^T)
  损失：加权交叉熵（对非零边使用 θ 权重惩罚）

论文对应：第 3.3 节 Structure Autoencoder (Equations 2-4)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATConv


class StructureAutoencoder(nn.Module):
    """
    GAT 结构自编码器

    编码服务间依赖关系，学习 STG 的结构特征表示。

    Args:
        input_dim: 输入特征维度（论文默认 4）
        hidden_dim: 隐藏层维度（论文默认 128）
        num_heads: 注意力头数（论文默认 4）
        dropout: Dropout 概率（论文默认 0.1）
    """

    def __init__(self, input_dim: int, hidden_dim: int = 128,
                 num_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_heads = num_heads
        self.gat_out_dim = hidden_dim // num_heads

        # 编码器
        self.linear = nn.Linear(input_dim, hidden_dim)
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

        self.gat1 = GATConv(
            hidden_dim, self.gat_out_dim,
            heads=num_heads,
            concat=True,
            dropout=dropout
        )
        self.gat2 = GATConv(
            hidden_dim, self.gat_out_dim,
            heads=num_heads,
            concat=True,
            dropout=dropout
        )

        # 正则化层
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.norm3 = nn.LayerNorm(hidden_dim)

    def encode(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        """
        结构编码器

        过程：Linear → ReLU → GATConv → ELU → GATConv

        Args:
            x: 节点特征 [num_nodes, input_dim]
            edge_index: 边索引 [2, num_edges]

        Returns:
            z_v: 结构嵌入 Z^V [num_nodes, hidden_dim]
        """
        # 线性变换降维
        h = self.linear(x)
        h = self.norm1(h)
        h = F.relu(h)
        h = self.dropout(h)

        # 第一层 GAT
        h = self.gat1(h, edge_index)
        h = self.norm2(h)
        h = F.elu(h)
        h = self.dropout(h)

        # 第二层 GAT
        z_v = self.gat2(h, edge_index)
        z_v = self.norm3(z_v)

        return z_v  # 结构嵌入 Z^V

    def decode(self, z_v: torch.Tensor) -> torch.Tensor:
        """
        结构解码器：内积重构邻接矩阵

        Â = σ(Z^V · (Z^V)^T)

        Args:
            z_v: 结构嵌入 [num_nodes, hidden_dim]

        Returns:
            adj_recon: 重构邻接矩阵 [num_nodes, num_nodes]
        """
        adj_recon = torch.sigmoid(torch.matmul(z_v, z_v.t()))
        return adj_recon

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> tuple:
        """
        前向传播

        Args:
            x: 节点特征 [num_nodes, input_dim]
            edge_index: 边索引 [2, num_edges]

        Returns:
            z_v: 结构嵌入
            adj_recon: 重构邻接矩阵
        """
        z_v = self.encode(x, edge_index)
        adj_recon = self.decode(z_v)
        return z_v, adj_recon

    def structure_loss(self, adj_original: torch.Tensor,
                        adj_recon: torch.Tensor,
                        theta: float = 40.0) -> torch.Tensor:
        """
        结构重构损失（加权交叉熵）

        L_struct = Σ θ_{i,j} · BCE(Â_{i,j}, A_{i,j})
        其中 θ_{i,j} = θ_0  if A_{i,j} ≠ 0, else 1

        Args:
            adj_original: 原始邻接矩阵 [num_nodes, num_nodes]
            adj_recon: 重构邻接矩阵 [num_nodes, num_nodes]
            theta: 非零元素惩罚权重（D1默认 40）

        Returns:
            loss: 标量损失值
        """
        # 构建权重矩阵；BCE 的 weight 参数按元素加权
        weight = torch.where(adj_original > 0, theta, torch.ones_like(adj_original))

        # 加权二元交叉熵：L = Σ w_{i,j} * BCE(Â_{i,j}, A_{i,j})
        loss = F.binary_cross_entropy(
            adj_recon,
            adj_original,
            weight=weight,
            reduction='mean'
        )
        return loss

    def encode_batch(self, x_list: list, edge_index_list: list) -> torch.Tensor:
        """
        批量编码多个图

        Args:
            x_list: 节点特征列表
            edge_index_list: 边索引列表

        Returns:
            z_v_list: 结构嵌入列表
        """
        z_v_list = []
        for x, edge_index in zip(x_list, edge_index_list):
            z_v = self.encode(x, edge_index)
            z_v_list.append(z_v)
        return z_v_list


class StructureAutoencoderV2(nn.Module):
    """
    结构自编码器变体：使用多层感知器重构邻接矩阵

    与基础版本的区别：
      - 使用 MLP 替代内积解码器
      - 更灵活的邻接矩阵重构
    """

    def __init__(self, input_dim: int, hidden_dim: int = 128,
                 num_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.base = StructureAutoencoder(input_dim, hidden_dim, num_heads, dropout)

        # MLP 解码器
        self.mlp_decoder = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid()
        )

    def encode(self, x, edge_index):
        return self.base.encode(x, edge_index)

    def decode(self, z_v: torch.Tensor) -> torch.Tensor:
        """MLP 解码器重构邻接矩阵"""
        num_nodes = z_v.size(0)
        adj_recon = torch.zeros((num_nodes, num_nodes), device=z_v.device)

        for i in range(num_nodes):
            for j in range(num_nodes):
                pair = torch.cat([z_v[i], z_v[j]], dim=-1)
                adj_recon[i, j] = self.mlp_decoder(pair).squeeze(-1)

        return adj_recon


if __name__ == "__main__":
    # 测试结构自编码器
    print("StructureAutoencoder 测试")
    print("=" * 50)

    # 模拟数据
    num_nodes = 6
    input_dim = 4
    hidden_dim = 128

    x = torch.randn(num_nodes, input_dim)
    edge_index = torch.tensor([
        [0, 1, 1, 2, 3, 4],
        [1, 2, 3, 4, 5, 5]
    ], dtype=torch.long)
    adj = torch.zeros((num_nodes, num_nodes))
    adj[edge_index[0], edge_index[1]] = 1.0

    # 创建模型
    model = StructureAutoencoder(input_dim, hidden_dim, num_heads=4)

    # 前向传播
    z_v, adj_recon = model(x, edge_index)
    loss = model.structure_loss(adj, adj_recon)

    print(f"输入节点数: {num_nodes}")
    print(f"输入特征维度: {input_dim}")
    print(f"结构嵌入 Z^V shape: {z_v.shape}")
    print(f"重构邻接矩阵 shape: {adj_recon.shape}")
    print(f"结构重构损失: {loss.item():.6f}")

    # 参数统计
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"总参数量: {total_params:,}")
    print(f"可训练参数量: {trainable_params:,}")
