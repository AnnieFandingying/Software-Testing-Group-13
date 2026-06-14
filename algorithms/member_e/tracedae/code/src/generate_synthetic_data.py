# -*- coding: utf-8 -*-
"""
TraceDAE 合成数据生成器
========================
生成高度逼真的微服务 trace + metric 数据，格式与 Jaeger + Prometheus 真实导出完全一致。

输出:
  data/raw/traces/all_traces.json   — Jaeger JSON 格式 trace 数据
  data/raw/metrics/<service>.csv    — 每个服务的时序指标
  data/raw/labels.csv               — trace_id → label 映射

数据规模: 260 条 trace (230 正常 + 30 异常)
异常类型: SRA (响应慢/CPU高/内存高) + SIA (调用链变化)
"""

import os
import json
import numpy as np


def set_seed(seed=42):
    np.random.seed(seed)


SERVICES = [
    "frontend",
    "cartservice",
    "checkoutservice",
    "productcatalogservice",
    "currencyservice",
    "shippingservice",
    "adservice",
    "recommendationservice",
]

# 正常调用链: 常见请求路径
NORMAL_CHAINS = [
    ["frontend", "cartservice", "productcatalogservice"],
    ["frontend", "checkoutservice", "currencyservice", "shippingservice"],
    ["frontend", "productcatalogservice"],
    ["frontend", "cartservice", "recommendationservice"],
    ["frontend", "checkoutservice", "shippingservice"],
    ["frontend", "adservice"],
    ["frontend", "cartservice"],
    ["frontend", "checkoutservice"],
    ["frontend", "currencyservice", "shippingservice"],
    ["frontend", "recommendationservice"],
]

# 异常调用链: SIA 场景 — 比正常多或少调用某个服务
ANOMALY_CHAINS_SIA = [
    ["frontend", "cartservice", "checkoutservice", "productcatalogservice"],  # 多了 checkout
    ["frontend", "checkoutservice"],  # 少了 currencyservice
    ["frontend", "productcatalogservice", "recommendationservice"],  # 多绕路
    ["frontend", "adservice", "currencyservice"],  # 跨模块调用
    ["frontend", "cartservice", "productcatalogservice", "checkoutservice", "currencyservice"],  # 全链路
]


def _normal_metric(service_idx, n_steps=30):
    """生成正常性能指标序列 [n_steps, 4] (timestamp, rt, cpu, mem)"""
    base_cpu = 15.0 + service_idx * 8.0   # 15-71%
    base_mem = 25.0 + service_idx * 6.0   # 25-67%
    base_rt = 8.0 + service_idx * 12.0    # 8-92ms

    data = np.zeros((n_steps, 4))
    for i in range(n_steps):
        data[i, 0] = i * 15.0  # 15s interval
        data[i, 1] = base_rt + np.random.randn() * base_rt * 0.08   # ±8% noise
        data[i, 2] = base_cpu + np.random.randn() * 3.0
        data[i, 3] = base_mem + np.random.randn() * 2.0

    data[:, 1] = np.clip(data[:, 1], 3, 120)
    data[:, 2] = np.clip(data[:, 2], 5, 75)
    data[:, 3] = np.clip(data[:, 3], 10, 80)
    return data


def _anomaly_metric(service_idx, n_steps=30, anomaly_type='mixed'):
    """生成异常性能指标序列 — 明显的时序异常"""
    normal = _normal_metric(service_idx, n_steps)

    # 异常开始点: 序列中段
    anomaly_start = n_steps // 3

    if anomaly_type == 'cpu_spike':
        normal[anomaly_start:, 1] = np.random.uniform(300, 2500, n_steps - anomaly_start)
        normal[anomaly_start:, 2] = np.random.uniform(88, 100, n_steps - anomaly_start)
        normal[anomaly_start:, 3] += np.random.uniform(5, 15, n_steps - anomaly_start)

    elif anomaly_type == 'memory_leak':
        trend = np.linspace(0, 1, n_steps - anomaly_start)
        normal[anomaly_start:, 1] += trend * np.random.uniform(200, 1500, n_steps - anomaly_start)
        normal[anomaly_start:, 3] = 70 + trend * 30
        normal[anomaly_start:, 2] = 60 + trend * 35

    elif anomaly_type == 'network_delay':
        normal[anomaly_start:, 1] = np.random.uniform(800, 4000, n_steps - anomaly_start)
        normal[anomaly_start:, 2] += np.random.uniform(0, 8, n_steps - anomaly_start)

    else:  # mixed — 最常见的异常模式
        normal[anomaly_start:, 1] = np.random.uniform(500, 3000, n_steps - anomaly_start)
        normal[anomaly_start:, 2] = np.random.uniform(85, 98, n_steps - anomaly_start)
        normal[anomaly_start:, 3] = np.random.uniform(80, 95, n_steps - anomaly_start)

    normal[:, 1] = np.clip(normal[:, 1], 0, 5000)
    normal[:, 2] = np.clip(normal[:, 2], 0, 100)
    normal[:, 3] = np.clip(normal[:, 3], 0, 100)
    return normal


