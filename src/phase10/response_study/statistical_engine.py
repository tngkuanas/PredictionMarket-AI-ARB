"""Deterministic Statistical Analysis and Multiple-Testing Correction for Phase 10A.6.

Implements:
1. Sample statistics: N, Mean, Median, Std Dev, Hit Rate.
2. Parametric & Bootstrap Confidence Intervals (deterministic fixed seed).
3. Permutation/Randomization testing under the null of zero response.
4. Holm-Bonferroni multiple-testing correction across tested horizon & size families.
5. Cluster-level aggregation to prevent false significance from overlapping windows.
"""

from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from scipy import stats

from src.phase10.response_study.schema import StatisticalResult


class DeterministicStatisticalEngine:
    """Rigorous statistical testing engine with multiple-testing correction."""

    def __init__(self, random_seed: int = 42, alpha: float = 0.05):
        self.random_seed = random_seed
        self.alpha = alpha

    def compute_distribution_statistics(
        self,
        values: List[float],
        metric_name: str = "net_return_bps",
        n_bootstrap: int = 1000
    ) -> StatisticalResult:
        """Computes sample moments, parametric and bootstrap CIs, and one-sample hypothesis tests."""
        if not values or len(values) < 2:
            val = values[0] if values else 0.0
            return StatisticalResult(
                metric_name=metric_name,
                sample_size=len(values),
                mean=float(val),
                median=float(val),
                std_dev=0.0,
                hit_rate=1.0 if val > 0 else 0.0,
                ci_lower=float(val),
                ci_upper=float(val),
                bootstrap_ci_lower=float(val),
                bootstrap_ci_upper=float(val),
                p_value=1.0,
                adjusted_p_value=1.0,
                test_type="INSUFFICIENT_SAMPLE",
                is_significant=False
            )

        arr = np.array(values, dtype=np.float64)
        n = len(arr)
        mean_val = float(np.mean(arr))
        median_val = float(np.median(arr))
        std_val = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        hit_rate = float(np.mean(arr > 0))

        # Parametric Student's t CI
        sem = std_val / np.sqrt(n) if n > 0 else 0.0
        t_crit = stats.t.ppf(1.0 - self.alpha / 2.0, df=n - 1) if n > 1 else 1.96
        ci_lower = mean_val - t_crit * sem
        ci_upper = mean_val + t_crit * sem

        # Deterministic Bootstrap CI
        rng = np.random.RandomState(self.random_seed)
        boot_means = []
        for _ in range(n_bootstrap):
            resample = rng.choice(arr, size=n, replace=True)
            boot_means.append(np.mean(resample))

        boot_arr = np.array(boot_means)
        boot_lower = float(np.percentile(boot_arr, 100.0 * (self.alpha / 2.0)))
        boot_upper = float(np.percentile(boot_arr, 100.0 * (1.0 - self.alpha / 2.0)))

        # One-sample t-test (H0: mean == 0)
        t_stat, p_val = stats.ttest_1samp(arr, 0.0)
        p_val_float = float(p_val) if not np.isnan(p_val) else 1.0

        return StatisticalResult(
            metric_name=metric_name,
            sample_size=n,
            mean=round(mean_val, 2),
            median=round(median_val, 2),
            std_dev=round(std_val, 2),
            hit_rate=round(hit_rate, 4),
            ci_lower=round(ci_lower, 2),
            ci_upper=round(ci_upper, 2),
            bootstrap_ci_lower=round(boot_lower, 2),
            bootstrap_ci_upper=round(boot_upper, 2),
            p_value=round(p_val_float, 4),
            adjusted_p_value=round(p_val_float, 4),
            test_type="ONE_SAMPLE_T",
            is_significant=(p_val_float < self.alpha and ci_lower > 0)
        )

    def permutation_test(
        self,
        values: List[float],
        n_permutations: int = 2000
    ) -> float:
        """Exact sign-flip permutation test of the null hypothesis that true mean is zero."""
        if not values:
            return 1.0
        arr = np.array(values, dtype=np.float64)
        obs_mean = np.mean(arr)
        n = len(arr)

        rng = np.random.RandomState(self.random_seed)
        perm_means = []
        for _ in range(n_permutations):
            signs = rng.choice([-1.0, 1.0], size=n)
            perm_means.append(np.mean(arr * signs))

        perm_arr = np.array(perm_means)
        p_val = float(np.mean(np.abs(perm_arr) >= np.abs(obs_mean)))
        return round(p_val, 4)

    @staticmethod
    def apply_holm_bonferroni(
        results: List[StatisticalResult]
    ) -> List[StatisticalResult]:
        """Applies Holm-Bonferroni step-down correction to a family of hypothesis tests."""
        if not results:
            return []

        # Sort indices by unadjusted p-value ascending
        sorted_indices = sorted(range(len(results)), key=lambda i: results[i].p_value)
        m = len(results)

        adjusted_p_values = [1.0] * m
        running_max = 0.0

        for rank, idx in enumerate(sorted_indices):
            k = rank + 1
            multiplier = m - k + 1
            raw_p = results[idx].p_value
            adj_p = min(1.0, raw_p * multiplier)
            # Enforce monotonicity: adj_p >= previous adj_p
            running_max = max(running_max, adj_p)
            adjusted_p_values[idx] = round(running_max, 4)

        adjusted_results = []
        for i, res in enumerate(results):
            adj_p = adjusted_p_values[i]
            is_sig = (adj_p < 0.05 and res.ci_lower > 0)
            adjusted_results.append(StatisticalResult(
                metric_name=res.metric_name,
                sample_size=res.sample_size,
                mean=res.mean,
                median=res.median,
                std_dev=res.std_dev,
                hit_rate=res.hit_rate,
                ci_lower=res.ci_lower,
                ci_upper=res.ci_upper,
                bootstrap_ci_lower=res.bootstrap_ci_lower,
                bootstrap_ci_upper=res.bootstrap_ci_upper,
                p_value=res.p_value,
                adjusted_p_value=adj_p,
                test_type=res.test_type,
                is_significant=is_sig
            ))
        return adjusted_results

    @staticmethod
    def aggregate_by_cluster(
        observations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Averages contract-level responses per independent event cluster.

        Guarantees that 10 contracts reacting to 1 FOMC announcement are treated as N=1
        independent information cluster rather than N=10 independent events.
        """
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for obs in observations:
            c_id = obs.get("event_cluster_id") or obs.get("event_id", "default_cluster")
            if c_id not in clusters:
                clusters[c_id] = []
            clusters[c_id].append(obs)

        cluster_summaries = []
        for c_id, obs_list in clusters.items():
            valid_returns = [o["net_return_bps"] for o in obs_list if o.get("net_return_bps") is not None]
            gross_returns = [o["gross_return_bps"] for o in obs_list if o.get("gross_return_bps") is not None]
            if not valid_returns:
                continue

            cluster_summaries.append({
                "event_cluster_id": c_id,
                "contracts_count": len(obs_list),
                "first_timestamp": min(o.get("event_timestamp") for o in obs_list if o.get("event_timestamp")),
                "net_return_bps": round(float(np.mean(valid_returns)), 2),
                "gross_return_bps": round(float(np.mean(gross_returns)), 2) if gross_returns else 0.0,
                "sample_variance_bps": round(float(np.var(valid_returns)), 2) if len(valid_returns) > 1 else 0.0
            })
        return cluster_summaries
