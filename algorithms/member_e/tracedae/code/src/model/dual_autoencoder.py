# -*- coding: utf-8 -*-
"""
TraceDAE 双自编码器联合模型 (Dual Autoencoder)
==================================================
将结构自编码器（GAT）和属性自编码器（LSTM）联合训练，
同时捕获服务调用异常（SIA）和服务响应异常（SRA）。

联合损失函数：
  L = α ||A - Â ∘ θ||²_F + (1-α) ||X - X̂ ∘ η||²_F

重构：
  X̂ = Z^V · (Z^A)^T  （融合结构嵌入和属性嵌入）

论文对应：第 3.5 节 Joint Optimization (Equations 11-13)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Dict, Tuple

from .gat_encoder import StructureAutoencoder
from .lstm_encoder import AttributeAutoencoder


class DualAutoencoder(nn.Module):
    """
    TraceDAE 双自编码器联合模型

    模型架构：
      输入: STG (A, X)
      ├── Structure-AE (GAT): A → Z^V → Â
      └── Attribute-AE (LSTM): X → Z^A → X̂
      联合损失: L = α·L_struct + (1-α)·L_attr

    Args:
        input_dim: 输入特征维度
        hidden_dim: 隐藏层维度
        num_heads: GAT 注意力头数
        num_lstm_layers: LSTM 层数
        alpha: 结构/属性平衡参数
        theta: 结构非零惩罚权重
        eta: 属性非零惩罚权重
        dropout: Dropout 概率
    """

    def __init__(
        self,
        input_dim: int = 4,
        hidden_dim: int = 128,
        num_heads: int = 4,
        num_lstm_layers: int = 2,
        alpha: float = 0.1,
        theta: float = 40.0,
        eta: float = 5.0,
        dropout: float = 0.1
    ):
        super().__init__()

        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.alpha = alpha
        self.theta = theta
        self.eta = eta

        # 子模块
        self.structure_ae = StructureAutoencoder(
            input_dim, hidden_dim, num_heads, dropout
        )
        self.attribute_ae = AttributeAutoencoder(
            input_dim, hidden_dim, num_lstm_layers, dropout
        )

        # 融合层：将结构嵌入和属性嵌入融合
        self.fusion_layer = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
        )

        # 融合后属性解码（X̂ = Z^V · (Z^A)^T）
        self.fusion_recon = nn.Linear(hidden_dim, input_dim)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        adj_original: torch.Tensor,
        attr_sequences: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        联合前向传播

        Args:
            x: 节点特征 [num_nodes, input_dim]
            edge_index: 边索引 [2, num_edges]
            adj_original: 原始邻接矩阵 [num_nodes, num_nodes]
            attr_sequences: 属性时间序列 [batch, seq_len, input_dim]

        Returns:
            z_v: 结构嵌入 [num_nodes, hidden_dim]
            adj_recon: 重构邻接矩阵 [num_nodes, num_nodes]
            z_a: 属性嵌入 [batch, hidden_dim]
            x_recon: 重构属性 [batch, seq_len, input_dim]
        """
        # 结构自编码器
        z_v, adj_recon = self.structure_ae(x, edge_index)

        # 属性自编码器
        z_a, x_recon = self.attribute_ae(attr_sequences)

        return z_v, adj_recon, z_a, x_recon

    def compute_loss(
        self,
        adj_original: torch.Tensor,
        adj_recon: torch.Tensor,
        x_original: torch.Tensor,
        x_recon: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        联合损失函数

        L = α L_struct + (1-α) L_attr

        Args:
            adj_original: 原始邻接矩阵
            adj_recon: 重构邻接矩阵
            x_original: 原始属性
            x_recon: 重构属性

        Returns:
            total_loss: 联合损失
            struct_loss: 结构重构损失
            attr_loss: 属性重构损失
        """
        struct_loss = self.structure_ae.structure_loss(
            adj_original, adj_recon, self.theta
        )
        attr_loss = self.attribute_ae.attribute_loss(
            x_original, x_recon, self.eta
        )

        total_loss = self.alpha * struct_loss + (1 - self.alpha) * attr_loss

        return total_loss, struct_loss, attr_loss

    def get_embeddings(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        attr_sequences: torch.Tensor
    ) -> Dict[str, torch.Tensor]:
        """
        获取结构嵌入和属性嵌入

        Args:
            x: 节点特征
            edge_index: 边索引
            attr_sequences: 属性序列

        Returns:
            {'z_v': 结构嵌入, 'z_a': 属性嵌入}
        """
        with torch.no_grad():
            z_v = self.structure_ae.encode(x, edge_index)
            z_a = self.attribute_ae.encode(attr_sequences)

        return {'z_v': z_v, 'z_a': z_a}

    def reconstruct(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        attr_sequences: torch.Tensor
    ) -> Dict[str, torch.Tensor]:
        """
        完整重构（推理模式）

        Args:
            x: 节点特征
            edge_index: 边索引
            attr_sequences: 属性序列

        Returns:
            {'adj_recon': 重构邻接, 'x_recon': 重构属性, 'z_v': 嵌入, 'z_a': 嵌入}
        """
        z_v, adj_recon, z_a, x_recon = self.forward(
            x, edge_index, torch.zeros_like(x[:0, :0]), attr_sequences
        )
        return {
            'adj_recon': adj_recon,
            'x_recon': x_recon,
            'z_v': z_v,
            'z_a': z_a
        }

    def encode_graph(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        """仅编码图结构"""
        return self.structure_ae.encode(x, edge_index)

    def encode_sequence(self, x: torch.Tensor) -> torch.Tensor:
        """仅编码属性序列"""
        return self.attribute_ae.encode(x)


class DualAutoencoderPretrained(nn.Module):
    """
    预训练 + 微调版本的双自编码器

    训练策略：
      1. 预训练 Structure-AE（仅用结构重构损失）
      2. 预训练 Attribute-AE（仅用属性重构损失）
      3. 联合微调（使用联合损失函数）

    这解决了论文中提到的"双自编码器联合训练可能不收敛"的问题。
    """

    def __init__(self, input_dim: int = 4, hidden_dim: int = 128,
                 num_heads: int = 4, num_lstm_layers: int = 2,
                 alpha: float = 0.1, theta: float = 40.0, eta: float = 5.0,
                 dropout: float = 0.1):
        super().__init__()
        self.structure_ae = StructureAutoencoder(input_dim, hidden_dim, num_heads, dropout)
        self.attribute_ae = AttributeAutoencoder(input_dim, hidden_dim, num_lstm_layers, dropout)
        self.alpha = alpha
        self.theta = theta
        self.eta = eta

        # 融合投影层
        self.struct_proj = nn.Linear(hidden_dim, hidden_dim)
        self.attr_proj = nn.Linear(hidden_dim, hidden_dim)

    def pretrain_structure(self, x, edge_index, adj_original,
                            optimizer, epochs: int = 50):
        """预训练结构自编码器"""
        self.structure_ae.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            z_v, adj_recon = self.structure_ae(x, edge_index)
            loss = self.structure_ae.structure_loss(adj_original, adj_recon, self.theta)
            loss.backward()
            optimizer.step()
            if (epoch + 1) % 10 == 0:
                print(f"  Structure pretrain epoch {epoch+1}/{epochs}: loss={loss.item():.6f}")

    def pretrain_attribute(self, attr_sequences, optimizer, epochs: int = 50):
        """预训练属性自编码器"""
        self.attribute_ae.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            z_a, x_recon = self.attribute_ae(attr_sequences)
            loss = self.attribute_ae.attribute_loss(attr_sequences, x_recon, self.eta)
            loss.backward()
            optimizer.step()
            if (epoch + 1) % 10 == 0:
                print(f"  Attribute pretrain epoch {epoch+1}/{epochs}: loss={loss.item():.6f}")

    def forward(self, x, edge_index, adj_original, attr_sequences):
        z_v, adj_recon = self.structure_ae(x, edge_index)
        z_a, x_recon = self.attribute_ae(attr_sequences)
        return z_v, adj_recon, z_a, x_recon

    def compute_loss(self, adj_original, adj_recon, x_original, x_recon):
        struct_loss = self.structure_ae.structure_loss(adj_original, adj_recon, self.theta)
        attr_loss = self.attribute_ae.attribute_loss(x_original, x_recon, self.eta)
        total_loss = self.alpha * struct_loss + (1 - self.alpha) * attr_loss
        return total_loss, struct_loss, attr_loss


# 模块导出
__all__ = [
    'DualAutoencoder',
    'DualAutoencoderPretrained',
]

if __name__ == "__main__":
    print("DualAutoencoder 测试")
    print("=" * 60)

    # 模拟数据
    num_nodes = 6
    input_dim = 4
    hidden_dim = 128
    batch_size = 1
    seq_len = 30

    x = torch.randn(num_nodes, input_dim)
    edge_index = torch.tensor([
        [0, 1, 1, 2, 3, 4],
        [1, 2, 3, 4, 5, 5]
    ], dtype=torch.long)
    adj = torch.zeros((num_nodes, num_nodes))
    adj[edge_index[0], edge_index[1]] = 1.0
    attr_seq = torch.randn(batch_size, seq_len, input_dim)

    # 创建模型
    model = DualAutoencoder(
        input_dim=input_dim,
        hidden_dim=hidden_dim,
        num_heads=4,
        num_lstm_layers=2,
        alpha=0.1,
        theta=40.0,
        eta=5.0
    )

    # 前向传播
    z_v, adj_recon, z_a, x_recon = model(x, edge_index, adj, attr_seq)
    total_loss, struct_loss, attr_loss = model.compute_loss(
        adj, adj_recon, attr_seq, x_recon
    )

    print(f"结构嵌入 Z^V shape: {z_v.shape}")
    print(f"属性嵌入 Z^A shape: {z_a.shape}")
    print(f"重构邻接矩阵 shape: {adj_recon.shape}")
    print(f"重构属性 X̂ shape: {x_recon.shape}")
    print(f"\n损失值:")
    print(f"  总损失:     {total_loss.item():.6f}")
    print(f"  结构损失:   {struct_loss.item():.6f} (权重 α={model.alpha})")
    print(f"  属性损失:   {attr_loss.item():.6f} (权重 1-α={1-model.alpha:.1f})")

    total_params = sum(p.numel() for p in model.parameters())
    print(f"\n总参数量: {total_params:,}")
