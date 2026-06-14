import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from src.bocpd.multivariate import MultivariateBOCPD
from src.data.synthetic_generator import SyntheticDataGenerator

try:
    gen = SyntheticDataGenerator(n_services=5, metrics_per_service=4, seed=42)
    data, gt, fault_start = gen.generate_case(fault_type='cpu_hog', target_service=0)

    print(f"Data shape: {data.shape}")
    print(f"Fault starts at: {fault_start}")
    print(f"Mean before fault: {data[:fault_start].mean(axis=0)[:4]}")
    print(f"Mean after fault: {data[fault_start:].mean(axis=0)[:4]}")

    le_indices = [i for i in range(data.shape[1]) if i % 4 in [0, 1]]
    le_data = data[:, le_indices]
    print(f"LE data shape: {le_data.shape}")

    for hr in [10, 50, 100, 200]:
        detector = MultivariateBOCPD(n_metrics=le_data.shape[1], hazard_rate=hr, sigma_hat=1.0)
        is_anomaly, anomaly_time = detector.detect_anomaly(le_data)
        print(f"hazard_rate={hr}: anomaly={is_anomaly}, time={anomaly_time}")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
