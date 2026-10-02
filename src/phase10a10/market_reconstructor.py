"""Market State Reconstruction Engine for Phase 10A.10.

Reconstructs genuine Polymarket L2 order book states around event timestamps at:
- Pre-event: T-60m, T-30m, T-10m, T-5m, T-1m, T-30s, T-10s, T-5s
- Event: T
- Post-event: T+100ms, T+250ms, T+500ms, T+1s, T+2s, T+5s, T+10s, T+30s, T+1m, T+5m, T+15m

Strictly no synthetic interpolation: uses actual recorded L2 book snapshots.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from src.phase10a10.schema import MarketStateSnapshot

logger = logging.getLogger(__name__)


class MarketStateReconstructor:
    """Reconstructs discrete L2 market states around authoritative events."""

    RECONSTRUCTION_OFFSETS_SEC = [
        ("T-60m", -3600.0),
        ("T-30m", -1800.0),
        ("T-10m", -600.0),
        ("T-5m", -300.0),
        ("T-1m", -60.0),
        ("T-30s", -30.0),
        ("T-10s", -10.0),
        ("T-5s", -5.0),
        ("T", 0.0),
        ("T+100ms", 0.1),
        ("T+250ms", 0.25),
        ("T+500ms", 0.5),
        ("T+1s", 1.0),
        ("T+2s", 2.0),
        ("T+5s", 5.0),
        ("T+10s", 10.0),
        ("T+30s", 30.0),
        ("T+1m", 60.0),
        ("T+5m", 300.0),
        ("T+15m", 900.0),
    ]

    @classmethod
    def find_nearest_snapshot(
        cls,
        snapshots: List[Dict[str, Any]],
        target_dt: datetime,
        require_forward: bool = False,
        max_delta_sec: float = 300.0
    ) -> Optional[Dict[str, Any]]:
        """Finds the nearest snapshot to target_dt.
        
        If require_forward=True (for post-event execution): selects min(ts) where ts >= target_dt.
        Otherwise: selects snapshot minimizing abs(ts - target_dt).
        """
        if not snapshots:
            return None

        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        target_utc = to_utc(target_dt)

        if require_forward:
            valid_forward = [
                s for s in snapshots
                if to_utc(s["timestamp"]) >= target_utc and (to_utc(s["timestamp"]) - target_utc).total_seconds() <= max_delta_sec
            ]
            if not valid_forward:
                return None
            return min(valid_forward, key=lambda s: to_utc(s["timestamp"]))
        else:
            valid = [
                s for s in snapshots
                if abs((to_utc(s["timestamp"]) - target_utc).total_seconds()) <= max_delta_sec
            ]
            if not valid:
                return None
            return min(valid, key=lambda s: abs((to_utc(s["timestamp"]) - target_utc).total_seconds()))

    @classmethod
    def reconstruct_event_window(
        cls,
        token_snapshots: List[Dict[str, Any]],
        event_timestamp: datetime,
        market_id: str,
        token_id: str
    ) -> Dict[str, MarketStateSnapshot]:
        """Reconstructs the full sequence of market states across all required offsets."""
        reconstructed: Dict[str, MarketStateSnapshot] = {}

        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        base_utc = to_utc(event_timestamp)

        for label, offset_sec in cls.RECONSTRUCTION_OFFSETS_SEC:
            target_ts = base_utc + timedelta(seconds=offset_sec)
            # For positive offsets (execution/reaction), enforce strict forward causality
            require_forward = (offset_sec >= 0.0)

            snap = cls.find_nearest_snapshot(
                snapshots=token_snapshots,
                target_dt=target_ts,
                require_forward=require_forward,
                max_delta_sec=600.0 if offset_sec < 0 else 300.0
            )

            if snap is not None:
                # Parse bids and asks
                bids_raw = snap.get("bids", [])
                asks_raw = snap.get("asks", [])
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

                best_bid = float(snap.get("best_bid") or 0.0)
                best_ask = float(snap.get("best_ask") or 1.0)
                midpoint = float(snap.get("midpoint") or (best_bid + best_ask) / 2.0)
                spread_bps = float(snap.get("spread_bps") or ((best_ask - best_bid) / midpoint * 10000 if midpoint > 0 else 0.0))

                # Calculate USD depths
                depth_bid_usd = sum(float(b.get("size_usd", float(b.get("price", 0.0)) * float(b.get("size", 0.0)))) for b in bids_raw)
                depth_ask_usd = sum(float(a.get("size_usd", float(a.get("price", 0.0)) * float(a.get("size", 0.0)))) for a in asks_raw)

                reconstructed[label] = MarketStateSnapshot(
                    snapshot_id=str(snap.get("snapshot_id", f"rec_{label}")),
                    market_id=market_id,
                    token_id=token_id,
                    timestamp=to_utc(snap["timestamp"]),
                    horizon_label=label,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    midpoint=midpoint,
                    spread_bps=spread_bps,
                    depth_bid_usd=depth_bid_usd,
                    depth_ask_usd=depth_ask_usd,
                    bids=bids_raw,
                    asks=asks_raw,
                    provenance="POLYMARKET_LIVE"
                )

        return reconstructed
