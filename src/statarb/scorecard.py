"""Machine-Readable Candidate Scorecard across 10 Independent Axes.

CRITICAL RULES:
1. NO overall composite "strategy score".
2. NO numerical ranking of candidate strategies.
3. Every validation axis is strictly categorical:
   PASS | FAIL | INSUFFICIENT_DATA | NOT_TESTED.
4. A strategy is ACCEPTED only if all active gates PASS without exception.
"""

import logging
from typing import Dict, Any, List, Optional

from src.statarb.schema import (
    HypothesisScorecard,
    ScorecardStatus,
    ScorecardVerdict,
    AdversarialVerdict,
    StructuredHypothesis,
)

logger = logging.getLogger(__name__)


class ScorecardEvaluator:
    """Evaluates and builds independent categorical hypothesis scorecards."""

    @classmethod
    def evaluate_scorecard(
        cls,
        hypothesis: StructuredHypothesis,
        statistical_metrics: Optional[Dict[str, Any]] = None,
        oos_results: Optional[Dict[str, Any]] = None,
        adversarial_results: Optional[Dict[str, Any]] = None,
        execution_results: Optional[Dict[str, Any]] = None,
        multiple_testing_fdr_passed: Optional[bool] = None,
        data_quality_clean: Optional[bool] = None,
    ) -> HypothesisScorecard:
        """Constructs an audit scorecard across the 10 independent categorical axes."""
        rejection_reasons: List[str] = []
        details: Dict[str, Any] = {}

        # 1. ECONOMIC MECHANISM
        # Validated if causal mechanism is coherent and non-trivial
        if len(hypothesis.causal_mechanism.strip()) >= 20:
            economic_status = ScorecardStatus.PASS
        else:
            economic_status = ScorecardStatus.FAIL
            rejection_reasons.append("Economic mechanism is too brief or trivial.")

        # 2. STATISTICAL EVIDENCE
        if statistical_metrics is None:
            stat_status = ScorecardStatus.NOT_TESTED
        elif statistical_metrics.get("sample_size", 0) < hypothesis.minimum_sample_requirement:
            stat_status = ScorecardStatus.INSUFFICIENT_DATA
            rejection_reasons.append(
                f"Sample size {statistical_metrics.get('sample_size', 0)} < required {hypothesis.minimum_sample_requirement}."
            )
        elif statistical_metrics.get("is_stationary", False) or statistical_metrics.get("is_cointegrated", False):
            stat_status = ScorecardStatus.PASS
            details["adf_pvalue"] = statistical_metrics.get("adf_pvalue")
            details["cointegration_pvalue"] = statistical_metrics.get("cointegration_pvalue")
        else:
            stat_status = ScorecardStatus.FAIL
            rejection_reasons.append("Failed stationarity and cointegration statistical tests.")

        # 3. OUT-OF-SAMPLE (OOS) STATUS
        if oos_results is None:
            oos_status = ScorecardStatus.NOT_TESTED
        elif oos_results.get("sample_size", 0) < 15:
            oos_status = ScorecardStatus.INSUFFICIENT_DATA
        elif oos_results.get("passed", False):
            oos_status = ScorecardStatus.PASS
            details["oos_net_bps"] = oos_results.get("out_of_sample_net_bps")
        else:
            oos_status = ScorecardStatus.FAIL
            rejection_reasons.append("Out-of-sample edge collapsed or degraded beyond tolerance.")

        # 4. PLACEBO & REVERSAL STATUS
        if adversarial_results is None:
            placebo_status = ScorecardStatus.NOT_TESTED
            robustness_status = ScorecardStatus.NOT_TESTED
            adv_verdict = AdversarialVerdict.PASS
        else:
            adv_verdict = adversarial_results.get("final_adversarial_verdict", AdversarialVerdict.PASS)
            
            # Placebo & Reversal
            pl_pass = adversarial_results.get("time_shift_placebo", {}).get("passed", False)
            rev_pass = adversarial_results.get("reverse_direction", {}).get("passed", False)
            rand_pass = adversarial_results.get("randomized_pair", {}).get("passed", False)
            
            if pl_pass and rev_pass and rand_pass:
                placebo_status = ScorecardStatus.PASS
            else:
                placebo_status = ScorecardStatus.FAIL
                rejection_reasons.append(f"Failed placebo/reversal controls: {adv_verdict.value}")

            # Robustness across regimes, horizons & ablations
            reg_pass = adversarial_results.get("liquidity_regime_stress", {}).get("passed", False)
            hor_pass = adversarial_results.get("different_horizon", {}).get("passed", False)
            abl_pass = adversarial_results.get("feature_removal_ablation", {}).get("passed", False)
            
            if reg_pass and hor_pass and abl_pass:
                robustness_status = ScorecardStatus.PASS
            else:
                robustness_status = ScorecardStatus.FAIL
                rejection_reasons.append("Failed robustness stress checks (regime, horizon, or ablation).")

        # 5. EXECUTION STATUS
        if execution_results is None:
            exec_status = ScorecardStatus.NOT_TESTED
            capacity_status = ScorecardStatus.NOT_TESTED
            latency_status = ScorecardStatus.NOT_TESTED
        elif not execution_results.get("is_executable", False):
            exec_status = ScorecardStatus.FAIL
            stage = execution_results.get("rejection_stage", "UNKNOWN")
            rejection_reasons.append(f"Execution gate rejected at stage: {stage}")
            capacity_status = ScorecardStatus.FAIL if stage == "INSUFFICIENT_DEPTH" else ScorecardStatus.NOT_TESTED
            latency_status = ScorecardStatus.FAIL if stage == "LATENCY" else ScorecardStatus.NOT_TESTED
        else:
            exec_status = ScorecardStatus.PASS
            details["net_executable_bps"] = execution_results.get("net_return_bps")
            details["fill_vwap"] = execution_results.get("fill_vwap")
            
            # Capacity check
            cap = execution_results.get("capacity_limit_usd", 0.0)
            if cap >= hypothesis.capacity_dependency:
                capacity_status = ScorecardStatus.PASS
            else:
                capacity_status = ScorecardStatus.FAIL
                rejection_reasons.append(f"Capacity {cap:.1f} USD < required {hypothesis.capacity_dependency:.1f} USD.")

            # Latency check
            lat_cost = execution_results.get("latency_cost_bps", 0.0)
            if lat_cost < 30.0:
                latency_status = ScorecardStatus.PASS
            else:
                latency_status = ScorecardStatus.FAIL
                rejection_reasons.append(f"Latency friction {lat_cost:.1f} bps excessive.")

        # 6. DATA QUALITY STATUS
        if data_quality_clean is None:
            dq_status = ScorecardStatus.NOT_TESTED
        elif data_quality_clean:
            dq_status = ScorecardStatus.PASS
        else:
            dq_status = ScorecardStatus.FAIL
            rejection_reasons.append("Data quality audit detected sequence gaps, clock jumps, or synthetic markers.")

        # 7. MULTIPLE TESTING STATUS
        if multiple_testing_fdr_passed is None:
            mt_status = ScorecardStatus.NOT_TESTED
        elif multiple_testing_fdr_passed:
            mt_status = ScorecardStatus.PASS
        else:
            mt_status = ScorecardStatus.FAIL
            rejection_reasons.append("Failed multiple-testing false discovery rate (FDR) / family penalty.")

        # OVERALL VERDICT DETERMINATION
        all_statuses = [
            economic_status,
            stat_status,
            oos_status,
            placebo_status,
            exec_status,
            capacity_status,
            latency_status,
            dq_status,
            mt_status,
            robustness_status,
        ]

        if any(s == ScorecardStatus.FAIL for s in all_statuses):
            verdict = ScorecardVerdict.REJECTED
        elif any(s in (ScorecardStatus.INSUFFICIENT_DATA, ScorecardStatus.NOT_TESTED) for s in all_statuses):
            verdict = ScorecardVerdict.INCONCLUSIVE
        else:
            verdict = ScorecardVerdict.ACCEPTED

        return HypothesisScorecard(
            hypothesis_id=hypothesis.hypothesis_id,
            lineage_family_id=hypothesis.lineage_family_id,
            config_hash=hypothesis.config_hash,
            statistical_evidence=stat_status,
            economic_mechanism=economic_status,
            oos_status=oos_status,
            placebo_status=placebo_status,
            execution_status=exec_status,
            capacity_status=capacity_status,
            latency_status=latency_status,
            data_quality_status=dq_status,
            multiple_testing_status=mt_status,
            robustness_status=robustness_status,
            adversarial_verdict=adv_verdict,
            verdict=verdict,
            rejection_reasons=rejection_reasons,
            details=details,
        )
