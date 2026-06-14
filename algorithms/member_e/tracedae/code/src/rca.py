# -*- coding: utf-8 -*-
"""
TraceDAE 根因定位 (Root Cause Analysis)
=========================================
独立的根因定位脚本，对检测到的异常 STG 进行逐节点分析，
定位故障根因微服务。

算法：
  1. 对异常 STG 进行逐节点重构误差计算
  2. 节点异常分数: S_i = α·struct_err_i + (1-α)·attr_err_i
  3. Top-k 分数最高的节点为根因
"""

import os
import sys
import yaml
import argparse
import numpy as np
import torch
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.dual_autoencoder import DualAutoencoder
from model.detector import RootCauseLocalizer
from data.dataset import STGDataset, create_dataloader


def load_model(model_path: str, config: dict, device: torch.device) -> DualAutoencoder:
    """加载训练好的模型"""
    model = DualAutoencoder(
        input_dim=config['model']['input_dim'],
        hidden_dim=config['model']['hidden_dim'],
        num_heads=config['model']['num_heads'],
        num_lstm_layers=config['model']['num_lstm_layers'],
        alpha=config['model']['alpha'],
        theta=config['model']['theta'],
        eta=config['model']['eta'],
    )
    checkpoint = torch.load(model_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    model.eval()
    return model


def run_root_cause_analysis(
    model: DualAutoencoder,
    test_loader,
    config: dict,
    device: torch.device,
    top_k: int = 5
) -> List[Dict]:
    """
    根因定位分析

    Args:
        model: 训练好的模型
        test_loader: 测试集 DataLoader
        config: 配置
        device: 设备
        top_k: 返回 Top-k 根因

    Returns:
        [{trace_id, root_causes: [(node_idx, score, name), ...], is_anomaly}]
    """
    from model.detector import AnomalyDetector

    localizer = RootCauseLocalizer(
        alpha=config['model']['alpha'],
        theta=config['model']['theta'],
        eta=config['model']['eta'],
        top_k=top_k
    )

    detector = AnomalyDetector(
        threshold=config['detection'].get('z_score_threshold', 3.0)
    )

    results = []

    print(f"\n[根因定位] 分析中...")

    with torch.no_grad():
        for i, data in enumerate(test_loader):
            data = data.to(device)

            # 获取重构
            z_v, adj_recon, z_a, x_recon = model(
                data.x, data.edge_index, data.adj, data.attr_sequences
            )

            # 计算总损失以判断异常
            total_loss, struct_loss, attr_loss = model.compute_loss(
                data.adj, adj_recon, data.x, x_recon
            )

            is_anomaly, score, _ = detector.detect(total_loss.item())
            trace_id = getattr(data, 'trace_id', f'trace_{i}')

            node_names = getattr(data, 'node_names', None)
            if node_names:
                node_names = list(node_names)

            # 定位根因
            root_causes = []
            if is_anomaly:
                root_causes = localizer.localize(model, data, node_names)

            results.append({
                'trace_id': trace_id,
                'is_anomaly': bool(is_anomaly),
                'anomaly_score': float(score),
                'total_loss': float(total_loss.item()),
                'struct_loss': float(struct_loss.item()),
                'attr_loss': float(attr_loss.item()),
                'root_causes': [
                    {
                        'node_idx': rc[0],
                        'score': float(rc[1]),
                        'name': rc[2]
                    }
                    for rc in root_causes
                ]
            })

            if (i + 1) % 50 == 0:
                print(f"  已处理 {i+1} 个样本...")

    # 统计
    n_anomalies = sum(1 for r in results if r['is_anomaly'])
    print(f"\n[根因定位] 完成!")
    print(f"  总样本数: {len(results)}")
    print(f"  检测到异常: {n_anomalies} ({n_anomalies/max(len(results),1)*100:.1f}%)")

    # 打印部分结果
    anomalies = [r for r in results if r['is_anomaly']]
    if anomalies:
        print(f"\n  异常样本详情（前5个）:")
        for r in anomalies[:5]:
            print(f"    {r['trace_id']}: score={r['anomaly_score']:.3f}")
            for i, rc in enumerate(r['root_causes'][:3]):
                print(f"      Rank {i+1}: {rc['name']} (score={rc['score']:.4f})")

    return results


def main():
    parser = argparse.ArgumentParser(description='TraceDAE 根因定位')
    parser.add_argument('--config', type=str, default='configs/default.yaml')
    parser.add_argument('--model', type=str, required=True)
    parser.add_argument('--data', type=str, default='data/processed/stgs/')
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--output', type=str, default=None)

    args = parser.parse_args()

    # 加载配置
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # 加载模型
    model = load_model(args.model, config, device)

    # 加载数据
    test_dataset = STGDataset(
        args.data, split='test',
        seed=config['training']['seed']
    )
    test_loader = create_dataloader(test_dataset, batch_size=1, shuffle=False)

    # 运行根因定位
    results = run_root_cause_analysis(
        model, test_loader, config, device, args.top_k
    )

    # 保存结果
    if args.output:
        import json
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存至: {args.output}")

    return results


if __name__ == "__main__":
    main()
