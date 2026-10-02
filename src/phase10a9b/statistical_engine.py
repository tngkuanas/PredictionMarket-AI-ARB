"""Statistical Inference Engine for Phase 10A.9-B Revalidation.

Fixes the degrees-of-freedom fallback artifact:
- When n_clusters == 1, cluster variance is mathematically undefined (df=0).
- Instead of defaulting p=1.0, explicitly computes observation-level Student's t-test
  and flags cluster inference as unavailable.
"""

from collections import defaultdict
from typing import Dict, Any, List
import numpy as np
from scipy import stats

from src.phase10a9b.schema import CausalHedgedEconomicsRecord


class CausalStatisticalEngine:
    """Computes statistical inference and cluster analysis without fallback artifacts."""

    def __init__(self, cluster_window_sec: float = 300.0):
        self.cluster_window_sec = cluster_window_sec

    def compute_causal_statistics(
        self,
        records: List[CausalHedgedEconomicsRecord]
    ) -> Dict[str, Any]:
        """Computes statistical parameters with explicit observation vs cluster distinction."""
        if not records:
            return {
                "n_raw": 0, "n_clusters": 0, "mean_ev_bps": 0.0, "median_ev_bps": 0.0,
                "cluster_robust_se": 0.0, "obs_se": 0.0, "t_stat": 0.0, "p_value": 0.0,
                "ci_lower": 0.0, "ci_upper": 0.0, "cluster_inference_available": False
            }

        all_vals = [r.hedged_net_ev_bps for r in records]
        cluster_map: Dict[str, List[float]] = defaultdict(list)
        for r in records:
            cluster_map[r.event_cluster_id].append(r.hedged_net_ev_bps)

        n_raw = len(all_vals)
        n_clusters = len(cluster_map)
        vals_arr = np.array(all_vals)

        grand_mean = float(np.mean(vals_arr))
        grand_median = float(np.median(vals_arr))
        std_val = float(np.std(vals_arr, ddof=1)) if n_raw > 1 else 0.0
        obs_se = float(std_val / np.sqrt(n_raw)) if n_raw > 1 else 0.0

        # Observation-level t-stat and p-value
        obs_t = grand_mean / max(1e-6, obs_se)
        obs_df = n_raw - 1
        obs_p = float(2.0 * (1.0 - stats.t.cdf(abs(obs_t), df=max(1, obs_df))))

        # Cluster-level t-stat and p-value
        cluster_means = [np.mean(v) for v in cluster_map.values()]
        if n_clusters > 1:
            cluster_var = np.var(cluster_means, ddof=1) / n_clusters
            cluster_se = float(np.sqrt(cluster_var))
            cluster_t = grand_mean / max(1e-6, cluster_se)
            cluster_df = n_clusters - 1
            cluster_p = float(2.0 * (1.0 - stats.t.cdf(abs(cluster_t), df=cluster_df)))
            cluster_avail = True
            primary_t = cluster_t
            primary_p = cluster_p
            primary_se = cluster_se
        else:
            cluster_se = 0.0
            cluster_avail = False
            primary_t = obs_t
            primary_p = obs_p
            primary_se = obs_se

        # Bootstrap CI (2,000 resamples)
        rng = np.random.default_rng(42)
        boot_means = []
        for _ in range(2000):
            sample = rng.choice(vals_arr, size=n_raw, replace=True)
            boot_means.append(np.mean(sample))
        ci_lower = float(np.percentile(boot_means, 2.5))
        ci_upper = float(np.percentile(boot_means, 97.5))

        return {
            "n_raw": n_raw,
            "n_clusters": n_clusters,
            "mean_ev_bps": round(grand_mean, 2),
            "median_ev_bps": round(grand_median, 2),
            "std_ev_bps": round(std_val, 2),
            "obs_se": round(obs_se, 2),
            "cluster_robust_se": round(cluster_se, 2),
            "t_stat": round(primary_t, 2),
            "p_value": primary_p,
            "obs_t_stat": round(obs_t, 2),
            "obs_p_value": obs_p,
            "ci_lower": round(ci_lower, 2),
            "ci_upper": round(ci_upper, 2),
            "cluster_inference_available": cluster_avail,
            "cluster_note": "Cluster SE computed from cluster means" if cluster_avail else "Cluster inference unavailable (N_clusters=1, df=0); observation-level Student's t reported"
        }
