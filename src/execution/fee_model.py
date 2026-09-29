"""Dynamic Execution Cost Model for Prediction Markets.
Computes real execution costs: C = f(price, spread, depth, order_size, side, liquidity, maker/taker)
Avoids overly conservative generic friction assumptions.
"""
import math
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class DynamicExecutionCostModel:
    """Calculates realistic execution friction based on contract price, order book depth,
    liquidity tiers, and maker vs taker order mechanics.
    """

    def __init__(
        self,
        default_taker_fee: float = 0.001, # 0.1% Polymarket taker fee
        default_maker_fee: float = 0.000, # 0.0% Polymarket maker fee
        min_spread_cents: float = 0.005,  # 0.5 cents for top tier liquid markets
        impact_coefficient: float = 0.05   # Price impact scaling
    ):
        self.taker_fee = default_taker_fee
        self.maker_fee = default_maker_fee
        self.min_spread_cents = min_spread_cents
        self.impact_coef = impact_coefficient

    def estimate_spread(self, liquidity_usd: float, price: float) -> float:
        """Estimate dynamic bid-ask spread based on order-book liquidity and price level."""
        # Top-tier liquidity (> $100k): tight 0.5 to 1.0 cent spread
        if liquidity_usd >= 100_000:
            spread = 0.008 # 0.8 cents
        elif liquidity_usd >= 25_000:
            spread = 0.015 # 1.5 cents
        elif liquidity_usd >= 5_000:
            spread = 0.025 # 2.5 cents
        else:
            spread = 0.050 # 5.0 cents illiquid

        # Boundary adjustment: near 0.05 or 0.95 spreads are naturally compressed in cents
        if price < 0.10 or price > 0.90:
            spread = min(spread, price * 0.20, (1.0 - price) * 0.20)

        return max(self.min_spread_cents, spread)

    def calculate_cost(
        self,
        price: float,
        order_size_usd: float = 1_000.0,
        liquidity_usd: float = 50_000.0,
        observed_spread: Optional[float] = None,
        is_maker: bool = False,
        platform: str = "polymarket"
    ) -> Dict[str, float]:
        """Compute all component execution costs for an order of size `order_size_usd`."""
        price = max(0.01, min(0.99, price))

        # 1. Effective Spread Cost
        spread = observed_spread if observed_spread is not None else self.estimate_spread(liquidity_usd, price)
        if is_maker:
            # Passive maker orders cross inside the spread or capture the spread
            spread_cost = 0.0
        else:
            # Taker orders pay half the spread on entry and half on exit
            spread_cost = spread # full round-trip spread

        # 2. Market Impact / Slippage
        # Sizing ratio against available order-book depth
        depth_estimate = max(500.0, liquidity_usd * 0.15) # ~15% of total liquidity at L1/L2
        participation_ratio = min(1.0, order_size_usd / depth_estimate)
        slippage_cost = self.impact_coef * (participation_ratio ** 1.5) * spread
        # Round trip slippage
        round_trip_slippage = slippage_cost * 2.0

        # 3. Exchange Fees
        if platform == "kalshi":
            # Kalshi fee formula: round(0.07 * P * (1-P))
            contract_fee = 0.07 * price * (1.0 - price)
            fee_cost = (contract_fee / price) * 2.0 # round trip relative fee
        else:
            # Polymarket: maker=0, taker=0.1%
            fee_cost = (2.0 * self.maker_fee) if is_maker else (2.0 * self.taker_fee)

        total_friction = spread_cost + round_trip_slippage + fee_cost

        return {
            "price": price,
            "order_size_usd": order_size_usd,
            "liquidity_usd": liquidity_usd,
            "spread": spread,
            "spread_cost": spread_cost,
            "slippage_cost": round_trip_slippage,
            "fee_cost": fee_cost,
            "total_friction": total_friction,
            "friction_bps": total_friction * 10_000.0
        }
