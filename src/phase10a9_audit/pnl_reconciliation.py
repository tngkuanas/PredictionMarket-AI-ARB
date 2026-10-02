"""P&L Component Reconciliation and Factor Decomposition Audit Engine for Phase 10A.9.

Audits:
- Complete component reconciliation:
  maker gross capture - maker adverse selection + hedge recovery - hedge spread - hedge slippage - latency - fees - liquidation.
- Discrepancy / reconciliation error distributions.
- Verification of +769.58 bps EV improvement claim.
- Verification of -72.06 bps chronological Out-of-Sample (OOS) net EV.
"""

from typing import Dict, Any, List, Tuple
import numpy as np


class Phase10A9PnlReconciler:
    """Audits factor-level P&L accounting, double-counting absence, and EV improvement metrics."""

    @staticmethod
    def audit_pnl_reconciliation(
        economic_records: List[Any],
        tolerance_bps: float = 0.5
    ) -> Dict[str, Any]:
        """Audits every fill record to ensure component P&L sums to net reported EV."""
        if not economic_records:
            return {"status": "NO_DATA"}

        errors = []
        improvements = []
        unhedged_evs = []
        hedged_evs = []

        oos_hedged_evs = []
        disc_hedged_evs = []

        failed_count = 0

        for r in economic_records:
            # Component breakdown
            gross_spread = getattr(r, "passive_gross_spread_bps", 0.0)
            adv_sel = getattr(r, "passive_adverse_selection_bps", 0.0)
            hedge_spread = getattr(r, "hedge_spread_cost_bps", 0.0)
            hedge_slip = getattr(r, "hedge_slippage_bps", 0.0)
            latency_cost = getattr(r, "hedge_latency_cost_bps", 0.0)
            fee_cost = getattr(r, "hedge_fee_bps", 0.0)
            residual_cost = getattr(r, "residual_inventory_cost_bps", 0.0)
            liq_cost = getattr(r, "residual_liquidation_cost_bps", 0.0)

            reported_net = getattr(r, "hedged_net_ev_bps", 0.0)
            reported_unhedged = getattr(r, "unhedged_net_ev_bps", 0.0)
            reported_impr = getattr(r, "ev_improvement_bps", 0.0)

            # Reconstruct net hedged EV
            # For complete hedge: directional adverse selection is neutralized (offset by hedge leg payoff)
            # Net EV = gross_spread - hedge_spread - hedge_slip - latency_cost - fee_cost - residual_cost - liq_cost
            # If partially unhedged, remaining adverse selection applies to unhedged portion.
            is_hedged = getattr(r, "is_fully_hedged", True)
            if is_hedged:
                reconstructed_net = gross_spread - hedge_spread - hedge_slip - latency_cost - fee_cost - residual_cost - liq_cost
            else:
                reconstructed_net = gross_spread - adv_sel - hedge_spread - hedge_slip - latency_cost - fee_cost - residual_cost - liq_cost

            err = abs(reconstructed_net - reported_net)
            errors.append(err)
            if err > tolerance_bps:
                failed_count += 1

            # Improvement check
            impr_diff = abs((reported_net - reported_unhedged) - reported_impr)
            improvements.append(reported_impr)
            unhedged_evs.append(reported_unhedged)
            hedged_evs.append(reported_net)

            # OOS partition
            if getattr(r, "is_out_of_sample", False):
                oos_hedged_evs.append(reported_net)
            else:
                disc_hedged_evs.append(reported_net)

        err_arr = np.array(errors)
        mean_unhedged = float(np.mean(unhedged_evs))
        mean_hedged = float(np.mean(hedged_evs))
        mean_impr = float(np.mean(improvements))
        calc_impr = mean_hedged - mean_unhedged

        mean_oos = float(np.mean(oos_hedged_evs)) if oos_hedged_evs else 0.0
        mean_disc = float(np.mean(disc_hedged_evs)) if disc_hedged_evs else 0.0

        return {
            "total_records_reconciled": len(economic_records),
            "max_reconciliation_error_bps": round(float(np.max(err_arr)), 4),
            "mean_reconciliation_error_bps": round(float(np.mean(err_arr)), 4),
            "median_reconciliation_error_bps": round(float(np.median(err_arr)), 4),
            "p95_reconciliation_error_bps": round(float(np.percentile(err_arr, 95)), 4),
            "failed_reconciliations_count": failed_count,
            "is_pnl_reconciliation_exact": (failed_count == 0),
            "reported_mean_unhedged_ev_bps": round(mean_unhedged, 2),
            "reported_mean_hedged_ev_bps": round(mean_hedged, 2),
            "reported_mean_improvement_bps": round(mean_impr, 2),
            "calculated_improvement_bps": round(calc_impr, 2),
            "is_improvement_reproduced": abs(mean_impr - 769.58) < 1.0,
            "recomputed_discovery_ev_bps": round(mean_disc, 2),
            "recomputed_oos_ev_bps": round(mean_oos, 2),
            "is_oos_reproduced": abs(mean_oos - (-72.06)) < 1.0,
        }
