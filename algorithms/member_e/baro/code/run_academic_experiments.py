# -*- coding: utf-8 -*-
"""
BARO — Academic Experiment Suite
=================================
Comprehensive evaluation including:
  1. Core anomaly detection + RCA (full pipeline)
  2. Parameter sensitivity analysis (BOCPD hazard_rate, N-Sigma threshold)
  3. Fault-type breakdown
  4. Detection delay distribution
  5. Statistical significance (McNemar, bootstrap CI)
  6. Multi-seed reproducibility
  7. Ablation: RobustScorer vs BaselineScorer under timing noise
"""

import sys, os, json, gc
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['MPLCONFIGDIR'] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.matplotlib_cache')
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

import numpy as np
import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from src.baro import BARO
from src.bocpd.univariate import MultivariateUnivariateBOCPD
from src.scorer.baseline_scorer import BaselineScorer
from src.data.synthetic_generator import SyntheticDataGenerator
from src.data.preprocessor import DataPreprocessor
from src.evaluate import Evaluator
from src.academic_eval import (
    sensitivity_bocpd_hazard_rate, sensitivity_nsigma,
    fault_type_breakdown, detection_delay_distribution,
    mcnemar_test, bootstrap_f1_ci, multi_seed_stability,
)
from baselines.n_sigma import NSigmaDetector
from baselines.spot import SPOTDetector
from src.bocpd.univariate import UnivariateBOCPD


