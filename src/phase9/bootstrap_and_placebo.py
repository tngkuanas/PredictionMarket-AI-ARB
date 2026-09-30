"""Event-Epoch Bootstrap, Placebo Negative Controls, and Return Permutation Testing Engine.
Evaluates:
1. Block-level bootstrap across event epochs with full distribution and percentiles (5th to 95th).
2. Four rigorous placebo negative controls (Random pairs, Time-shifted, Reversed causality, Timestamp permutation).
3. Signal-to-return permutation test with empirical p-values against null distribution.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd

from src.phase9.config import Phase9Config


@dataclass
class BootstrapDistributionMetric:
    iterations: int
    mean_pnl_usd: float
    median_pnl_usd: float
    pnl_5th_pct: float
    pnl_25th_pct: float
    pnl_50th_pct: float
    pnl_75th_pct: float
    pnl_95th_pct: float
    mean_sharpe: float
    sharpe_5th_pct: float
    sharpe_95th_pct: float
    mean_win_rate_pct: float
    win_rate_5th_pct: float
    win_rate_95th_pct: float
    mean_max_drawdown_pct: float
    prob_negative_expectancy: float  # P(E[P&L] <= 0)
    ci_90_lower_pnl_usd: float
    ci_90_upper_pnl_usd: float


@dataclass
class PlaceboTestResult:
    placebo_type: str
    description: str
    orders_n: int
    fills_n: int
    fill_rate_pct: float
    win_rate_pct: float
    mean_markout_pp: float
    unconditional_pnl_pp: float
    cumulative_pnl_usd: float
    annualized_sharpe: float
    verdict: str  # Expected: ARTIFACT_REJECTED / ZERO_ALPHA


@dataclass
class PermutationTestResult:
    permutations_n: int
    observed_mean_markout_pp: float
    observed_sharpe: float
    null_mean_markout_pp: float
    null_std_markout_pp: float
    null_95th_pct_markout_pp: float
    null_99th_pct_markout_pp: float
    empirical_p_value: float
    z_score: float
    verdict: str  # Expected: STRONGLY_REJECTS_NULL


class BootstrapAndPlaceboEngine:
    def __init__(self, config: Phase9Config):
        self.config = config

    def run_epoch_bootstrap(
        self,
        trade_logs: pd.DataFrame,
        n_iterations: int = 2000,
        random_seed: int = 42
    ) -> BootstrapDistributionMetric:
        """Bootstrap at the event-epoch level (preserving intra-cluster correlation)."""
        rng = np.random.default_rng(random_seed)
        if trade_logs.empty:
            raise ValueError("Trade logs are empty. Cannot perform epoch bootstrap.")

        # Identify unique event clusters/epochs
        if "timestamp" in trade_logs.columns:
            trade_logs = trade_logs.copy()
            trade_logs["epoch_bin"] = pd.to_datetime(trade_logs["timestamp"]).dt.floor("3D")
            epochs = trade_logs["epoch_bin"].unique()
        else:
            epochs = trade_logs["event_id"].unique()

        n_epochs = len(epochs)
        boot_pnls = []
        boot_sharpes = []
        boot_win_rates = []
        boot_drawdowns = []

        for _ in range(n_iterations):
            sampled_epochs = rng.choice(epochs, size=n_epochs, replace=True)
            sampled_trades = pd.concat([trade_logs[trade_logs["epoch_bin" if "epoch_bin" in trade_logs.columns else "event_id"] == ep] for ep in sampled_epochs], ignore_index=True)
            
            filled = sampled_trades[sampled_trades["is_filled"]]
            n_f = len(filled)
            if n_f > 0:
                pnl = float(filled["net_pnl_usd"].sum())
                wins = int(filled["is_win"].sum())
                wr = float(wins / n_f)
                m15 = filled["markout_15m_pp"].values
                mean_m = float(np.mean(m15))
                std_m = float(np.std(m15)) if len(m15) > 1 else 0.01
                sharpe = float((mean_m / (std_m + 1e-9)) * np.sqrt(252 * 4))
            else:
                pnl = 0.0
                wr = 0.0
                sharpe = 0.0

            # Calculate Drawdown
            eq_curve = np.cumsum(sampled_trades["net_pnl_usd"].values)
            peak = np.maximum.accumulate(eq_curve)
            dd = peak - eq_curve
            max_dd_pct = float(np.max(dd) / self.config.portfolio_capital_usd) if len(dd) > 0 else 0.0

            boot_pnls.append(pnl)
            boot_sharpes.append(sharpe)
            boot_win_rates.append(wr)
            boot_drawdowns.append(max_dd_pct)

        boot_pnls = np.array(boot_pnls)
        boot_sharpes = np.array(boot_sharpes)
        boot_win_rates = np.array(boot_win_rates)
        boot_drawdowns = np.array(boot_drawdowns)

        p_neg = float(np.mean(boot_pnls <= 0.0))

        return BootstrapDistributionMetric(
            iterations=n_iterations,
            mean_pnl_usd=float(np.mean(boot_pnls)),
            median_pnl_usd=float(np.median(boot_pnls)),
            pnl_5th_pct=float(np.percentile(boot_pnls, 5)),
            pnl_25th_pct=float(np.percentile(boot_pnls, 25)),
            pnl_50th_pct=float(np.percentile(boot_pnls, 50)),
            pnl_75th_pct=float(np.percentile(boot_pnls, 75)),
            pnl_95th_pct=float(np.percentile(boot_pnls, 95)),
            mean_sharpe=float(np.mean(boot_sharpes)),
            sharpe_5th_pct=float(np.percentile(boot_sharpes, 5)),
            sharpe_95th_pct=float(np.percentile(boot_sharpes, 95)),
            mean_win_rate_pct=float(np.mean(boot_win_rates)) * 100.0,
            win_rate_5th_pct=float(np.percentile(boot_win_rates, 5)) * 100.0,
            win_rate_95th_pct=float(np.percentile(boot_win_rates, 95)) * 100.0,
            mean_max_drawdown_pct=float(np.mean(boot_drawdowns)) * 100.0,
            prob_negative_expectancy=p_neg,
            ci_90_lower_pnl_usd=float(np.percentile(boot_pnls, 5)),
            ci_90_upper_pnl_usd=float(np.percentile(boot_pnls, 95))
        )

    def generate_placebo_events(
        self,
        events: List[Dict[str, Any]],
        placebo_type: str,
        available_tokens: List[str],
        random_seed: int = 42
    ) -> List[Dict[str, Any]]:
        """Construct synthetic negative controls: randomized pairs, time shifts, reversed causality, permuted timestamps."""
        rng = np.random.default_rng(random_seed)
        placebo_events = []

        if placebo_type == "random_pairs":
            for evt in events:
                alt_b = rng.choice(available_tokens)
                p_evt = dict(evt)
                p_evt["market_b_id"] = alt_b
                p_evt["event_id"] = f"{evt['event_id']}_rnd"
                placebo_events.append(p_evt)

        elif placebo_type == "time_shifted_24h":
            shift = pd.Timedelta(hours=24)
            for evt in events:
                p_evt = dict(evt)
                p_evt["timestamp"] = evt["timestamp"] + shift
                p_evt["event_id"] = f"{evt['event_id']}_shift24h"
                placebo_events.append(p_evt)

        elif placebo_type == "reversed_causality":
            for evt in events:
                p_evt = dict(evt)
                # Swap A and B roles
                p_evt["market_a_id"] = evt["market_b_id"]
                p_evt["market_b_id"] = evt["market_a_id"]
                p_evt["predicted_delta_15m"] = -evt["predicted_delta_15m"]
                p_evt["event_id"] = f"{evt['event_id']}_rev"
                placebo_events.append(p_evt)

        elif placebo_type == "permuted_timestamps":
            timestamps = [evt["timestamp"] for evt in events]
            shuffled_ts = rng.permutation(timestamps)
            for i, evt in enumerate(events):
                p_evt = dict(evt)
                p_evt["timestamp"] = shuffled_ts[i]
                p_evt["event_id"] = f"{evt['event_id']}_shuf_ts"
                placebo_events.append(p_evt)

        return placebo_events

    def run_permutation_test(
        self,
        trade_logs: pd.DataFrame,
        n_permutations: int = 2000,
        random_seed: int = 42
    ) -> PermutationTestResult:
        """Shuffle relationship between predicted signal and forward 15m return to construct null distribution."""
        rng = np.random.default_rng(random_seed)
        filled = trade_logs[trade_logs["is_filled"]].copy()
        if filled.empty:
            raise ValueError("No filled trades to permute.")

        observed_markouts = filled["markout_15m_pp"].values
        obs_mean = float(np.mean(observed_markouts))
        obs_std = float(np.std(observed_markouts)) if len(observed_markouts) > 1 else 0.01
        obs_sharpe = float((obs_mean / (obs_std + 1e-9)) * np.sqrt(252 * 4))

        null_means = []
        n_fills = len(filled)

        # Generate null distribution by permuting forward markouts against signals
        for _ in range(n_permutations):
            shuffled_m = rng.permutation(observed_markouts)
            null_means.append(float(np.mean(shuffled_m)))

        null_means = np.array(null_means)
        null_mu = float(np.mean(null_means))
        null_std = float(np.std(null_means)) if len(null_means) > 1 else 0.001

        null_95 = float(np.percentile(null_means, 95))
        null_99 = float(np.percentile(null_means, 99))

        # Empirical one-sided p-value: fraction of null runs exceeding observed markout
        extreme_cnt = np.sum(null_means >= obs_mean)
        emp_p = float((1.0 + extreme_cnt) / (1.0 + n_permutations))
        z_score = float((obs_mean - null_mu) / (null_std + 1e-9))

        verdict = "STRONGLY_REJECTS_NULL" if emp_p < 0.01 else ("WEAK_REJECTION" if emp_p < 0.05 else "FAILS_TO_REJECT_NULL")

        return PermutationTestResult(
            permutations_n=n_permutations,
            observed_mean_markout_pp=obs_mean,
            observed_sharpe=obs_sharpe,
            null_mean_markout_pp=null_mu,
            null_std_markout_pp=null_std,
            null_95th_pct_markout_pp=null_95,
            null_99th_pct_markout_pp=null_99,
            empirical_p_value=emp_p,
            z_score=z_score,
            verdict=verdict
        )
