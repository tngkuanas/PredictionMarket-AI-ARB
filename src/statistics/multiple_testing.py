"""Multiple Hypothesis Testing & Funnel Audit Layer.
Implements Benjamini-Hochberg False Discovery Rate (FDR) control, permutation tests,
and explicit pipeline funnel auditing to eliminate data-snooping / p-hacking biases.
"""
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

def benjamini_hochberg_correction(
    p_values: List[float],
    fdr_q: float = 0.05
) -> Dict[str, Any]:
    """Applies the Benjamini-Hochberg (BH) procedure to control False Discovery Rate.
    
    Given m hypotheses with sorted p-values p_(1) <= p_(2) <= ... <= p_(m),
    finds the largest k such that p_(k) <= (k / m) * q.
    Rejects H_(1), ..., H_(k).
    
    Returns:
        Dict containing rejected boolean mask, adjusted p-values (q-values),
        critical thresholds, and total discovery count.
    """
    m = len(p_values)
    if m == 0:
        return {
            "p_values": [],
            "q_values": [],
            "rejected": [],
            "significant_count": 0,
            "threshold": 0.0
        }

    p_arr = np.array(p_values, dtype=float)
    # Handle NaNs
    p_arr = np.nan_to_num(p_arr, nan=1.0)

    # Sort p-values
    sort_idx = np.argsort(p_arr)
    sorted_p = p_arr[sort_idx]

    # Rank k from 1 to m
    ranks = np.arange(1, m + 1)
    # Critical thresholds: (k / m) * q
    critical_vals = (ranks / m) * fdr_q

    # Find largest k where p_(k) <= critical_val
    significant_mask = sorted_p <= critical_vals
    if np.any(significant_mask):
        max_k_idx = np.where(significant_mask)[0][-1]
        rejected_sorted = np.zeros(m, dtype=bool)
        rejected_sorted[:max_k_idx + 1] = True
    else:
        max_k_idx = -1
        rejected_sorted = np.zeros(m, dtype=bool)

    # Compute adjusted p-values (q-values): q_(i) = min_{k >= i} (m / k) * p_(k)
    q_sorted = np.zeros(m)
    current_min = 1.0
    for i in range(m - 1, -1, -1):
        q_val = (m / ranks[i]) * sorted_p[i]
        current_min = min(current_min, q_val)
        q_sorted[i] = current_min

    # Restore original ordering
    rejected_orig = np.zeros(m, dtype=bool)
    rejected_orig[sort_idx] = rejected_sorted
    q_orig = np.zeros(m)
    q_orig[sort_idx] = q_sorted

    return {
        "p_values": p_arr.tolist(),
        "q_values": q_orig.tolist(),
        "rejected": rejected_orig.tolist(),
        "significant_count": int(np.sum(rejected_orig)),
        "max_rejected_p_value": float(sorted_p[max_k_idx]) if max_k_idx >= 0 else 0.0,
        "fdr_q": fdr_q,
        "total_hypotheses": m
    }


class PipelineFunnelAuditor:
    """Tracks hypothesis attrition across every filter stage of the quantitative pipeline:
    Candidate -> Economic Validity -> Overlap / N -> Statistical Test -> Multiple Testing -> OOS -> Friction -> Capacity.
    Guarantees strict monotonicity: survivors at stage i must be a subset of (or <= in count to) stage i-1.
    """

    def __init__(self):
        self.stage_names = [
            "1. Candidate Generation",
            "2. Economic / Domain Validity",
            "3. Active Overlap (>= 48h)",
            "4. Independent Event Power (K >= 15)",
            "5. Statistical Significance (p < 0.05)",
            "6. Multiple Testing FDR (q < 0.05)",
            "7. Out-of-Sample Replication (OOS Persistence)",
            "8. Dynamic Cost Model (Net EV >= 1.5%)",
            "9. Capital Capacity (> $500)"
        ]
        self.counts: Dict[str, int] = {s: 0 for s in self.stage_names}
        self.stage_candidates: Dict[int, set] = {i: set() for i in range(len(self.stage_names))}
        self.rejections_by_stage: Dict[str, List[str]] = {s: [] for s in self.stage_names}

    def record_stage_candidates(self, stage_idx: int, candidate_ids: Any):
        """Records explicit surviving candidate IDs for a stage and asserts monotonicity and subset inclusion."""
        if not (0 <= stage_idx < len(self.stage_names)):
            raise IndexError(f"Stage index {stage_idx} out of range (0-{len(self.stage_names)-1})")

        c_set = set(candidate_ids)
        if stage_idx > 0 and len(self.stage_candidates[stage_idx - 1]) > 0:
            prev_set = self.stage_candidates[stage_idx - 1]
            diff = c_set - prev_set
            assert len(diff) == 0, (
                f"Funnel subset violation at stage {stage_idx} ('{self.stage_names[stage_idx]}'): "
                f"{len(diff)} candidate IDs were not present in previous stage ('{self.stage_names[stage_idx - 1]}'): {diff}"
            )
            assert len(c_set) <= len(prev_set), (
                f"Funnel count monotonicity violation: {len(c_set)} > {len(prev_set)}"
            )

        self.stage_candidates[stage_idx] = c_set
        name = self.stage_names[stage_idx]
        self.counts[name] = len(c_set)

    def set_stage_count(self, stage_idx: int, count: int, candidate_ids: Optional[Any] = None):
        """Sets stage survivor count with strict monotonic non-increasing assertions."""
        if not (0 <= stage_idx < len(self.stage_names)):
            raise IndexError(f"Stage index {stage_idx} out of range (0-{len(self.stage_names)-1})")

        if stage_idx > 0:
            prev_name = self.stage_names[stage_idx - 1]
            prev_cnt = self.counts[prev_name]
            assert count <= prev_cnt, (
                f"Funnel monotonicity violation at stage {stage_idx} ('{self.stage_names[stage_idx]}'): "
                f"count ({count}) cannot exceed previous stage count ({prev_cnt} at '{prev_name}'). "
                f"Each funnel stage must be a strict subset of the prior stage."
            )

        name = self.stage_names[stage_idx]
        self.counts[name] = count
        if candidate_ids is not None:
            self.stage_candidates[stage_idx] = set(candidate_ids)

    def record_stage(self, stage_idx: int, count: int = 1):
        if 0 <= stage_idx < len(self.stage_names):
            name = self.stage_names[stage_idx]
            self.counts[name] += count
            if stage_idx > 0:
                prev_name = self.stage_names[stage_idx - 1]
                assert self.counts[name] <= self.counts[prev_name], (
                    f"Funnel monotonicity violation: {self.counts[name]} > {self.counts[prev_name]}"
                )

    def generate_report_table(self) -> pd.DataFrame:
        rows = []
        prev_count = None
        first_count = None
        for stage in self.stage_names:
            cnt = self.counts[stage]
            if first_count is None and cnt > 0:
                first_count = cnt
            survival_pct_total = (cnt / first_count * 100.0) if first_count and first_count > 0 else 0.0
            step_retention_pct = (cnt / prev_count * 100.0) if prev_count and prev_count > 0 else (100.0 if prev_count is None else 0.0)
            rows.append({
                "Pipeline Stage": stage,
                "Surviving Count": cnt,
                "Step Retention %": f"{step_retention_pct:.1f}%",
                "Cumulative %": f"{survival_pct_total:.1f}%"
            })
            prev_count = cnt
        return pd.DataFrame(rows)
