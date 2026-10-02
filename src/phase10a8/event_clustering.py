"""Event Clustering and Effective Degrees of Freedom Computation for Phase 10A.8.

Responsibilities:
1. Eliminate pseudo-sample inflation by grouping observations into 5-minute market event clusters.
2. Calculate effective degrees of freedom and cluster collapse ratio.
3. Compute cluster-robust standard errors for statistical inference.
"""

from datetime import datetime
from typing import Dict, Any, List, Tuple
import numpy as np


class EventClusterEngine:
    """Assigns event cluster identifiers and computes clustered statistical metrics."""

    @staticmethod
    def get_cluster_id(market_id: str, timestamp: datetime, window_minutes: int = 5) -> str:
        """Generates deterministic cluster key grouping quotes into window_minutes blocks."""
        dt_str = timestamp.strftime("%Y%m%d_%H")
        minute_bucket = timestamp.minute // window_minutes
        return f"{market_id}_{dt_str}_{minute_bucket}"

    @classmethod
    def analyze_clusters(
        cls,
        observations: List[Dict[str, Any]],
        value_key: str = "net_maker_pnl_bps",
    ) -> Dict[str, Any]:
        """Calculates clustering metrics, effective N, and cluster-robust standard error."""
        if not observations:
            return {
                "n_raw": 0,
                "n_clusters": 0,
                "cluster_reduction_pct": 0.0,
                "cluster_se": 0.0,
                "cluster_mean": 0.0,
            }

        n_raw = len(observations)
        clusters: Dict[str, List[float]] = {}

        for obs in observations:
            c_id = obs.get("cluster_id", "default_cluster")
            val = float(obs.get(value_key, 0.0))
            if c_id not in clusters:
                clusters[c_id] = []
            clusters[c_id].append(val)

        n_clusters = len(clusters)
        reduction_pct = round((1.0 - (n_clusters / n_raw)) * 100.0, 2) if n_raw > 0 else 0.0

        all_vals = [v for vals in clusters.values() for v in vals]
        grand_mean = float(np.mean(all_vals)) if all_vals else 0.0

        # Cluster-robust standard error calculation
        # Sum of squared cluster residuals
        if n_clusters > 1 and n_raw > 0:
            cluster_residuals = []
            for c_id, vals in clusters.items():
                cluster_sum_res = sum(v - grand_mean for v in vals)
                cluster_residuals.append(cluster_sum_res ** 2)
            
            # Variance estimator: (G / (G-1)) * (1 / N^2) * sum(cluster_sum_res^2)
            g_factor = n_clusters / (n_clusters - 1)
            var_cluster = g_factor * (sum(cluster_residuals) / (n_raw ** 2))
            cluster_se = float(np.sqrt(max(0.0, var_cluster)))
        else:
            cluster_se = float(np.std(all_vals) / np.sqrt(n_raw)) if n_raw > 0 else 0.0

        return {
            "n_raw": n_raw,
            "n_clusters": n_clusters,
            "cluster_reduction_pct": reduction_pct,
            "cluster_mean": round(grand_mean, 4),
            "cluster_se": round(cluster_se, 4),
        }
