# -*- coding: utf-8 -*-
"""
Data preprocessing module for BARO.

Supports three normalisation modes:
  - "none":    pass-through (suitable for synthetic data where all metrics
               share the same scale by construction)
  - "zscore":  standardisation using pre-fault statistics with soft clipping
               (suitable for real heterogeneous metric data)
  - "minmax":  legacy MinMax (kept for ablation comparisons)
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List


class DataPreprocessor:
    """
    Data preprocessor for microservice metric time series.

    Design rationale
    ----------------
    BOCPD operates on raw (or lightly scaled) data — its Gaussian
    likelihood assumes zero-mean, moderate-variance observations.
    The RobustScorer compares pre- and post-fault windows using
    per-metric normalised deviations, so metrics with different
    units (ms, %, count) must be brought to comparable scales.

    For synthetic data where all metrics already share the same scale
    (~N(0, 1) normal, +3–5 for faults), no normalisation is needed.
    For real heterogeneous data, z-score per metric using pre-fault
    statistics is applied with clipping to keep BOCPD numerically stable.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._norm_params = {}

    def process(
        self,
        raw_data: np.ndarray,
        fault_start: Optional[int] = None,
        method: str = "none",
        clip: float = 15.0,
    ) -> pd.DataFrame:
        """
        Preprocess metric data.

        Args:
            raw_data:    [T, M] array
            fault_start: first fault time-step (exclusive); used as
                         the boundary for computing normalisation params
            method:      "none" | "zscore" | "minmax"
            clip:        soft-clip range for zscore mode (±clip)

        Returns:
            pd.DataFrame with columns 0..M-1
        """
        df = pd.DataFrame(raw_data)
        df = df.ffill().bfill().fillna(0.0)
        df.columns = list(range(raw_data.shape[1]))

        if method == "zscore":
            df = self._zscore(df, fault_start, clip)
        elif method == "minmax":
            df = self._minmax(df)
        # else "none": pass through

        return df

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def _zscore(
        self, df: pd.DataFrame, fault_start: Optional[int], clip: float
    ) -> pd.DataFrame:
        out = df.copy()
        for col in df.columns:
            series = df[col].values.astype(np.float64)
            if fault_start is not None and fault_start > 10:
                normal = series[:fault_start]
                mu = float(np.mean(normal))
                sd = float(np.std(normal))
            else:
                mu = float(np.mean(series))
                sd = float(np.std(series))
            if sd < 1e-8:
                sd = 1.0
            out[col] = np.clip((series - mu) / sd, -clip, clip)
            self._norm_params[col] = {"mean": mu, "std": sd}
        return out

    def _minmax(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in df.columns:
            series = df[col].values.astype(np.float64)
            lo, hi = series.min(), series.max()
            rng = hi - lo
            out[col] = 0.0 if rng < 1e-8 else (series - lo) / rng
        return out

    # ------------------------------------------------------------------
    # Metric splitting
    # ------------------------------------------------------------------

    def split_metrics(
        self, df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray, List, List]:
        """
        Split into Latency+Error subset (for BOCPD) and full set (for RCA).

        Convention (per service, 4 metrics):  0=lat, 1=err, 2=traffic, 3=cpu
        LE columns are those where col_idx % 4 ∈ {0, 1}.

        Returns
        -------
        le_data  : [T, n_le]   Latency+Error
        all_data : [T, n_all]  all metrics
        le_cols  : list[int]   column identifiers of LE metrics in all_data
        all_cols : list[int]   all column identifiers
        """
        all_cols = list(df.columns)
        le_cols = [c for c in all_cols if int(c) % 4 in [0, 1]]

        le_data = df[le_cols].values.astype(np.float64)
        all_data = df[all_cols].values.astype(np.float64)

        return le_data, all_data, le_cols, all_cols
