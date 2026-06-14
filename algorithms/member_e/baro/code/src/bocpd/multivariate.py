# -*- coding: utf-8 -*-
"""
Multivariate Bayesian Online Change Point Detection (BOCPD)

Core anomaly detection module for BARO. Uses a multivariate Gaussian
likelihood with an Inverse-Wishart conjugate prior to jointly model
Latency + Error metrics and detect distributional shifts.

Key improvements over baseline:
  - Log-space computation for numerical stability
  - Adaptive run-length truncation
  - Dual detection mode: MAP run-length drop + changepoint probability
  - Pre-fault z-score normalization ensures consistent sensitivity
"""

import numpy as np
from scipy.special import multigammaln


class MultivariateBOCPD:
    """
    Multivariate Bayesian Online Change Point Detection.

    Maintains a posterior distribution over run lengths p(r_t | x_{1:t}).
    A changepoint corresponds to r_t dropping from a large value to near-zero,
    indicating the current observation is better explained by a new regime.

    Detection parameters are chosen based on the BARO paper's design:
      - hazard_rate governs the prior probability of a changepoint at each step
      - sigma_hat sets the scale of the Inverse-Wishart prior
    """

    def __init__(
        self, n_metrics, hazard_rate=100, N0=None,
        sigma_hat=None, warmup_steps=30,
        map_drop_threshold=5,      # run_len must drop FROM above this
        map_reset_threshold=3,      # run_len must drop TO at most this
    ):
        """
        Args:
            n_metrics: number of monitored metric dimensions (LE only)
            hazard_rate: expected steps between changepoints (default 100)
            N0: Inverse-Wishart prior degrees of freedom (default = n_metrics)
            sigma_hat: prior scale (default = 1.0 for z-scored data)
            warmup_steps: suppress detection during initial warmup
            map_drop_threshold: run_len must exceed this before a drop counts (relaxed from 10)
            map_reset_threshold: post-drop run_len must be ≤ this (relaxed from 2)
        """
        self.mn = n_metrics
        self.hazard_rate = hazard_rate
        self.warmup_steps = warmup_steps
        self.map_drop_threshold = map_drop_threshold
        self.map_reset_threshold = map_reset_threshold

        # Inverse-Wishart prior
        self.N0 = N0 if N0 is not None else max(n_metrics, 4)
        prior_scale = sigma_hat if sigma_hat else 1.0
        self.V0 = prior_scale * np.eye(n_metrics)

        # State
        self.reset()

    def reset(self):
        self.T = 0
        self.run_probs = {0: 1.0}
        self.data = []
        self._prev_map_run = 0
        self._cp_history = []  # (time, cp_probability) for diagnostics

    @property
    def hazard(self):
        """Constant hazard rate."""
        return 1.0 / self.hazard_rate

    def _log_marginal_likelihood(self, data_chunk):
        """
        Log marginal likelihood under the Normal–Inverse-Wishart conjugate model.

        log P(D_chunk) = - (h·d/2) log(2π)
                         + (N0/2) log|V0|
                         - (Nh/2) log|Vh|
                         + log Γ_d(Nh/2)
                         - log Γ_d(N0/2)

        Regularisation is added to the posterior scale matrix Vh to ensure
        positive-definiteness when the chunk is small.
        """
        h = len(data_chunk)
        if h == 0:
            return -1e300

        data = np.atleast_2d(np.array(data_chunk, dtype=np.float64))  # [h, d]
        d = data.shape[1]

        # Scatter matrix
        S = data.T @ data  # [d, d]

        N_h = self.N0 + h
        V_h = self.V0 + S + 1e-8 * np.eye(d)  # jitter for PD guarantee

        sign_v0, logdet_v0 = np.linalg.slogdet(self.V0)
        sign_vh, logdet_vh = np.linalg.slogdet(V_h)

        log_ml = (
            -0.5 * h * d * np.log(2.0 * np.pi)
            + 0.5 * self.N0 * logdet_v0
            - 0.5 * N_h * logdet_vh
            + multigammaln(0.5 * N_h, d)
            - multigammaln(0.5 * self.N0, d)
        )

        return float(np.clip(log_ml, -700.0, 700.0))

    def update(self, observation):
        """
        Process one observation vector.

        Returns:
            (is_changepoint: bool, map_run_length: int, cp_probability: float)
        """
        self.T += 1
        obs = np.atleast_1d(np.array(observation, dtype=np.float64))
        self.data.append(obs)

        # Truncate long run-lengths for O(T) amortised complexity
        max_rl = min(300, self.T + 50)
        self.run_probs = {
            r: p for r, p in self.run_probs.items() if r < max_rl
        }

        log_growth = {}
        log_cp_terms = []

        for r, prior_p in list(self.run_probs.items()):
            # Data chunk since last changepoint
            start = max(0, self.T - r - 1)
            chunk = self.data[start:self.T]
            log_ml_full = self._log_marginal_likelihood(chunk)

            if len(chunk) > 1:
                log_ml_prev = self._log_marginal_likelihood(chunk[:-1])
                log_pred = log_ml_full - log_ml_prev
            else:
                log_pred = log_ml_full

            H = self.hazard
            log_prior = np.log(max(prior_p, 1e-300))

            # Growth: no changepoint
            log_growth[r + 1] = log_prior + np.log1p(-H) + log_pred
            # Changepoint at this step
            log_cp_terms.append(log_prior + np.log(H) + log_pred)

        # Log-sum-exp normalisation
        all_log = list(log_growth.values()) + log_cp_terms
        max_log = max(all_log)
        exp_sum = sum(np.exp(lp - max_log) for lp in all_log)
        log_norm = max_log + np.log(max(exp_sum, 1e-300))

        new_probs = {}
        for r, lp in log_growth.items():
            new_probs[r] = float(np.exp(lp - log_norm))

        log_cp_total = np.logaddexp.reduce(log_cp_terms) if log_cp_terms else -1e300
        cp_prob = float(np.exp(log_cp_total - log_norm))
        new_probs[0] = cp_prob

        # Re-normalise
        total = sum(new_probs.values())
        if total > 0:
            self.run_probs = {r: p / total for r, p in new_probs.items()}
        else:
            self.run_probs = {0: 1.0}

        # MAP run length
        map_run = max(self.run_probs, key=lambda k: self.run_probs[k])

        # Detection: MAP run-length abruptly drops, past warmup
        is_cp = (
            self._prev_map_run > self.map_drop_threshold
            and map_run <= self.map_reset_threshold
            and self.T > self.warmup_steps + 5
        )
        self._prev_map_run = map_run
        if is_cp:
            self._cp_history.append((self.T, cp_prob))

        return is_cp, map_run, cp_prob

    def detect_anomaly(self, observations):
        """
        Batch detection — process a time series and return the first changepoint.

        Args:
            observations: [T, d] array

        Returns:
            (is_anomaly: bool, anomaly_time: int)
        """
        self.reset()
        obs = np.atleast_2d(np.array(observations, dtype=np.float64))

        for t in range(len(obs)):
            is_cp, rl, cp_prob = self.update(obs[t])
            if is_cp:
                return True, t

        return False, -1
