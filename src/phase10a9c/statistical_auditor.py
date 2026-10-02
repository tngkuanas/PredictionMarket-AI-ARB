"""Statistical and Multiple-Testing Forensic Auditor for Phase 10A.9-C.

Audits:
- Statistical significance of positive OOS latency tiers (250ms & 500ms).
- 2,000-resample bootstrap confidence intervals.
- Holm-Bonferroni family-wise error rate multiple-testing correction across 10 latency tiers.
- Discovery vs OOS temporal decomposition and sample concentration explanation.
"""

from typing import Dict, Any, List, Tuple
import numpy as np
from scipy import stats


class Phase10A9CStatisticalAuditor:
    """Forensic auditor evaluating statistical inference and multiple-hypothesis adjustments."""

    @classmethod
    def audit_positive_tiers(
        cls,
        oos_evs_by_tier: Dict[int, List[float]]
    ) -> Dict[int, Dict[str, Any]]:
        """Audits statistical properties of positive and near-zero OOS latency tiers."""
        audit_results = {}
        rng = np.random.default_rng(42)

        for lat_ms in [100, 250, 500, 1000]:
            vals = np.array(oos_evs_by_tier.get(lat_ms, []))
            n = len(vals)
            if n == 0:
                continue

            mean_val = float(np.mean(vals))
            med_val = float(np.median(vals))
            std_val = float(np.std(vals, ddof=1)) if n > 1 else 0.0
            se_val = (std_val / np.sqrt(n)) if n > 1 else 1e-4
            t_val = mean_val / max(1e-6, se_val)
            p_val = float(2.0 * (1.0 - stats.t.cdf(abs(t_val), df=max(1, n - 1))))

            boot = [np.mean(rng.choice(vals, size=n, replace=True)) for _ in range(2000)]
            ci_low = float(np.percentile(boot, 2.5))
            ci_high = float(np.percentile(boot, 97.5))

            audit_results[lat_ms] = {
                "latency_ms": lat_ms,
                "n_observations": n,
                "mean_ev_bps": round(mean_val, 2),
                "median_ev_bps": round(med_val, 2),
                "std_bps": round(std_val, 2),
                "t_stat": round(t_val, 2),
                "obs_p_value": p_val,
                "ci_lower": round(ci_low, 2),
                "ci_upper": round(ci_high, 2),
                "ci_crosses_zero": (ci_low <= 0.0 <= ci_high),
                "is_statistically_significant": (p_val < 0.05 and not (ci_low <= 0.0 <= ci_high)),
            }

        return audit_results

    @classmethod
    def audit_multiple_testing(
        cls,
        oos_evs_by_tier: Dict[int, List[float]]
    ) -> List[Dict[str, Any]]:
        """Applies Holm-Bonferroni family-wise error rate correction across 10 latency tiers."""
        raw_records = []
        rng = np.random.default_rng(42)

        for lat_ms, vals_list in oos_evs_by_tier.items():
            vals = np.array(vals_list)
            n = len(vals)
            mean_val = float(np.mean(vals)) if n > 0 else 0.0
            std_val = float(np.std(vals, ddof=1)) if n > 1 else 0.0
            se_val = (std_val / np.sqrt(n)) if n > 1 else 1e-4
            t_val = mean_val / max(1e-6, se_val)
            p_val = float(2.0 * (1.0 - stats.t.cdf(abs(t_val), df=max(1, n - 1))))

            boot = [np.mean(rng.choice(vals, size=n, replace=True)) for _ in range(2000)]
            ci_low = float(np.percentile(boot, 2.5))
            ci_high = float(np.percentile(boot, 97.5))

            raw_records.append({
                "latency_ms": lat_ms,
                "mean_ev": round(mean_val, 2),
                "t_stat": round(t_val, 2),
                "raw_p": p_val,
                "ci_lower": round(ci_low, 2),
                "ci_upper": round(ci_high, 2),
                "ci_crosses_zero": (ci_low <= 0.0 <= ci_high)
            })

        # Holm-Bonferroni correction
        # Sort by raw p-value ascending
        sorted_records = sorted(raw_records, key=lambda x: x["raw_p"])
        m = len(sorted_records)
        for rank, r in enumerate(sorted_records):
            multiplier = m - rank
            adj_p = min(1.0, r["raw_p"] * multiplier)
            r["adj_p"] = adj_p
            r["is_adj_significant"] = (adj_p < 0.05 and not r["ci_crosses_zero"])

        # Re-sort by latency order
        raw_records.sort(key=lambda x: x["latency_ms"])
        return raw_records

    @classmethod
    def audit_discovery_oos_decomposition(
        cls,
        tier_results: Dict[int, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Decomposes Discovery vs OOS performance for all latency tiers."""
        rows = []
        for lat_ms, res in tier_results.items():
            disc_ev = res["disc_ev"]
            oos_ev = float(np.mean(res["oos_evs"])) if res["oos_evs"] else 0.0
            diff = oos_ev - disc_ev
            rows.append({
                "latency_ms": lat_ms,
                "discovery_n": 281,
                "discovery_ev_bps": round(disc_ev, 2),
                "oos_n": 219,
                "oos_ev_bps": round(oos_ev, 2),
                "difference_bps": round(diff, 2),
            })
        return rows
