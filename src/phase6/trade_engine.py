"""Phase 6: Separated Trade Construction and Execution Engine.
Separates statistical relationship discovery from trade construction:
Discovery (Historical predictive relationship & residual mean reversion)
    ↓
Forecast (Given today's A and market state, expected B = X)
    ↓
Fair value (Current market quote B = Y)
    ↓
Mispricing (Gross Edge = |X - Y|)
    ↓
Execution (Net Edge = Gross Edge - Spread - Fees - Slippage - Latency)
    ↓
Trade (Executed ONLY if Net Edge >= Hurdle)
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import numpy as np

from src.normalization.schema import OrderSide, OpportunityClass
from src.phase6.config import Phase6Config
from src.phase6.strict_hypotheses import StrictHypothesis
from src.phase6.relative_value_stat_arb import RelativeValueStatArbModel, ResidualAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    """Complete decomposed trade construction decision record."""
    timestamp: datetime
    hypothesis_id: str
    market_a_id: str
    market_b_id: str
    side: OrderSide
    # Step 1: Forecast
    forecast_fair_value_x: float
    # Step 2: Market Quote
    market_quote_y: float
    market_bid: float
    market_ask: float
    market_mid: float
    # Step 3: Raw Mispricing
    gross_edge: float
    # Step 4: Execution Cost Breakdown
    spread_cost: float
    fee_cost: float
    slippage_cost: float
    latency_drag: float
    basis_risk_discount: float
    total_friction: float
    # Step 5: Net Edge
    net_edge: float
    # Step 6: Trade Decision
    hurdle_rate: float
    is_executed: bool
    rejection_stage: Optional[str]
    rejection_reason: Optional[str]


class Phase6TradeEngine:
    """Implements strict separation between discovery, forecast, fair value, mispricing, and execution."""

    def __init__(self, config: Optional[Phase6Config] = None):
        self.config = config or Phase6Config()

    def evaluate_opportunity(
        self,
        hypothesis: StrictHypothesis,
        model: RelativeValueStatArbModel,
        residual_result: ResidualAnalysisResult,
        current_state_features: Dict[str, float],
        market_bid_b: float,
        market_ask_b: float,
        current_timestamp: Optional[datetime] = None,
        order_size_usd: float = 500.0,
        book_liquidity_usd: float = 50000.0,
    ) -> TradeDecision:
        """Execute the 6-stage trade construction pipeline."""
        now = current_timestamp or datetime.utcnow()
        mid_b = (market_bid_b + market_ask_b) / 2.0
        spread_b = max(0.001, market_ask_b - market_bid_b)

        # =========================================================================
        # STAGE 1: DISCOVERY CHECK
        # =========================================================================
        if not residual_result.is_statistically_mean_reverting:
            return TradeDecision(
                timestamp=now,
                hypothesis_id=hypothesis.hypothesis_id,
                market_a_id=hypothesis.market_a_id,
                market_b_id=hypothesis.market_b_id,
                side=OrderSide.BUY,
                forecast_fair_value_x=mid_b,
                market_quote_y=mid_b,
                market_bid=market_bid_b,
                market_ask=market_ask_b,
                market_mid=mid_b,
                gross_edge=0.0,
                spread_cost=spread_b / 2.0,
                fee_cost=self.config.taker_fee_rate,
                slippage_cost=0.002,
                latency_drag=0.001,
                basis_risk_discount=0.0,
                total_friction=spread_b / 2.0 + self.config.taker_fee_rate + 0.003,
                net_edge=0.0,
                hurdle_rate=self.config.min_net_edge_hurdle,
                is_executed=False,
                rejection_stage="DISCOVERY_FAILED",
                rejection_reason=residual_result.rejection_reason or "Statistical mean-reversion criteria failed."
            )

        # =========================================================================
        # STAGE 2: FORECAST (State-conditional expected value X)
        # =========================================================================
        # Feature row matching design matrix
        # [intercept, pa, delta_a, vol, spread, time_rem, delta_a_x_regime]
        pa = current_state_features.get("price_a", 0.50)
        delta_a = current_state_features.get("delta_a", 0.0)
        vol_a = current_state_features.get("volatility_a", 0.015)
        time_rem = current_state_features.get("time_to_expiry", 30.0)
        regime_high = current_state_features.get("regime_high_vol", 0.0)

        x_row = np.array([
            1.0,
            pa,
            delta_a,
            vol_a,
            spread_b,
            time_rem,
            delta_a * regime_high
        ]).reshape(1, -1)

        forecast_x = float(np.clip(x_row @ model.fitted_beta, 0.01, 0.99)[0])

        # =========================================================================
        # STAGE 3: FAIR VALUE & MARKET QUOTE Y
        # =========================================================================
        # Determine candidate trading direction
        if forecast_x > mid_b:
            # Model believes target contract is underpriced -> BUY YES
            side = OrderSide.BUY
            market_quote_y = market_ask_b # Crossing the spread to buy
            gross_edge = forecast_x - market_quote_y
        else:
            # Model believes target contract is overpriced -> SELL YES (or BUY NO)
            side = OrderSide.SELL
            market_quote_y = market_bid_b # Crossing the spread to hit the bid
            gross_edge = market_quote_y - forecast_x

        if gross_edge <= 0:
            return TradeDecision(
                timestamp=now,
                hypothesis_id=hypothesis.hypothesis_id,
                market_a_id=hypothesis.market_a_id,
                market_b_id=hypothesis.market_b_id,
                side=side,
                forecast_fair_value_x=forecast_x,
                market_quote_y=market_quote_y,
                market_bid=market_bid_b,
                market_ask=market_ask_b,
                market_mid=mid_b,
                gross_edge=gross_edge,
                spread_cost=spread_b / 2.0,
                fee_cost=self.config.taker_fee_rate,
                slippage_cost=0.002,
                latency_drag=0.001,
                basis_risk_discount=0.0,
                total_friction=spread_b / 2.0 + self.config.taker_fee_rate + 0.003,
                net_edge=0.0,
                hurdle_rate=self.config.min_net_edge_hurdle,
                is_executed=False,
                rejection_stage="NO_GROSS_EDGE",
                rejection_reason=f"Gross edge non-positive ({gross_edge*100:+.2f}%): forecast ({forecast_x:.3f}) inside market quote ({market_quote_y:.3f})."
            )

        # =========================================================================
        # STAGE 4: EXECUTION FRICTION MODELING
        # =========================================================================
        # 1. Spread crossing cost (already embedded in quote difference vs mid, but tracked explicitly)
        half_spread = spread_b / 2.0

        # 2. Polymarket taker fee: 10 bps
        fee_cost = self.config.taker_fee_rate

        # 3. Modeled slippage based on book depth and order size
        participation_ratio = min(1.0, order_size_usd / max(5000.0, book_liquidity_usd))
        slippage_cost = 0.002 + 0.015 * (participation_ratio ** 1.5)

        # 4. Latency drag: price movement during latency window (e.g. 250ms)
        # delta_p_latency ~ 0.5 * sigma * sqrt(latency_seconds / (24 * 3600))
        latency_sec = self.config.simulated_latency_ms / 1000.0
        latency_drag = 0.5 * vol_a * np.sqrt(latency_sec / 3600.0)

        # 5. Basis risk discount (for non-structural opportunities)
        if hypothesis.opportunity_class == OpportunityClass.STRUCTURAL:
            basis_risk_discount = 0.0
        else:
            basis_risk_discount = 0.15 * gross_edge # 15% haircut for resolution / settlement divergence

        total_friction = half_spread + fee_cost + slippage_cost + latency_drag + basis_risk_discount

        # =========================================================================
        # STAGE 5: NET EDGE
        # =========================================================================
        net_edge = gross_edge - total_friction

        # =========================================================================
        # STAGE 6: TRADE DECISION (Hurdle Filter)
        # =========================================================================
        if net_edge >= self.config.min_net_edge_hurdle:
            is_executed = True
            rejection_stage = None
            rejection_reason = None
        else:
            is_executed = False
            rejection_stage = "HURDLE_FAILED"
            rejection_reason = (
                f"Net executable edge (+{net_edge*100:.2f}%) below frozen hurdle ({self.config.min_net_edge_hurdle*100:.2f}%). "
                f"Gross edge (+{gross_edge*100:.2f}%) eroded by friction ({total_friction*100:.2f}%)."
            )

        return TradeDecision(
            timestamp=now,
            hypothesis_id=hypothesis.hypothesis_id,
            market_a_id=hypothesis.market_a_id,
            market_b_id=hypothesis.market_b_id,
            side=side,
            forecast_fair_value_x=forecast_x,
            market_quote_y=market_quote_y,
            market_bid=market_bid_b,
            market_ask=market_ask_b,
            market_mid=mid_b,
            gross_edge=gross_edge,
            spread_cost=half_spread,
            fee_cost=fee_cost,
            slippage_cost=slippage_cost,
            latency_drag=latency_drag,
            basis_risk_discount=basis_risk_discount,
            total_friction=total_friction,
            net_edge=net_edge,
            hurdle_rate=self.config.min_net_edge_hurdle,
            is_executed=is_executed,
            rejection_stage=rejection_stage,
            rejection_reason=rejection_reason
        )
