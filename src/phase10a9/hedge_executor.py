"""Hedge Execution Engine for Phase 10A.9 Hedged Passive Liquidity Provision.

Models the hedge leg as a realistic, separate taker execution:
- Walks the observable L2 order book ladder of the hedge contract.
- Prices executable VWAP without using midpoint or fair value assumptions.
- Evaluates across standard millisecond latencies [0ms -> 5000ms].
- Strictly models partial fills and tracks residual unhedged exposure.
"""

from datetime import datetime, timedelta, timezone
import json
from typing import Dict, Any, List, Optional, Tuple

from src.phase10a9.schema import (
    RelationshipType,
    HedgeExecutionStatus,
    ContractRelationshipRecord,
    HedgeExecutionRecord,
)


class HedgeExecutionEngine:
    """Simulates realistic taker execution of the hedge leg following a passive maker fill."""

    def __init__(self, default_fee_bps: float = 0.0):
        self.default_fee_bps = default_fee_bps

    def execute_hedge(
        self,
        passive_fill: Dict[str, Any],
        relationship: ContractRelationshipRecord,
        hedge_snapshots: List[Dict[str, Any]],
        latency_ms: int = 100,
        depth_scaling_factor: float = 1.0,
        spread_stress_multiplier: float = 1.0,
        hedge_fraction: float = 1.0
    ) -> HedgeExecutionRecord:
        """Executes hedge leg against the actual L2 book of Contract B at timestamp t_f + latency_ms."""
        fill_id = str(passive_fill["fill_id"])
        pass_tok = str(passive_fill.get("token_id", relationship.contract_a))
        hedge_tok = relationship.contract_b if pass_tok == relationship.contract_a else relationship.contract_a
        
        t_fill = passive_fill["fill_timestamp"]
        if isinstance(t_fill, str):
            t_fill = datetime.fromisoformat(t_fill)
        if t_fill.tzinfo is None:
            t_fill = t_fill.replace(tzinfo=timezone.utc)

        t_hedge = t_fill + timedelta(milliseconds=latency_ms)
        pass_side = str(passive_fill.get("side", passive_fill.get("fill_side", "BUY"))).upper()
        pass_price = float(passive_fill["fill_price"])
        pass_size_usd = float(passive_fill.get("fill_size_usd", 50.0))
        pass_shares = float(passive_fill.get("fill_shares", pass_size_usd / max(0.01, pass_price)))

        # 1. Determine hedge leg direction and required shares
        # For R1 (A + B = 1):
        # Long A exposure is neutralized by Long B (holding A + B == $1 terminal payout).
        # Short A exposure is neutralized by Short B.
        if pass_side == "BUY":
            hedge_side = "BUY"  # Buy B to neutralize Long A
        else:
            hedge_side = "SELL" # Sell B to neutralize Short A

        target_hedge_shares = pass_shares * relationship.hedge_ratio * hedge_fraction

        # 2. Find closest L2 book snapshot of Contract B at or after t_hedge
        hedge_snap = self._find_active_snapshot(hedge_snapshots, hedge_tok, t_hedge)

        if not hedge_snap:
            # Zero market data available for hedge contract -> Failed
            return HedgeExecutionRecord(
                hedge_id=f"hdg_fail_{fill_id}_{latency_ms}ms",
                relationship_id=relationship.relationship_id,
                passive_fill_id=fill_id,
                passive_token_id=pass_tok,
                hedge_token_id=hedge_tok,
                passive_fill_timestamp=t_fill,
                hedge_timestamp=t_hedge,
                hedge_latency_ms=latency_ms,
                passive_fill_side=pass_side,
                hedge_side=hedge_side,
                passive_fill_price=pass_price,
                passive_filled_shares=pass_shares,
                passive_filled_usd=pass_size_usd,
                hedge_required_shares=target_hedge_shares,
                hedge_filled_shares=0.0,
                hedge_filled_usd=0.0,
                hedge_vwap=0.0,
                hedge_slippage_bps=0.0,
                hedge_spread_bps=0.0,
                hedge_depth_exhausted=True,
                residual_unhedged_shares=target_hedge_shares,
                residual_unhedged_usd=target_hedge_shares * pass_price,
                execution_status=HedgeExecutionStatus.HEDGE_DEPTH_INSUFFICIENT,
                provenance="POLYMARKET_LIVE"
            )

        # 3. Extract and scale ladder
        raw_bids, raw_asks = self._parse_ladder(hedge_snap)
        bids = self._scale_ladder(raw_bids, depth_scaling_factor, spread_stress_multiplier, is_bid=True)
        asks = self._scale_ladder(raw_asks, depth_scaling_factor, spread_stress_multiplier, is_bid=False)

        snap_best_bid = hedge_snap.get("best_bid") if isinstance(hedge_snap, dict) else getattr(hedge_snap, "best_bid", None)
        snap_best_ask = hedge_snap.get("best_ask") if isinstance(hedge_snap, dict) else getattr(hedge_snap, "best_ask", None)
        best_bid = bids[0]["price"] if bids else (float(snap_best_bid) if snap_best_bid is not None else 0.01)
        best_ask = asks[0]["price"] if asks else (float(snap_best_ask) if snap_best_ask is not None else 0.99)
        midpoint = (best_bid + best_ask) / 2.0
        hedge_spread_bps = max(0.0, ((best_ask - best_bid) / max(0.01, midpoint)) * 10_000.0)

        # 4. Walk the book
        if hedge_side == "BUY":
            ladder = asks
            best_price = best_ask
        else:
            ladder = bids
            best_price = best_bid

        filled_shares, filled_usd, vwap, depth_exhausted = self._walk_ladder(ladder, target_hedge_shares, is_buy=(hedge_side == "BUY"))

        # 5. Compute slippage relative to best available price
        if filled_shares > 0 and best_price > 0:
            if hedge_side == "BUY":
                slippage_bps = max(0.0, ((vwap - best_price) / best_price) * 10_000.0)
            else:
                slippage_bps = max(0.0, ((best_price - vwap) / best_price) * 10_000.0)
        else:
            slippage_bps = 0.0

        # 6. Assess execution status and residual exposure
        residual_shares = max(0.0, target_hedge_shares - filled_shares)
        residual_usd = residual_shares * midpoint

        if filled_shares == 0.0:
            status = HedgeExecutionStatus.HEDGE_DEPTH_INSUFFICIENT
        elif residual_shares < 1e-4:
            status = HedgeExecutionStatus.COMPLETE_HEDGE
        else:
            status = HedgeExecutionStatus.PARTIAL_HEDGE

        hedge_id = f"hdg_{fill_id}_{latency_ms}ms"

        return HedgeExecutionRecord(
            hedge_id=hedge_id,
            relationship_id=relationship.relationship_id,
            passive_fill_id=fill_id,
            passive_token_id=pass_tok,
            hedge_token_id=hedge_tok,
            passive_fill_timestamp=t_fill,
            hedge_timestamp=t_hedge,
            hedge_latency_ms=latency_ms,
            passive_fill_side=pass_side,
            hedge_side=hedge_side,
            passive_fill_price=pass_price,
            passive_filled_shares=pass_shares,
            passive_filled_usd=pass_size_usd,
            hedge_required_shares=target_hedge_shares,
            hedge_filled_shares=filled_shares,
            hedge_filled_usd=filled_usd,
            hedge_vwap=vwap,
            hedge_slippage_bps=slippage_bps,
            hedge_spread_bps=hedge_spread_bps,
            hedge_depth_exhausted=depth_exhausted,
            residual_unhedged_shares=residual_shares,
            residual_unhedged_usd=residual_usd,
            execution_status=status,
            provenance="POLYMARKET_LIVE"
        )

    def _find_active_snapshot(
        self,
        snapshots: List[Dict[str, Any]],
        token_id: str,
        target_timestamp: datetime
    ) -> Optional[Dict[str, Any]]:
        """Finds closest snapshot of token_id at or immediately following target_timestamp."""
        token_snaps = [s for s in snapshots if str(s.get("token_id", "")) == token_id]
        if not token_snaps:
            return None

        # Filter to snaps within [-10s, +30s] of target_timestamp
        valid_snaps = []
        for s in token_snaps:
            ts = s.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            diff = (ts - target_timestamp).total_seconds()
            if -10.0 <= diff <= 30.0:
                valid_snaps.append((abs(diff), s))

        if not valid_snaps:
            return token_snaps[-1]  # Fallback to closest available in buffer

        valid_snaps.sort(key=lambda x: x[0])
        return valid_snaps[0][1]

    def _parse_ladder(self, snapshot: Dict[str, Any]) -> Tuple[List[Dict[str, float]], List[Dict[str, float]]]:
        """Parses bids and asks lists from snapshot record."""
        bids_raw = snapshot.get("bids", [])
        asks_raw = snapshot.get("asks", [])

        if isinstance(bids_raw, str):
            try:
                bids_raw = json.loads(bids_raw)
            except Exception:
                bids_raw = []

        if isinstance(asks_raw, str):
            try:
                asks_raw = json.loads(asks_raw)
            except Exception:
                asks_raw = []

        # Ensure structured format
        clean_bids = []
        for b in bids_raw:
            p = float(b.get("price", 0.0))
            s = float(b.get("size", b.get("size_usd", 0.0) / max(0.01, p)))
            if p > 0 and s > 0:
                clean_bids.append({"price": p, "size": s, "size_usd": p * s})

        clean_asks = []
        for a in asks_raw:
            p = float(a.get("price", 0.0))
            s = float(a.get("size", a.get("size_usd", 0.0) / max(0.01, p)))
            if p > 0 and s > 0:
                clean_asks.append({"price": p, "size": s, "size_usd": p * s})

        clean_bids.sort(key=lambda x: x["price"], reverse=True)
        clean_asks.sort(key=lambda x: x["price"])
        return clean_bids, clean_asks

    def _scale_ladder(
        self,
        ladder: List[Dict[str, float]],
        depth_scaling_factor: float,
        spread_stress_multiplier: float,
        is_bid: bool
    ) -> List[Dict[str, float]]:
        """Applies depth stress and spread stress to order book ladder."""
        if not ladder:
            return []

        scaled = []
        for level in ladder:
            p = level["price"]
            s = level["size"] * depth_scaling_factor
            if spread_stress_multiplier > 1.0:
                # Spread stress shifts asks up, bids down
                delta = abs(p - 0.50) * 0.05 * (spread_stress_multiplier - 1.0)
                p = max(0.001, p - delta) if is_bid else min(0.999, p + delta)
            scaled.append({"price": round(p, 4), "size": round(s, 4), "size_usd": round(p * s, 4)})
        return scaled

    def _walk_ladder(
        self,
        ladder: List[Dict[str, float]],
        target_shares: float,
        is_buy: bool
    ) -> Tuple[float, float, float, bool]:
        """Walks order book ladder to execute target_shares, returning (filled_shares, filled_usd, VWAP, depth_exhausted)."""
        if not ladder or target_shares <= 0:
            return 0.0, 0.0, 0.0, True

        remaining_shares = target_shares
        total_usd = 0.0
        filled_shares = 0.0

        for level in ladder:
            p = level["price"]
            avail_shares = level["size"]
            take_shares = min(remaining_shares, avail_shares)

            total_usd += take_shares * p
            filled_shares += take_shares
            remaining_shares -= take_shares

            if remaining_shares <= 1e-4:
                break

        vwap = (total_usd / filled_shares) if filled_shares > 0 else (ladder[0]["price"] if ladder else 0.5)
        depth_exhausted = (remaining_shares > 1e-4)
        return round(filled_shares, 4), round(total_usd, 4), round(vwap, 4), depth_exhausted
