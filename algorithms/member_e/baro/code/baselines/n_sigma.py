# -*- coding: utf-8 -*-
"""
N-Sigma anomaly detection baseline.

Flags data points whose absolute z-score exceeds a given number of
standard deviations from the pre-fault mean. With proper pre-fault
z-score normalisation this is a clean, interpretable baseline.
"""

import numpy as np


class NSigmaDetector:
    """
    N-Sigma detector.

    Fit on normal (pre-fault) data → learn per-dimension mean/std.
    Detection scans the full series; the first point where ANY
    dimension exceeds n_sigma is flagged as the anomaly onset.
    """

    def __init__(self, n_sigma=3.0):
        self.n_sigma = n_sigma
        self.mean = None
        self.std = None

    def fit(self, normal_data: np.ndarray):
        """Learn normal distribution parameters.

        Args:
            normal_data: [T, D] array of pre-fault (normal) observations.
        """
        data = np.atleast_2d(np.array(normal_data, dtype=np.float64))
        self.mean = np.mean(data, axis=0)
        self.std = np.std(data, axis=0)
        self.std = np.where(self.std < 1e-8, 1.0, self.std)

    def detect(self, data: np.ndarray):
        """Scan for anomalies.

        Args:
            data: [T, D] full time series (normal + possibly faulty).

        Returns:
            (is_anomaly: bool, anomaly_time: int)
        """
        if self.mean is None:
            raise RuntimeError("Must call fit() before detect()")

        data = np.atleast_2d(np.array(data, dtype=np.float64))
        for t in range(len(data)):
            deviations = np.abs(data[t] - self.mean) / self.std
            if np.any(deviations > self.n_sigma):
                return True, t
        return False, -1
