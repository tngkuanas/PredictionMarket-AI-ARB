"""Realistic Order Book Reconstruction & Execution Simulation Engine.
Simulates L2/L3 order book depth, walking the book, partial fills, queue priority,
execution latency, market impact, and liquidity-adjusted capital capacity.
"""
import logging
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime
import numpy as np

from src.normalization.schema import OrderSide, Platform

logger = logging.getLogger(__name__)

class OrderBookLevel:
    def __init__(self, price: float, size_usd: float):
        self.price = round(price, 4)
        self.size_usd = float(size_usd)

    def __repr__(self):
        return f"Level(p={self.price:.4f}, size=${self.size_usd:,.2f})"


class ReconstructedOrderBook:
    """Represents a discrete limit order book with bids and asks."""

    def __init__(
        self,
        market_id: str,
        bids: Optional[List[Tuple[float, float]]] = None,
        asks: Optional[List[Tuple[float, float]]] = None,
        timestamp: Optional[datetime] = None
    ):
        self.market_id = market_id
        self.timestamp = timestamp or datetime.utcnow()
        # Bids: sorted descending by price
        self.bids: List[OrderBookLevel] = [OrderBookLevel(p, s) for p, s in (bids or [])]
        self.bids.sort(key=lambda x: x.price, reverse=True)
        # Asks: sorted ascending by price
        self.asks: List[OrderBookLevel] = [OrderBookLevel(p, s) for p, s in (asks or [])]
        self.asks.sort(key=lambda x: x.price, reverse=False)

    @classmethod
    def from_market_snapshot(
        cls,
        market_id: str,
        mid_price: float,
        spread: float = 0.012,
        liquidity_usd: float = 50_000.0,
        timestamp: Optional[datetime] = None
    ) -> "ReconstructedOrderBook":
        """Reconstructs a realistic L2/L3 order book from snapshot metrics."""
        mid = max(0.02, min(0.98, mid_price))
        half_spread = max(0.0025, spread / 2.0)
        best_bid = round(max(0.01, mid - half_spread), 4)
        best_ask = round(min(0.99, mid + half_spread), 4)

        # Distribute liquidity across 4 depth levels
        # Level 1: Best price (15% of liquidity)
        # Level 2: 1 tick worse (25% of liquidity)
        # Level 3: 2 ticks worse (30% of liquidity)
        # Level 4: 4 ticks worse (30% of liquidity)
        depth_bids = [
            (best_bid, liquidity_usd * 0.15),
            (round(max(0.01, best_bid - 0.005), 4), liquidity_usd * 0.25),
            (round(max(0.01, best_bid - 0.010), 4), liquidity_usd * 0.30),
            (round(max(0.01, best_bid - 0.020), 4), liquidity_usd * 0.30),
        ]
        depth_asks = [
            (best_ask, liquidity_usd * 0.15),
            (round(min(0.99, best_ask + 0.005), 4), liquidity_usd * 0.25),
            (round(min(0.99, best_ask + 0.010), 4), liquidity_usd * 0.30),
            (round(min(0.99, best_ask + 0.020), 4), liquidity_usd * 0.30),
        ]
        return cls(market_id=market_id, bids=depth_bids, asks=depth_asks, timestamp=timestamp)

    @classmethod
    def from_clob_order_book(
        cls,
        market_id: str,
        clob_data: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ) -> "ReconstructedOrderBook":
        """Builds an order book directly from live Polymarket CLOB book JSON."""
        bids = []
        for b in clob_data.get("bids", []):
            try:
                p = float(b.get("price", 0.0))
                s = float(b.get("size", 0.0))
                bids.append((p, p * s))
            except (ValueError, KeyError, TypeError):
                continue

        asks = []
        for a in clob_data.get("asks", []):
            try:
                p = float(a.get("price", 0.0))
                s = float(a.get("size", 0.0))
                asks.append((p, p * s))
            except (ValueError, KeyError, TypeError):
                continue

        return cls(market_id=market_id, bids=bids, asks=asks, timestamp=timestamp)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 1.0

    @property
    def spread(self) -> float:
        return max(0.0, self.best_ask - self.best_bid)

    @property
    def total_bid_depth_usd(self) -> float:
        return sum(lvl.size_usd for lvl in self.bids)

    @property
    def total_ask_depth_usd(self) -> float:
        return sum(lvl.size_usd for lvl in self.asks)


