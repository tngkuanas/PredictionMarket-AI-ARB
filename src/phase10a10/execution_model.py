"""Execution and Economic Model for Phase 10A.10 Deterministic Resolution Lag.

Implements:
- Actual L2 book ladder walking for buying winning contracts (or shorting/buying opposing).
- Calculation of executable VWAP, filled shares, levels consumed, and slippage.
- Gross deterministic edge: (settlement_value - VWAP) / VWAP * 10,000 bps.
- Net EV accounting: fees, slippage, and market friction.
- Evaluation across 8 edge thresholds: 5, 10, 25, 50, 100, 250, 500, 1000 bps.
- Evaluation across 7 position sizes: $10, $25, $50, $100, $250, $500, $1,000.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from src.phase10a10.schema import (
    CandidateOpportunity,
    ExecutionRecord,
    DeterministicState,
    LatencyBucket,
)

logger = logging.getLogger(__name__)


class ExecutionSimulator:
    """Simulates realistic aggressive execution on deterministic resolution opportunities."""

    ENTRY_THRESHOLDS_BPS = [5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    POSITION_SIZES_USD = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]

    # Baseline fees: Polymarket base trading fee on CLOB is 0 bps for standard markets,
    # but we include a conservative 5.0 bps baseline for maker/taker gas & network friction.
    BASE_FEE_BPS = 5.0

    @classmethod
    def walk_l2_book(
        cls,
        asks: List[Dict[str, float]],
        target_size_usd: float
    ) -> Tuple[float, float, int, float]:
        """Walks the ask ladder to fill target_size_usd.
        
        Returns:
            (vwap, filled_shares, levels_consumed, available_depth_usd)
        """
        if not asks or target_size_usd <= 0:
            return 1.0, 0.0, 0, 0.0

        # Sort asks ascending by price
        sorted_asks = sorted(asks, key=lambda x: float(x.get("price", 1.0)))

        total_depth_usd = 0.0
        for level in sorted_asks:
            price = float(level.get("price", 1.0))
            size = float(level.get("size", 0.0))
            lvl_usd = float(level.get("size_usd", price * size))
            total_depth_usd += lvl_usd

        remaining_usd = target_size_usd
        accum_cost = 0.0
        accum_shares = 0.0
        levels = 0

        for level in sorted_asks:
            price = float(level.get("price", 1.0))
            size = float(level.get("size", 0.0))
            lvl_usd = float(level.get("size_usd", price * size))

            if price <= 0.0:
                continue

            levels += 1
            if remaining_usd <= lvl_usd:
                # Fill remainder
                fill_shares = remaining_usd / price
                accum_shares += fill_shares
                accum_cost += remaining_usd
                remaining_usd = 0.0
                break
            else:
                fill_shares = size if size > 0 else (lvl_usd / price)
                accum_shares += fill_shares
                accum_cost += lvl_usd
                remaining_usd -= lvl_usd

        if accum_shares <= 0.0:
            return 1.0, 0.0, levels, total_depth_usd

        vwap = accum_cost / accum_shares
        return vwap, accum_shares, levels, total_depth_usd

    @classmethod
    def simulate_execution(
        cls,
        candidate: CandidateOpportunity,
        asks: List[Dict[str, float]],
        settlement_value: float = 1.0,
        fee_stress_multiplier: float = 1.0,
    ) -> Optional[ExecutionRecord]:
        """Executes candidate against order book depth."""
        target_size = candidate.target_size_usd
        vwap, shares, levels, available_depth = cls.walk_l2_book(asks, target_size)

        if available_depth < target_size * 0.90:  # Allow 90% partial fill threshold
            return None

        best_ask = candidate.best_ask
        slippage_bps = max(0.0, ((vwap - best_ask) / best_ask) * 10000.0) if best_ask > 0 else 0.0
        fee_bps = cls.BASE_FEE_BPS * fee_stress_multiplier

        # Gross edge: (settlement_value - VWAP) / VWAP in bps
        if vwap <= 0.0 or vwap >= settlement_value:
            gross_edge_bps = 0.0
        else:
            gross_edge_bps = ((settlement_value - vwap) / vwap) * 10000.0

        net_ev_bps = gross_edge_bps - fee_bps - slippage_bps

        return ExecutionRecord(
            execution_id=f"exec_{candidate.candidate_id}_{int(target_size)}",
            candidate_id=candidate.candidate_id,
            event_id=candidate.event_id,
            market_id=candidate.market_id,
            token_id=candidate.token_id,
            outcome=candidate.outcome,
            execution_timestamp=candidate.market_observation_timestamp,
            position_size_usd=target_size,
            filled_shares=shares,
            vwap=vwap,
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            gross_deterministic_edge_bps=gross_edge_bps,
            net_ev_bps=net_ev_bps,
            levels_consumed=levels,
            is_out_of_sample=candidate.is_out_of_sample
        )
