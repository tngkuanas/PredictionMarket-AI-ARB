"""Multi-Tier Executability Gate for Prediction Market Stat-Arb Candidates.

Enforces strict sequential execution gating:
SIGNAL -> QUOTE AVAILABLE? -> SPREAD -> DEPTH -> EXECUTION PRICE (VWAP) -> FEES -> SLIPPAGE -> LATENCY -> CAPACITY -> NET EV.

Rejects any candidate with positive theoretical return but negative net executable return.
Enforces depth constraints: never extrapolates capacity beyond observed L2 depth.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Union
import numpy as np

from src.phase10.response_study.executable_price_model import (
    ExecutablePriceModel,
    TakerExecutionFill,
)
from src.statarb.schema import ExecutionGateResult

logger = logging.getLogger(__name__)


class ExecutabilityGate:
    """Enforces multi-tier microstructure and execution friction gates."""

    def __init__(
        self,
        default_fee_bps: float = 20.0,
        max_allowable_spread_bps: float = 500.0,  # 5.0 cents in prediction market
        max_allowable_slippage_bps: float = 100.0,
        default_latency_penalty_bps: float = 5.0,
    ):
        self.default_fee_bps = default_fee_bps
        self.max_allowable_spread_bps = max_allowable_spread_bps
        self.max_allowable_slippage_bps = max_allowable_slippage_bps
        self.default_latency_penalty_bps = default_latency_penalty_bps
        self.l2_model = ExecutablePriceModel(default_fee_bps=default_fee_bps)

    def evaluate_execution(
        self,
        bids_raw: Union[str, List[Any], None],
        asks_raw: Union[str, List[Any], None],
        direction: str,
        order_size_usd: float,
        gross_expected_return_bps: float,
        latency_penalty_bps: Optional[float] = None,
        custom_fee_bps: Optional[float] = None,
    ) -> ExecutionGateResult:
        """Evaluates an order through all 10 sequential execution tiers.
        
        Returns ExecutionGateResult with is_executable boolean and cost breakdown.
        """
        dir_upper = direction.upper()
        fee_bps = custom_fee_bps if custom_fee_bps is not None else self.default_fee_bps
        latency_cost_bps = latency_penalty_bps if latency_penalty_bps is not None else self.default_latency_penalty_bps

        # Tier 1: SIGNAL VALIDITY
        if dir_upper not in ("BUY", "SELL"):
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="SIGNAL_INVALID",
                reason=f"Direction must be BUY or SELL, got {direction}"
            )
        if order_size_usd <= 0.0:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="ORDER_SIZE_ZERO",
                reason=f"Order size must be positive, got {order_size_usd}"
            )

        # Tier 2: QUOTE AVAILABLE?
        clean_bids = self.l2_model._parse_ladder(bids_raw)
        clean_asks = self.l2_model._parse_ladder(asks_raw)

        if not clean_bids or not clean_asks:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="QUOTE_UNAVAILABLE",
                reason="One or both sides of the L2 book are empty or missing."
            )

        best_bid = max(b["price"] for b in clean_bids)
        best_ask = min(a["price"] for a in clean_asks)

        # Tier 3: SPREAD GATE
        if best_bid >= best_ask:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="CROSSED_BOOK",
                reason=f"Crossed/locked order book: best_bid {best_bid} >= best_ask {best_ask}"
            )

        midpoint = (best_bid + best_ask) / 2.0
        spread_abs = best_ask - best_bid
        spread_bps = (spread_abs / midpoint) * 10000.0 if midpoint > 0 else 9999.0

        if spread_bps > self.max_allowable_spread_bps:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="WIDE_SPREAD",
                spread_cost_bps=round(spread_bps, 2),
                reason=f"Bid-ask spread {spread_bps:.1f} bps exceeds limit {self.max_allowable_spread_bps:.1f} bps."
            )

        # Tier 4 & 5: DEPTH & VWAP EXECUTION
        fill = self.l2_model.execute_taker_order(
            bids_raw=clean_bids,
            asks_raw=clean_asks,
            direction=dir_upper,
            order_size_usd=order_size_usd,
            fee_bps=fee_bps
        )

        if not fill.is_fillable:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="INSUFFICIENT_DEPTH",
                total_depth_available_usd=round(fill.total_depth_available_usd, 2),
                capacity_limit_usd=round(fill.total_depth_available_usd, 2),
                reason=f"Insufficient depth: requested {order_size_usd} USD but book only has {fill.total_depth_available_usd:.2f} USD."
            )

        # Tier 6: FEES
        taker_fee_bps = fill.exchange_fee_bps

        # Tier 7: SLIPPAGE
        slippage_bps = fill.slippage_bps
        if slippage_bps > self.max_allowable_slippage_bps:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="EXCESSIVE_SLIPPAGE",
                slippage_bps=round(slippage_bps, 2),
                reason=f"VWAP slippage {slippage_bps:.1f} bps exceeds tolerance {self.max_allowable_slippage_bps:.1f} bps."
            )

        # Half-spread cost in bps
        half_spread_bps = (abs(fill.best_price - fill.midpoint) / fill.midpoint) * 10000.0 if fill.midpoint > 0 else 0.0

        # Tier 8: LATENCY PENALTY
        # Latency penalty models information leakage / quote adverse move before fill

        # Tier 9: CAPACITY LIMIT (Strictly bounded by observed L2 depth within slippage tolerance)
        capacity_usd = self._calculate_capacity_limit(clean_bids if dir_upper == "SELL" else clean_asks, midpoint)

        # Tier 10: NET EV EVALUATION
        # Total round-trip or one-way frictions
        total_friction_bps = half_spread_bps + slippage_bps + taker_fee_bps + latency_cost_bps
        net_return_bps = gross_expected_return_bps - total_friction_bps

        if net_return_bps <= 0.0:
            return ExecutionGateResult(
                is_executable=False,
                rejection_stage="NEGATIVE_NET_EV",
                gross_return_bps=round(gross_expected_return_bps, 2),
                spread_cost_bps=round(half_spread_bps, 2),
                slippage_bps=round(slippage_bps, 2),
                taker_fee_bps=round(taker_fee_bps, 2),
                latency_cost_bps=round(latency_cost_bps, 2),
                net_return_bps=round(net_return_bps, 2),
                fill_vwap=round(fill.fill_price_vwap, 4),
                total_depth_available_usd=round(fill.total_depth_available_usd, 2),
                capacity_limit_usd=round(capacity_usd, 2),
                reason=f"Gross return {gross_expected_return_bps:.1f} bps fails to cover total friction {total_friction_bps:.1f} bps (Net: {net_return_bps:.1f} bps)."
            )

        # PASSED ALL GATES
        return ExecutionGateResult(
            is_executable=True,
            rejection_stage=None,
            gross_return_bps=round(gross_expected_return_bps, 2),
            spread_cost_bps=round(half_spread_bps, 2),
            slippage_bps=round(slippage_bps, 2),
            taker_fee_bps=round(taker_fee_bps, 2),
            latency_cost_bps=round(latency_cost_bps, 2),
            net_return_bps=round(net_return_bps, 2),
            fill_vwap=round(fill.fill_price_vwap, 4),
            total_depth_available_usd=round(fill.total_depth_available_usd, 2),
            capacity_limit_usd=round(capacity_usd, 2),
            reason="Passed all 10 execution tiers with positive net executable return."
        )

    def _calculate_capacity_limit(self, ladder: List[Dict[str, float]], midpoint: float) -> float:
        """Calculates maximum executable capacity in USD before slippage exceeds tolerance.
        
        Strictly bounded by observable order book ladder. Never extrapolated.
        """
        if not ladder or midpoint <= 0:
            return 0.0

        cum_usd = 0.0
        cum_shares = 0.0

        for level in ladder:
            p = level["price"]
            u = level["size_usd"]
            s = level["size"]

            cum_usd += u
            cum_shares += s
            vwap = cum_usd / cum_shares if cum_shares > 0 else p

            # Slippage from best price
            best_p = ladder[0]["price"]
            slip_bps = (abs(vwap - best_p) / midpoint) * 10000.0
            if slip_bps > self.max_allowable_slippage_bps:
                # Capacity capped at previous level
                return max(0.0, cum_usd - u)

        return cum_usd
