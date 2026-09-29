"""Phase 6: Multi-Horizon Signal Age Decay Analyzer.
Evaluates out-of-sample price realization across discrete time horizons:
1 minute, 5 minutes, 15 minutes, 1 hour, 6 hours, 24 hours, and final resolution.
Tests whether prediction market dislocations peak at short horizons (e.g. 15m - 1h)
and decay before reaching the standard 24-hour prospective evaluation window.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from src.normalization.schema import OrderSide
from src.phase6.config import Phase6Config

logger = logging.getLogger(__name__)

HORIZON_LABELS = {
    1.0 / 60.0: "1m",
    5.0 / 60.0: "5m",
    0.25: "15m",
    1.0: "1h",
    6.0: "6h",
    24.0: "24h",
    72.0: "resolution",
}


@dataclass
class SignalHorizonObservation:
    """Realized price evolution for a single signal at a specific horizon."""
    signal_id: str
    t0: datetime
    horizon_hours: float
    horizon_label: str
    target_market_id: str
    side: OrderSide
    p0: float
    p_h: float
    gross_movement_pp: float
    total_friction_pp: float
    net_realized_return_pp: float
    is_directional_hit: bool


@dataclass
class HorizonAggregateMetrics:
    """Summary metrics across all signals for a single evaluation horizon."""
    horizon_hours: float
    horizon_label: str
    sample_size_n: int
    mean_gross_movement_pp: float
    median_gross_movement_pp: float
    mean_net_return_pp: float
    directional_hit_rate: float
    std_error_pp: float
    t_statistic: float
    p_value: float


class MultiHorizonDecayAnalyzer:
    """Computes empirical signal decay curves across multiple time horizons."""

    def __init__(self, config: Optional[Phase6Config] = None):
        self.config = config or Phase6Config()

    def evaluate_signal_trajectory(
        self,
        signal_id: str,
        t0: datetime,
        side: OrderSide,
        price_series: pd.Series,
        total_friction: float = 0.016,
    ) -> List[SignalHorizonObservation]:
        """Compute realized price trajectory for a single signal across all horizons."""
        if price_series.empty or t0 not in price_series.index:
            # If exact t0 not in index, find closest preceding index
            valid_idx = price_series.index[price_series.index <= t0]
            if len(valid_idx) == 0:
                return []
            t0 = valid_idx[-1]

        p0 = float(price_series.loc[t0])
        observations: List[SignalHorizonObservation] = []

        for h in self.config.evaluation_horizons_hours:
            label = HORIZON_LABELS.get(h, f"{h:.2f}h")
            target_time = t0 + pd.Timedelta(hours=h)

            # Find closest observation at or after target_time
            future_sub = price_series[price_series.index >= target_time]
            if not future_sub.empty:
                p_h = float(future_sub.iloc[0])
            else:
                # If horizon extends past data, take final available observation
                p_h = float(price_series.iloc[-1])

            # Directional return
            if side == OrderSide.BUY:
                gross_move = p_h - p0
            else:
                gross_move = p0 - p_h

            net_return = gross_move - total_friction
            hit = gross_move > 0

            observations.append(SignalHorizonObservation(
                signal_id=signal_id,
                t0=t0,
                horizon_hours=h,
                horizon_label=label,
                target_market_id=str(price_series.name or "target"),
                side=side,
                p0=p0,
                p_h=p_h,
                gross_movement_pp=gross_move,
                total_friction_pp=total_friction,
                net_realized_return_pp=net_return,
                is_directional_hit=hit
            ))

        return observations

    def compute_decay_curve(
        self,
        observations: List[SignalHorizonObservation]
    ) -> Dict[str, HorizonAggregateMetrics]:
        """Aggregate observations by horizon to generate the empirical decay profile."""
        from scipy import stats

        by_horizon: Dict[float, List[SignalHorizonObservation]] = {}
        for obs in observations:
            by_horizon.setdefault(obs.horizon_hours, []).append(obs)

        aggregates: Dict[str, HorizonAggregateMetrics] = {}

        for h in self.config.evaluation_horizons_hours:
            label = HORIZON_LABELS.get(h, f"{h:.2f}h")
            obs_list = by_horizon.get(h, [])

            if not obs_list:
                aggregates[label] = HorizonAggregateMetrics(
                    horizon_hours=h,
                    horizon_label=label,
                    sample_size_n=0,
                    mean_gross_movement_pp=0.0,
                    median_gross_movement_pp=0.0,
                    mean_net_return_pp=0.0,
                    directional_hit_rate=0.0,
                    std_error_pp=0.0,
                    t_statistic=0.0,
                    p_value=1.0
                )
                continue

            gross_moves = np.array([o.gross_movement_pp for o in obs_list])
            net_returns = np.array([o.net_realized_return_pp for o in obs_list])
            hits = np.array([1.0 if o.is_directional_hit else 0.0 for o in obs_list])

            mean_gross = float(np.mean(gross_moves))
            median_gross = float(np.median(gross_moves))
            mean_net = float(np.mean(net_returns))
            hit_rate = float(np.mean(hits))

            std_err = float(stats.sem(gross_moves)) if len(gross_moves) > 1 else 0.01
            if len(gross_moves) > 1 and np.std(gross_moves) > 1e-9:
                t_stat, p_val = stats.ttest_1samp(gross_moves, 0.0)
                t_stat = float(t_stat) if not np.isnan(t_stat) else 0.0
                p_val = float(p_val) if not np.isnan(p_val) else 1.0
            else:
                t_stat = 0.0
                p_val = 1.0

            aggregates[label] = HorizonAggregateMetrics(
                horizon_hours=h,
                horizon_label=label,
                sample_size_n=len(obs_list),
                mean_gross_movement_pp=mean_gross,
                median_gross_movement_pp=median_gross,
                mean_net_return_pp=mean_net,
                directional_hit_rate=hit_rate,
                std_error_pp=std_err,
                t_statistic=t_stat,
                p_value=p_val
            )

        return aggregates
