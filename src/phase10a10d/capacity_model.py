"""Capacity and Order Book Depth Model for Phase 10A.10-D.

Evaluates executable capacity across $10, $25, $50, $100, $250, $500, $1,000 tiers.
Correctly models full fill, partial fill, and no fill based on actual L2 depth.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple


@dataclass
class CapacityFillResult:
    """Detailed capacity fill evaluation for a specific target size tier."""
    target_size_usd: float
    filled_usd: float
    filled_shares: float
    executable_vwap: float
    slippage_bps: float
    fill_status: str  # 'FULL_FILL', 'PARTIAL_FILL', 'NO_FILL'
    fill_ratio: float
    is_fully_filled: bool
    levels_consumed: int


class CapacityEvaluationModel:
    """Evaluates position size capacity against L2 ask ladders."""

    TIERS = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]

    @classmethod
    def walk_ask_ladder(
        cls,
        asks: List[Dict[str, float]],
        target_size_usd: float
    ) -> CapacityFillResult:
        """Walks ask ladder to calculate VWAP and fill status.

        Args:
            asks: List of dicts with 'price' and 'size' (or 'amount') in ascending price order.
            target_size_usd: Requested order size in USD.

        Returns:
            CapacityFillResult.
        """
        if not asks or target_size_usd <= 0:
            return CapacityFillResult(
                target_size_usd=target_size_usd,
                filled_usd=0.0,
                filled_shares=0.0,
                executable_vwap=0.0,
                slippage_bps=0.0,
                fill_status="NO_FILL",
                fill_ratio=0.0,
                is_fully_filled=False,
                levels_consumed=0,
            )

        best_ask = asks[0]["price"]
        remaining_usd = target_size_usd
        total_spent = 0.0
        total_shares = 0.0
        levels = 0

        for level in asks:
            p = level["price"]
            s = level["size"]  # available shares
            level_usd = p * s

            levels += 1
            if remaining_usd <= level_usd:
                # Fill remainder
                needed_shares = remaining_usd / p
                total_spent += remaining_usd
                total_shares += needed_shares
                remaining_usd = 0.0
                break
            else:
                total_spent += level_usd
                total_shares += s
                remaining_usd -= level_usd

        if total_shares == 0.0:
            return CapacityFillResult(
                target_size_usd=target_size_usd,
                filled_usd=0.0,
                filled_shares=0.0,
                executable_vwap=0.0,
                slippage_bps=0.0,
                fill_status="NO_FILL",
                fill_ratio=0.0,
                is_fully_filled=False,
                levels_consumed=0,
            )

        vwap = total_spent / total_shares
        slippage_bps = ((vwap - best_ask) / best_ask) * 10000.0
        fill_ratio = total_spent / target_size_usd
        is_full = (remaining_usd <= 1e-4)

        status = "FULL_FILL" if is_full else ("PARTIAL_FILL" if total_spent > 0 else "NO_FILL")

        return CapacityFillResult(
            target_size_usd=target_size_usd,
            filled_usd=total_spent,
            filled_shares=total_shares,
            executable_vwap=vwap,
            slippage_bps=slippage_bps,
            fill_status=status,
            fill_ratio=fill_ratio,
            is_fully_filled=is_full,
            levels_consumed=levels,
        )

    @classmethod
    def evaluate_all_tiers(
        cls,
        asks: List[Dict[str, float]]
    ) -> Dict[float, CapacityFillResult]:
        """Evaluates fill across all 7 standard capacity tiers."""
        return {tier: cls.walk_ask_ladder(asks, tier) for tier in cls.TIERS}
