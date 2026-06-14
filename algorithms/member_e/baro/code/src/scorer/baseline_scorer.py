"""
Baseline Scorer using mean and std (non-robust version for ablation study).
"""

from .robust_scorer import RobustScorer


class BaselineScorer(RobustScorer):
    """
    基线Scorer：使用 mean + std（非鲁棒版本）
    用于消融实验，验证 RobustScorer 中 median+IQR 的优势
    """

    def __init__(self):
        super().__init__(use_median_iqr=False)
