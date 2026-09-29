"""Phase 8: Microstructure Stress Testing - Latency Sweep & Queue Position Grid.
Audits the Phase 7 passive edge against:
1. Latency Sweep: 0ms -> 50ms -> 100ms -> 250ms -> 500ms -> 1s -> 2s -> 5s.
   Measures E[P&L | fill], unconditional E[P&L], and the latency half-life of alpha.
2. Queue Position Stress: 0% (front) -> 25% -> 50% -> 75% -> 90% -> 99% (back).
   Tests whether edge survives when queue position is realistic rather than front-of-book.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd

from src.normalization.schema import OrderSide
from src.phase8.config import Phase8Config

logger = logging.getLogger(__name__)


@dataclass
class LatencySweepMetric:
    """Performance metrics for a specific execution latency setting."""
    latency_ms: float
    latency_label: str
    total_opportunities: int
    filled_orders_count: int
    fill_probability: float
    adverse_selection_rate: float
    mean_markout_15m_pp: float
    expected_pnl_per_fill_pp: float
    unconditional_expected_pnl_pp: float
    simulated_total_pnl_usd: float
    is_profitable: bool
    verdict: str


@dataclass
class QueuePositionMetric:
    """Performance metrics for a specific queue position depth ratio."""
    queue_ahead_ratio: float
    queue_label: str
    total_opportunities: int
    filled_orders_count: int
    fill_probability: float
    adverse_selection_rate: float
    mean_markout_15m_pp: float
    expected_pnl_per_fill_pp: float
    unconditional_expected_pnl_pp: float
    simulated_total_pnl_usd: float
    is_profitable: bool
    verdict: str


class LatencyQueueStressTester:
    """Stress tests passive market making against latency degradation and queue depth starvation."""

    def __init__(self, config: Optional[Phase8Config] = None):
        self.config = config or Phase8Config()

    def simulate_order_under_stress(
        self,
        t0: datetime,
        market_id: str,
        predicted_delta_15m: float,
        price_series: pd.Series,
        latency_ms: float,
        queue_ahead_ratio: float,
        quote_distance_d: int = 1,
    ) -> Dict[str, Any]:
        """Simulate a passive limit order under explicit latency and queue position constraints."""
        clean_prices = price_series[~price_series.index.duplicated(keep="last")].sort_index()
        valid_idx = clean_prices.index[clean_prices.index <= t0]
        if len(valid_idx) == 0:
            return {"is_filled": False, "reason": "No price history at t0"}

        actual_t0 = valid_idx[-1]
        mid_0 = float(clean_prices.loc[actual_t0])
        half_spread = 0.0075 # 0.75% half spread
        bid_0 = max(0.01, round(mid_0 - half_spread, 4))
        ask_0 = min(0.99, round(mid_0 + half_spread, 4))

        side = OrderSide.BUY if predicted_delta_15m >= 0 else OrderSide.SELL

        # 1. Latency Price Drift Impact:
        # During the latency window (latency_ms), competing market participants react
        # The quote price or fill price suffers adverse drift proportional to sqrt(latency)
        latency_sec = latency_ms / 1000.0
        # Typical price excursion during latency
        vol_hourly = 0.02
        latency_adverse_drift = vol_hourly * np.sqrt(latency_sec / 3600.0)

        if side == OrderSide.BUY:
            quote_price = round(max(0.01, bid_0 - (quote_distance_d * self.config.tick_size)), 4)
        else:
            quote_price = round(min(0.99, ask_0 + (quote_distance_d * self.config.tick_size)), 4)

        # 2. Forward snapshot lookup
        future_prices = clean_prices[clean_prices.index > actual_t0]
        if future_prices.empty:
            return {"is_filled": False, "reason": "No forward price history"}

        t_next = future_prices.index[0]
        p_next = float(future_prices.iloc[0])
        dt_hours = max(0.25, (t_next - actual_t0).total_seconds() / 3600.0)

        # 3. Queue Position Attenuation:
        # Effective barrier distance increases when behind queue (excursion must be deeper)
        # queue_ahead_ratio in [0.0, 0.99]
        queue_barrier_penalty = queue_ahead_ratio * 0.004

        if side == OrderSide.BUY:
            eff_barrier = quote_price - queue_barrier_penalty
            if p_next <= eff_barrier:
                # Guaranteed fill on downward move
                fill_prob = 1.0
            else:
                dist_0 = max(0.001, mid_0 - eff_barrier)
                dist_1 = max(0.001, p_next - eff_barrier)
                exponent = - (2.0 * dist_0 * dist_1) / ((vol_hourly ** 2) * dt_hours)
                fill_prob = float(np.exp(np.clip(exponent, -25.0, 0.0))) * (1.0 - 0.40 * queue_ahead_ratio)
        else:
            eff_barrier = quote_price + queue_barrier_penalty
            if p_next >= eff_barrier:
                fill_prob = 1.0
            else:
                dist_0 = max(0.001, eff_barrier - mid_0)
                dist_1 = max(0.001, eff_barrier - p_next)
                exponent = - (2.0 * dist_0 * dist_1) / ((vol_hourly ** 2) * dt_hours)
                fill_prob = float(np.exp(np.clip(exponent, -25.0, 0.0))) * (1.0 - 0.40 * queue_ahead_ratio)

        # Deterministic pseudo-random seed based on quote parameters
        import hashlib
        seed_str = f"{t0.isoformat()}_{market_id}_{latency_ms}_{queue_ahead_ratio}_{quote_distance_d}"
        h_val = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
        u_rand = float(h_val / 0xFFFFFFFF)

        is_filled = (u_rand <= fill_prob)
        if not is_filled:
            return {"is_filled": False, "fill_prob": fill_prob, "reason": "Queue attenuation unfilled"}

        # Order Filled: Markout suffers latency adverse drift
        if side == OrderSide.BUY:
            raw_markout = p_next - quote_price
            effective_markout = raw_markout - latency_adverse_drift
        else:
            raw_markout = quote_price - p_next
            effective_markout = raw_markout - latency_adverse_drift

        is_toxic = (effective_markout < -0.005)
        net_pnl_pp = effective_markout - self.config.maker_fee_rate
        net_pnl_usd = net_pnl_pp * self.config.order_size_usd

        return {
            "is_filled": True,
            "fill_prob": fill_prob,
            "fill_price": quote_price,
            "markout_15m_pp": effective_markout,
            "is_toxic": is_toxic,
            "net_pnl_pp": net_pnl_pp,
            "net_pnl_usd": net_pnl_usd,
            "latency_drag_pp": latency_adverse_drift
        }

    def run_latency_sweep(
        self,
        event_impulses: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        fixed_queue_ratio: float = 0.75,
        quote_distance_d: int = 1
    ) -> List[LatencySweepMetric]:
        """Execute sweep across latency grid: [0, 50, 100, 250, 500, 1000, 2000, 5000] ms."""
        results: List[LatencySweepMetric] = []

        for lat in self.config.latency_sweep_ms:
            lat_label = f"{lat:.0f}ms" if lat < 1000 else f"{lat/1000:.1f}s"
            orders_total = len(event_impulses)
            filled_records = []

            for evt in event_impulses:
                m_id = evt["market_b_id"]
                tkn = market_to_token.get(m_id)
                df = token_snapshots.get(tkn)
                if df is None:
                    continue
                price_series = df["yes_mid"].dropna()

                sim = self.simulate_order_under_stress(
                    t0=evt["timestamp"],
                    market_id=m_id,
                    predicted_delta_15m=evt["predicted_delta_15m"],
                    price_series=price_series,
                    latency_ms=lat,
                    queue_ahead_ratio=fixed_queue_ratio,
                    quote_distance_d=quote_distance_d
                )
                if sim["is_filled"]:
                    filled_records.append(sim)

            n_filled = len(filled_records)
            fill_p = float(n_filled / orders_total) if orders_total > 0 else 0.0

            if n_filled > 0:
                m15 = np.array([r["markout_15m_pp"] for r in filled_records])
                toxic_cnt = sum(1 for r in filled_records if r["is_toxic"])
                adverse_rate = float(toxic_cnt / n_filled)
                mean_m15 = float(np.mean(m15))
                pnl_per_fill = mean_m15
                uncond_pnl = fill_p * pnl_per_fill
                sim_usd = float(np.sum([r["net_pnl_usd"] for r in filled_records]))
            else:
                adverse_rate = 0.0
                mean_m15 = 0.0
                pnl_per_fill = 0.0
                uncond_pnl = 0.0
                sim_usd = 0.0

            is_prof = (uncond_pnl > 0.001)
            verdict = "PROFITABLE" if is_prof else ("LATENCY_ERODED" if uncond_pnl <= 0 else "MARGINAL")

            results.append(LatencySweepMetric(
                latency_ms=lat,
                latency_label=lat_label,
                total_opportunities=orders_total,
                filled_orders_count=n_filled,
                fill_probability=fill_p,
                adverse_selection_rate=adverse_rate,
                mean_markout_15m_pp=mean_m15,
                expected_pnl_per_fill_pp=pnl_per_fill,
                unconditional_expected_pnl_pp=uncond_pnl,
                simulated_total_pnl_usd=sim_usd,
                is_profitable=is_prof,
                verdict=verdict
            ))

        return results

    def run_queue_stress(
        self,
        event_impulses: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        fixed_latency_ms: float = 150.0,
        quote_distance_d: int = 1
    ) -> List[QueuePositionMetric]:
        """Execute stress test across queue ahead ratios: [0.0, 0.25, 0.50, 0.75, 0.90, 0.99]."""
        results: List[QueuePositionMetric] = []

        for q in self.config.queue_ahead_ratios:
            q_label = f"{q*100:.0f}% ahead"
            orders_total = len(event_impulses)
            filled_records = []

            for evt in event_impulses:
                m_id = evt["market_b_id"]
                tkn = market_to_token.get(m_id)
                df = token_snapshots.get(tkn)
                if df is None:
                    continue
                price_series = df["yes_mid"].dropna()

                sim = self.simulate_order_under_stress(
                    t0=evt["timestamp"],
                    market_id=m_id,
                    predicted_delta_15m=evt["predicted_delta_15m"],
                    price_series=price_series,
                    latency_ms=fixed_latency_ms,
                    queue_ahead_ratio=q,
                    quote_distance_d=quote_distance_d
                )
                if sim["is_filled"]:
                    filled_records.append(sim)

            n_filled = len(filled_records)
            fill_p = float(n_filled / orders_total) if orders_total > 0 else 0.0

            if n_filled > 0:
                m15 = np.array([r["markout_15m_pp"] for r in filled_records])
                toxic_cnt = sum(1 for r in filled_records if r["is_toxic"])
                adverse_rate = float(toxic_cnt / n_filled)
                mean_m15 = float(np.mean(m15))
                pnl_per_fill = mean_m15
                uncond_pnl = fill_p * pnl_per_fill
                sim_usd = float(np.sum([r["net_pnl_usd"] for r in filled_records]))
            else:
                adverse_rate = 0.0
                mean_m15 = 0.0
                pnl_per_fill = 0.0
                uncond_pnl = 0.0
                sim_usd = 0.0

            is_prof = (uncond_pnl > 0.001)
            verdict = "ROBUST" if is_prof else ("QUEUE_STARVED" if fill_p < 0.15 else "UNPROFITABLE")

            results.append(QueuePositionMetric(
                queue_ahead_ratio=q,
                queue_label=q_label,
                total_opportunities=orders_total,
                filled_orders_count=n_filled,
                fill_probability=fill_p,
                adverse_selection_rate=adverse_rate,
                mean_markout_15m_pp=mean_m15,
                expected_pnl_per_fill_pp=pnl_per_fill,
                unconditional_expected_pnl_pp=uncond_pnl,
                simulated_total_pnl_usd=sim_usd,
                is_profitable=is_prof,
                verdict=verdict
            ))

        return results
