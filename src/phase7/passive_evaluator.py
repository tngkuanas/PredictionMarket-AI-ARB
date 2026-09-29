"""Phase 7: Passive Execution Evaluator.
Aggregates simulated passive quotes across the tick distance grid (d in {0, 1, 2, 3}).
Computes fill probabilities, adverse selection rates, markout trajectories (1m, 5m, 15m),
and unconditional expected P&L:
    E[P&L] = P(fill | d) * E[Markout_15m | fill]
Determines whether providing liquidity overcomes the taker friction barrier.
"""
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from scipy import stats

from src.phase7.config import Phase7Config
from src.phase7.passive_order_simulator import PassiveQuoteSimulationRecord, DistanceAggregateMetrics

logger = logging.getLogger(__name__)


class PassiveExecutionEvaluator:
    """Evaluates passive quote performance across distance levels and market conditions."""

    def __init__(self, config: Optional[Phase7Config] = None):
        self.config = config or Phase7Config()

    def evaluate_distance_performance(
        self,
        records: List[PassiveQuoteSimulationRecord],
        tick_distance_d: int
    ) -> DistanceAggregateMetrics:
        """Compute aggregate metrics for all orders placed at a specific tick distance d."""
        d_records = [r for r in records if r.tick_distance_d == tick_distance_d]
        n_total = len(d_records)
        dist_label = f"d={tick_distance_d} ({'Best Quote' if tick_distance_d == 0 else f'{tick_distance_d} ticks passive'})"

        if n_total == 0:
            return DistanceAggregateMetrics(
                tick_distance_d=tick_distance_d,
                distance_label=dist_label,
                total_orders_posted=0,
                filled_orders_count=0,
                unfilled_orders_count=0,
                fill_probability=0.0,
                adverse_selection_rate=0.0,
                mean_realized_spread_pp=0.0,
                mean_markout_1m_pp=0.0,
                mean_markout_5m_pp=0.0,
                mean_markout_15m_pp=0.0,
                expected_pnl_per_fill_pp=0.0,
                unconditional_expected_pnl_pp=0.0,
                total_simulated_pnl_usd=0.0,
                is_profitable=False,
                verdict="NO_ORDERS"
            )

        filled = [r for r in d_records if r.is_filled]
        n_filled = len(filled)
        n_unfilled = n_total - n_filled
        fill_prob = float(n_filled / n_total)

        if n_filled == 0:
            return DistanceAggregateMetrics(
                tick_distance_d=tick_distance_d,
                distance_label=dist_label,
                total_orders_posted=n_total,
                filled_orders_count=0,
                unfilled_orders_count=n_unfilled,
                fill_probability=0.0,
                adverse_selection_rate=0.0,
                mean_realized_spread_pp=0.0,
                mean_markout_1m_pp=0.0,
                mean_markout_5m_pp=0.0,
                mean_markout_15m_pp=0.0,
                expected_pnl_per_fill_pp=0.0,
                unconditional_expected_pnl_pp=0.0,
                total_simulated_pnl_usd=0.0,
                is_profitable=False,
                verdict="ZERO_FILLS"
            )

        # Metrics for filled orders
        m_1m = np.array([r.markout_1m_pp for r in filled if r.markout_1m_pp is not None])
        m_5m = np.array([r.markout_5m_pp for r in filled if r.markout_5m_pp is not None])
        m_15m = np.array([r.markout_15m_pp for r in filled if r.markout_15m_pp is not None])
        spreads = np.array([r.spread_captured_pp for r in filled])
        adverse_fills = sum(1 for r in filled if r.is_adverse_fill)
        adverse_rate = float(adverse_fills / n_filled)

        mean_1m = float(np.mean(m_1m)) if len(m_1m) > 0 else 0.0
        mean_5m = float(np.mean(m_5m)) if len(m_5m) > 0 else 0.0
        mean_15m = float(np.mean(m_15m)) if len(m_15m) > 0 else 0.0
        mean_spread = float(np.mean(spreads)) if len(spreads) > 0 else 0.0

        pnl_per_fill = mean_15m - self.config.maker_fee_rate
        unconditional_pnl = fill_prob * pnl_per_fill
        total_pnl_usd = float(np.sum([r.net_pnl_usd for r in filled]))

        is_profit = (unconditional_pnl > 0.001) # Net positive expected return > 10 bps

        if is_profit:
            verdict = "PROFITABLE_PASSIVE_MAKER"
        elif adverse_rate >= 0.50:
            verdict = "REJECTED_ADVERSE_SELECTION"
        elif fill_prob < 0.20:
            verdict = "REJECTED_LOW_FILL_RATE"
        else:
            verdict = "REJECTED_NEGATIVE_EXPECTANCY"

        return DistanceAggregateMetrics(
            tick_distance_d=tick_distance_d,
            distance_label=dist_label,
            total_orders_posted=n_total,
            filled_orders_count=n_filled,
            unfilled_orders_count=n_unfilled,
            fill_probability=fill_prob,
            adverse_selection_rate=adverse_rate,
            mean_realized_spread_pp=mean_spread,
            mean_markout_1m_pp=mean_1m,
            mean_markout_5m_pp=mean_5m,
            mean_markout_15m_pp=mean_15m,
            expected_pnl_per_fill_pp=pnl_per_fill,
            unconditional_expected_pnl_pp=unconditional_pnl,
            total_simulated_pnl_usd=total_pnl_usd,
            is_profitable=is_profit,
            verdict=verdict
        )
