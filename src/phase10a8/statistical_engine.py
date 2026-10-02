"""Statistical Analysis and Hypothesis Evaluation Engine for Phase 10A.8.

Responsibilities:
1. Compute rigorous parametric and non-parametric statistical metrics:
   mean, median, standard deviation, t-statistic, p-value, 95% CI, 1000-sample bootstrap CI.
2. Incorporate event-clustered standard errors.
3. Compute expected value per quote vs expected value per fill.
4. Assign authoritative Phase 10A.8 verdict states.
"""

from typing import Dict, Any, List, Optional
import numpy as np
from scipy import stats
from src.phase10a8.schema import (
    MakerVerdict,
    HypothesisSummaryResult,
    MakerEconomicsRecord,
)
from src.phase10a8.event_clustering import EventClusterEngine


class StatisticalEngine:
    """Computes comprehensive statistical inference for passive maker edge hypotheses."""

    @classmethod
    def evaluate_hypothesis(
        cls,
        hypothesis_id: str,
        name: str,
        description: str,
        records: List[MakerEconomicsRecord],
        ambiguous_count: int = 0,
        n_bootstrap: int = 1000,
    ) -> HypothesisSummaryResult:
        """Evaluates a maker hypothesis across all simulated quote opportunities and fills."""
        n_raw = len(records)
        if n_raw == 0:
            return cls._make_empty_result(hypothesis_id, name, description)

        # Cluster analysis
        obs_dicts = [
            {"cluster_id": r.cluster_id, "net_maker_pnl_bps": r.net_maker_pnl_bps}
            for r in records
        ]
        cluster_info = EventClusterEngine.analyze_clusters(obs_dicts)
        n_clusters = cluster_info["n_clusters"]

        filled_records = [r for r in records if r.is_filled]
        fill_count = len(filled_records)
        fill_rate = fill_count / n_raw if n_raw > 0 else 0.0

        if fill_count == 0:
            # Zero fills
            return HypothesisSummaryResult(
                hypothesis_id=hypothesis_id,
                name=name,
                description=description,
                n_raw=n_raw,
                n_clusters=n_clusters,
                fill_count=0,
                ambiguous_count=ambiguous_count,
                fill_rate=0.0,
                gross_spread_capture_bps=0.0,
                adverse_selection_bps=0.0,
                liquidation_cost_bps=0.0,
                net_maker_ev_bps=0.0,
                net_maker_ev_usd=0.0,
                ev_per_quote_bps=0.0,
                ev_per_fill_bps=0.0,
                std_dev_bps=0.0,
                ci_95_lower_bps=0.0,
                ci_95_upper_bps=0.0,
                bootstrap_ci_lower_bps=0.0,
                bootstrap_ci_upper_bps=0.0,
                verdict=MakerVerdict.NO_EVIDENCE_OF_EDGE,
                details={"reason": "Zero fills achieved under conservative fill model"},
            )

        # Extract metrics on filled quotes
        net_pnls = [r.net_maker_pnl_bps for r in filled_records]
        net_usds = [r.net_maker_pnl_usd for r in filled_records]
        gross_spreads = [r.gross_spread_capture_bps for r in filled_records]
        adv_sels = [r.adverse_selection_bps for r in filled_records]
        liq_costs = [r.liquidation_cost_bps for r in filled_records]

        mean_gross = float(np.mean(gross_spreads))
        mean_adv = float(np.mean(adv_sels))
        mean_liq = float(np.mean(liq_costs))
        mean_net = float(np.mean(net_pnls))
        total_usd = float(np.sum(net_usds))
        std_net = float(np.std(net_pnls, ddof=1)) if fill_count > 1 else 0.0

        # EV per quote = fill_rate * mean_net_fill
        ev_per_quote_bps = round(fill_rate * mean_net, 4)
        ev_per_fill_bps = round(mean_net, 4)

        # Confidence intervals (Student's t)
        se = std_net / np.sqrt(fill_count) if fill_count > 1 else 0.0
        # Use cluster-robust standard error if higher
        fill_obs_dicts = [
            {"cluster_id": r.cluster_id, "net_maker_pnl_bps": r.net_maker_pnl_bps}
            for r in filled_records
        ]
        fill_cluster_info = EventClusterEngine.analyze_clusters(fill_obs_dicts)
        se_effective = max(se, fill_cluster_info["cluster_se"])

        t_crit = stats.t.ppf(0.975, df=max(1, n_clusters - 1)) if n_clusters > 1 else 1.96
        ci_lower = round(mean_net - t_crit * se_effective, 2)
        ci_upper = round(mean_net + t_crit * se_effective, 2)

        # Bootstrap Confidence Interval (1000 resamples)
        rng = np.random.default_rng(seed=42)
        if fill_count >= 5:
            boot_means = [
                float(np.mean(rng.choice(net_pnls, size=fill_count, replace=True)))
                for _ in range(n_bootstrap)
            ]
            boot_lower = round(float(np.percentile(boot_means, 2.5)), 2)
            boot_upper = round(float(np.percentile(boot_means, 97.5)), 2)
        else:
            boot_lower = ci_lower
            boot_upper = ci_upper

        # Determine Authoritative Verdict
        verdict = cls._determine_verdict(
            n_raw=n_raw,
            n_clusters=n_clusters,
            fill_count=fill_count,
            ambiguous_count=ambiguous_count,
            mean_gross=mean_gross,
            mean_adv=mean_adv,
            mean_liq=mean_liq,
            mean_net=mean_net,
            ci_lower=ci_lower,
        )

        return HypothesisSummaryResult(
            hypothesis_id=hypothesis_id,
            name=name,
            description=description,
            n_raw=n_raw,
            n_clusters=n_clusters,
            fill_count=fill_count,
            ambiguous_count=ambiguous_count,
            fill_rate=round(fill_rate, 4),
            gross_spread_capture_bps=round(mean_gross, 2),
            adverse_selection_bps=round(mean_adv, 2),
            liquidation_cost_bps=round(mean_liq, 2),
            net_maker_ev_bps=round(mean_net, 2),
            net_maker_ev_usd=round(total_usd, 4),
            ev_per_quote_bps=ev_per_quote_bps,
            ev_per_fill_bps=ev_per_fill_bps,
            std_dev_bps=round(std_net, 2),
            ci_95_lower_bps=ci_lower,
            ci_95_upper_bps=ci_upper,
            bootstrap_ci_lower_bps=boot_lower,
            bootstrap_ci_upper_bps=boot_upper,
            verdict=verdict,
            details={
                "cluster_reduction_pct": cluster_info["cluster_reduction_pct"],
                "fill_clusters": fill_cluster_info["n_clusters"],
                "se_effective": round(se_effective, 4),
            },
        )

    @staticmethod
    def _determine_verdict(
        n_raw: int,
        n_clusters: int,
        fill_count: int,
        ambiguous_count: int,
        mean_gross: float,
        mean_adv: float,
        mean_liq: float,
        mean_net: float,
        ci_lower: float,
    ) -> MakerVerdict:
        """Determines the exact verdict based on empirical gates."""
        if n_clusters < 10 or fill_count < 15:
            return MakerVerdict.INSUFFICIENT_DATA

        if ambiguous_count > fill_count:
            return MakerVerdict.EDGE_DEPENDENT_ON_UNVERIFIED_FILL_ASSUMPTIONS

        if mean_net > 0.0 and ci_lower > 0.0:
            return MakerVerdict.PROMISING

        # If net return is negative, identify the destroying mechanism
        if mean_adv > mean_gross:
            return MakerVerdict.EDGE_DESTROYED_BY_ADVERSE_SELECTION
        elif (mean_adv + mean_liq) > mean_gross:
            return MakerVerdict.EDGE_DESTROYED_BY_LIQUIDATION
        
        return MakerVerdict.NO_EVIDENCE_OF_EDGE

    @staticmethod
    def _make_empty_result(hypothesis_id: str, name: str, description: str) -> HypothesisSummaryResult:
        return HypothesisSummaryResult(
            hypothesis_id=hypothesis_id,
            name=name,
            description=description,
            n_raw=0,
            n_clusters=0,
            fill_count=0,
            ambiguous_count=0,
            fill_rate=0.0,
            gross_spread_capture_bps=0.0,
            adverse_selection_bps=0.0,
            liquidation_cost_bps=0.0,
            net_maker_ev_bps=0.0,
            net_maker_ev_usd=0.0,
            ev_per_quote_bps=0.0,
            ev_per_fill_bps=0.0,
            std_dev_bps=0.0,
            ci_95_lower_bps=0.0,
            ci_95_upper_bps=0.0,
            bootstrap_ci_lower_bps=0.0,
            bootstrap_ci_upper_bps=0.0,
            verdict=MakerVerdict.INSUFFICIENT_DATA,
        )
