# -*- coding: utf-8 -*-
"""
TraceDAE LSTM 属性自编码器 (Attribute Autoencoder)
======================================================
使用 LSTM 编码时间序列特征变化，捕获服务响应异常（SRA）。

架构：
  编码器：LSTM（2层）处理属性时间序列
  解码器：LSTM 重构原始属性
  损失：加权 MSE（对非零值使用 η 权重惩罚）

论文对应：第 3.4 节 Attribute Autoencoder (Equations 5-10)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class LSTMAttributeEncoder(nn.Module):
    """
    LSTM 属性编码器

    编码监控的微服务特征属性时间序列数据 X 为属性嵌入 Z^A。
    论文结构：
    - 遗忘门 f_t
    - 输入门 i_t
    - 输出门 o_t
    - 通过门控机制捕获时间序列的长短期依赖
    """

    def __init__(self, input_dim: int, hidden_dim: int = 128,
                 num_layers: int = 2, dropout: float = 0.1):
        """
        Args:
            input_dim: 输入特征维度
            hidden_dim: 隐藏层维度（论文默认 128）
            num_layers: LSTM 层数（论文默认 2）
            dropout: Dropout 概率（仅在多层时生效）
        """
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=False
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        编码时间序列

        Args:
            x: 输入序列 [batch, seq_len, input_dim]

        Returns:
            z_a: 属性嵌入 Z^A [batch, hidden_dim]（使用最后时刻的隐藏状态）
        """
        _, (h_n, c_n) = self.lstm(x)
        # h_n: [num_layers, batch, hidden_dim]
        # 取最后一层的隐藏状态作为属性嵌入
        z_a = h_n[-1]  # [batch, hidden_dim]
        return z_a


class LSTMAttributeDecoder(nn.Module):
    """LSTM 属性解码器"""

    def __init__(self, hidden_dim: int, input_dim: int, num_layers: int = 2,
                 dropout: float = 0.1):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.input_dim = input_dim
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0
        )
        self.output_proj = nn.Linear(hidden_dim, input_dim)

    def forward(self, z_a: torch.Tensor, seq_len: int) -> torch.Tensor:
        """
        解码重构原始属性

        Args:
            z_a: 属性嵌入 [batch, hidden_dim]
            seq_len: 目标序列长度

        Returns:
            x_recon: 重构属性 [batch, seq_len, input_dim]
        """
        batch_size = z_a.size(0)

        # 将嵌入扩展到序列长度
        decoder_input = z_a.unsqueeze(1).repeat(1, seq_len, 1)
        # decoder_input: [batch, seq_len, hidden_dim]

        output, _ = self.lstm(decoder_input)
        # output: [batch, seq_len, hidden_dim]

        x_recon = self.output_proj(output)
        # x_recon: [batch, seq_len, input_dim]

        return x_recon


class AttributeAutoencoder(nn.Module):
    """
    LSTM 属性自编码器

    完整流程：
      X (属性时间序列) → LSTM Encoder → Z^A (属性嵌入) → LSTM Decoder → X̂ (重构)
    """

    def __init__(self, input_dim: int, hidden_dim: int = 128,
                 num_layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.encoder = LSTMAttributeEncoder(input_dim, hidden_dim, num_layers, dropout)
        self.decoder = LSTMAttributeDecoder(hidden_dim, input_dim, num_layers, dropout)

        # 嵌入规范化
        self.embed_norm = nn.LayerNorm(hidden_dim)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """
        编码属性时间序列

        Args:
            x: 属性序列 [batch, seq_len, input_dim]

        Returns:
            z_a: 属性嵌入 Z^A [batch, hidden_dim]
        """
        z_a = self.encoder(x)
        z_a = self.embed_norm(z_a)
        return z_a

    def decode(self, z_a: torch.Tensor, seq_len: int) -> torch.Tensor:
        """
        解码属性嵌入

        Args:
            z_a: 属性嵌入
            seq_len: 序列长度

        Returns:
            x_recon: 重构属性
        """
        return self.decoder(z_a, seq_len)

    def forward(self, x: torch.Tensor) -> tuple:
        """
        前向传播

        Args:
            x: 属性序列 [batch, seq_len, input_dim]

        Returns:
            z_a: 属性嵌入 [batch, hidden_dim]
            x_recon: 重构属性 [batch, seq_len, input_dim]
        """
        batch_size, seq_len, input_dim = x.shape
        z_a = self.encode(x)
        x_recon = self.decode(z_a, seq_len)
        return z_a, x_recon

    def attribute_loss(self, x_original: torch.Tensor,
                        x_recon: torch.Tensor,
                        eta: float = 5.0) -> torch.Tensor:
        """
        属性重构损失（加权 MSE）

        L_attr = Σ η_{i,j} · MSE(X̂_{i,j}, X_{i,j})
        其中 η_{i,j} = η_0  if X_{i,j} ≠ 0, else 1

        Args:
            x_original: 原始属性 [batch, seq_len, input_dim]
            x_recon: 重构属性 [batch, seq_len, input_dim]
            eta: 非零元素惩罚权重（D1默认 5）

        Returns:
            loss: 标量损失值
        """
        # 构建权重矩阵
        weight = torch.where(x_original != 0, eta, torch.ones_like(x_original))

        # 加权 MSE：L = Σ w_{i,j} * (X̂ - X)^2
        loss = ((x_recon - x_original) ** 2 * weight).mean()
        return loss


class AttributeAutoencoderV2(nn.Module):
    """
    属性自编码器变体：使用 Transformer 替代 LSTM

    适用场景：需要捕获更长距离时间依赖的场景。
    """

    def __init__(self, input_dim: int, hidden_dim: int = 128,
                 num_layers: int = 2, nhead: int = 4, dropout: float = 0.1):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        self.input_proj = nn.Linear(input_dim, hidden_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=nhead,
            dim_feedforward=hidden_dim * 4,
            dropout=dropout,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)

        self.decoder = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.GELU(),
            nn.Linear(hidden_dim * 2, input_dim)
        )

    def forward(self, x: torch.Tensor) -> tuple:
        batch_size, seq_len, input_dim = x.shape
        h = self.input_proj(x)
        h = self.transformer(h)
        z_a = h.mean(dim=1)  # 全局平均池化
        x_recon = self.decoder(h)
        return z_a, x_recon

    def attribute_loss(self, x_original, x_recon, eta=5.0):
        weight = torch.where(x_original != 0, eta, torch.ones_like(x_original))
        return F.mse_loss(x_recon * weight, x_original * weight, reduction='mean')


if __name__ == "__main__":
    # 测试属性自编码器
    print("AttributeAutoencoder 测试")
    print("=" * 50)

    batch_size = 4
    seq_len = 30
    input_dim = 4
    hidden_dim = 128

    # 模拟时间序列数据
    x = torch.randn(batch_size, seq_len, input_dim)

    # 创建模型
    model = AttributeAutoencoder(input_dim, hidden_dim, num_layers=2)

    # 前向传播
    z_a, x_recon = model(x)
    loss = model.attribute_loss(x, x_recon)

    print(f"输入 shape: {x.shape}")
    print(f"属性嵌入 Z^A shape: {z_a.shape}")
    print(f"重构属性 X̂ shape: {x_recon.shape}")
    print(f"属性重构损失: {loss.item():.6f}")

    total_params = sum(p.numel() for p in model.parameters())
    print(f"总参数量: {total_params:,}")
