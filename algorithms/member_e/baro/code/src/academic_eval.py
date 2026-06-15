# -*- coding: utf-8 -*-
"""
Academic evaluation module for BARO reproduction.

Extends the basic evaluation with:
  - Parameter sensitivity analysis
  - Fault-type breakdown
  - Detection delay distribution
  - Statistical significance (McNemar, bootstrap CIs)
  - Multi-seed reproducibility assessment
"""

import numpy as np
from collections import defaultdict


def sensitivity_bocpd_hazard_rate(processed_cases, hazard_rates=None):
    """Sensitivity of BARO detection to hazard_rate parameter."""
    from src.baro import BARO
    if hazard_rates is None:
        hazard_rates = [10, 30, 50, 100, 200, 500]

    results = {}
    for hr in hazard_rates:
        preds = []
        for case in processed_cases:
            baro = BARO(
                n_metrics=case['latency_error_data'].shape[1],
                hazard_rate=hr, sigma_hat=1.0, use_robust_scorer=True,
            )
            is_a, t, _ = baro.analyze(case['data'], case['latency_error_indices'])
            preds.append((is_a, t))
        results[hr] = _compute_ad_metrics(preds, processed_cases)
    return results


def sensitivity_nsigma(processed_cases, sigma_values=None):
    """Sensitivity of N-Sigma to threshold value."""
    from baselines.n_sigma import NSigmaDetector
    if sigma_values is None:
        sigma_values = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]

    results = {}
    for ns in sigma_values:
        preds = []
        for case in processed_cases:
            train = case['latency_error_data'][:case['fault_start']]
            test = case['latency_error_data']
            det = NSigmaDetector(n_sigma=ns)
            det.fit(train)
            preds.append(det.detect(test))
        results[ns] = _compute_ad_metrics(preds, processed_cases)
    return results


def fault_type_breakdown(baro_predictions, processed_cases):
    """Anomaly detection metrics broken down by fault type."""
    breakdown = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'total': 0})

    for (is_a, t), case in zip(baro_predictions, processed_cases):
        ft = case.get('fault_type', 'unknown')
        true_fs = case['fault_start']
        breakdown[ft]['total'] += 1

        if is_a and abs(t - true_fs) <= 10:
            breakdown[ft]['tp'] += 1
        elif is_a:
            breakdown[ft]['fp'] += 1
        else:
            breakdown[ft]['fn'] += 1

    result = {}
    for ft, counts in breakdown.items():
        tp, fp, fn = counts['tp'], counts['fp'], counts['fn']
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        result[ft] = {
            'precision': p, 'recall': r, 'f1': f1,
            'tp': tp, 'fp': fp, 'fn': fn, 'n_cases': counts['total'],
        }
    return result


def detection_delay_distribution(predictions, processed_cases):
    """Distribution of detection delay (detection_time - fault_start)."""
    delays = []
    for (is_a, t), case in zip(predictions, processed_cases):
        if is_a:
            delays.append(t - case['fault_start'])

    if not delays:
        return {'mean': None, 'std': None, 'median': None, 'values': []}

    d = np.array(delays)
    return {
        'mean': float(np.mean(d)),
        'std': float(np.std(d)),
        'median': float(np.median(d)),
        'min': int(np.min(d)),
        'max': int(np.max(d)),
        'values': [int(x) for x in d],
    }


def mcnemar_test(preds_a, preds_b, processed_cases):
    """
    McNemar's test for paired binary predictions.

    H0: the two methods have the same error rate.
    Returns (statistic, p_value) — reject H0 if p < 0.05.
    """
    n01 = 0  # A wrong, B correct
    n10 = 0  # A correct, B wrong

    for (pa, ta), (pb, tb), case in zip(preds_a, preds_b, processed_cases):
        true_fs = case['fault_start']
        a_ok = pa and abs(ta - true_fs) <= 10
        b_ok = pb and abs(tb - true_fs) <= 10

        if not a_ok and b_ok:
            n01 += 1
        elif a_ok and not b_ok:
            n10 += 1

    if n01 + n10 == 0:
        return {'statistic': 0.0, 'p_value': 1.0}

    # McNemar with continuity correction
    stat = (abs(n01 - n10) - 1) ** 2 / (n01 + n10)
    from scipy.stats import chi2
    p_val = 1.0 - chi2.cdf(stat, 1)

    return {
        'statistic': float(stat),
        'p_value': float(p_val),
        'n_a_wrong_b_correct': n01,
        'n_a_correct_b_wrong': n10,
    }


