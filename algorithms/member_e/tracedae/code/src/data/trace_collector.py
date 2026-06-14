# -*- coding: utf-8 -*-
"""
TraceDAE Trace 数据采集器
==============================
负责从 OpenTelemetry/Jaeger 等追踪系统中采集分布式追踪数据。
复现环境中支持两种模式：
  1. 模拟模式：从本地 JSON/CSV 文件加载预先采集的 trace 数据
  2. 实时模式：通过 API 从 Prometheus/Jaeger 采集（需要实际 K8s 集群）
"""

import json
import os
import glob
from typing import Dict, List, Optional, Any
from datetime import datetime


class TraceCollector:
    """
    Trace 数据采集器

    Trace 数据结构：
    {
        "traceId": "abc123",
        "spans": [
            {
                "spanId": "span1",
                "parentSpanId": null,      # null 表示根 span
                "serviceName": "ts-travel-service",
                "operationName": "GET /api/travel",
                "startTime": 1717000000000, # unix 毫秒时间戳
                "duration": 150,            # 微秒
                "status": "OK",
                "tags": {...}
            },
            ...
        ]
    }
    """

    def __init__(self, data_source: str = "json", data_path: Optional[str] = None):
        """
        初始化 Trace 采集器

        Args:
            data_source: 数据源类型 ("json" | "csv" | "api")
            data_path: 数据文件路径（json/csv模式）或 API 地址（api模式）
        """
        self.data_source = data_source
        self.data_path = data_path
        self.traces: Dict[str, Dict] = {}

    def load_traces(self, path: Optional[str] = None) -> Dict[str, Dict]:
        """
        加载 trace 数据

        Args:
            path: 数据目录路径

        Returns:
            {trace_id: trace_data} 字典
        """
        target_path = path or self.data_path
        if not target_path:
            raise ValueError("必须提供数据路径")

        if self.data_source == "json":
            self._load_json_traces(target_path)
        elif self.data_source == "csv":
            self._load_csv_traces(target_path)
        elif self.data_source == "api":
            self._fetch_api_traces(target_path)
        else:
            raise ValueError(f"不支持的数据源类型: {self.data_source}")

        print(f"[TraceCollector] 成功加载 {len(self.traces)} 条 trace")
        return self.traces

    def _load_json_traces(self, path: str) -> None:
        """从 JSON 文件加载 trace 数据"""
        if os.path.isdir(path):
            files = glob.glob(os.path.join(path, "*.json"))
            for f in files:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    if isinstance(data, list):
                        for trace in data:
                            self.traces[trace['traceId']] = trace
                    else:
                        self.traces[data['traceId']] = data
        else:
            with open(path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    for trace in data:
                        self.traces[trace['traceId']] = trace
                else:
                    self.traces[data['traceId']] = data

    def _load_csv_traces(self, path: str) -> None:
        """从 CSV 文件加载 trace 数据"""
        import pandas as pd
        df = pd.read_csv(path)
        # 按 traceId 分组
        for trace_id, group in df.groupby('traceId'):
            spans = []
            for _, row in group.iterrows():
                span = {
                    'spanId': row.get('spanId', ''),
                    'parentSpanId': row.get('parentSpanId', None),
                    'serviceName': row.get('serviceName', ''),
                    'operationName': row.get('operationName', ''),
                    'startTime': row.get('startTime', 0),
                    'duration': row.get('duration', 0),
                    'status': row.get('status', 'OK'),
                }
                spans.append(span)
            self.traces[trace_id] = {
                'traceId': trace_id,
                'spans': spans
            }

    def _fetch_api_traces(self, api_url: str) -> None:
        """
        通过 API 获取 trace 数据（如 Jaeger API）

        注意：需要实际部署的微服务环境。复现时优先使用模拟模式。
        """
        try:
            import requests
            # Jaeger API: GET /api/traces
            resp = requests.get(f"{api_url}/api/traces", params={"limit": 10000})
            resp.raise_for_status()
            data = resp.json()
            for trace in data.get('data', []):
                trace_id = trace['traceID']
                spans = []
                for span in trace.get('spans', []):
                    spans.append({
                        'spanId': span['spanID'],
                        'parentSpanId': span.get('references', [{}])[0].get('spanID') if span.get('references') else None,
                        'serviceName': span.get('process', {}).get('serviceName', ''),
                        'operationName': span.get('operationName', ''),
                        'startTime': span.get('startTime', 0),
                        'duration': span.get('duration', 0),
                    })
                self.traces[trace_id] = {
                    'traceId': trace_id,
                    'spans': spans
                }
        except ImportError:
            print("[警告] requests 库未安装，跳过 API 采集")
        except Exception as e:
            print(f"[错误] API 采集失败: {e}")

    def get_trace(self, trace_id: str) -> Optional[Dict]:
        """获取单条 trace"""
        return self.traces.get(trace_id)

    def get_trace_ids(self) -> List[str]:
        """获取所有 trace ID"""
        return list(self.traces.keys())

    def get_statistics(self) -> Dict[str, Any]:
        """获取 trace 统计信息"""
        if not self.traces:
            return {}

        span_counts = [len(t['spans']) for t in self.traces.values()]
        return {
            'total_traces': len(self.traces),
            'total_spans': sum(span_counts),
            'avg_spans_per_trace': sum(span_counts) / len(span_counts),
            'max_spans': max(span_counts),
            'min_spans': min(span_counts),
        }

    def save_traces(self, output_path: str) -> None:
        """保存 trace 数据到 JSON 文件"""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(list(self.traces.values()), f, indent=2, ensure_ascii=False)
        print(f"[TraceCollector] Trace 数据已保存至: {output_path}")

    def filter_by_service(self, service_name: str) -> Dict[str, Dict]:
        """按服务名过滤 trace"""
        filtered = {}
        for tid, trace in self.traces.items():
            if any(s['serviceName'] == service_name for s in trace['spans']):
                filtered[tid] = trace
        return filtered

    def filter_by_duration(self, min_duration: float = 0, max_duration: float = float('inf')) -> Dict[str, Dict]:
        """按总耗时过滤 trace"""
        filtered = {}
        for tid, trace in self.traces.items():
            total_dur = sum(s['duration'] for s in trace['spans'])
            if min_duration <= total_dur <= max_duration:
                filtered[tid] = trace
        return filtered


if __name__ == "__main__":
    # 示例：从 JSON 加载
    collector = TraceCollector(data_source="json")
    # collector.load_traces("data/raw/traces/")
    # print(collector.get_statistics())
    print("TraceCollector 初始化完成（请在加载数据后调用 load_traces）")
