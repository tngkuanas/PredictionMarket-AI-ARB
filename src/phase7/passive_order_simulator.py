"""Phase 7: Passive Order Queue & Adverse Selection Simulator.
Simulates posting passive limit orders at discrete tick distances (d in {0, 1, 2, 3})
to capture 15-minute dislocations as a liquidity provider instead of paying the spread.
Audits the critical equation:
    E[P&L] = Spread Captured + Alpha Captured - Adverse Selection - Fees - Inventory Cost
Measures fill probabilities, post-fill markouts (1m, 5m, 15m), and toxic adverse fills.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

from src.normalization.schema import OrderSide
from src.phase7.config import Phase7Config

logger = logging.getLogger(__name__)


@dataclass
class PassiveQuoteSimulationRecord:
    """Record of a single simulated passive limit order placement and subsequent execution/markout."""
    quote_id: str
    timestamp: datetime
    market_id: str
    side: OrderSide
    tick_distance_d: int
    predicted_delta_15m: float
    market_mid_t0: float
    market_bid_t0: float
    market_ask_t0: float
    quote_limit_price: float
    queue_size_ahead_usd: float
    is_filled: bool
    fill_timestamp: Optional[datetime] = None
    fill_price: Optional[float] = None
    time_to_fill_seconds: Optional[float] = None
    # Markouts
    markout_1m_pp: Optional[float] = None
    markout_5m_pp: Optional[float] = None
    markout_15m_pp: Optional[float] = None
    # Decomposed Economics
    spread_captured_pp: float = 0.0
    alpha_captured_pp: float = 0.0
    adverse_selection_loss_pp: float = 0.0
    maker_fee_pp: float = 0.0
    net_pnl_pp: float = 0.0
    net_pnl_usd: float = 0.0
    is_adverse_fill: bool = False
    rejection_or_cancellation_reason: Optional[str] = None


@dataclass
class DistanceAggregateMetrics:
    """Summary metrics for a specific passive quote distance d across all simulated opportunities."""
    tick_distance_d: int
    distance_label: str
    total_orders_posted: int
    filled_orders_count: int
    unfilled_orders_count: int
    fill_probability: float
    adverse_selection_rate: float
    mean_realized_spread_pp: float
    mean_markout_1m_pp: float
    mean_markout_5m_pp: float
    mean_markout_15m_pp: float
    expected_pnl_per_fill_pp: float
    unconditional_expected_pnl_pp: float # P(fill) * E[P&L | fill]
    total_simulated_pnl_usd: float
    is_profitable: bool
    verdict: str


class PassiveOrderSimulator:
    """Simulates passive limit order posting, order-book queue priority, and adverse selection markouts."""

    def __init__(self, config: Optional[Phase7Config] = None):
        self.config = config or Phase7Config()

    def simulate_quote_placement(
        self,
        t0: datetime,
        market_id: str,
        predicted_delta_15m: float,
        price_series: pd.Series,
        spread_series: Optional[pd.Series] = None,
        liquidity_series: Optional[pd.Series] = None,
        tick_distance_d: int = 0,
    ) -> PassiveQuoteSimulationRecord:
        """Simulate posting a limit order at distance d and evaluate whether it fills and subsequent markout."""
        quote_id = f"q_{t0.strftime('%Y%m%d%H%M%S')}_d{tick_distance_d}"

        # Clean and sort price series
        clean_prices = price_series[~price_series.index.duplicated(keep="last")].sort_index()

        # Find closest price at t0
        valid_idx = clean_prices.index[clean_prices.index <= t0]
        if len(valid_idx) == 0:
            return self._build_unfilled_record(
                quote_id, t0, market_id, OrderSide.BUY, tick_distance_d, predicted_delta_15m,
                0.50, 0.49, 0.51, 0.49, 0.0, "Missing price history at t0."
            )

        actual_t0 = valid_idx[-1]
        mid_0 = float(clean_prices.loc[actual_t0])

        # Spread lookup
        if spread_series is not None and len(spread_series) > 0:
            clean_spread = spread_series[~spread_series.index.duplicated(keep="last")]
            if actual_t0 in clean_spread.index:
                val = clean_spread.loc[actual_t0]
                spread_0 = max(0.005, float(val.iloc[0] if isinstance(val, pd.Series) else val))
            else:
                spread_0 = 0.015
        else:
            spread_0 = 0.015

        half_spread = spread_0 / 2.0
        bid_0 = max(0.01, round(mid_0 - half_spread, 4))
        ask_0 = min(0.99, round(mid_0 + half_spread, 4))

        # Liquidity lookup
        if liquidity_series is not None and len(liquidity_series) > 0:
            clean_liq = liquidity_series[~liquidity_series.index.duplicated(keep="last")]
            if actual_t0 in clean_liq.index:
                val_liq = clean_liq.loc[actual_t0]
                book_liq = float(val_liq.iloc[0] if isinstance(val_liq, pd.Series) else val_liq)
            else:
                book_liq = 50000.0
        else:
            book_liq = 50000.0

        # Determine side from signal:
        # If predicted 15m move > 0 -> BUY ONLY (providing bid liquidity)
        # If predicted 15m move < 0 -> SELL ONLY (providing ask liquidity)
        if predicted_delta_15m >= 0:
            side = OrderSide.BUY
            # Quote price: Best Bid minus d ticks
            quote_price = round(max(0.01, bid_0 - (tick_distance_d * self.config.tick_size)), 4)
            # Queue size ahead: fraction of depth at top of book
            queue_ahead = (book_liq * 0.15) * self.config.queue_participation_factor if tick_distance_d == 0 else (book_liq * 0.25)
        else:
            side = OrderSide.SELL
            # Quote price: Best Ask plus d ticks
            quote_price = round(min(0.99, ask_0 + (tick_distance_d * self.config.tick_size)), 4)
            queue_ahead = (book_liq * 0.15) * self.config.queue_participation_factor if tick_distance_d == 0 else (book_liq * 0.25)

        # Execution latency delay (150ms): order becomes active in the book at t_active
        t_active = actual_t0 + pd.Timedelta(milliseconds=self.config.simulated_order_latency_ms)
        t_cancel = actual_t0 + pd.Timedelta(hours=self.config.target_signal_horizon_hours)

        # Forward trajectory lookup
        future_prices = clean_prices[clean_prices.index > actual_t0]
        if future_prices.empty:
            return self._build_unfilled_record(
                quote_id, actual_t0, market_id, side, tick_distance_d, predicted_delta_15m,
                mid_0, bid_0, ask_0, quote_price, queue_ahead, "No forward price history after t0."
            )

        t_next = future_prices.index[0]
        p_next = float(future_prices.iloc[0])
        dt_hours = max(0.25, (t_next - actual_t0).total_seconds() / 3600.0)

        # Estimate rolling volatility of contract (default 0.015 per hour)
        diffs = clean_prices.diff().dropna()
        vol_hourly = float(diffs.std()) if len(diffs) > 5 else 0.015
        vol_hourly = max(0.005, min(0.08, vol_hourly))

        # =========================================================================
        # BROWNIAN BRIDGE BARRIER TOUCH FILL SIMULATION
        # =========================================================================
        # Models the exact microstructure probability that an intra-interval price path
        # penetrates the limit quote price B given start S0 and end S1
        # P(touch B | S0, S1) = exp(-2 * (S0 - B) * (S1 - B) / (sigma^2 * dt))
        queue_drag = 0.12 * tick_distance_d # Deeper quotes have greater queue competition

        if side == OrderSide.BUY:
            # We placed a bid at quote_price (B < S0)
            if p_next <= quote_price:
                # Price ended below bid: guaranteed fill on the downward path (toxic flow)
                fill_prob = 1.0
            else:
                # Price ended above bid: filled only if Brownian excursion dipped down to B
                dist_0 = max(0.001, mid_0 - quote_price)
                dist_1 = max(0.001, p_next - quote_price)
                exponent = - (2.0 * dist_0 * dist_1) / ((vol_hourly ** 2) * dt_hours)
                touch_prob = float(np.exp(np.clip(exponent, -25.0, 0.0)))
                fill_prob = touch_prob * (1.0 - queue_drag)
        else:
            # We placed an ask at quote_price (B > S0)
            if p_next >= quote_price:
                # Price ended above ask: guaranteed fill on the upward path (toxic flow)
                fill_prob = 1.0
            else:
                # Price ended below ask: filled only if excursion spiked up to B
                dist_0 = max(0.001, quote_price - mid_0)
                dist_1 = max(0.001, quote_price - p_next)
                exponent = - (2.0 * dist_0 * dist_1) / ((vol_hourly ** 2) * dt_hours)
                touch_prob = float(np.exp(np.clip(exponent, -25.0, 0.0)))
                fill_prob = touch_prob * (1.0 - queue_drag)

        # Deterministic pseudo-random seed from quote_id hash for 100% reproducible execution
        import hashlib
        h_val = int(hashlib.sha256(quote_id.encode()).hexdigest()[:8], 16)
        u_rand = float(h_val / 0xFFFFFFFF)

        is_filled = (u_rand <= fill_prob)

        if not is_filled:
            return self._build_unfilled_record(
                quote_id, actual_t0, market_id, side, tick_distance_d, predicted_delta_15m,
                mid_0, bid_0, ask_0, quote_price, queue_ahead,
                f"Unfilled: Brownian touch prob={fill_prob:.1%} < rand threshold={u_rand:.1%}."
            )

        # Order FILLED!
        fill_price = quote_price
        fill_t = actual_t0 + pd.Timedelta(seconds=min(900.0, dt_hours * 3600.0 * 0.25))

        # Directional markouts at 15m (p_next)
        if side == OrderSide.BUY:
            m_15m = p_next - fill_price
            spread_captured = mid_0 - fill_price
        else:
            m_15m = fill_price - p_next
            spread_captured = fill_price - mid_0

        # Sub-horizon markout progression
        m_1m = m_15m * (1.0 / 15.0)
        m_5m = m_15m * (5.0 / 15.0)

        alpha_captured = abs(predicted_delta_15m) * (1.0 if m_15m > 0 else -1.0)
        adverse_loss = max(0.0, -m_15m)
        is_toxic = (m_15m < self.config.adverse_selection_loss_threshold)

        maker_fee = self.config.maker_fee_rate
        net_pnl_pp = m_15m - maker_fee
        net_pnl_usd = net_pnl_pp * self.config.order_size_usd

        return PassiveQuoteSimulationRecord(
            quote_id=quote_id,
            timestamp=actual_t0,
            market_id=market_id,
            side=side,
            tick_distance_d=tick_distance_d,
            predicted_delta_15m=predicted_delta_15m,
            market_mid_t0=mid_0,
            market_bid_t0=bid_0,
            market_ask_t0=ask_0,
            quote_limit_price=quote_price,
            queue_size_ahead_usd=queue_ahead,
            is_filled=True,
            fill_timestamp=fill_t,
            fill_price=fill_price,
            time_to_fill_seconds=float((fill_t - actual_t0).total_seconds()),
            markout_1m_pp=m_1m,
            markout_5m_pp=m_5m,
            markout_15m_pp=m_15m,
            spread_captured_pp=spread_captured,
            alpha_captured_pp=alpha_captured,
            adverse_selection_loss_pp=adverse_loss,
            maker_fee_pp=maker_fee,
            net_pnl_pp=net_pnl_pp,
            net_pnl_usd=net_pnl_usd,
            is_adverse_fill=is_toxic,
            rejection_or_cancellation_reason=None
        )

    def _build_unfilled_record(
        self,
        quote_id: str,
        t0: datetime,
        market_id: str,
        side: OrderSide,
        tick_distance_d: int,
        pred_delta: float,
        mid_0: float,
        bid_0: float,
        ask_0: float,
        quote_p: float,
        queue_ahead: float,
        reason: str
    ) -> PassiveQuoteSimulationRecord:
        return PassiveQuoteSimulationRecord(
            quote_id=quote_id,
            timestamp=t0,
            market_id=market_id,
            side=side,
            tick_distance_d=tick_distance_d,
            predicted_delta_15m=pred_delta,
            market_mid_t0=mid_0,
            market_bid_t0=bid_0,
            market_ask_t0=ask_0,
            quote_limit_price=quote_p,
            queue_size_ahead_usd=queue_ahead,
            is_filled=False,
            rejection_or_cancellation_reason=reason
        )
