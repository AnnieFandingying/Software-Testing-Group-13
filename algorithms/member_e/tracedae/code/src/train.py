# -*- coding: utf-8 -*-
"""
TraceDAE 训练脚本
=====================
端到端训练 TraceDAE 双自编码器模型。

训练流程：
  1. 加载 STG 数据集
  2. 初始化双自编码器模型
  3. 联合训练（Adam 优化器）
  4. Early Stopping
  5. 保存最佳模型

使用方法：
  python src/train.py --config configs/default.yaml --data data/processed/stgs/
"""

import os
import sys
import yaml
import argparse
import random
import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam, AdamW
from torch.optim.lr_scheduler import ReduceLROnPlateau, CosineAnnealingLR
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.dual_autoencoder import DualAutoencoder
from data.dataset import STGDataset, create_dataloader


def set_seed(seed: int = 42):
    """设置全局随机种子"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def create_model(config: dict) -> DualAutoencoder:
    """
    根据配置创建双自编码器模型

    Args:
        config: 配置字典

    Returns:
        DualAutoencoder 实例
    """
    model_config = config['model']
    model = DualAutoencoder(
        input_dim=model_config.get('input_dim', 4),
        hidden_dim=model_config.get('hidden_dim', 128),
        num_heads=model_config.get('num_heads', 4),
        num_lstm_layers=model_config.get('num_lstm_layers', 2),
        alpha=model_config.get('alpha', 0.1),
        theta=model_config.get('theta', 40.0),
        eta=model_config.get('eta', 5.0),
        dropout=model_config.get('dropout', 0.1)
    )
    return model


def train_epoch(
    model: nn.Module,
    dataloader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    gradient_clip: float = 1.0
) -> Dict[str, float]:
    """
    训练一个 epoch

    Returns:
        {'total_loss', 'struct_loss', 'attr_loss'}
    """
    model.train()
    total_loss_sum = 0.0
    struct_loss_sum = 0.0
    attr_loss_sum = 0.0
    num_batches = 0

    for batch_idx, data in enumerate(dataloader):
        data = data.to(device)

        optimizer.zero_grad()

        # 前向传播
        z_v, adj_recon, z_a, x_recon = model(
            data.x, data.edge_index, data.adj, data.attr_sequences
        )

        # 计算损失
        total_loss, struct_loss, attr_loss = model.compute_loss(
            data.adj, adj_recon, data.x, x_recon
        )

        # 反向传播
        total_loss.backward()

        # 梯度裁剪（防止梯度爆炸）
        if gradient_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)

        optimizer.step()

        total_loss_sum += total_loss.item()
        struct_loss_sum += struct_loss.item()
        attr_loss_sum += attr_loss.item()
        num_batches += 1

    return {
        'total_loss': total_loss_sum / num_batches if num_batches > 0 else 0,
        'struct_loss': struct_loss_sum / num_batches if num_batches > 0 else 0,
        'attr_loss': attr_loss_sum / num_batches if num_batches > 0 else 0,
    }


@torch.no_grad()
def validate_epoch(
    model: nn.Module,
    dataloader,
    device: torch.device
) -> Dict[str, float]:
    """
    验证一个 epoch
    """
    model.eval()
    total_loss_sum = 0.0
    struct_loss_sum = 0.0
    attr_loss_sum = 0.0
    num_batches = 0

    for data in dataloader:
        data = data.to(device)

        z_v, adj_recon, z_a, x_recon = model(
            data.x, data.edge_index, data.adj, data.attr_sequences
        )

        total_loss, struct_loss, attr_loss = model.compute_loss(
            data.adj, adj_recon, data.x, x_recon
        )

        total_loss_sum += total_loss.item()
        struct_loss_sum += struct_loss.item()
        attr_loss_sum += attr_loss.item()
        num_batches += 1

    return {
        'total_loss': total_loss_sum / num_batches if num_batches > 0 else 0,
        'struct_loss': struct_loss_sum / num_batches if num_batches > 0 else 0,
        'attr_loss': attr_loss_sum / num_batches if num_batches > 0 else 0,
    }


def train(config: dict, data_dir: str, output_dir: Optional[str] = None):
    """
    TraceDAE 完整训练流程

    Args:
        config: 配置字典
        data_dir: STG 数据目录
        output_dir: 输出目录
    """
    # 设置随机种子
    train_config = config['training']
    set_seed(train_config.get('seed', 42))

    # 选择设备
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"[训练] 使用设备: {device}")

    # 加载数据集
    print(f"[训练] 加载数据集: {data_dir}")
    train_dataset = STGDataset(data_dir, split='train',
                                train_ratio=config['data']['train_ratio'],
                                val_ratio=config['data']['val_ratio'],
                                test_ratio=config['data']['test_ratio'],
                                seed=config['training']['seed'])
    val_dataset = STGDataset(data_dir, split='val',
                              train_ratio=config['data']['train_ratio'],
                              val_ratio=config['data']['val_ratio'],
                              test_ratio=config['data']['test_ratio'],
                              seed=config['training']['seed'])

    print(f"  训练集: {len(train_dataset)} 样本")
    print(f"  验证集: {len(val_dataset)} 样本")

    # 创建 DataLoader
    train_loader = create_dataloader(
        train_dataset,
        batch_size=train_config.get('batch_size', 32),
        shuffle=True,
        num_workers=config['data'].get('num_workers', 0)
    )
    val_loader = create_dataloader(
        val_dataset,
        batch_size=train_config.get('batch_size', 32),
        shuffle=False,
        num_workers=config['data'].get('num_workers', 0)
    )

    # 创建模型
    print(f"[训练] 创建双自编码器模型")
    model = create_model(config).to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"  总参数量: {total_params:,}")

    # 创建优化器
    lr = train_config.get('learning_rate', 0.001)
    weight_decay = train_config.get('weight_decay', 1e-5)

    optimizer_name = train_config.get('optimizer', 'adam').lower()
    if optimizer_name == 'adam':
        optimizer = Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    elif optimizer_name == 'adamw':
        optimizer = AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    else:
        raise ValueError(f"不支持的优化器: {optimizer_name}")

    # 学习率调度器
    scheduler = ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=5, verbose=True
    )

    # 训练循环
    epochs = train_config.get('epochs', 100)
    early_stopping = train_config.get('early_stopping', 10)
    gradient_clip = train_config.get('gradient_clip', 1.0)

    checkpoint_dir = output_dir or config['output'].get('checkpoint_dir', 'data/models')
    os.makedirs(checkpoint_dir, exist_ok=True)

    best_val_loss = float('inf')
    patience_counter = 0
    history = {'train': [], 'val': []}

    print(f"\n[训练] 开始训练（共 {epochs} epochs）")
    print("=" * 60)

    for epoch in range(epochs):
        # 训练
        train_metrics = train_epoch(model, train_loader, optimizer, device, gradient_clip)
        history['train'].append(train_metrics)

        # 验证
        val_metrics = validate_epoch(model, val_loader, device)
        history['val'].append(val_metrics)

        # 学习率调度
        scheduler.step(val_metrics['total_loss'])

        # 打印进度
        print(f"Epoch {epoch+1:3d}/{epochs} | "
              f"Train: {train_metrics['total_loss']:.4f} "
              f"(S:{train_metrics['struct_loss']:.4f} A:{train_metrics['attr_loss']:.4f}) | "
              f"Val: {val_metrics['total_loss']:.4f} "
              f"(S:{val_metrics['struct_loss']:.4f} A:{val_metrics['attr_loss']:.4f})")

        # Early Stopping
        if val_metrics['total_loss'] < best_val_loss:
            best_val_loss = val_metrics['total_loss']
            patience_counter = 0

            # 保存最佳模型
            checkpoint_path = os.path.join(checkpoint_dir, 'tracedae_best.pth')
            torch.save({
                'epoch': epoch + 1,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_loss': best_val_loss,
                'config': config,
            }, checkpoint_path)
            print(f"  -> 保存最佳模型: {checkpoint_path}")
        else:
            patience_counter += 1
            if patience_counter >= early_stopping:
                print(f"\n[训练] Early stopping at epoch {epoch+1}")
                break

    # 保存最终模型
    final_path = os.path.join(checkpoint_dir, 'tracedae_final.pth')
    torch.save({
        'epoch': epoch + 1,
        'model_state_dict': model.state_dict(),
        'val_loss': best_val_loss,
        'config': config,
    }, final_path)

    print(f"\n[训练] 完成!")
    print(f"  最佳验证损失: {best_val_loss:.4f}")
    print(f"  模型保存至: {checkpoint_dir}")

    return model, history


def load_config(config_path: str) -> dict:
    """加载 YAML 配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='TraceDAE 模型训练')
    parser.add_argument('--config', type=str, default='configs/default.yaml',
                        help='配置文件路径')
    parser.add_argument('--data', type=str, default='data/processed/stgs/',
                        help='STG 数据目录')
    parser.add_argument('--output', type=str, default=None,
                        help='模型输出目录')
    parser.add_argument('--device', type=str, default=None,
                        help='训练设备 (cuda/cpu)')

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    print(f"配置已加载: {args.config}")
    print(f"模型参数: α={config['model']['alpha']}, "
          f"θ={config['model']['theta']}, η={config['model']['eta']}")

    # 训练
    model, history = train(config, args.data, args.output)
