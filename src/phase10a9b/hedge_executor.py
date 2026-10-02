"""Strict Forward-Causal Hedge Execution Engine for Phase 10A.9-B.

Enforces:
- Strict forward causality: min(snapshot_timestamp) subject to snapshot_timestamp >= hedge_target_timestamp.
- Absolute prohibition on pre-target book snapshots.
- Hard invariant assertion: selected_snapshot_timestamp >= hedge_target_timestamp.
- Explicit status tracking: COMPLETED, PARTIAL, FAILED_NO_FORWARD_BOOK, FAILED_INSUFFICIENT_DEPTH, AMBIGUOUS.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from src.phase10a9b.schema import (
    CausalHedgeExecutionStatus,
    CausalHedgeExecutionRecord,
)

from bisect import bisect_left

logger = logging.getLogger(__name__)


class StrictForwardCausalHedgeExecutor:
    """Simulates hedge execution enforcing strict forward timestamp causality."""

    def __init__(
        self,
        default_fee_bps: float = 0.0,
        max_forward_horizon_sec: float = 30.0
    ):
        self.default_fee_bps = default_fee_bps
        self.max_forward_horizon_sec = max_forward_horizon_sec
        self._indexed_snapshots: Optional[Dict[str, Tuple[List[datetime], List[Dict[str, Any]]]]] = None

    def index_snapshots(self, snapshots: List[Dict[str, Any]]) -> None:
        """Pre-indexes snapshots by token_id sorted by timestamp for O(log N) causal lookup."""
        by_token: Dict[str, List[Tuple[datetime, Dict[str, Any]]]] = {}
        for s in snapshots:
            tok = str(s.get("token_id", ""))
            ts = s.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if tok not in by_token:
                by_token[tok] = []
            by_token[tok].append((ts, s))

        indexed: Dict[str, Tuple[List[datetime], List[Dict[str, Any]]]] = {}
        for tok, items in by_token.items():
            items.sort(key=lambda x: x[0])
            timestamps = [it[0] for it in items]
            snaps = [it[1] for it in items]
            indexed[tok] = (timestamps, snaps)
        self._indexed_snapshots = indexed

    def execute_causal_hedge(
        self,
        passive_fill: Dict[str, Any],
        relationship: Any,
        hedge_snapshots: List[Dict[str, Any]],
        latency_ms: int = 100,
        depth_scaling_factor: float = 1.0,
        spread_stress_multiplier: float = 1.0,
        hedge_fraction: float = 1.0
    ) -> CausalHedgeExecutionRecord:
        """Executes hedge using strictly forward-causal order book selection."""
        fill_id = str(passive_fill.get("fill_id", "f0"))
        pass_tok = str(passive_fill["token_id"])
        
        # Determine hedge token from relationship
        c_a = getattr(relationship, "contract_a", relationship.get("contract_a") if isinstance(relationship, dict) else "")
        c_b = getattr(relationship, "contract_b", relationship.get("contract_b") if isinstance(relationship, dict) else "")
        hedge_tok = c_b if pass_tok == c_a else c_a
        hedge_ratio = float(getattr(relationship, "hedge_ratio", relationship.get("hedge_ratio", 1.0) if isinstance(relationship, dict) else 1.0))
        rel_id = getattr(relationship, "relationship_id", relationship.get("relationship_id", "") if isinstance(relationship, dict) else "")

        # Timing
        t_fill = passive_fill["fill_timestamp"]
        if isinstance(t_fill, str):
            t_fill = datetime.fromisoformat(t_fill)
        if t_fill.tzinfo is None:
            t_fill = t_fill.replace(tzinfo=timezone.utc)

        t_target = t_fill + timedelta(milliseconds=latency_ms)

        pass_side = str(passive_fill.get("side", passive_fill.get("fill_side", "BUY"))).upper()
        pass_price = float(passive_fill["fill_price"])
        pass_size_usd = float(passive_fill.get("fill_size_usd", 50.0))
        pass_shares = float(passive_fill.get("fill_shares", pass_size_usd / max(0.01, pass_price)))

        # Side: Long A is neutralized by Long B; Short A by Short B
        hedge_side = "BUY" if pass_side == "BUY" else "SELL"
        target_hedge_shares = pass_shares * hedge_ratio * hedge_fraction

        # 1. Forward-Causal Snapshot Selection:
        # min(ts) subject to ts >= t_target within max_forward_horizon_sec
        selected_snap = None
        snap_ts = None
        pre_target_count = 0

        if self._indexed_snapshots is not None and hedge_tok in self._indexed_snapshots:
            timestamps, s_list = self._indexed_snapshots[hedge_tok]
            idx = bisect_left(timestamps, t_target)
            pre_target_count = idx
            if idx < len(timestamps):
                candidate_ts = timestamps[idx]
                if 0.0 <= (candidate_ts - t_target).total_seconds() <= self.max_forward_horizon_sec:
                    selected_snap = s_list[idx]
                    snap_ts = candidate_ts
        else:
            token_snaps = [s for s in hedge_snapshots if str(s.get("token_id", "")) == hedge_tok]
            forward_snaps: List[Tuple[float, Dict[str, Any]]] = []

            for s in token_snaps:
                ts = s.get("timestamp")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                
                diff_sec = (ts - t_target).total_seconds()
                # STRICT RULE: diff_sec MUST be >= 0.0 (strictly forward in time)
                if diff_sec < 0.0:
                    pre_target_count += 1
                elif diff_sec <= self.max_forward_horizon_sec:
                    forward_snaps.append((diff_sec, s))

            if forward_snaps:
                forward_snaps.sort(key=lambda x: x[0])
                selected_snap = forward_snaps[0][1]
                snap_ts = selected_snap.get("timestamp")
                if isinstance(snap_ts, str):
                    snap_ts = datetime.fromisoformat(snap_ts)
                if snap_ts.tzinfo is None:
                    snap_ts = snap_ts.replace(tzinfo=timezone.utc)

        if selected_snap is None:
            # No valid forward snapshot exists
            return CausalHedgeExecutionRecord(
                hedge_id=f"hdg_{fill_id}_{latency_ms}ms",
                relationship_id=rel_id,
                passive_fill_id=fill_id,
                passive_token_id=pass_tok,
                hedge_token_id=hedge_tok,
                passive_fill_timestamp=t_fill,
                hedge_latency_ms=latency_ms,
                hedge_target_timestamp=t_target,
                selected_snapshot_timestamp=None,
                snapshot_delta_ms=0.0,
                snapshot_was_forward=False,
                passive_fill_side=pass_side,
                hedge_side=hedge_side,
                passive_fill_price=pass_price,
                passive_filled_shares=pass_shares,
                passive_filled_usd=pass_size_usd,
                required_quantity=target_hedge_shares,
                available_quantity=0.0,
                filled_quantity=0.0,
                VWAP=0.0,
                hedge_slippage_bps=0.0,
                hedge_spread_bps=0.0,
                hedge_status=CausalHedgeExecutionStatus.FAILED_NO_FORWARD_BOOK,
                residual_unhedged_shares=target_hedge_shares,
                residual_unhedged_usd=target_hedge_shares * pass_price,
                pre_target_rejected_count=pre_target_count,
                provenance="POLYMARKET_LIVE"
            )

        # HARD ASSERTION: Must never be prior to target
        assert snap_ts >= t_target, f"Causality Violation! Selected {snap_ts} < target {t_target}"
        delta_ms = (snap_ts - t_target).total_seconds() * 1000.0

        # 2. Extract and scale ladder
        raw_bids, raw_asks = self._parse_ladder(selected_snap)
        bids = self._scale_ladder(raw_bids, depth_scaling_factor, spread_stress_multiplier, is_bid=True)
        asks = self._scale_ladder(raw_asks, depth_scaling_factor, spread_stress_multiplier, is_bid=False)

        snap_best_bid = selected_snap.get("best_bid") if isinstance(selected_snap, dict) else getattr(selected_snap, "best_bid", None)
        snap_best_ask = selected_snap.get("best_ask") if isinstance(selected_snap, dict) else getattr(selected_snap, "best_ask", None)
        best_bid = bids[0]["price"] if bids else (float(snap_best_bid) if snap_best_bid is not None else 0.01)
        best_ask = asks[0]["price"] if asks else (float(snap_best_ask) if snap_best_ask is not None else 0.99)
        midpoint = (best_bid + best_ask) / 2.0
        hedge_spread_bps = max(0.0, ((best_ask - best_bid) / max(0.01, midpoint)) * 10_000.0)

        # 3. Walk the book
        if hedge_side == "BUY":
            ladder = asks
            best_price = best_ask
        else:
            ladder = bids
            best_price = best_bid

        available_qty = sum(l["size"] for l in ladder)
        filled_shares, filled_usd, vwap, depth_exhausted = self._walk_ladder(ladder, target_hedge_shares, is_buy=(hedge_side == "BUY"))

        # 4. Slippage calculation relative to top-of-book
        if filled_shares > 0 and best_price > 0:
            if hedge_side == "BUY":
                slippage_bps = max(0.0, ((vwap - best_price) / best_price) * 10_000.0)
            else:
                slippage_bps = max(0.0, ((best_price - vwap) / best_price) * 10_000.0)
        else:
            slippage_bps = 0.0

        residual_shares = max(0.0, target_hedge_shares - filled_shares)
        residual_usd = residual_shares * midpoint

        # 5. Status determination
        if available_qty == 0.0 or filled_shares == 0.0:
            status = CausalHedgeExecutionStatus.FAILED_INSUFFICIENT_DEPTH
        elif residual_shares < 1e-4:
            status = CausalHedgeExecutionStatus.COMPLETED
        else:
            status = CausalHedgeExecutionStatus.PARTIAL

        rec = CausalHedgeExecutionRecord(
            hedge_id=f"hdg_{fill_id}_{latency_ms}ms",
            relationship_id=rel_id,
            passive_fill_id=fill_id,
            passive_token_id=pass_tok,
            hedge_token_id=hedge_tok,
            passive_fill_timestamp=t_fill,
            hedge_latency_ms=latency_ms,
            hedge_target_timestamp=t_target,
            selected_snapshot_timestamp=snap_ts,
            snapshot_delta_ms=round(delta_ms, 2),
            snapshot_was_forward=True,
            passive_fill_side=pass_side,
            hedge_side=hedge_side,
            passive_fill_price=pass_price,
            passive_filled_shares=pass_shares,
            passive_filled_usd=pass_size_usd,
            required_quantity=target_hedge_shares,
            available_quantity=available_qty,
            filled_quantity=filled_shares,
            VWAP=vwap,
            hedge_slippage_bps=round(slippage_bps, 2),
            hedge_spread_bps=round(hedge_spread_bps, 2),
            hedge_status=status,
            residual_unhedged_shares=round(residual_shares, 4),
            residual_unhedged_usd=round(residual_usd, 4),
            pre_target_rejected_count=pre_target_count,
            provenance="POLYMARKET_LIVE"
        )
        return rec

    def _walk_ladder(
        self,
        ladder: List[Dict[str, float]],
        target_shares: float,
        is_buy: bool
    ) -> Tuple[float, float, float, bool]:
        """Walks book ladder sequentially to calculate executed VWAP."""
        remaining_shares = target_shares
        filled_shares = 0.0
        filled_usd = 0.0

        for level in ladder:
            p = level["price"]
            s = level["size"]
            take_s = min(remaining_shares, s)
            take_usd = take_s * p

            filled_shares += take_s
            filled_usd += take_usd
            remaining_shares -= take_s

            if remaining_shares <= 1e-6:
                break

        depth_exhausted = (remaining_shares > 1e-4)
        vwap = (filled_usd / filled_shares) if filled_shares > 0 else 0.0
        return filled_shares, filled_usd, vwap, depth_exhausted

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
        """Scales depth and applies spread stress multipliers."""
        scaled = []
        for lvl in ladder:
            p = lvl["price"]
            s = lvl["size"] * depth_scaling_factor
            if spread_stress_multiplier != 1.0:
                if is_bid:
                    p = max(0.01, p / spread_stress_multiplier)
                else:
                    p = min(0.99, p * spread_stress_multiplier)
            scaled.append({"price": p, "size": s, "size_usd": p * s})
        return scaled
