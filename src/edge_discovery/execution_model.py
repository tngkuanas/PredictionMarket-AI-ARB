"""Deterministic L2 Order-Book Walking and Realistic Taker Execution Model for Phase 10A.7.

Strict Requirements:
1. Never assume midpoint execution.
2. Taker BUY orders walk the ask ladder; taker SELL orders walk the bid ladder.
3. Compute exact VWAP, spread cost, exchange fee, book-walking slippage, latency penalty,
   and adverse selection.
4. Test capacity limits at $100, $500, and $1,000 standard trade sizes.
5. If available book depth is less than order size, flag depth_exhausted = True.
"""

from dataclasses import dataclass
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Union

from src.edge_discovery.schema import (
    TradeDirection,
    ExecutableEvaluationRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class LadderFillResult:
    """Exact result of walking an L2 order ladder."""
    order_size_usd: float
    direction: TradeDirection
    is_fillable: bool
    fill_vwap: float
    best_price: float
    midpoint: float
    shares_filled: float
    notional_filled: float
    total_depth_usd: float
    spread_cost_bps: float
    slippage_bps: float
    depth_exhausted: bool


class OrderBookTakerExecutor:
    """Walks order book ladders to determine realistic executable pricing."""

    def __init__(self, default_fee_bps: float = 0.0):
        # Polymarket CLOB base taker fee is 0 bps (or dynamic on select fee markets).
        self.default_fee_bps = default_fee_bps

    @staticmethod
    def parse_ladder(ladder_raw: Union[str, List[Any], None]) -> List[Dict[str, float]]:
        """Parses and normalizes order book ladder from JSON string or list."""
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
                if p > 0.0 and s > 0.0:
                    clean_ladder.append({"price": p, "size": s, "size_usd": p * s})
        return clean_ladder

    def walk_ladder(
        self,
        bids_raw: Union[str, List[Any], None],
        asks_raw: Union[str, List[Any], None],
        direction: TradeDirection,
        order_size_usd: float,
    ) -> LadderFillResult:
        """Walks the L2 ladder to fill order_size_usd."""
        bids = self.parse_ladder(bids_raw)
        asks = self.parse_ladder(asks_raw)

        # Sort bids descending, asks ascending
        bids = sorted(bids, key=lambda x: x["price"], reverse=True)
        asks = sorted(asks, key=lambda x: x["price"], reverse=False)

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 1.0
        midpoint = round((best_bid + best_ask) / 2.0, 6) if (bids and asks) else 0.5

        if direction == TradeDirection.BUY:
            ladder = asks
            best_price = best_ask
        else:
            ladder = bids
            best_price = best_bid

        total_depth_usd = sum(level["size_usd"] for level in ladder)

        if not ladder or best_price <= 0.0:
            return LadderFillResult(
                order_size_usd=order_size_usd,
                direction=direction,
                is_fillable=False,
                fill_vwap=best_price,
                best_price=best_price,
                midpoint=midpoint,
                shares_filled=0.0,
                notional_filled=0.0,
                total_depth_usd=total_depth_usd,
                spread_cost_bps=0.0,
                slippage_bps=0.0,
                depth_exhausted=True,
            )

        remaining_usd = order_size_usd
        total_shares = 0.0
        total_spent_usd = 0.0

        for level in ladder:
            p = level["price"]
            avail_usd = level["size_usd"]
            if remaining_usd <= avail_usd:
                # Level covers remainder
                shares = remaining_usd / p
                total_shares += shares
                total_spent_usd += remaining_usd
                remaining_usd = 0.0
                break
            else:
                shares = level["size"]
                total_shares += shares
                total_spent_usd += avail_usd
                remaining_usd -= avail_usd

        depth_exhausted = remaining_usd > 1e-4
        if depth_exhausted:
            # Partial fill or unable to fill requested size
            fill_vwap = (total_spent_usd / total_shares) if total_shares > 0 else best_price
        else:
            fill_vwap = total_spent_usd / total_shares

        # Spread cost bps relative to midpoint
        if midpoint > 0.0:
            if direction == TradeDirection.BUY:
                spread_cost_bps = max(0.0, (best_price - midpoint) / midpoint * 10000.0)
            else:
                spread_cost_bps = max(0.0, (midpoint - best_price) / midpoint * 10000.0)
        else:
            spread_cost_bps = 0.0

        # Slippage bps relative to top of book
        if best_price > 0.0:
            if direction == TradeDirection.BUY:
                slippage_bps = max(0.0, (fill_vwap - best_price) / best_price * 10000.0)
            else:
                slippage_bps = max(0.0, (best_price - fill_vwap) / best_price * 10000.0)
        else:
            slippage_bps = 0.0

        return LadderFillResult(
            order_size_usd=order_size_usd,
            direction=direction,
            is_fillable=not depth_exhausted,
            fill_vwap=round(fill_vwap, 6),
            best_price=round(best_price, 6),
            midpoint=round(midpoint, 6),
            shares_filled=round(total_shares, 4),
            notional_filled=round(total_spent_usd, 4),
            total_depth_usd=round(total_depth_usd, 4),
            spread_cost_bps=round(spread_cost_bps, 2),
            slippage_bps=round(slippage_bps, 2),
            depth_exhausted=depth_exhausted,
        )

    def evaluate_execution(
        self,
        evaluation_id: str,
        observation_id: str,
        hypothesis_id: str,
        entry_bids: Union[str, List[Any], None],
        entry_asks: Union[str, List[Any], None],
        exit_bids: Union[str, List[Any], None],
        exit_asks: Union[str, List[Any], None],
        direction: TradeDirection,
        horizon_ms: int,
        target_size_usd: float = 100.0,
        fee_bps: Optional[float] = None,
        latency_penalty_bps: float = 0.0,
        adverse_selection_bps: float = 0.0,
    ) -> ExecutableEvaluationRecord:
        """Full realistic execution evaluation with multi-component cost decomposition."""
        fee_rate_bps = fee_bps if fee_bps is not None else self.default_fee_bps

        # Entry fill: taker order walking ladder
        entry_fill = self.walk_ladder(entry_bids, entry_asks, direction, target_size_usd)

        # Exit fill: opposite direction to close position
        exit_direction = TradeDirection.SELL if direction == TradeDirection.BUY else TradeDirection.BUY
        exit_fill = self.walk_ladder(exit_bids, exit_asks, exit_direction, target_size_usd)

        # Midpoint return: theoretical mid-to-mid change
        if entry_fill.midpoint > 0.0 and exit_fill.midpoint > 0.0:
            if direction == TradeDirection.BUY:
                mid_ret_bps = (exit_fill.midpoint - entry_fill.midpoint) / entry_fill.midpoint * 10000.0
            else:
                mid_ret_bps = (entry_fill.midpoint - exit_fill.midpoint) / entry_fill.midpoint * 10000.0
        else:
            mid_ret_bps = 0.0

        # Executable gross return: entry VWAP to exit VWAP
        if entry_fill.fill_vwap > 0.0 and exit_fill.fill_vwap > 0.0:
            if direction == TradeDirection.BUY:
                gross_ret_bps = (exit_fill.fill_vwap - entry_fill.fill_vwap) / entry_fill.fill_vwap * 10000.0
            else:
                gross_ret_bps = (entry_fill.fill_vwap - exit_fill.fill_vwap) / entry_fill.fill_vwap * 10000.0
        else:
            gross_ret_bps = 0.0

        spread_cost_total_bps = entry_fill.spread_cost_bps + exit_fill.spread_cost_bps
        slippage_total_bps = entry_fill.slippage_bps + exit_fill.slippage_bps
        fees_total_bps = fee_rate_bps * 2.0  # roundtrip fees

        # Net return = Gross return - (Spread cost + Fees + Slippage + Latency + Adverse Selection)
        # Note: if gross_ret_bps is already computed between VWAPs, spread and slippage are already
        # partially embedded in the VWAP spread relative to mid.
        # To be strictly rigorous and avoid double counting:
        # Net executable return = mid_ret_bps - spread_cost_total_bps - slippage_total_bps - fees_total_bps - latency_penalty_bps - adverse_selection_bps
        net_ret_bps = (
            mid_ret_bps
            - spread_cost_total_bps
            - slippage_total_bps
            - fees_total_bps
            - latency_penalty_bps
            - adverse_selection_bps
        )

        depth_exhausted = entry_fill.depth_exhausted or exit_fill.depth_exhausted

        return ExecutableEvaluationRecord(
            evaluation_id=evaluation_id,
            observation_id=observation_id,
            hypothesis_id=hypothesis_id,
            horizon_ms=horizon_ms,
            target_size_usd=target_size_usd,
            executable_entry_vwap=entry_fill.fill_vwap,
            executable_exit_vwap=exit_fill.fill_vwap,
            midpoint_return_bps=round(mid_ret_bps, 2),
            gross_executable_return_bps=round(gross_ret_bps, 2),
            spread_cost_bps=round(spread_cost_total_bps, 2),
            fee_bps=round(fees_total_bps, 2),
            slippage_bps=round(slippage_total_bps, 2),
            latency_penalty_bps=round(latency_penalty_bps, 2),
            adverse_selection_bps=round(adverse_selection_bps, 2),
            net_executable_return_bps=round(net_ret_bps, 2),
            is_profitable_net=(net_ret_bps > 0.0 and not depth_exhausted),
            depth_exhausted=depth_exhausted,
        )
