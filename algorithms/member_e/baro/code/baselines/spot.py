# -*- coding: utf-8 -*-
"""
SPOT (Streaming Peaks-Over-Threshold) anomaly detection baseline.

Based on Siffer et al. (KDD 2017): fits a Generalised Pareto Distribution
to excesses above a high quantile threshold, then uses the fitted GPD to
compute an anomaly threshold with a controlled false-positive rate.

This implementation uses the method-of-moments (MOM) estimator for the
GPD parameters, which is fast and numerically stable for the moderate
sample sizes typical in microservice monitoring.
"""

import numpy as np


class SPOTDetector:
    """
    SPOT anomaly detector using GPD tail modelling.

    Parameters
    ----------
    q : float
        Low-probability quantile used to define the initial threshold.
        Default 0.01 (1% — i.e. 99th-percentile threshold).
    level : float
        Target quantile for the anomaly threshold (higher = fewer false positives).
        Default 0.998 (0.2 % expected false-positive rate).
    """

    def __init__(self, q=1e-2, level=0.998):
        if not 0 < q < 1:
            raise ValueError("q must be in (0, 1)")
        if not 0 < level < 1:
            raise ValueError("level must be in (0, 1)")
        self.q = q
        self.level = level
        self._init_threshold = None
        self._anomaly_threshold = None
        self._gamma = None   # GPD shape parameter
        self._sigma = None   # GPD scale parameter
        self._n_excesses = 0

    def fit(self, normal_data: np.ndarray):
        """
        Fit the GPD on normal (pre-fault) data.

        Steps:
          1. Compute the q-quantile threshold z_q from normal data.
          2. Collect excesses (values - z_q) for points above z_q.
          3. Fit GPD(γ, σ) to excesses via method-of-moments.
          4. Compute the anomaly threshold z_level from the fitted GPD.
        """
        data = np.atleast_2d(np.array(normal_data, dtype=np.float64))
        flat = data.flatten()

        # 1. Initial threshold: high quantile of normal data
        self._init_threshold = float(np.percentile(flat, 100.0 * (1.0 - self.q)))

        # 2. Excesses
        excesses = flat[flat > self._init_threshold] - self._init_threshold

        if len(excesses) < 5:
            # Not enough tail data — fall back to Gaussian threshold
            self._sigma = 1.0
            self._gamma = 0.0
            self._anomaly_threshold = self._init_threshold + 3.0 * np.std(flat)
            self._n_excesses = len(excesses)
            return

        self._n_excesses = len(excesses)

        # 3. Fit GPD via method-of-moments
        #  E[X] = σ / (1 − γ)  for γ < 1
        #  Var[X] = σ² / ((1 − γ)² (1 − 2γ))  for γ < 0.5
        m1 = np.mean(excesses)
        m2 = np.var(excesses)

        if m2 < 1e-12:
            # Constant excess — degenerate
            self._gamma = 0.0
            self._sigma = m1
        else:
            # Moment estimators
            ratio = m1 ** 2 / m2
            gamma_hat = 0.5 * (1.0 - ratio)  # MoM estimate
            # Regularise γ to stay in the GPD support
            self._gamma = float(np.clip(gamma_hat, -0.5, 0.99))
            self._sigma = float(m1 * (1.0 - self._gamma))

        # 4. Anomaly threshold via GPD quantile
        #  P(X > z_level) = P(X > z_q) · P(X - z_q > z_level - z_q | X > z_q)
        #                 = q · (1 + γ·(z_level - z_q)/σ)^{-1/γ}
        #  Set P(X > z_level) = 1 - level:
        #  → (1 - level) / q = (1 + γ·Δz/σ)^{-1/γ}
        #  → Δz = σ/γ · (((1 - level) / q)^{-γ} - 1)
        tail_prob = (1.0 - self.level) / self.q

        # When γ < -0.1 the GPD has an effective upper bound (bounded tail);
        # this occurs with light-tailed data (e.g. Gaussian).  Fall back to
        # a conservative empirical threshold to avoid false positives.
        if self._gamma < -0.1:
            # Empirical: use the maximum of training data × safety margin
            self._anomaly_threshold = float(
                max(np.max(flat), self._init_threshold) * 1.5
            )
        elif abs(self._gamma) < 1e-8:
            z_extra = self._sigma * np.log(tail_prob)
            self._anomaly_threshold = float(self._init_threshold + max(z_extra, 0.0))
        else:
            z_extra = (self._sigma / self._gamma) * (tail_prob ** (-self._gamma) - 1.0)
            self._anomaly_threshold = float(self._init_threshold + max(z_extra, 0.0))

        # Safety floor: threshold must at least exceed all training data
        train_max = float(np.max(flat))
        self._anomaly_threshold = max(self._anomaly_threshold, train_max * 1.2)

    def detect(self, data: np.ndarray):
        """
        Scan for anomalies using the fitted GPD threshold.

        Returns:
            (is_anomaly: bool, anomaly_time: int)
        """
        if self._anomaly_threshold is None:
            raise RuntimeError("Must call fit() before detect()")

        data = np.atleast_2d(np.array(data, dtype=np.float64))
        for t in range(len(data)):
            if np.any(data[t] > self._anomaly_threshold):
                return True, t
        return False, -1

    @property
    def threshold(self):
        """The computed anomaly threshold (after fit)."""
        return self._anomaly_threshold

    @property
    def gpd_params(self):
        """Fitted GPD parameters (gamma, sigma)."""
        return self._gamma, self._sigma
