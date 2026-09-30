"""Deterministic Order-Book Walking & Taker Execution Model for Phase 10A.6.

Answers the fundamental question:
"If a taker order of size X USD is submitted at this exact observed L2 book state,
what VWAP price, depth consumption, slippage, and net return will be realized?"
"""

from dataclasses import dataclass
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Union

logger = logging.getLogger(__name__)


@dataclass
class TakerExecutionFill:
    """Exact deterministic result of walking an L2 order-book ladder."""
    order_size_usd: float
    direction: str                     # "BUY" or "SELL"
    is_fillable: bool
    fill_price_vwap: float
    best_price: float
    midpoint: float
    total_shares_filled: float
    gross_notional_filled: float
    total_depth_available_usd: float
    spread_cost_usd: float
    spread_cost_bps: float
    slippage_usd: float
    slippage_bps: float
    exchange_fee_usd: float
    exchange_fee_bps: float
    capacity_limit_usd: float
    rejection_reason: Optional[str] = None


class ExecutablePriceModel:
    """Deterministic taker execution simulator traversing genuine L2 book ladders."""

    def __init__(self, default_fee_bps: float = 20.0):
        self.default_fee_bps = default_fee_bps

    @staticmethod
    def _parse_ladder(ladder_raw: Union[str, List[Any], None]) -> List[Dict[str, float]]:
        """Parses and sanitizes order book ladder from JSON string or list of dicts."""
        if not ladder_raw:
            return []
        if isinstance(ladder_raw, str):
            try:
                data = json.loads(ladder_raw)
            except Exception:
                return []
        elif isinstance(ladder_raw, list):
            data = ladder_raw
        else:
            return []

        clean_ladder = []
        for level in data:
            if isinstance(level, dict):
                p = float(level.get("price", 0.0))
                s = float(level.get("size", 0.0))
                u = float(level.get("size_usd", p * s))
                if p > 0.0 and s > 0.0:
                    clean_ladder.append({"price": p, "size": s, "size_usd": u})
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                p = float(level[0])
                s = float(level[1])
                clean_ladder.append({"price": p, "size": s, "size_usd": p * s})
        return clean_ladder

    def execute_taker_order(
        self,
        bids_raw: Union[str, List[Any], None],
        asks_raw: Union[str, List[Any], None],
        direction: str,
        order_size_usd: float,
        fee_bps: Optional[float] = None
    ) -> TakerExecutionFill:
        """Simulates walking the actual L2 order book for a taker order of size `order_size_usd`."""
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError(f"Invalid direction '{direction}'; must be BUY or SELL")

        applied_fee_bps = fee_bps if fee_bps is not None else self.default_fee_bps

        bids = self._parse_ladder(bids_raw)
        asks = self._parse_ladder(asks_raw)

        # Sort ladders strictly:
        # Bids: descending by price (highest bid first)
        # Asks: ascending by price (lowest ask first)
        bids = sorted(bids, key=lambda x: x["price"], reverse=True)
        asks = sorted(asks, key=lambda x: x["price"], reverse=False)

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 1.0
        midpoint = round((best_bid + best_ask) / 2.0, 5) if (bids and asks) else 0.5

        if direction == "BUY":
            ladder = asks
            best_price = best_ask
        else:
            ladder = bids
            best_price = best_bid

        total_depth_usd = sum(level["size_usd"] for level in ladder)

        # Capacity check: cannot fill if requested size exceeds total available depth
        if total_depth_usd < order_size_usd or not ladder:
            return TakerExecutionFill(
                order_size_usd=order_size_usd,
                direction=direction,
                is_fillable=False,
                fill_price_vwap=best_price,
                best_price=best_price,
                midpoint=midpoint,
                total_shares_filled=0.0,
                gross_notional_filled=0.0,
                total_depth_available_usd=round(total_depth_usd, 2),
                spread_cost_usd=0.0,
                spread_cost_bps=0.0,
                slippage_usd=0.0,
                slippage_bps=0.0,
                exchange_fee_usd=0.0,
                exchange_fee_bps=applied_fee_bps,
                capacity_limit_usd=round(total_depth_usd, 2),
                rejection_reason=f"Insufficient ladder depth ({total_depth_usd:.2f} USD < {order_size_usd:.2f} USD)"
            )

        # Walk ladder level by level
        remaining_usd = order_size_usd
        total_shares = 0.0
        total_notional = 0.0

        for level in ladder:
            p = level["price"]
            lvl_usd = level["size_usd"]
            if lvl_usd <= 0.0:
                continue

            take_usd = min(remaining_usd, lvl_usd)
            take_shares = take_usd / p

            total_shares += take_shares
            total_notional += take_usd
            remaining_usd -= take_usd

            if remaining_usd <= 1e-6:
                break

        vwap = round(total_notional / total_shares, 5) if total_shares > 0 else best_price

        # Microstructure cost attribution:
        # 1. Spread cost: cost of crossing from midpoint to top of book
        if direction == "BUY":
            spread_diff = max(0.0, best_price - midpoint)
            slippage_diff = max(0.0, vwap - best_price)
        else:
            spread_diff = max(0.0, midpoint - best_price)
            slippage_diff = max(0.0, best_price - vwap)

        spread_bps = round((spread_diff / midpoint) * 10000.0, 2) if midpoint > 0 else 0.0
        spread_usd = round((spread_diff / best_price) * total_notional, 4) if best_price > 0 else 0.0

        slippage_bps = round((slippage_diff / best_price) * 10000.0, 2) if best_price > 0 else 0.0
        slippage_usd = round(slippage_diff * total_shares, 4)

        fee_usd = round((applied_fee_bps / 10000.0) * total_notional, 4)

        return TakerExecutionFill(
            order_size_usd=order_size_usd,
            direction=direction,
            is_fillable=True,
            fill_price_vwap=vwap,
            best_price=best_price,
            midpoint=midpoint,
            total_shares_filled=round(total_shares, 4),
            gross_notional_filled=round(total_notional, 2),
            total_depth_available_usd=round(total_depth_usd, 2),
            spread_cost_usd=spread_usd,
            spread_cost_bps=spread_bps,
            slippage_usd=slippage_usd,
            slippage_bps=slippage_bps,
            exchange_fee_usd=fee_usd,
            exchange_fee_bps=applied_fee_bps,
            capacity_limit_usd=round(total_depth_usd, 2),
            rejection_reason=None
        )

    def calculate_net_response(
        self,
        entry_fill: TakerExecutionFill,
        exit_fill: TakerExecutionFill,
    ) -> Dict[str, float]:
        """Calculates exact gross and net PnL / return between entry and exit fills."""
        if not entry_fill.is_fillable or not exit_fill.is_fillable:
            return {
                "gross_pnl_usd": 0.0,
                "gross_return_bps": 0.0,
                "net_pnl_usd": 0.0,
                "net_return_bps": 0.0,
                "total_friction_bps": 0.0
            }

        # If entry was BUY, exit is SELL
        if entry_fill.direction == "BUY":
            gross_return_pct = (exit_fill.fill_price_vwap - entry_fill.fill_price_vwap) / entry_fill.fill_price_vwap
        else:
            gross_return_pct = (entry_fill.fill_price_vwap - exit_fill.fill_price_vwap) / entry_fill.fill_price_vwap

        gross_return_bps = round(gross_return_pct * 10000.0, 2)
        gross_pnl_usd = round(gross_return_pct * entry_fill.gross_notional_filled, 2)

        # Total round-trip frictions in bps:
        total_friction_bps = (
            entry_fill.spread_cost_bps + exit_fill.spread_cost_bps +
            entry_fill.slippage_bps + exit_fill.slippage_bps +
            entry_fill.exchange_fee_bps + exit_fill.exchange_fee_bps
        )
        total_friction_usd = (
            entry_fill.spread_cost_usd + exit_fill.spread_cost_usd +
            entry_fill.slippage_usd + exit_fill.slippage_usd +
            entry_fill.exchange_fee_usd + exit_fill.exchange_fee_usd
        )

        net_return_bps = round(gross_return_bps - total_friction_bps, 2)
        net_pnl_usd = round(gross_pnl_usd - total_friction_usd, 2)

        return {
            "gross_pnl_usd": gross_pnl_usd,
            "gross_return_bps": gross_return_bps,
            "net_pnl_usd": net_pnl_usd,
            "net_return_bps": net_return_bps,
            "total_friction_bps": round(total_friction_bps, 2)
        }
