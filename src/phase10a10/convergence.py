"""Market Price Convergence Tracking Engine for Phase 10A.10.

Measures the deterministic convergence path of Polymarket contracts:
- Convergence condition: executable ask >= 1.0 - epsilon (or executable liquidation value).
- Epsilon grid: 1bp, 5bp, 10bp, 25bp, 50bp, 100bp.
- Separates market convergence from formal settlement / UMA oracle resolution.
- Computes market reaction delay: first_convergence_ts - source_timestamp.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from src.phase10a10.schema import ConvergenceRecord, MarketStateSnapshot


class ConvergenceTracker:
    """Tracks price convergence toward deterministic settlement value ($1.00)."""

    EPSILON_GRID_BPS = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]

    @classmethod
    def evaluate_convergence(
        cls,
        event_id: str,
        market_id: str,
        token_id: str,
        source_ts: datetime,
        snapshots: List[Dict[str, Any]],
        formal_resolution_ts: Optional[datetime] = None,
        epsilon_bps: float = 10.0,
    ) -> ConvergenceRecord:
        """Evaluates convergence across ordered snapshots for a winning token."""
        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        src_utc = to_utc(source_ts)
        # Threshold price: 1.0 - (epsilon_bps / 10000.0)
        threshold_price = 1.0 - (epsilon_bps / 10000.0)

        # Filter snapshots occurring after source timestamp
        forward_snaps = [s for s in snapshots if to_utc(s["timestamp"]) >= src_utc]
        forward_snaps.sort(key=lambda s: to_utc(s["timestamp"]))

        first_market_ts: Optional[datetime] = None
        first_edge_ts: Optional[datetime] = None
        first_conv_ts: Optional[datetime] = None

        if forward_snaps:
            first_market_ts = to_utc(forward_snaps[0]["timestamp"])

        for snap in forward_snaps:
            ts = to_utc(snap["timestamp"])
            best_ask = float(snap.get("best_ask") or 1.0)
            best_bid = float(snap.get("best_bid") or 0.0)

            # Check if mispricing / edge exists (ask < 0.999)
            if best_ask < 0.999 and first_edge_ts is None:
                first_edge_ts = ts

            # Check if converged (best_bid or best_ask >= threshold_price)
            if best_bid >= threshold_price or best_ask >= threshold_price:
                if first_conv_ts is None:
                    first_conv_ts = ts
                    break

        reaction_delay_sec: Optional[float] = None
        if first_conv_ts is not None:
            reaction_delay_sec = max(0.0, (first_conv_ts - src_utc).total_seconds())

        formal_delay_sec: Optional[float] = None
        if formal_resolution_ts is not None:
            formal_delay_sec = max(0.0, (to_utc(formal_resolution_ts) - src_utc).total_seconds())

        return ConvergenceRecord(
            convergence_id=f"conv_{event_id}_{int(epsilon_bps)}bp",
            event_id=event_id,
            market_id=market_id,
            token_id=token_id,
            source_timestamp=src_utc,
            first_market_timestamp=first_market_ts,
            first_executable_edge_timestamp=first_edge_ts,
            first_convergence_timestamp=first_conv_ts,
            formal_resolution_timestamp=to_utc(formal_resolution_ts) if formal_resolution_ts else None,
            epsilon_bps=epsilon_bps,
            reaction_delay_sec=reaction_delay_sec,
            formal_delay_sec=formal_delay_sec,
            has_converged=(first_conv_ts is not None)
        )
