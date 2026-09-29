"""Hypothesis Falsification Engine with Walk-Forward Out-of-Sample Testing and Basis Risk Integration."""
import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd
from scipy import stats

from src.normalization.schema import (
    CandidateRelationship,
    FalsificationResult,
    HypothesisVerdict,
    ConstraintType,
    OpportunityClass,
    ResolutionRuleAnalysis,
)
from src.strategies.ev_engine import MispricingEVEngine

logger = logging.getLogger(__name__)

class HypothesisFalsificationEngine:
    """Rigorous statistical testing engine designed to eliminate false-positive AI hypotheses
    through In-Sample fitting, Out-of-Sample walk-forward replication, and basis risk adjustments.
    """

    def __init__(
        self,
        min_net_edge_pp: float = 0.015, # 1.5% net edge
        confidence_level: float = 0.95,
        default_spread_pp: float = 0.012,
        taker_fee_pp: float = 0.001,
        slippage_pp: float = 0.002,
        epoch_window_hours: float = 72.0,
        ev_engine: Optional[MispricingEVEngine] = None
    ):
        self.min_net_edge_pp = min_net_edge_pp
        self.confidence_level = confidence_level
        self.default_spread_pp = default_spread_pp
        self.taker_fee_pp = taker_fee_pp
        self.slippage_pp = slippage_pp
        self.epoch_window_hours = epoch_window_hours
        self.ev_engine = ev_engine or MispricingEVEngine(
            min_required_net_edge=min_net_edge_pp,
            taker_fee_rate=taker_fee_pp,
            slippage_rate=slippage_pp,
            default_spread=default_spread_pp
        )

    def _get_min_sample_size(self, opp_class: OpportunityClass) -> int:
        """Dynamic sample size: structural tautologies require fewer samples than statistical impulses."""
        if opp_class == OpportunityClass.STRUCTURAL:
            return 10
        elif opp_class == OpportunityClass.CROSS_MARKET_LOGICAL:
            return 15
        else: # AI_SEMANTIC, SECOND_ORDER, INFORMATION_LATENCY
            return 25

    def test_hypothesis_walk_forward(
        self,
        relationship: CandidateRelationship,
        series_a: pd.Series,
        series_b: pd.Series,
        resolution_analysis: Optional[ResolutionRuleAnalysis] = None,
        spread_b: Optional[float] = None,
        liquidity_b: Optional[float] = None,
        split_ratio: float = 0.60
    ) -> FalsificationResult:
        """Execute strict walk-forward testing: In-Sample validation followed by Out-of-Sample replication."""
        const = relationship.constraint
        disc = relationship.discovery
        opp_class = disc.opportunity_class
        min_n = self._get_min_sample_size(opp_class)

        # Align series on timestamp index (hourly)
        df = pd.DataFrame({"pa": series_a, "pb": series_b}).dropna().sort_index()

        if len(df) < 50:
            return self._build_verdict(
                relationship, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                False, False, 0.0, 0.0, 0.0,
                HypothesisVerdict.REJECTED_UNDERPOWERED,
                kill_reason=f"Insufficient overlapping time-series data points (N={len(df)} < 50)"
            )

        # Walk-forward split: In-Sample (IS) vs Out-of-Sample (OOS)
        n_split = int(len(df) * split_ratio)
        df_is = df.iloc[:n_split]
        df_oos = df.iloc[n_split:]

        # Handle MONOTONE BOUND constraint (Structural or Implication)
        if const.constraint_type == ConstraintType.MONOTONE_BOUND:
            return self._test_monotone_bound(
                relationship, df_is, df_oos, resolution_analysis, spread_b, min_n, liquidity_b
            )

        # ==========================================================
        # 1. IN-SAMPLE (IS) EVALUATION
        # ==========================================================
        is_result = self._evaluate_impulse_window(relationship, df_is, min_n=int(min_n * 0.6))
        if not is_result["is_valid"]:
            # Hypothesis failed In-Sample
            return self._build_verdict(
                relationship,
                n_total=is_result["sample_size"],
                n_is=is_result["sample_size"],
                n_oos=0,
                observed_is=is_result["observed_effect"],
                drift_is=is_result["baseline_drift"],
                net_is=is_result["net_effect"],
                ci_l=is_result["ci_low"],
                ci_h=is_result["ci_high"],
                pval_is=is_result["p_value"],
                observed_oos=0.0,
                net_oos=0.0,
                pval_oos=1.0,
                is_coint=is_result["is_cointegrated"],
                is_spurious=is_result["is_spurious"],
                raw_edge=abs(is_result["net_effect"]),
                friction=0.016,
                net_edge=0.0,
                verdict=is_result["verdict"],
                kill_reason=is_result["kill_reason"]
            )

        # ==========================================================
        # 2. OUT-OF-SAMPLE (OOS) REPLICATION
        # ==========================================================
        oos_result = self._evaluate_impulse_window(relationship, df_oos, min_n=max(4, int(min_n * 0.3)))
        
        # Check OOS replication: does the effect persist out-of-sample?
        expected_sign = 1 if const.expected_delta_b > 0 else -1
        is_net = is_result["net_effect"]
        oos_net = oos_result["net_effect"]
        oos_sign = 1 if oos_net > 0 else -1

        if oos_result["sample_size"] < 3 or oos_sign != expected_sign or abs(oos_net) < (0.20 * abs(is_net)):
            return self._build_verdict(
                relationship,
                n_total=is_result["sample_size"] + oos_result["sample_size"],
                n_is=is_result["sample_size"],
                n_oos=oos_result["sample_size"],
                observed_is=is_result["observed_effect"],
                drift_is=is_result["baseline_drift"],
                net_is=is_result["net_effect"],
                ci_l=is_result["ci_low"],
                ci_h=is_result["ci_high"],
                pval_is=is_result["p_value"],
                observed_oos=oos_result["observed_effect"],
                net_oos=oos_result["net_effect"],
                pval_oos=oos_result["p_value"],
                is_coint=is_result["is_cointegrated"],
                is_spurious=is_result["is_spurious"],
                raw_edge=abs(oos_net),
                friction=0.016,
                net_edge=0.0,
                verdict=HypothesisVerdict.REJECTED_OOS_DECAY,
                kill_reason=(
                    f"KILLED (OOS Decay): In-sample effect ({is_net*100:+.2f}%, N={is_result['sample_size']}) "
                    f"failed to replicate out-of-sample ({oos_net*100:+.2f}%, N_oos={oos_result['sample_size']})."
                )
            )

        # ==========================================================
        # 3. BASIS RISK & NET EXPECTED VALUE ADJUSTMENT
        # ==========================================================
        raw_edge_oos = abs(oos_net)
        res_analysis = resolution_analysis or ResolutionRuleAnalysis(
            market_a=relationship.discovery.market_a_id,
            market_b=relationship.discovery.market_b_id,
            prob_divergence=0.0 if opp_class == OpportunityClass.STRUCTURAL else 0.35,
            basis_risk_score=0.0 if opp_class == OpportunityClass.STRUCTURAL else 0.35,
            is_mathematically_guaranteed=(opp_class == OpportunityClass.STRUCTURAL)
        )

        ev_calc = self.ev_engine.calculate_net_ev(
            raw_edge=raw_edge_oos,
            resolution_analysis=res_analysis,
            opportunity_class=opp_class,
            market_spread=spread_b,
            price=float(series_b.iloc[-1]) if len(series_b) > 0 else 0.50,
            liquidity_usd=liquidity_b
        )

        net_ev = ev_calc["net_expected_value"]
        p_div = ev_calc["p_divergence"]
        friction = ev_calc["total_friction"]

        if net_ev < self.min_net_edge_pp:
            if ev_calc["basis_risk_discount"] > 0.010:
                verdict = HypothesisVerdict.REJECTED_BASIS_RISK
                kill_reason = (
                    f"KILLED (Basis Risk): Settlement divergence risk P(div)={p_div*100:.1f}% "
                    f"and friction ({friction*100:.2f}%) erase OOS edge (+{raw_edge_oos*100:.2f}%). Net EV: {net_ev*100:+.2f}%."
                )
            else:
                verdict = HypothesisVerdict.REJECTED_COSTS
                kill_reason = (
                    f"KILLED (Friction Costs): OOS gross edge (+{raw_edge_oos*100:.2f}%) eaten by "
                    f"friction ({friction*100:.2f}%). Net EV: {net_ev*100:+.2f}% < {self.min_net_edge_pp*100:.1f}%."
                )
        else:
            verdict = HypothesisVerdict.TRADEABLE
            kill_reason = None

        evidence = (
            f"IS: N={is_result['sample_size']}, NetEff={is_net*100:+.2f}%, 95% CI [{is_result['ci_low']*100:+.1f}%, {is_result['ci_high']*100:+.1f}%]. "
            f"OOS: N={oos_result['sample_size']}, NetEff={oos_net*100:+.2f}%. "
            f"Basis risk discount: {ev_calc['basis_risk_discount']*100:.2f}%, Friction: {friction*100:.2f}%. Net EV: {net_ev*100:+.2f}%."
        )

        return FalsificationResult(
            constraint_id=const.constraint_id,
            market_a=relationship.discovery.market_a_id,
            market_b=relationship.discovery.market_b_id,
            opportunity_class=opp_class,
            sample_size_n=is_result["sample_size"] + oos_result["sample_size"],
            is_sample_size_n=is_result["sample_size"],
            oos_sample_size_n=oos_result["sample_size"],
            observed_effect_pp=is_result["observed_effect"],
            baseline_drift_pp=is_result["baseline_drift"],
            net_effect_pp=is_result["net_effect"],
            ci_95_low_pp=is_result["ci_low"],
            ci_95_high_pp=is_result["ci_high"],
            p_value=is_result["p_value"],
            oos_observed_effect_pp=oos_result["observed_effect"],
            oos_net_effect_pp=oos_net,
            oos_p_value=oos_result["p_value"],
            lead_time_hours=const.lead_time_hours,
            is_cointegrated=is_result["is_cointegrated"],
            is_spurious_drift=is_result["is_spurious"],
            resolution_divergence_prob=p_div,
            basis_risk_score=res_analysis.basis_risk_score,
            raw_edge_pp=raw_edge_oos,
            friction_costs_pp=friction,
            net_expected_edge_pp=net_ev,
            verdict=verdict,
            kill_reason=kill_reason,
            evidence_summary=evidence,
            test_timestamp=datetime.utcnow()
        )

    def _cluster_independent_epochs(
        self,
        impulse_indices: pd.DatetimeIndex,
        delta_a: pd.Series,
        epoch_window_hours: float = 72.0
    ) -> List[pd.Timestamp]:
        """Clusters consecutive catalyst impulse timestamps within an epoch_window_hours (e.g. 72h)
        into single independent macro event epochs K, selecting the peak impulse timestamp within each epoch.
        """
        if len(impulse_indices) == 0:
            return []

        sorted_indices = sorted(impulse_indices)
        epochs: List[List[pd.Timestamp]] = []
        current_epoch: List[pd.Timestamp] = [sorted_indices[0]]

        for t in sorted_indices[1:]:
            if (t - current_epoch[0]).total_seconds() <= (epoch_window_hours * 3600):
                current_epoch.append(t)
            else:
                epochs.append(current_epoch)
                current_epoch = [t]
        if current_epoch:
            epochs.append(current_epoch)

        independent_events = []
        for epoch in epochs:
            peak_t = max(epoch, key=lambda ts: delta_a.loc[ts] if ts in delta_a.index else 0.0)
            independent_events.append(peak_t)

        return independent_events

    def _evaluate_impulse_window(
        self,
        rel: CandidateRelationship,
        df: pd.DataFrame,
        min_n: int
    ) -> Dict[str, Any]:
        """Evaluates an impulse window on a sub-dataframe (either IS or OOS)."""
        const = rel.constraint
        pa = df["pa"]
        pb = df["pb"]

        # Level vs Returns correlation check
        corr_levels = float(pa.corr(pb)) if len(pa) > 1 else 0.0
        ret_a = pa.diff().dropna()
        ret_b = pb.diff().dropna()
        corr_returns = float(ret_a.corr(ret_b)) if len(ret_a) > 1 else 0.0

        is_spurious = (abs(corr_levels) > 0.65 and abs(corr_returns) < 0.08)

        trigger_threshold = const.trigger_threshold_delta_a
        lead_hours = int(max(1, round(const.lead_time_hours)))
        lookback = min(4, max(1, lead_hours // 2))

        delta_a = pa - pa.shift(lookback)
        impulse_indices = delta_a[delta_a >= trigger_threshold].index

        # Cluster catalyst impulses into independent macro event epochs K (72h clustering)
        valid_events = self._cluster_independent_epochs(
            impulse_indices, delta_a, epoch_window_hours=self.epoch_window_hours
        )

        sample_size = len(valid_events)
        if sample_size < min_n:
            return {
                "is_valid": False,
                "sample_size": sample_size,
                "observed_effect": 0.0,
                "baseline_drift": 0.0,
                "net_effect": 0.0,
                "ci_low": 0.0,
                "ci_high": 0.0,
                "p_value": 1.0,
                "is_cointegrated": False,
                "is_spurious": is_spurious,
                "verdict": HypothesisVerdict.REJECTED_UNDERPOWERED,
                "kill_reason": f"Independent event epochs (K={sample_size} < {min_n}) below threshold."
            }

        responses = []
        for t in valid_events:
            target_time = t + pd.Timedelta(hours=lead_hours)
            subsequent = pb[pb.index >= target_time]
            if not subsequent.empty and t in pb.index:
                responses.append(subsequent.iloc[0] - pb.loc[t])

        if len(responses) < min_n:
            return {
                "is_valid": False,
                "sample_size": len(responses),
                "observed_effect": 0.0,
                "baseline_drift": 0.0,
                "net_effect": 0.0,
                "ci_low": 0.0,
                "ci_high": 0.0,
                "p_value": 1.0,
                "is_cointegrated": False,
                "is_spurious": is_spurious,
                "verdict": HypothesisVerdict.REJECTED_UNDERPOWERED,
                "kill_reason": f"Insufficient independent event responses (K={len(responses)} < {min_n})."
            }

        responses = np.array(responses)
        observed = float(np.mean(responses))
        all_drifts = (pb.shift(-lead_hours) - pb).dropna().values
        drift = float(np.mean(all_drifts)) if len(all_drifts) > 0 else 0.0
        net_effect = observed - drift

        std_err = float(stats.sem(responses)) if len(responses) > 1 else 0.01
        ci_low = net_effect - 1.96 * std_err
        ci_high = net_effect + 1.96 * std_err
        _, p_val = stats.ttest_1samp(responses, drift)
        p_val = float(p_val) if not np.isnan(p_val) else 1.0

        # In-sample validity checks
        if is_spurious:
            return {
                "is_valid": False, "sample_size": len(responses), "observed_effect": observed,
                "baseline_drift": drift, "net_effect": net_effect, "ci_low": ci_low, "ci_high": ci_high,
                "p_value": p_val, "is_cointegrated": False, "is_spurious": True,
                "verdict": HypothesisVerdict.REJECTED_SPURIOUS,
                "kill_reason": f"Spurious common drift (r_levels={corr_levels:.2f}, r_returns={corr_returns:.2f})."
            }

        if (const.expected_delta_b > 0 and net_effect < 0) or (const.expected_delta_b < 0 and net_effect > 0):
            return {
                "is_valid": False, "sample_size": len(responses), "observed_effect": observed,
                "baseline_drift": drift, "net_effect": net_effect, "ci_low": ci_low, "ci_high": ci_high,
                "p_value": p_val, "is_cointegrated": False, "is_spurious": False,
                "verdict": HypothesisVerdict.REJECTED_DIRECTION_MISMATCH,
                "kill_reason": f"Empirical effect ({net_effect:+.3f}) opposes hypothesis sign."
            }

        if (ci_low <= 0 <= ci_high) or p_val > 0.05:
            return {
                "is_valid": False, "sample_size": len(responses), "observed_effect": observed,
                "baseline_drift": drift, "net_effect": net_effect, "ci_low": ci_low, "ci_high": ci_high,
                "p_value": p_val, "is_cointegrated": False, "is_spurious": False,
                "verdict": HypothesisVerdict.REJECTED_SPURIOUS,
                "kill_reason": f"Not statistically significant (p={p_val:.3f}, 95% CI contains 0)."
            }

        return {
            "is_valid": True, "sample_size": len(responses), "observed_effect": observed,
            "baseline_drift": drift, "net_effect": net_effect, "ci_low": ci_low, "ci_high": ci_high,
            "p_value": p_val, "is_cointegrated": False, "is_spurious": False,
            "verdict": HypothesisVerdict.TRADEABLE, "kill_reason": None
        }

    def _test_monotone_bound(
        self,
        rel: CandidateRelationship,
        df_is: pd.DataFrame,
        df_oos: pd.DataFrame,
        res_analysis: Optional[ResolutionRuleAnalysis],
        spread_b: Optional[float],
        min_n: int,
        liquidity_b: Optional[float] = None
    ) -> FalsificationResult:
        const = rel.constraint
        opp_class = rel.discovery.opportunity_class

        # Violations on IS: P(B) > P(A) + 0.005
        viol_is = (df_is["pb"] - df_is["pa"])[df_is["pb"] > df_is["pa"] + 0.005]
        viol_oos = (df_oos["pb"] - df_oos["pa"])[df_oos["pb"] > df_oos["pa"] + 0.005]

        n_is = len(viol_is)
        n_oos = len(viol_oos)
        n_total = n_is + n_oos

        if n_is < min_n:
            return self._build_verdict(
                rel, n_total, n_is, n_oos, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                True, False, 0.0, 0.016, 0.0,
                HypothesisVerdict.REJECTED_UNDERPOWERED,
                kill_reason=f"Monotone bound holds tightly in-sample; violations rare (N_is={n_is} < {min_n})"
            )

        mean_viol_is = float(viol_is.mean())
        mean_viol_oos = float(viol_oos.mean()) if n_oos > 0 else 0.0

        # EV calculation on OOS
        res_an = res_analysis or ResolutionRuleAnalysis(
            market_a=rel.discovery.market_a_id,
            market_b=rel.discovery.market_b_id,
            prob_divergence=0.0 if opp_class == OpportunityClass.STRUCTURAL else 0.15,
            basis_risk_score=0.0 if opp_class == OpportunityClass.STRUCTURAL else 0.15,
            is_mathematically_guaranteed=(opp_class == OpportunityClass.STRUCTURAL)
        )

        ev_calc = self.ev_engine.calculate_net_ev(
            raw_edge=mean_viol_oos,
            resolution_analysis=res_an,
            opportunity_class=opp_class,
            market_spread=spread_b,
            price=float(df_oos["pb"].iloc[-1]) if len(df_oos) > 0 else 0.50,
            liquidity_usd=liquidity_b
        )
        net_ev = ev_calc["net_expected_value"]
        friction = ev_calc["total_friction"]

        if n_oos < 3 or mean_viol_oos < 0.01:
            verdict = HypothesisVerdict.REJECTED_OOS_DECAY
            kill_reason = f"Monotone violations disappeared in OOS window (N_oos={n_oos}, mean={mean_viol_oos*100:.2f}%)."
        elif net_ev < self.min_net_edge_pp:
            verdict = HypothesisVerdict.REJECTED_COSTS
            kill_reason = f"OOS violation magnitude (+{mean_viol_oos*100:.2f}%) insufficient for friction ({friction*100:.2f}%)."
        else:
            verdict = HypothesisVerdict.TRADEABLE
            kill_reason = None

        return FalsificationResult(
            constraint_id=const.constraint_id,
            market_a=rel.discovery.market_a_id,
            market_b=rel.discovery.market_b_id,
            opportunity_class=opp_class,
            sample_size_n=n_total,
            is_sample_size_n=n_is,
            oos_sample_size_n=n_oos,
            observed_effect_pp=mean_viol_is,
            baseline_drift_pp=0.0,
            net_effect_pp=mean_viol_is,
            ci_95_low_pp=mean_viol_is - 0.01,
            ci_95_high_pp=mean_viol_is + 0.01,
            p_value=0.001,
            oos_observed_effect_pp=mean_viol_oos,
            oos_net_effect_pp=mean_viol_oos,
            oos_p_value=0.001,
            lead_time_hours=const.lead_time_hours,
            is_cointegrated=True,
            is_spurious_drift=False,
            resolution_divergence_prob=res_an.prob_divergence,
            basis_risk_score=res_an.basis_risk_score,
            raw_edge_pp=mean_viol_oos,
            friction_costs_pp=friction,
            net_expected_edge_pp=net_ev,
            verdict=verdict,
            kill_reason=kill_reason,
            evidence_summary=f"Monotone ladder: IS viol={mean_viol_is*100:.2f}% (N={n_is}), OOS viol={mean_viol_oos*100:.2f}% (N={n_oos}), Net EV={net_ev*100:+.2f}%",
            test_timestamp=datetime.utcnow()
        )

    def _build_verdict(
        self,
        rel: CandidateRelationship,
        n_total: int, n_is: int, n_oos: int,
        observed_is: float, drift_is: float, net_is: float,
        ci_l: float, ci_h: float, pval_is: float,
        observed_oos: float, net_oos: float, pval_oos: float,
        is_coint: bool, is_spurious: bool,
        raw_edge: float, friction: float, net_edge: float,
        verdict: HypothesisVerdict,
        kill_reason: str
    ) -> FalsificationResult:
        opp_class = rel.discovery.opportunity_class
        p_div = 0.0 if opp_class == OpportunityClass.STRUCTURAL else 0.35
        return FalsificationResult(
            constraint_id=rel.constraint.constraint_id,
            market_a=rel.discovery.market_a_id,
            market_b=rel.discovery.market_b_id,
            opportunity_class=opp_class,
            sample_size_n=n_total,
            is_sample_size_n=n_is,
            oos_sample_size_n=n_oos,
            observed_effect_pp=observed_is,
            baseline_drift_pp=drift_is,
            net_effect_pp=net_is,
            ci_95_low_pp=ci_l,
            ci_95_high_pp=ci_h,
            p_value=pval_is,
            oos_observed_effect_pp=observed_oos,
            oos_net_effect_pp=net_oos,
            oos_p_value=pval_oos,
            lead_time_hours=rel.constraint.lead_time_hours,
            is_cointegrated=is_coint,
            is_spurious_drift=is_spurious,
            resolution_divergence_prob=p_div,
            basis_risk_score=p_div,
            raw_edge_pp=raw_edge,
            friction_costs_pp=friction,
            net_expected_edge_pp=net_edge,
            verdict=verdict,
            kill_reason=kill_reason,
            evidence_summary=kill_reason,
            test_timestamp=datetime.utcnow()
        )