def _build_trace(trace_id, chain, base_time, is_anomaly=False):
    """构建单条 trace 的 Jaeger JSON 格式"""
    spans = []
    parent_span_id = None
    current_time = base_time

    for svc_name in chain:
        span_id = f"{trace_id}_{svc_name}"

        if is_anomaly:
            duration = np.random.uniform(500, 5000)  # 全部异常trace延时都显著偏高
        else:
            duration = np.random.uniform(10, 200)  # 正常延时

        status = "ERROR" if (is_anomaly and np.random.random() < 0.3) else "OK"

        spans.append({
            "spanId": span_id,
            "parentSpanId": parent_span_id,
            "serviceName": svc_name,
            "operationName": f"GET /{svc_name}",
            "startTime": int(current_time * 1000),  # 毫秒时间戳
            "duration": int(duration * 1000),  # 微秒
            "status": status,
        })

        parent_span_id = span_id
        current_time += np.random.uniform(0.001, 0.005)  # 1-5ms 间隔

    return {
        "traceId": str(trace_id),
        "spans": spans,
    }


def generate_all(output_dir="data/raw", seed=42):
    """主入口: 生成全部合成数据到 data/raw/"""
    set_seed(seed)
    base_time = 1717000000.0  # epoch seconds

    os.makedirs(os.path.join(output_dir, "traces"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "metrics"), exist_ok=True)

    NUM_NORMAL = 400
    NUM_ANOMALY_SRA = 40
    NUM_ANOMALY_SIA = 20

    all_traces = []
    labels = {}

    # ---- 正常 trace ----
    for i in range(NUM_NORMAL):
        chain = NORMAL_CHAINS[i % len(NORMAL_CHAINS)]
        trace = _build_trace(f"normal_{i:04d}", chain, base_time + i * 0.01, is_anomaly=False)
        all_traces.append(trace)
        labels[trace["traceId"]] = 0

    # ---- SRA 异常 trace (同链，指标异常) ----
    anomaly_types = ['mixed', 'cpu_spike', 'memory_leak', 'network_delay']
    for i in range(NUM_ANOMALY_SRA):
        chain = NORMAL_CHAINS[i % len(NORMAL_CHAINS)]  # 调用链不变
        trace = _build_trace(f"sra_{i:04d}", chain, base_time + (NUM_NORMAL + i) * 0.01, is_anomaly=True)
        trace["anomaly_type"] = anomaly_types[i % len(anomaly_types)]
        all_traces.append(trace)
        labels[trace["traceId"]] = 1

    # ---- SIA 异常 trace (不同链) ----
    for i in range(NUM_ANOMALY_SIA):
        chain = ANOMALY_CHAINS_SIA[i % len(ANOMALY_CHAINS_SIA)]
        trace = _build_trace(f"sia_{i:04d}", chain, base_time + (NUM_NORMAL + NUM_ANOMALY_SRA + i) * 0.01, is_anomaly=True)
        trace["anomaly_type"] = "sia"
        all_traces.append(trace)
        labels[trace["traceId"]] = 1

    # ---- 写入文件 ----
    # Trace JSON (Jaeger 兼容格式)
    trace_path = os.path.join(output_dir, "traces", "all_traces.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(all_traces, f, indent=2, ensure_ascii=False)
    print(f"[生成] {len(all_traces)} 条 trace -> {trace_path}")

    # Labels CSV
    label_path = os.path.join(output_dir, "labels.csv")
    with open(label_path, "w") as f:
        f.write("trace_id,label\n")
        for tid, lbl in labels.items():
            f.write(f"{tid},{lbl}\n")
    print(f"[生成] {len(labels)} 条标签 -> {label_path}")

    # Metrics CSV (per service)
    service_metrics = {}  # svc_name -> list of arrays
    for svc in SERVICES:
        svc_idx = SERVICES.index(svc)
        # 正常 metrics
        normal_metrics = _normal_metric(svc_idx, n_steps=100)
        service_metrics[svc] = [normal_metrics]

    metrics_dir = os.path.join(output_dir, "metrics")
    for svc, data_list in service_metrics.items():
        combined = data_list[0]  # [100, 4]
        path = os.path.join(metrics_dir, f"{svc}.csv")
        header = "timestamp,avg_response_time,cpu_usage,memory_usage"
        np.savetxt(path, combined, delimiter=",", header=header, comments="", fmt="%.2f")
    print(f"[生成] {len(SERVICES)} 个服务 metrics -> {metrics_dir}/")

    total = NUM_NORMAL + NUM_ANOMALY_SRA + NUM_ANOMALY_SIA
    n_anomaly = NUM_ANOMALY_SRA + NUM_ANOMALY_SIA
    print(f"\n[总结] 总计 {total} 条 (正常 {NUM_NORMAL}, 异常 {n_anomaly}), "
          f"异常占比 {n_anomaly/total:.1%}")
    print(f"[提示] 真实数据到达后, 只需替换 data/raw/ 下同名文件即可切换")
    return all_traces, labels, SERVICES


if __name__ == "__main__":
    generate_all()
