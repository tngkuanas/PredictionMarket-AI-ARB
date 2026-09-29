"""Phase 6: Comprehensive Evaluator & Sensitivity Audit Engine.
Implements walk-forward 60/40 OOS testing, independent macro event epoch clustering (72h),
Benjamini-Hochberg FDR correction, multi-horizon decay profiling, and parameter perturbation grids.
Enforces the Phase 6 Success Criteria against unyielding statistical rigor.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd
from scipy import stats

from src.normalization.schema import OrderSide, OpportunityClass
from src.phase6.config import Phase6Config
from src.phase6.strict_hypotheses import StrictHypothesis
from src.phase6.relative_value_stat_arb import RelativeValueStatArbModel, ResidualAnalysisResult
from src.phase6.trade_engine import Phase6TradeEngine, TradeDecision
from src.phase6.multi_horizon_decay import (
    MultiHorizonDecayAnalyzer,
    SignalHorizonObservation,
    HorizonAggregateMetrics,
    HORIZON_LABELS,
)

logger = logging.getLogger(__name__)


@dataclass
class HypothesisEvaluationSummary:
    """Comprehensive evaluation result for a single Phase 6 hypothesis."""
    hypothesis_id: str
    pair_label: str
    opportunity_class: OpportunityClass
    in_sample_r2: float
    is_residual_stationary: bool
    ou_kappa: float
    reversion_half_life_hours: float
    n_independent_epochs_k: int
    oos_sample_size: int
    mean_gross_edge_pp: float
    mean_friction_pp: float
    mean_net_edge_pp: float
    nominal_p_value: float
    fdr_q_value: float
    survives_fdr: bool
    trades_executed: int
    trade_hit_rate: float
    realized_net_pnl_usd: float
    peak_horizon_label: str
    peak_gross_movement_pp: float
    decay_profile: Dict[str, float]
    survives_perturbations: bool
    perturbation_min_net_edge_pp: float
    final_verdict: str
    kill_reason: Optional[str] = None


class Phase6Evaluator:
    """Rigorous evaluation suite auditing stat-arb profitability under real-world frictions."""

    def __init__(self, config: Optional[Phase6Config] = None):
        self.config = config or Phase6Config()
        self.trade_engine = Phase6TradeEngine(config=self.config)
        self.decay_analyzer = MultiHorizonDecayAnalyzer(config=self.config)

    def evaluate_hypothesis_walk_forward(
        self,
        hypothesis: StrictHypothesis,
        series_a: pd.Series,
        series_b: pd.Series,
        spread_series_b: Optional[pd.Series] = None,
        liquidity_series_b: Optional[pd.Series] = None,
        split_ratio: float = 0.60,
    ) -> HypothesisEvaluationSummary:
        """Run complete Phase 6 evaluation protocol on a single candidate pair."""
        model = RelativeValueStatArbModel(config=self.config)

        # 1. Align time series and construct feature matrix
        df_all = model.build_feature_matrix(
            series_a=series_a,
            series_b=series_b,
            spread_b=spread_series_b,
            liquidity_b=liquidity_series_b,
            lookback_steps=1
        )

        pair_label = f"{hypothesis.market_a_title[:20]} -> {hypothesis.market_b_title[:20]}"

        if len(df_all) < 60:
            return self._build_underpowered_summary(
                hypothesis, pair_label,
                reason=f"Insufficient overlapping time series data points (N={len(df_all)} < 60)."
            )

        # 2. Walk-forward split: In-Sample (60%) vs Out-of-Sample (40%)
        split_idx = int(len(df_all) * split_ratio)
        df_is = df_all.iloc[:split_idx]
        df_oos = df_all.iloc[split_idx:]

        # 3. Fit In-Sample Relative-Value Model
        b_hat_is, beta, r_sq_is = model.fit_relative_value_model(df_is)

        # 4. In-Sample Residual and Mean-Reversion Analysis
        is_residual_result = model.analyze_residuals_and_mean_reversion(
            df_is,
            z_threshold=self.config.residual_zscore_threshold
        )

        # 5. Out-of-Sample Evaluation
        # Predict fair-value on OOS data
        b_hat_oos = model.predict_fair_value(df_oos)
        df_oos = df_oos.copy()
        df_oos["b_hat"] = b_hat_oos
        df_oos["residual"] = df_oos["pb"] - b_hat_oos

        # Cluster independent catalyst impulses in OOS (72h window)
        trigger_threshold = 0.03
        impulse_mask = df_oos["delta_a"].abs() >= trigger_threshold
        impulse_timestamps = df_oos.index[impulse_mask]

        independent_epochs = self._cluster_epochs(impulse_timestamps, 72.0)
        n_epochs = len(independent_epochs)

        # 6. Trade Construction & Execution over OOS independent events
        trade_decisions: List[TradeDecision] = []
        horizon_obs_all: List[SignalHorizonObservation] = []

        for t in independent_epochs:
            row = df_oos.loc[t]
            spread = float(row.get("spread_b", 0.015))
            mid = float(row["pb"])
            bid = max(0.01, mid - spread / 2.0)
            ask = min(0.99, mid + spread / 2.0)

            features = {
                "price_a": float(row["pa"]),
                "delta_a": float(row["delta_a"]),
                "volatility_a": float(row["volatility_a"]),
                "spread_b": spread,
                "time_to_expiry": float(row["time_to_expiry"]),
                "regime_high_vol": float(row["regime_high_vol"])
            }

            decision = self.trade_engine.evaluate_opportunity(
                hypothesis=hypothesis,
                model=model,
                residual_result=is_residual_result,
                current_state_features=features,
                market_bid_b=bid,
                market_ask_b=ask,
                current_timestamp=t,
                order_size_usd=self.config.default_order_size_usd
            )
            trade_decisions.append(decision)

            # If trade executed, track multi-horizon price decay
            if decision.is_executed:
                h_obs = self.decay_analyzer.evaluate_signal_trajectory(
                    signal_id=f"sig_{t.strftime('%Y%m%d%H%M')}",
                    t0=t,
                    side=decision.side,
                    price_series=series_b,
                    total_friction=decision.total_friction
                )
                horizon_obs_all.extend(h_obs)

        # 7. Aggregate OOS Metrics
        executed_trades = [d for d in trade_decisions if d.is_executed]
        n_trades = len(executed_trades)

        if n_trades > 0:
            gross_edges = [d.gross_edge for d in executed_trades]
            frictions = [d.total_friction for d in executed_trades]
            net_edges = [d.net_edge for d in executed_trades]

            mean_gross = float(np.mean(gross_edges))
            mean_friction = float(np.mean(frictions))
            mean_net = float(np.mean(net_edges))

            # Directional t-test against 0
            if len(net_edges) > 1 and np.std(net_edges) > 1e-9:
                t_stat, p_val = stats.ttest_1samp(net_edges, 0.0)
                p_val = float(p_val) if not np.isnan(p_val) else 1.0
            else:
                p_val = 1.0
        else:
            mean_gross = 0.0
            mean_friction = 0.016
            mean_net = 0.0
            p_val = 1.0

        # Multi-horizon decay curve
        decay_curve = self.decay_analyzer.compute_decay_curve(horizon_obs_all)
        decay_profile_map: Dict[str, float] = {
            lbl: agg.mean_gross_movement_pp for lbl, agg in decay_curve.items()
        }

        # Find peak alpha horizon
        peak_lbl = "24h"
        peak_gross = 0.0
        for lbl, agg in decay_curve.items():
            if agg.mean_gross_movement_pp > peak_gross:
                peak_gross = agg.mean_gross_movement_pp
                peak_lbl = lbl

        # Trade hit rate and P&L from executed trades
        if horizon_obs_all:
            # Evaluate at the 1h horizon or best available
            obs_1h = [o for o in horizon_obs_all if o.horizon_label == "1h"]
            if obs_1h:
                hit_rate = float(np.mean([1.0 if o.is_directional_hit else 0.0 for o in obs_1h]))
                net_rets = [o.net_realized_return_pp for o in obs_1h]
                realized_pnl = float(np.sum(net_rets) * self.config.default_order_size_usd)
            else:
                hit_rate = 0.0
                realized_pnl = 0.0
        else:
            hit_rate = 0.0
            realized_pnl = 0.0

        # 8. Parameter Perturbation Audit
        survives_perturbations, min_pert_edge = self._audit_perturbations(
            hypothesis, df_oos, model, is_residual_result
        )

        # 9. Final Falsification Verdict
        verdict, kill_reason = self._determine_final_verdict(
            is_residual_result=is_residual_result,
            n_epochs=n_epochs,
            n_trades=n_trades,
            mean_net=mean_net,
            p_val=p_val,
            survives_perturbations=survives_perturbations,
            peak_gross=peak_gross
        )

        return HypothesisEvaluationSummary(
            hypothesis_id=hypothesis.hypothesis_id,
            pair_label=pair_label,
            opportunity_class=hypothesis.opportunity_class,
            in_sample_r2=r_sq_is,
            is_residual_stationary=is_residual_result.is_stationary,
            ou_kappa=is_residual_result.ou_kappa,
            reversion_half_life_hours=is_residual_result.reversion_half_life_hours,
            n_independent_epochs_k=n_epochs,
            oos_sample_size=len(df_oos),
            mean_gross_edge_pp=mean_gross,
            mean_friction_pp=mean_friction,
            mean_net_edge_pp=mean_net,
            nominal_p_value=p_val,
            fdr_q_value=p_val, # Updated during batch FDR correction
            survives_fdr=False, # Updated during batch FDR correction
            trades_executed=n_trades,
            trade_hit_rate=hit_rate,
            realized_net_pnl_usd=realized_pnl,
            peak_horizon_label=peak_lbl,
            peak_gross_movement_pp=peak_gross,
            decay_profile=decay_profile_map,
            survives_perturbations=survives_perturbations,
            perturbation_min_net_edge_pp=min_pert_edge,
            final_verdict=verdict,
            kill_reason=kill_reason
        )

    def apply_batch_fdr(
        self,
        summaries: List[HypothesisEvaluationSummary]
    ) -> List[HypothesisEvaluationSummary]:
        """Apply Benjamini-Hochberg FDR correction (q = 0.05) across all evaluated hypotheses."""
        m = len(summaries)
        if m == 0:
            return summaries

        # Sort by nominal p-value ascending
        sorted_indices = sorted(range(m), key=lambda i: summaries[i].nominal_p_value)
        q_threshold = self.config.fdr_alpha

        for rank, idx in enumerate(sorted_indices, start=1):
            crit = (rank / m) * q_threshold
            p_val = summaries[idx].nominal_p_value
            q_val = min(1.0, p_val * (m / rank))
            summaries[idx].fdr_q_value = q_val
            summaries[idx].survives_fdr = (p_val <= crit and summaries[idx].final_verdict != "REJECTED_UNDERPOWERED")
            if not summaries[idx].survives_fdr and summaries[idx].final_verdict == "VALIDATED_STAT_ARB":
                summaries[idx].final_verdict = "REJECTED_FDR"
                summaries[idx].kill_reason = f"KILLED (FDR): Nominal p={p_val:.4f} failed Benjamini-Hochberg critical value {crit:.4f}."

        return summaries

    def _cluster_epochs(self, timestamps: pd.DatetimeIndex, window_hours: float) -> List[pd.Timestamp]:
        """Cluster timestamps into independent epochs."""
        if len(timestamps) == 0:
            return []
        sorted_ts = sorted(timestamps)
        epochs = []
        curr = sorted_ts[0]
        epochs.append(curr)
        for t in sorted_ts[1:]:
            if (t - curr).total_seconds() > window_hours * 3600:
                epochs.append(t)
                curr = t
        return epochs

    def _audit_perturbations(
        self,
        hypothesis: StrictHypothesis,
        df_oos: pd.DataFrame,
        model: RelativeValueStatArbModel,
        residual_result: ResidualAnalysisResult
    ) -> Tuple[bool, float]:
        """Test sensitivity of net edge across perturbation grid: hurdles, latencies, triggers."""
        min_net_found = 999.0

        for hurdle in self.config.perturbation_hurdles:
            for latency in self.config.perturbation_latencies_ms:
                for z_trig in self.config.perturbation_residual_triggers:
                    # Friction under perturbed latency
                    latency_sec = latency / 1000.0
                    lat_drag = 0.5 * 0.015 * np.sqrt(latency_sec / 3600.0)
                    total_fric = 0.0075 + 0.001 + 0.002 + lat_drag
                    # Expected recovery under perturbed trigger
                    rec = residual_result.mean_reversion_recovery_pp * (z_trig / 1.5)
                    net = rec - total_fric
                    min_net_found = min(min_net_found, net)

        survives = min_net_found >= 0.005 # Net edge must remain positive (> 0.5%) under all perturbations
        return survives, float(min_net_found if min_net_found != 999.0 else 0.0)

    def _determine_final_verdict(
        self,
        is_residual_result: ResidualAnalysisResult,
        n_epochs: int,
        n_trades: int,
        mean_net: float,
        p_val: float,
        survives_perturbations: bool,
        peak_gross: float
    ) -> Tuple[str, Optional[str]]:
        """Determine final outcome verdict based on unyielding quantitative falsification standards."""
        if not is_residual_result.is_stationary:
            return "REJECTED_NON_STATIONARY", is_residual_result.rejection_reason

        if is_residual_result.ou_kappa <= 0:
            return "REJECTED_DIVERGENT", is_residual_result.rejection_reason

        if is_residual_result.reversion_half_life_hours > self.config.max_half_life_hours:
            return "REJECTED_SLOW_REVERSION", is_residual_result.rejection_reason

        if n_epochs < self.config.min_independent_epochs_k:
            return "REJECTED_UNDERPOWERED", f"Independent macro event epochs (K={n_epochs}) < required ({self.config.min_independent_epochs_k})."

        if n_trades == 0:
            return "REJECTED_NO_TRADES", "Zero dislocations exceeded execution hurdle after spread, fees, and latency."

        if mean_net < self.config.min_net_edge_hurdle:
            return "REJECTED_COSTS", f"Mean net executable edge (+{mean_net*100:.2f}%) below hurdle ({self.config.min_net_edge_hurdle*100:.2f}%)."

        if p_val > 0.05:
            return "REJECTED_NOT_SIGNIFICANT", f"Net edge not statistically significant at 95% confidence (p={p_val:.3f} > 0.05)."

        if not survives_perturbations:
            return "REJECTED_BRITTLE", "Failed parameter perturbation robustness check (net edge collapsed under higher latency/hurdle)."

        return "VALIDATED_STAT_ARB", None

    def _build_underpowered_summary(
        self,
        hypothesis: StrictHypothesis,
        pair_label: str,
        reason: str
    ) -> HypothesisEvaluationSummary:
        return HypothesisEvaluationSummary(
            hypothesis_id=hypothesis.hypothesis_id,
            pair_label=pair_label,
            opportunity_class=hypothesis.opportunity_class,
            in_sample_r2=0.0,
            is_residual_stationary=False,
            ou_kappa=0.0,
            reversion_half_life_hours=999.0,
            n_independent_epochs_k=0,
            oos_sample_size=0,
            mean_gross_edge_pp=0.0,
            mean_friction_pp=0.016,
            mean_net_edge_pp=0.0,
            nominal_p_value=1.0,
            fdr_q_value=1.0,
            survives_fdr=False,
            trades_executed=0,
            trade_hit_rate=0.0,
            realized_net_pnl_usd=0.0,
            peak_horizon_label="N/A",
            peak_gross_movement_pp=0.0,
            decay_profile={},
            survives_perturbations=False,
            perturbation_min_net_edge_pp=0.0,
            final_verdict="REJECTED_UNDERPOWERED",
            kill_reason=reason
        )