def bootstrap_f1_ci(predictions, processed_cases, n_bootstrap=2000, alpha=0.05):
    """Bootstrap confidence interval for F1 score."""
    n = len(predictions)
    f1_samples = np.zeros(n_bootstrap)
    rng = np.random.RandomState(42)

    for b in range(n_bootstrap):
        idx = rng.choice(n, size=n, replace=True)
        sample_preds = [predictions[i] for i in idx]
        sample_cases = [processed_cases[i] for i in idx]
        metrics = _compute_ad_metrics(sample_preds, sample_cases)
        f1_samples[b] = metrics['f1']

    lo = np.percentile(f1_samples, 100 * alpha / 2)
    hi = np.percentile(f1_samples, 100 * (1 - alpha / 2))

    return {
        'f1_mean': float(np.mean(f1_samples)),
        'f1_std': float(np.std(f1_samples)),
        f'ci_{int(100*(1-alpha))}_low': float(lo),
        f'ci_{int(100*(1-alpha))}_high': float(hi),
    }


def multi_seed_stability(n_seeds=5):
    """Assess BARO stability across random seeds for data generation."""
    from src.data.synthetic_generator import SyntheticDataGenerator
    from src.data.preprocessor import DataPreprocessor
    from src.baro import BARO

    all_f1 = []
    for seed in range(n_seeds):
        gen = SyntheticDataGenerator(n_services=5, metrics_per_service=4, seed=seed)
        preprocessor = DataPreprocessor()

        dataset = []
        for i in range(15):
            data, gt, fs = gen.generate_simple_case(
                n_steps=200, target_service=i % 5, fault_start=80 + (i % 3) * 20,
            )
            dataset.append({'data': data, 'ground_truth': gt, 'fault_start': fs,
                            'fault_type': 'simple', 'target_service': i % 5})
        complex_cases = gen.generate_dataset(n_cases=10, n_services=5)
        dataset.extend(complex_cases)

        processed = []
        for case in dataset:
            df = preprocessor.process(case['data'], fault_start=case['fault_start'],
                                      method="none")
            le_data, all_data, le_cols, all_cols = preprocessor.split_metrics(df)
            n_all = all_data.shape[1]
            le_idx = [i for i in range(n_all) if i % 4 in [0, 1]]
            processed.append({
                'data': all_data, 'latency_error_data': le_data,
                'latency_error_indices': le_idx,
                'ground_truth': case['ground_truth'],
                'fault_type': case['fault_type'],
                'fault_start': case['fault_start'],
            })

        preds = []
        for case in processed:
            baro = BARO(
                n_metrics=case['latency_error_data'].shape[1],
                hazard_rate=100, sigma_hat=1.0, use_robust_scorer=True,
            )
            is_a, t, _ = baro.analyze(case['data'], case['latency_error_indices'])
            preds.append((is_a, t))

        m = _compute_ad_metrics(preds, processed)
        all_f1.append(m['f1'])

    return {
        'f1_values': all_f1,
        'f1_mean': float(np.mean(all_f1)),
        'f1_std': float(np.std(all_f1)),
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _compute_ad_metrics(predictions, processed_cases):
    tp = fp = fn = 0
    for (is_a, t), case in zip(predictions, processed_cases):
        true_fs = case['fault_start']
        if is_a and abs(t - true_fs) <= 10:
            tp += 1
        elif is_a:
            fp += 1
        else:
            fn += 1
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return {'precision': p, 'recall': r, 'f1': f1, 'tp': tp, 'fp': fp, 'fn': fn}