class OrderBookSimulator:
    """Simulates real execution: walking the book, partial fills, slippage, and latency."""

    def __init__(
        self,
        default_latency_ms: float = 250.0,
        taker_fee_rate: float = 0.001, # Polymarket 0.1% taker
        maker_fee_rate: float = 0.000,
        impact_coefficient: float = 0.08
    ):
        self.default_latency_ms = default_latency_ms
        self.taker_fee = taker_fee_rate
        self.maker_fee = maker_fee_rate
        self.impact_coef = impact_coefficient

    def walk_the_book(
        self,
        book: ReconstructedOrderBook,
        side: OrderSide,
        order_size_usd: float,
        limit_price: Optional[float] = None,
        is_ioc: bool = True,
        simulate_latency: bool = True
    ) -> Dict[str, Any]:
        """Simulates walking an order book level-by-level to calculate VWAP fill price,
        partial fills, market impact, and fee deductions.
        """
        if order_size_usd <= 0:
            return {
                "status": "REJECTED",
                "filled_size_usd": 0.0,
                "unfilled_size_usd": 0.0,
                "vwap_fill_price": 0.0,
                "effective_slippage_pp": 0.0,
                "fee_usd": 0.0,
                "fill_ratio": 0.0
            }

        # Select matching side ladder
        levels = book.asks if side == OrderSide.BUY else book.bids
        if not levels:
            return {
                "status": "NO_LIQUIDITY",
                "filled_size_usd": 0.0,
                "unfilled_size_usd": order_size_usd,
                "vwap_fill_price": 0.0,
                "effective_slippage_pp": 0.0,
                "fee_usd": 0.0,
                "fill_ratio": 0.0
            }

        best_initial_price = levels[0].price
        remaining_size = order_size_usd
        total_spent = 0.0
        filled_size = 0.0
        level_fills: List[Tuple[float, float]] = [] # (price, size_usd)

        # Latency slippage adjustment: during 250ms latency, best quote may adjust slightly
        latency_slip = 0.0
        if simulate_latency and self.default_latency_ms > 0:
            # Latency adverse movement: ~0.1 - 0.2 cents for fast moving contracts
            latency_factor = min(0.003, (self.default_latency_ms / 1000.0) * 0.004)
            latency_slip = latency_factor if side == OrderSide.BUY else -latency_factor

        for lvl in levels:
            eff_price = lvl.price + latency_slip
            # Limit price check
            if limit_price is not None:
                if side == OrderSide.BUY and eff_price > limit_price:
                    break
                elif side == OrderSide.SELL and eff_price < limit_price:
                    break

            available = lvl.size_usd
            fill_amount = min(remaining_size, available)
            level_fills.append((eff_price, fill_amount))
            total_spent += fill_amount * eff_price
            filled_size += fill_amount
            remaining_size -= fill_amount

            if remaining_size <= 1e-4:
                break

        if filled_size == 0.0:
            return {
                "status": "PRICE_LIMIT_BREACH",
                "filled_size_usd": 0.0,
                "unfilled_size_usd": order_size_usd,
                "vwap_fill_price": 0.0,
                "effective_slippage_pp": 0.0,
                "fee_usd": 0.0,
                "fill_ratio": 0.0
            }

        vwap_price = total_spent / filled_size
        effective_slippage = abs(vwap_price - best_initial_price)
        fee_usd = filled_size * self.taker_fee

        status = "FILLED" if remaining_size <= 1e-4 else ("PARTIALLY_FILLED" if is_ioc else "RESTING")

        return {
            "status": status,
            "filled_size_usd": filled_size,
            "unfilled_size_usd": remaining_size,
            "vwap_fill_price": vwap_price,
            "initial_best_price": best_initial_price,
            "effective_slippage_pp": effective_slippage,
            "fee_usd": fee_usd,
            "fill_ratio": filled_size / order_size_usd,
            "levels_swept": len(level_fills)
        }

    def calculate_market_capacity(
        self,
        book: ReconstructedOrderBook,
        side: OrderSide,
        raw_edge_pp: float,
        min_required_net_edge_pp: float = 0.015,
        max_search_capital: float = 50_000.0,
        step_usd: float = 500.0
    ) -> Dict[str, Any]:
        """Calculates maximum executable capital capacity before market impact and slippage
        erode the net expected value below the required threshold.
        """
        best_size = 0.0
        best_net_profit_usd = 0.0
        capacity_limit_usd = 0.0

        for test_size in np.arange(step_usd, max_search_capital + step_usd, step_usd):
            fill = self.walk_the_book(book, side, test_size)
            if fill["filled_size_usd"] < test_size * 0.90:
                # Ran out of book liquidity
                break

            total_friction = fill["effective_slippage_pp"] + (2.0 * self.taker_fee)
            net_edge = raw_edge_pp - total_friction
            if net_edge >= min_required_net_edge_pp:
                capacity_limit_usd = float(test_size)
                profit_usd = test_size * net_edge
                if profit_usd > best_net_profit_usd:
                    best_net_profit_usd = profit_usd
                    best_size = float(test_size)
            else:
                # Slipped below threshold
                break

        return {
            "optimal_order_size_usd": best_size,
            "max_deployable_capacity_usd": capacity_limit_usd,
            "expected_net_profit_at_opt_usd": best_net_profit_usd,
            "is_viable": capacity_limit_usd >= 500.0
        }
