"""L2 Order Book Execution and Capacity Model for Phase 10A.11.

Simulates actual order book execution by walking the L2 ladder (bids/asks JSON).
Computes exact VWAP, market impact, slippage, taker fees, and multi-tier capacity
evaluation across [$10, $25, $50, $100, $250, $500, $1,000].
Rejects midpoint fills as primary execution metric.
"""

from dataclasses import dataclass, field
import datetime
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from src.phase10a11 import FillStatus


@dataclass
class OrderBookLevel:
    price: float
    size: float
    size_usd: float


@dataclass
class ExecutionResult:
    fill_status: FillStatus
    requested_size_usd: float
    filled_size_usd: float
    filled_shares: float
    vwap: float
    top_of_book_price: float
    slippage_usd: float
    slippage_bps: float
    fee_usd: float
    fee_bps: float
    effective_price: float
    unfilled_size_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_status": self.fill_status.value,
            "requested_size_usd": round(self.requested_size_usd, 2),
            "filled_size_usd": round(self.filled_size_usd, 2),
            "filled_shares": round(self.filled_shares, 4),
            "vwap": round(self.vwap, 4),
            "top_of_book_price": round(self.top_of_book_price, 4),
            "slippage_usd": round(self.slippage_usd, 4),
            "slippage_bps": round(self.slippage_bps, 2),
            "fee_usd": round(self.fee_usd, 4),
            "fee_bps": round(self.fee_bps, 2),
            "effective_price": round(self.effective_price, 4),
            "unfilled_size_usd": round(self.unfilled_size_usd, 2),
        }


CAPACITY_TIERS_USD: List[float] = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]


class L2ExecutionModel:
    """Executes trades against actual L2 book ladders with slippage, VWAP, and fees."""

    DEFAULT_TAKER_FEE_BPS = 5.0  # 0.05% taker fee baseline

    @staticmethod
    def parse_ladder(ladder_raw: Union[str, List[Any], None]) -> List[OrderBookLevel]:
        """Parses JSON or list-based order book ladder into OrderBookLevel objects."""
        if not ladder_raw:
            return []
        
        parsed = ladder_raw
        if isinstance(ladder_raw, str):
            try:
                parsed = json.loads(ladder_raw)
            except Exception:
                return []

        levels: List[OrderBookLevel] = []
        if not isinstance(parsed, list):
            return levels

        for item in parsed:
            p, s = 0.0, 0.0
            if isinstance(item, dict):
                p = float(item.get("price", 0.0) or 0.0)
                s = float(item.get("size", 0.0) or 0.0)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                p = float(item[0] or 0.0)
                s = float(item[1] or 0.0)
            
            if p > 0 and s > 0:
                levels.append(OrderBookLevel(price=p, size=s, size_usd=p * s))

        return levels

    def execute_order(
        self,
        side: str,  # "BUY" or "SELL"
        order_size_usd: float,
        book_snapshot: Dict[str, Any],
        fee_rate_bps: float = DEFAULT_TAKER_FEE_BPS,
    ) -> ExecutionResult:
        """Simulates an executable taker order by walking the L2 order book."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Side must be 'BUY' or 'SELL', got '{side}'")

        if order_size_usd <= 0:
            raise ValueError(f"order_size_usd must be positive, got {order_size_usd}")

        # BUY orders walk the asks; SELL orders walk the bids
        ladder_key = "asks" if side == "BUY" else "bids"
        raw_ladder = book_snapshot.get(ladder_key, [])
        levels = self.parse_ladder(raw_ladder)

        # Sort order: asks ascending by price, bids descending by price
        if side == "BUY":
            levels.sort(key=lambda lvl: lvl.price)
        else:
            levels.sort(key=lambda lvl: lvl.price, reverse=True)

        if not levels:
            # Empty order book side
            top_price = float(book_snapshot.get("best_ask" if side == "BUY" else "best_bid", 0.0) or 0.0)
            return ExecutionResult(
                fill_status=FillStatus.UNFILLED,
                requested_size_usd=order_size_usd,
                filled_size_usd=0.0,
                filled_shares=0.0,
                vwap=0.0,
                top_of_book_price=top_price,
                slippage_usd=0.0,
                slippage_bps=0.0,
                fee_usd=0.0,
                fee_bps=0.0,
                effective_price=0.0,
                unfilled_size_usd=order_size_usd,
            )

        top_price = levels[0].price
        remaining_usd = order_size_usd
        total_filled_usd = 0.0
        total_shares = 0.0

        for lvl in levels:
            if remaining_usd <= 0:
                break
            
            fill_usd = min(remaining_usd, lvl.size_usd)
            fill_shares = fill_usd / lvl.price
            
            total_filled_usd += fill_usd
            total_shares += fill_shares
            remaining_usd -= fill_usd

        if total_shares <= 0:
            return ExecutionResult(
                fill_status=FillStatus.UNFILLED,
                requested_size_usd=order_size_usd,
                filled_size_usd=0.0,
                filled_shares=0.0,
                vwap=0.0,
                top_of_book_price=top_price,
                slippage_usd=0.0,
                slippage_bps=0.0,
                fee_usd=0.0,
                fee_bps=0.0,
                effective_price=0.0,
                unfilled_size_usd=order_size_usd,
            )

        vwap = total_filled_usd / total_shares

        # Slippage vs top of book
        if side == "BUY":
            slippage_bps = max(0.0, (vwap - top_price) / top_price * 10000.0) if top_price > 0 else 0.0
            slippage_usd = max(0.0, (vwap - top_price) * total_shares)
        else:
            slippage_bps = max(0.0, (top_price - vwap) / top_price * 10000.0) if top_price > 0 else 0.0
            slippage_usd = max(0.0, (top_price - vwap) * total_shares)

        fee_usd = total_filled_usd * (fee_rate_bps / 10000.0)

        # Effective price per share after fee
        if side == "BUY":
            effective_price = (total_filled_usd + fee_usd) / total_shares
        else:
            effective_price = (total_filled_usd - fee_usd) / total_shares

        fill_status = FillStatus.FULL_FILL if remaining_usd < 1e-4 else FillStatus.PARTIAL_FILL

        return ExecutionResult(
            fill_status=fill_status,
            requested_size_usd=order_size_usd,
            filled_size_usd=total_filled_usd,
            filled_shares=total_shares,
            vwap=vwap,
            top_of_book_price=top_price,
            slippage_usd=slippage_usd,
            slippage_bps=slippage_bps,
            fee_usd=fee_usd,
            fee_bps=fee_rate_bps,
            effective_price=effective_price,
            unfilled_size_usd=max(0.0, remaining_usd),
        )

    def evaluate_capacity_sweep(
        self,
        side: str,
        book_snapshot: Dict[str, Any],
        tiers: Optional[List[float]] = None,
        fee_rate_bps: float = DEFAULT_TAKER_FEE_BPS,
    ) -> Dict[float, ExecutionResult]:
        """Runs execution sweep across standard capacity tiers ($10 to $1,000)."""
        target_tiers = tiers or CAPACITY_TIERS_USD
        results: Dict[float, ExecutionResult] = {}
        for tier in target_tiers:
            res = self.execute_order(
                side=side,
                order_size_usd=tier,
                book_snapshot=book_snapshot,
                fee_rate_bps=fee_rate_bps,
            )
            results[tier] = res
        return results
