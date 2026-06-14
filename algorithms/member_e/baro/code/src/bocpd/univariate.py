# -*- coding: utf-8 -*-
"""
Univariate Bayesian Online Change Point Detection
==================================================

Baseline for comparison with Multivariate BOCPD. Each metric dimension
is monitored independently; an anomaly is declared when any single
dimension detects a changepoint.

Uses a Normal–Inverse-Gamma conjugate model (Gaussian likelihood,
unknown mean and precision).
"""

import numpy as np
from scipy.special import gammaln


class UnivariateBOCPD:
    """
    Univariate BOCPD — Gaussian likelihood with NIG prior.

    Detection thresholds are relaxed compared to the original
    implementation so that univariate detection is competitive
    on synthetic data where fault signatures span multiple
    standard deviations.
    """

    def __init__(
        self, hazard_rate=100, alpha0=1.0, beta0=1.0,
        mu0=0.0, kappa0=1.0, warmup_steps=30,
        map_drop_threshold=5, map_reset_threshold=3,
    ):
        self.hazard_rate = hazard_rate
        self.alpha0 = alpha0
        self.beta0 = beta0
        self.mu0 = mu0
        self.kappa0 = kappa0
        self.warmup_steps = warmup_steps
        self.map_drop_threshold = map_drop_threshold
        self.map_reset_threshold = map_reset_threshold
        self.reset()

    def reset(self):
        self.T = 0
        self.run_probs = {0: 1.0}
        self.data = []
        self._prev_map_run = 0

    @property
    def hazard(self):
        return 1.0 / self.hazard_rate

    def _log_marginal_likelihood(self, data_chunk):
        """Log marginal likelihood under NIG prior."""
        h = len(data_chunk)
        if h == 0:
            return -1e300

        data = np.array(data_chunk, dtype=np.float64)
        sum_x = float(np.sum(data))
        sum_x2 = float(np.sum(data ** 2))

        alpha_h = self.alpha0 + 0.5 * h
        kappa_h = self.kappa0 + h
        mu_h = (self.kappa0 * self.mu0 + sum_x) / kappa_h
        beta_h = self.beta0 + 0.5 * (
            sum_x2 + self.kappa0 * self.mu0 ** 2 - kappa_h * mu_h ** 2
        )
        beta_h = max(beta_h, 1e-300)

        log_ml = (
            gammaln(alpha_h) - gammaln(self.alpha0)
            + self.alpha0 * np.log(max(self.beta0, 1e-300))
            - alpha_h * np.log(beta_h)
            + 0.5 * (np.log(max(self.kappa0, 1e-300)) - np.log(kappa_h))
            - 0.5 * h * np.log(2.0 * np.pi)
        )
        return float(np.clip(log_ml, -700.0, 700.0))

    def update(self, observation):
        self.T += 1
        self.data.append(float(observation))

        max_rl = min(300, self.T + 50)
        self.run_probs = {r: p for r, p in self.run_probs.items() if r < max_rl}

        log_growth = {}
        log_cp_terms = []

        for r, prior_p in list(self.run_probs.items()):
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

            log_growth[r + 1] = log_prior + np.log1p(-H) + log_pred
            log_cp_terms.append(log_prior + np.log(H) + log_pred)

        all_log = list(log_growth.values()) + log_cp_terms
        max_log = max(all_log)
        exp_sum = sum(np.exp(lp - max_log) for lp in all_log)
        log_norm = max_log + np.log(max(exp_sum, 1e-300))

        new_probs = {}
        for r, lp in log_growth.items():
            new_probs[r] = float(np.exp(lp - log_norm))

        cp_total = np.logaddexp.reduce(log_cp_terms) if log_cp_terms else -1e300
        new_probs[0] = float(np.exp(cp_total - log_norm))

        total = sum(new_probs.values())
        if total > 0:
            self.run_probs = {r: p / total for r, p in new_probs.items()}
        else:
            self.run_probs = {0: 1.0}

        map_run = max(self.run_probs, key=lambda k: self.run_probs[k])

        is_cp = (
            self._prev_map_run > self.map_drop_threshold
            and map_run <= self.map_reset_threshold
            and self.T > self.warmup_steps + 5
        )
        self._prev_map_run = map_run

        return is_cp, map_run

    def detect_anomaly(self, observations):
        self.reset()
        for t, obs in enumerate(observations):
            is_cp, _ = self.update(float(obs))
            if is_cp:
                return True, t
        return False, -1


class MultivariateUnivariateBOCPD:
    """
    Per-dimension univariate BOCPD.

    Runs an independent univariate detector on each metric dimension.
    A case is flagged as anomalous as soon as ANY dimension detects
    a changepoint; the earliest detection time across dimensions is
    returned.
    """

    def __init__(
        self, n_metrics, hazard_rate=100, alpha0=1.0, beta0=1.0,
        mu0=0.0, kappa0=1.0, warmup_steps=30,
    ):
        self.n_metrics = n_metrics
        self.hazard_rate = hazard_rate
        self.alpha0 = alpha0
        self.beta0 = beta0
        self.mu0 = mu0
        self.kappa0 = kappa0
        self.warmup_steps = warmup_steps
        self.detectors = []
        self.reset()

    def reset(self):
        self.detectors = [
            UnivariateBOCPD(
                hazard_rate=self.hazard_rate,
                alpha0=self.alpha0, beta0=self.beta0,
                mu0=self.mu0, kappa0=self.kappa0,
                warmup_steps=self.warmup_steps,
            )
            for _ in range(self.n_metrics)
        ]

    def detect_anomaly(self, observations):
        """Returns (is_anomaly, earliest_anomaly_time)."""
        obs = np.atleast_2d(np.array(observations, dtype=np.float64))
        earliest = -1
        for dim in range(self.n_metrics):
            self.detectors[dim].reset()
            is_a, t = self.detectors[dim].detect_anomaly(obs[:, dim])
            if is_a and (earliest == -1 or t < earliest):
                earliest = t
        if earliest >= 0:
            return True, earliest
        return False, -1
