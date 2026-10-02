"""Portfolio Inventory Tracking and Liquidation Engine for Phase 10A.8.

Responsibilities:
1. Track per-market cumulative inventory (YES, NO, and net directional USD exposure).
2. Enforce explicit inventory capacity constraints ($25, $50, $100, $250, $500).
3. Model liquidation using executable opposite-side order book depth when limits are breached.
4. Calculate realistic liquidation costs and inventory drag.
"""

from typing import Dict, Any, List, Optional
from src.phase10a8.schema import (
    QuoteSide,
    FillResult,
    InventoryPositionRecord,
    STANDARD_INVENTORY_LIMITS_USD,
)
from src.phase10a8.book_features import BookFeatureExtractor


class PortfolioInventoryEngine:
    """Simulates portfolio-level inventory accumulation, position limits, and liquidations."""

    def __init__(self, inventory_limits_usd: Optional[List[float]] = None):
        self.inventory_limits_usd = inventory_limits_usd or STANDARD_INVENTORY_LIMITS_USD

    def simulate_market_inventory(
        self,
        market_id: str,
        fills: List[FillResult],
        quotes_dict: Dict[str, Any],
        snapshots_by_time: List[Dict[str, Any]],
        limit_usd: float,
    ) -> InventoryPositionRecord:
        """Simulates chronological inventory tracking and forced liquidations for a specific limit."""
        record = InventoryPositionRecord(
            market_id=market_id,
            inventory_limit_usd=limit_usd,
        )

        current_inventory_usd = 0.0  # Positive = net YES / long, Negative = net NO / short
        cum_yes = 0.0
        cum_no = 0.0
        max_inv = 0.0
        accepted_fills = 0
        rejected_fills = 0
        liquidation_events = 0
        total_liq_cost_usd = 0.0
        total_holding_sec = 0.0

        # Sort fills chronologically
        valid_fills = [f for f in fills if f.fill_timestamp and f.fill_size_usd > 0]
        sorted_fills = sorted(valid_fills, key=lambda x: x.fill_timestamp)

        for fill in sorted_fills:
            quote = quotes_dict.get(fill.quote_id)
            if not quote:
                continue

            side = quote.side
            delta_usd = fill.fill_size_usd if side == QuoteSide.BUY else -fill.fill_size_usd
            projected_inv = current_inventory_usd + delta_usd

            # Check if limit breached
            if abs(projected_inv) > limit_usd:
                # Inventory limit reached!
                # Strategy: reject fill or trigger liquidation
                rejected_fills += 1

                # If current inventory is already near limit, force a liquidation to half-limit
                if abs(current_inventory_usd) >= limit_usd * 0.8:
                    liquidation_events += 1
                    # Find matching snapshot at liquidation time
                    liq_snap = self._find_snapshot_at_or_after(snapshots_by_time, fill.fill_timestamp)
                    liq_cost = self._calculate_liquidation_cost(
                        liq_snap, current_inventory_usd, quote.midpoint
                    )
                    total_liq_cost_usd += liq_cost
                    # Reset inventory to flattened position
                    current_inventory_usd = 0.0
            else:
                # Accept fill
                accepted_fills += 1
                current_inventory_usd = projected_inv
                if side == QuoteSide.BUY:
                    cum_yes += fill.fill_size_usd
                else:
                    cum_no += fill.fill_size_usd

                max_inv = max(max_inv, abs(current_inventory_usd))

        record.cumulative_yes_usd = round(cum_yes, 4)
        record.cumulative_no_usd = round(cum_no, 4)
        record.net_directional_usd = round(current_inventory_usd, 4)
        record.max_inventory_usd = round(max_inv, 4)
        record.cumulative_fills_count = accepted_fills
        record.rejected_fills_count = rejected_fills
        record.total_liquidation_events = liquidation_events
        record.total_liquidation_cost_usd = round(total_liq_cost_usd, 4)

        return record

    @staticmethod
    def _find_snapshot_at_or_after(
        snapshots: List[Dict[str, Any]],
        t: Any,
    ) -> Optional[Dict[str, Any]]:
        for s in snapshots:
            if s["timestamp"] >= t:
                return s
        return snapshots[-1] if snapshots else None

    @staticmethod
    def _calculate_liquidation_cost(
        snapshot: Optional[Dict[str, Any]],
        inventory_usd: float,
        fallback_midpoint: float,
    ) -> float:
        """Calculates cost of liquidating current inventory by crossing the book."""
        if abs(inventory_usd) <= 0.0:
            return 0.0

        if not snapshot:
            # Conservative fallback: 200 bps liquidation penalty
            return abs(inventory_usd) * 0.02

        bids = BookFeatureExtractor.parse_ladder(snapshot.get("bids"))
        asks = BookFeatureExtractor.parse_ladder(snapshot.get("asks"))
        mid = snapshot.get("midpoint", fallback_midpoint)

        # If long (inventory > 0), must sell into bids
        # If short (inventory < 0), must buy from asks
        target_size = abs(inventory_usd)
        ladder = bids if inventory_usd > 0 else asks
        ladder = sorted(ladder, key=lambda x: x["price"], reverse=(inventory_usd > 0))

        if not ladder:
            return target_size * 0.05  # Severe penalty if book is empty

        filled_usd = 0.0
        filled_shares = 0.0
        for lvl in ladder:
            u = lvl["size_usd"]
            s = lvl["size"]
            needed = target_size - filled_usd
            if u <= needed:
                filled_usd += u
                filled_shares += s
            else:
                filled_usd += needed
                filled_shares += s * (needed / u)
                break

        exec_vwap = filled_usd / filled_shares if filled_shares > 0 else mid
        if inventory_usd > 0:
            # Liquidating long: sold at exec_vwap <= mid
            cost = max(0.0, (mid - exec_vwap) * filled_shares)
        else:
            # Liquidating short: bought at exec_vwap >= mid
            cost = max(0.0, (exec_vwap - mid) * filled_shares)

        return max(cost, target_size * 0.005)  # At least 50 bps half-spread