def load_config(path='configs/default.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_dataset(seed=42):
    """Generate the standard 25-case dataset."""
    gen = SyntheticDataGenerator(n_services=5, metrics_per_service=4, seed=seed)
    dataset = []
    for i in range(15):
        data, gt, fs = gen.generate_simple_case(
            n_steps=200, target_service=i % 5,
            fault_start=80 + (i % 3) * 20,
        )
        dataset.append({
            'data': data, 'ground_truth': gt, 'fault_type': 'simple',
            'target_service': i % 5, 'fault_start': fs,
        })
    complex_cases = gen.generate_dataset(n_cases=10, n_services=5)
    dataset.extend(complex_cases)
    return dataset


def preprocess_dataset(dataset):
    """Preprocess all cases (no normalisation — synthetic data is homogeneous)."""
    preprocessor = DataPreprocessor()
    processed = []
    for case in dataset:
        df = preprocessor.process(case['data'], fault_start=case['fault_start'],
                                  method="none")
        le_data, all_data, _, _ = preprocessor.split_metrics(df)
        n_all = all_data.shape[1]
        le_idx = [i for i in range(n_all) if i % 4 in [0, 1]]
        processed.append({
            'data': all_data,
            'latency_error_data': le_data,
            'latency_error_indices': le_idx,
            'ground_truth': case['ground_truth'],
            'fault_type': case['fault_type'],
            'fault_start': case['fault_start'],
        })
    return processed


def run_all_methods(processed_cases, config):
    """Run BARO and all baselines, return predictions."""
    results = {}

    # --- BARO ---
    print("  Running BARO...", flush=True)
    baro_preds, baro_ranks = [], []
    for case in processed_cases:
        baro = BARO(
            n_metrics=case['latency_error_data'].shape[1],
            hazard_rate=config['bocpd']['hazard_rate'],
            sigma_hat=config['bocpd']['sigma_hat'],
            use_robust_scorer=True,
        )
        is_a, t, ranking = baro.analyze(case['data'], case['latency_error_indices'])
        baro_preds.append((is_a, t))
        baro_ranks.append(ranking)
    results['BARO'] = {'preds': baro_preds, 'rankings': baro_ranks}

    # --- N-Sigma ---
    print("  Running N-Sigma...", flush=True)
    ns_preds = []
    for case in processed_cases:
        train = case['latency_error_data'][:case['fault_start']]
        test = case['latency_error_data']
        det = NSigmaDetector(n_sigma=5)
        det.fit(train)
        ns_preds.append(det.detect(test))
    results['N-Sigma'] = {'preds': ns_preds}

    # --- SPOT ---
    print("  Running SPOT...", flush=True)
    spot_preds = []
    for case in processed_cases:
        train = case['latency_error_data'][:case['fault_start']]
        test = case['latency_error_data']
        det = SPOTDetector(q=0.02, level=0.998)
        det.fit(train)
        spot_preds.append(det.detect(test))
    results['SPOT'] = {'preds': spot_preds}

    # --- Univariate BOCPD ---
    print("  Running Univariate BOCPD...", flush=True)
    uni_preds = []
    for case in processed_cases:
        uni = UnivariateBOCPD(hazard_rate=100, warmup_steps=30)
        uni_preds.append(uni.detect_anomaly(case['latency_error_data'][:, 0]))
    results['Univariate BOCPD'] = {'preds': uni_preds}

    # --- Baseline Scorer ---
    print("  Running Baseline Scorer...", flush=True)
    bs = BaselineScorer()
    bs_ranks = []
    for case in processed_cases:
        bs_ranks.append(bs.score(case['data'], case['fault_start']))
    results['Baseline Scorer'] = {'rankings': bs_ranks}

    return results


def main():
    config = load_config()

    print("=" * 70)
    print("BARO — Academic Experiment Suite")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    # ---- 1. Generate + Preprocess ----
    print("\n[1] Generating and preprocessing dataset...")
    dataset = build_dataset(seed=42)
    processed = preprocess_dataset(dataset)
    print(f"    {len(processed)} cases ready")

    # ---- 2. Run all methods ----
    print("\n[2] Running all methods...")
    all_results = run_all_methods(processed, config)

    # ---- 3. Core evaluation ----
    print("\n[3] Core evaluation...")
    evaluator = Evaluator()
    labels = [(True, c['fault_start']) for c in processed]

    ad_summary = {}
    for name, res in all_results.items():
        if 'preds' in res:
            m = evaluator.anomaly_detection_metrics(res['preds'], labels)
            ad_summary[name] = m
            print(f"    {name:25s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}")

    rca_summary = {}
    gt_list = [c['ground_truth'] for c in processed]
    for name in ['BARO', 'Baseline Scorer']:
        if name in all_results:
            m = evaluator.rca_top_k_accuracy(all_results[name]['rankings'], gt_list)
            rca_summary[name] = m
            print(f"    {name:25s}  A@1={m['A@1']:.3f}  A@2={m['A@2']:.3f}  A@3={m['A@3']:.3f}")

    # ---- 4. Parameter Sensitivity ----
    print("\n[4] Parameter sensitivity analysis...")

    print("    BOCPD hazard_rate sensitivity...", flush=True)
    hr_sensitivity = sensitivity_bocpd_hazard_rate(processed)

    print("    N-Sigma threshold sensitivity...", flush=True)
    ns_sensitivity = sensitivity_nsigma(processed)

    # ---- 5. Fault-type breakdown ----
    print("\n[5] Fault-type breakdown...")
    ft_breakdown = fault_type_breakdown(all_results['BARO']['preds'], processed)
    for ft, m in ft_breakdown.items():
        print(f"    {ft:15s}  n={m['n_cases']:2d}  F1={m['f1']:.3f}")

    # ---- 6. Detection delay ----
    print("\n[6] Detection delay distribution...")
    delays = detection_delay_distribution(all_results['BARO']['preds'], processed)
    print(f"    BARO: mean={delays['mean']:.1f}, median={delays['median']:.1f}, "
          f"min={delays['min']}, max={delays['max']} steps")

    # ---- 7. Statistical tests ----
    print("\n[7] Statistical significance...")
    mcnemar_ns = mcnemar_test(
        all_results['BARO']['preds'], all_results['N-Sigma']['preds'], processed)
    print(f"    McNemar BARO vs N-Sigma: p={mcnemar_ns['p_value']:.4f}")

    mcnemar_spot = mcnemar_test(
        all_results['BARO']['preds'], all_results['SPOT']['preds'], processed)
    print(f"    McNemar BARO vs SPOT:   p={mcnemar_spot['p_value']:.4f}")

    baro_bootstrap = bootstrap_f1_ci(all_results['BARO']['preds'], processed)
    print(f"    BARO F1 95% CI: [{baro_bootstrap['ci_95_low']:.3f}, "
          f"{baro_bootstrap['ci_95_high']:.3f}]")

    # ---- 8. Multi-seed stability ----
    print("\n[8] Multi-seed reproducibility...")
    seed_results = multi_seed_stability(n_seeds=5)
    print(f"    F1 across 5 seeds: {[f'{x:.3f}' for x in seed_results['f1_values']]}")
    print(f"    Mean={seed_results['f1_mean']:.3f}, Std={seed_results['f1_std']:.3f}")

    # ---- 9. Robustness (timing shift) ----
    print("\n[9] Robustness to anomaly detection timing error...")
    baro_model = BARO(
        n_metrics=processed[0]['latency_error_data'].shape[1],
        hazard_rate=100, sigma_hat=1.0, use_robust_scorer=True,
    )
    robustness = evaluator.robustness_test(baro_model, processed)
    for shift_str, acc in sorted(robustness.items(), key=lambda x: int(x[0])):
        print(f"    Shift {int(shift_str):+3d}: A@1={acc['A@1']:.3f}")

    # ---- Assemble final report ----
    final = {
        'timestamp': datetime.now().isoformat(),
        'dataset': {'n_cases': len(processed), 'n_services': 5,
                     'metrics_per_service': 4},
        'anomaly_detection': ad_summary,
        'root_cause_analysis': rca_summary,
        'parameter_sensitivity': {
            'bocpd_hazard_rate': hr_sensitivity,
            'nsigma_threshold': ns_sensitivity,
        },
        'fault_type_breakdown': ft_breakdown,
        'detection_delay': delays,
        'statistical_tests': {
            'mcnemar_baro_vs_nsigma': mcnemar_ns,
            'mcnemar_baro_vs_spot': mcnemar_spot,
            'baro_bootstrap_ci': baro_bootstrap,
        },
        'multi_seed_stability': seed_results,
        'robustness': {str(k): v for k, v in robustness.items()},
    }

    os.makedirs('data/results', exist_ok=True)
    out_path = 'data/results/academic_results.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")

    # ---- Generate figures ----
    plot_academic_figures(final, ad_summary, hr_sensitivity, ns_sensitivity,
                          ft_breakdown, final['robustness'])

    print("\n" + "=" * 70)
    print("Academic experiment suite complete.")
    print("=" * 70)
    return final


def plot_academic_figures(final, ad_summary, hr_sensitivity, ns_sensitivity,
                          ft_breakdown, robustness):
    save_dir = 'data/results'
    os.makedirs(save_dir, exist_ok=True)

    # Figure 1: Anomaly Detection F1 comparison
    fig, ax = plt.subplots(figsize=(9, 5))
    methods = list(ad_summary.keys())
    f1s = [ad_summary[m]['f1'] for m in methods]
    colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D']
    bars = ax.bar(methods, f1s, color=colors[:len(methods)], edgecolor='black', linewidth=1.2)
    for bar, s in zip(bars, f1s):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f'{s:.3f}', ha='center', fontweight='bold')
    ax.set_ylabel('F1-Score')
    ax.set_title('Anomaly Detection — F1 Comparison')
    ax.set_ylim(0, 1.15)
    plt.xticks(rotation=15, ha='right')
    plt.tight_layout()
    plt.savefig(f'{save_dir}/ad_f1_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Figure 2: BOCPD hazard_rate sensitivity
    fig, ax = plt.subplots(figsize=(8, 4))
    hrs = sorted(hr_sensitivity.keys())
    f1_vals = [hr_sensitivity[hr]['f1'] for hr in hrs]
    ax.plot(hrs, f1_vals, 'o-', color='#2E86AB', linewidth=2, markersize=8)
    ax.set_xlabel('Hazard Rate')
    ax.set_ylabel('F1-Score')
    ax.set_title('BARO Sensitivity to BOCPD Hazard Rate')
    ax.set_xscale('log')
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{save_dir}/sensitivity_hazard_rate.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Figure 3: N-Sigma threshold sensitivity
    fig, ax = plt.subplots(figsize=(8, 4))
    sigmas = sorted(ns_sensitivity.keys())
    f1_vals = [ns_sensitivity[s]['f1'] for s in sigmas]
    ax.plot(sigmas, f1_vals, 's-', color='#A23B72', linewidth=2, markersize=8)
    ax.set_xlabel('N-Sigma Threshold')
    ax.set_ylabel('F1-Score')
    ax.set_title('N-Sigma Sensitivity to Threshold Value')
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{save_dir}/sensitivity_nsigma.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Figure 4: Fault-type breakdown
    fig, ax = plt.subplots(figsize=(8, 4))
    ftypes = list(ft_breakdown.keys())
    f1s = [ft_breakdown[ft]['f1'] for ft in ftypes]
    ax.barh(ftypes, f1s, color='#2E86AB', edgecolor='black')
    ax.set_xlabel('F1-Score')
    ax.set_title('BARO F1 by Fault Type')
    ax.set_xlim(0, 1.1)
    for i, (ft, s) in enumerate(zip(ftypes, f1s)):
        ax.text(s + 0.02, i, f'{s:.3f}', va='center')
    plt.tight_layout()
    plt.savefig(f'{save_dir}/fault_type_breakdown.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Figure 5: Robustness to timing shift
    fig, ax = plt.subplots(figsize=(8, 4))
    shifts = sorted([int(s) for s in robustness.keys()])
    a1s = [robustness[str(s)]['A@1'] for s in shifts]
    ax.plot(shifts, a1s, 'o-', color='#2E86AB', linewidth=2, markersize=8)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('Time Shift (steps)')
    ax.set_ylabel('A@1 Accuracy')
    ax.set_title('RobustScorer Robustness to Detection Timing Error')
    ax.set_ylim(0, 1.1)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{save_dir}/robustness_timing.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Figures saved to {save_dir}/")


if __name__ == '__main__':
    main()
