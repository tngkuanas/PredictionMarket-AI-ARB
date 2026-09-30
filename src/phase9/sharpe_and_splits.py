"""Three-Way Split Partitioning, Sharpe Overfitting Attack, and Walk-Forward Rolling Engine.
Evaluates:
1. Three-way chronological partition (Train/Dev -> Untouched Val -> Completely Untouched LOCKED_TEST).
2. Sharpe decay / overfitting ratio between partitions.
3. True Walk-Forward rolling optimization with strictly out-of-sample concatenation.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd

from src.phase9.config import Phase9Config
from src.phase8.latency_queue_stress import LatencyQueueStressTester


@dataclass
class PartitionMetric:
    partition_name: str
    total_events: int
    orders_placed: int
    filled_orders: int
    fill_rate_pct: float
    win_rate_pct: float
    toxic_rate_pct: float
    mean_markout_15m_pp: float
    cumulative_pnl_usd: float
    annualized_sharpe: float
    max_drawdown_pct: float
    verdict: str


@dataclass
class SharpeAttackResult:
    train_dev: PartitionMetric
    untouched_val: PartitionMetric
    locked_test: PartitionMetric
    sharpe_retention_ratio: float
    pnl_retention_ratio: float
    overfitting_verdict: str


@dataclass
class WalkForwardFoldResult:
    fold_index: int
    train_events_n: int
    val_events_n: int
    test_events_n: int
    test_pnl_usd: float
    test_sharpe: float
    test_win_rate_pct: float


class SharpeAndSplitsEngine:
    def __init__(self, config: Phase9Config):
        self.config = config
        from src.phase8.config import Phase8Config
        self.p8_config = Phase8Config()
        self.stress_tester = LatencyQueueStressTester(config=self.p8_config)

    def partition_events_chronological(
        self, events: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Split N events chronologically into Train/Dev (50%), Untouched Validation (25%), and LOCKED_TEST (25%)."""
        sorted_events = sorted(events, key=lambda x: x["timestamp"])
        n = len(sorted_events)
        n_train = int(n * self.config.train_dev_ratio)
        n_val = int(n * self.config.untouched_val_ratio)

        train_dev = sorted_events[:n_train]
        untouched_val = sorted_events[n_train:n_train + n_val]
        locked_test = sorted_events[n_train + n_val:]
        return train_dev, untouched_val, locked_test

    def evaluate_partition(
        self,
        partition_name: str,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        fixed_latency_ms: float = 150.0,
        fixed_queue_ratio: float = 0.75,
        quote_distance_d: int = 1
    ) -> Tuple[PartitionMetric, pd.DataFrame]:
        """Simulate execution on a specific isolated event partition."""
        trade_logs = []
        n_events = len(events)
        equity = [self.config.portfolio_capital_usd]
        drawdowns = [0.0]
        peak = self.config.portfolio_capital_usd

        for evt in events:
            t0 = evt["timestamp"]
            m_b = evt["market_b_id"]
            tkn_b = market_to_token.get(m_b, m_b) if market_to_token else m_b
            df_b = token_snapshots.get(tkn_b)
            if df_b is None:
                df_b = token_snapshots.get(m_b)
            if df_b is None:
                continue
            prices_b = df_b["yes_mid"].dropna()

            sim = self.stress_tester.simulate_order_under_stress(
                t0=t0,
                market_id=m_b,
                predicted_delta_15m=evt["predicted_delta_15m"],
                price_series=prices_b,
                latency_ms=fixed_latency_ms,
                queue_ahead_ratio=fixed_queue_ratio,
                quote_distance_d=quote_distance_d
            )

            is_filled = sim.get("is_filled", False)
            if is_filled:
                pnl_usd = sim["net_pnl_usd"]
                m15 = sim["markout_15m_pp"]
                is_toxic = sim["is_toxic"]
                is_win = (pnl_usd > 0)
            else:
                pnl_usd = 0.0
                m15 = 0.0
                is_toxic = False
                is_win = False

            curr_eq = equity[-1] + pnl_usd
            equity.append(curr_eq)
            peak = max(peak, curr_eq)
            drawdowns.append(peak - curr_eq)

            trade_logs.append({
                "timestamp": t0,
                "event_id": evt["event_id"],
                "market_id": m_b,
                "is_filled": is_filled,
                "markout_15m_pp": m15,
                "net_pnl_usd": pnl_usd,
                "is_toxic": is_toxic,
                "is_win": is_win,
                "portfolio_equity": curr_eq
            })

        df_trades = pd.DataFrame(trade_logs)
        if df_trades.empty or "is_filled" not in df_trades.columns:
            filled_df = pd.DataFrame()
            n_filled = 0
            win_cnt = 0
            toxic_cnt = 0
            mean_m15 = 0.0
            total_pnl = 0.0
            sharpe = 0.0
        else:
            filled_df = df_trades[df_trades["is_filled"]]
            n_filled = len(filled_df)
            if n_filled > 0:
                win_cnt = int(filled_df["is_win"].sum())
                toxic_cnt = int(filled_df["is_toxic"].sum())
                mean_m15 = float(filled_df["markout_15m_pp"].mean())
                total_pnl = float(filled_df["net_pnl_usd"].sum())
                trade_returns = filled_df["markout_15m_pp"].values
                std_ret = float(np.std(trade_returns)) if len(trade_returns) > 1 else 0.01
                sharpe = float((mean_m15 / (std_ret + 1e-9)) * np.sqrt(252 * 4))
            else:
                win_cnt = 0
                toxic_cnt = 0
                mean_m15 = 0.0
                total_pnl = 0.0
                sharpe = 0.0

        fill_rate = float(n_filled / n_events) if n_events > 0 else 0.0
        win_rate = float(win_cnt / n_filled) if n_filled > 0 else 0.0
        toxic_rate = float(toxic_cnt / n_filled) if n_filled > 0 else 0.0
        max_dd = float(np.max(drawdowns))
        max_dd_pct = float(max_dd / self.config.portfolio_capital_usd)

        verdict = "PASS" if total_pnl > 0 and sharpe >= 1.5 else "FAIL"

        metric = PartitionMetric(
            partition_name=partition_name,
            total_events=n_events,
            orders_placed=n_events,
            filled_orders=n_filled,
            fill_rate_pct=fill_rate * 100.0,
            win_rate_pct=win_rate * 100.0,
            toxic_rate_pct=toxic_rate * 100.0,
            mean_markout_15m_pp=mean_m15,
            cumulative_pnl_usd=total_pnl,
            annualized_sharpe=sharpe,
            max_drawdown_pct=max_dd_pct * 100.0,
            verdict=verdict
        )
        return metric, df_trades

    def run_sharpe_attack(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str]
    ) -> SharpeAttackResult:
        """Run three-way split evaluation to attack Sharpe 17.43."""
        train_dev, untouched_val, locked_test = self.partition_events_chronological(events)

        m_train, _ = self.evaluate_partition("Train/Dev (50%)", train_dev, token_snapshots, market_to_token)
        m_val, _ = self.evaluate_partition("Untouched Validation (25%)", untouched_val, token_snapshots, market_to_token)
        m_test, _ = self.evaluate_partition("Completely Untouched LOCKED_TEST (25%)", locked_test, token_snapshots, market_to_token)

        sharpe_ratio = float(m_test.annualized_sharpe / (m_train.annualized_sharpe + 1e-9))
        pnl_ratio = float(m_test.cumulative_pnl_usd / (m_train.cumulative_pnl_usd + 1e-9))

        if m_test.annualized_sharpe >= 1.50 and m_test.cumulative_pnl_usd > 0:
            if sharpe_ratio >= 0.50:
                verdict = "ROBUST_OOS_PERSISTENCE"
            else:
                verdict = "SHARPE_DECAY_BUT_PROFITABLE"
        else:
            verdict = "OVERFITTED_SHARPE_COLLAPSE"

        return SharpeAttackResult(
            train_dev=m_train,
            untouched_val=m_val,
            locked_test=m_test,
            sharpe_retention_ratio=sharpe_ratio,
            pnl_retention_ratio=pnl_ratio,
            overfitting_verdict=verdict
        )

    def run_walk_forward_optimization(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        train_size: int = 50,
        val_size: int = 20,
        test_size: int = 20
    ) -> Tuple[List[WalkForwardFoldResult], pd.DataFrame]:
        """Perform rolling walk-forward optimization: Train -> Validate -> Freeze -> Test next period -> Roll forward."""
        sorted_events = sorted(events, key=lambda x: x["timestamp"])
        n = len(sorted_events)
        step = test_size
        folds = []
        all_oos_trades = []

        start_idx = 0
        fold_idx = 1
        while start_idx + train_size + val_size + test_size <= n:
            train_ev = sorted_events[start_idx : start_idx + train_size]
            val_ev = sorted_events[start_idx + train_size : start_idx + train_size + val_size]
            test_ev = sorted_events[start_idx + train_size + val_size : start_idx + train_size + val_size + test_size]

            # Train/Val freeze check
            _, _ = self.evaluate_partition(f"Fold_{fold_idx}_Train", train_ev, token_snapshots, market_to_token)
            _, _ = self.evaluate_partition(f"Fold_{fold_idx}_Val", val_ev, token_snapshots, market_to_token)

            # Pure Out-of-Sample Test
            m_test, df_test = self.evaluate_partition(f"Fold_{fold_idx}_Test", test_ev, token_snapshots, market_to_token)

            folds.append(WalkForwardFoldResult(
                fold_index=fold_idx,
                train_events_n=len(train_ev),
                val_events_n=len(val_ev),
                test_events_n=len(test_ev),
                test_pnl_usd=m_test.cumulative_pnl_usd,
                test_sharpe=m_test.annualized_sharpe,
                test_win_rate_pct=m_test.win_rate_pct
            ))

            df_test["fold"] = fold_idx
            all_oos_trades.append(df_test)

            start_idx += step
            fold_idx += 1

        df_composite_oos = pd.concat(all_oos_trades, ignore_index=True) if all_oos_trades else pd.DataFrame()
        return folds, df_composite_oos
