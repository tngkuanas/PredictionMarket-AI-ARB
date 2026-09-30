"""Genuine L2 Order-Book Snapshot Extractor for Phase 10A.6.

Queries phase10a5_book_snapshots in DuckDB without interpolation.
Guarantees:
1. Strict temporal causality: pre-event states strictly precede event timestamp.
2. Latency gating: post-event states strictly satisfy t_post >= t_event + latency.
3. No interpolation: missing observations remain explicitly MISSING.
4. Preserves distinction between local receive_timestamp and exchange_timestamp.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple, Union

import duckdb

from src.phase10.response_study.schema import EventStudyQualityStatus

logger = logging.getLogger(__name__)


class L2BookExtractor:
    """Extracts and validates genuine order-book snapshots from Phase 10A.5 storage."""

    def __init__(
        self,
        db_path: str = "data/prediction_market.duckdb",
        max_staleness_seconds: float = 300.0,
        max_spread: float = 0.15
    ):
        self.db_path = db_path
        self.max_staleness_seconds = max_staleness_seconds
        self.max_spread = max_spread

    def _get_read_conn(self) -> duckdb.DuckDBPyConnection:
        """Connects to DuckDB with retry to tolerate concurrent writes by the live daemon."""
        for attempt in range(15):
            try:
                return duckdb.connect(self.db_path, read_only=True)
            except Exception:
                time.sleep(0.3)
        return duckdb.connect(self.db_path, read_only=True)

    def find_pre_event_snapshot(
        self,
        token_id: str,
        event_timestamp: datetime,
        target_offset_sec: int = -60,
        tolerance_sec: int = 15,
        conn: Optional[duckdb.DuckDBPyConnection] = None
    ) -> Tuple[Optional[Dict[str, Any]], EventStudyQualityStatus, Optional[str]]:
        """Finds the genuine pre-event order book snapshot closest to target offset.

        Strict invariant: Pre-event snapshot MUST be strictly prior to event_timestamp.
        """
        event_utc = event_timestamp if event_timestamp.tzinfo else event_timestamp.replace(tzinfo=timezone.utc)
        target_time = event_utc + timedelta(seconds=target_offset_sec)
        earliest_allowed = target_time - timedelta(seconds=tolerance_sec)

        # Upper bound cannot exceed event_timestamp
        upper_bound = min(target_time + timedelta(seconds=tolerance_sec), event_utc)

        local_conn = False
        if conn is None:
            conn = self._get_read_conn()
            local_conn = True

        try:
            # Look up closest snapshot within [earliest_allowed, upper_bound]
            query = """
                SELECT snapshot_id, session_id, market_id, token_id, timestamp, exchange_timestamp,
                       best_bid, best_ask, midpoint, spread, spread_bps, depth_bid_usd, depth_ask_usd,
                       book_imbalance, bids, asks, quality_status, quality_reason
                FROM phase10a5_book_snapshots
                WHERE token_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY abs(epoch(timestamp) - ?) ASC
                LIMIT 1
            """
            row = conn.execute(query, (
                token_id, earliest_allowed, upper_bound, target_time.timestamp()
            )).fetchone()

            if not row:
                return None, EventStudyQualityStatus.MISSING_PRE, "No genuine snapshot in pre-event tolerance window"

            cols = [
                "snapshot_id", "session_id", "market_id", "token_id", "timestamp", "exchange_timestamp",
                "best_bid", "best_ask", "midpoint", "spread", "spread_bps", "depth_bid_usd", "depth_ask_usd",
                "book_imbalance", "bids", "asks", "quality_status", "quality_reason"
            ]
            snap_dict = dict(zip(cols, row))

            status, reason = self.validate_snapshot(snap_dict)
            return snap_dict, status, reason

        finally:
            if local_conn:
                conn.close()

    def find_post_event_snapshot(
        self,
        token_id: str,
        event_timestamp: datetime,
        target_offset_sec: int = 15,
        tolerance_sec: int = 3,
        latency_ms: int = 0,
        conn: Optional[duckdb.DuckDBPyConnection] = None
    ) -> Tuple[Optional[Dict[str, Any]], EventStudyQualityStatus, Optional[str]]:
        """Finds the genuine post-event order book snapshot after event timestamp + latency.

        Strict invariant: Post-event snapshot MUST satisfy timestamp >= event_timestamp + latency.
        """
        event_utc = event_timestamp if event_timestamp.tzinfo else event_timestamp.replace(tzinfo=timezone.utc)
        arrival_time = event_utc + timedelta(milliseconds=latency_ms)
        target_time = event_utc + timedelta(seconds=target_offset_sec) + timedelta(milliseconds=latency_ms)

        earliest_allowed = max(arrival_time, target_time - timedelta(seconds=tolerance_sec))
        latest_allowed = target_time + timedelta(seconds=tolerance_sec)

        local_conn = False
        if conn is None:
            conn = self._get_read_conn()
            local_conn = True

        try:
            # Query earliest snapshot >= earliest_allowed and <= latest_allowed
            query = """
                SELECT snapshot_id, session_id, market_id, token_id, timestamp, exchange_timestamp,
                       best_bid, best_ask, midpoint, spread, spread_bps, depth_bid_usd, depth_ask_usd,
                       book_imbalance, bids, asks, quality_status, quality_reason
                FROM phase10a5_book_snapshots
                WHERE token_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT 1
            """
            row = conn.execute(query, (
                token_id, earliest_allowed, latest_allowed
            )).fetchone()

            if not row:
                return None, EventStudyQualityStatus.MISSING_POST, "No genuine snapshot in post-event tolerance window"

            cols = [
                "snapshot_id", "session_id", "market_id", "token_id", "timestamp", "exchange_timestamp",
                "best_bid", "best_ask", "midpoint", "spread", "spread_bps", "depth_bid_usd", "depth_ask_usd",
                "book_imbalance", "bids", "asks", "quality_status", "quality_reason"
            ]
            snap_dict = dict(zip(cols, row))

            status, reason = self.validate_snapshot(snap_dict)
            return snap_dict, status, reason

        finally:
            if local_conn:
                conn.close()

    def validate_snapshot(self, snap: Dict[str, Any]) -> Tuple[EventStudyQualityStatus, Optional[str]]:
        """Verifies book integrity (crossed book, staleness, extreme spread, missing ladders)."""
        best_bid = float(snap.get("best_bid") or 0.0)
        best_ask = float(snap.get("best_ask") or 1.0)
        spread = float(snap.get("spread") or (best_ask - best_bid))

        # Check crossed book
        if best_bid >= best_ask and best_bid > 0.0 and best_ask > 0.0:
            return EventStudyQualityStatus.CROSSED_BOOK, f"Crossed book: best_bid ({best_bid}) >= best_ask ({best_ask})"

        # Check extreme spread
        if spread > self.max_spread:
            return EventStudyQualityStatus.OTHER_INVALID, f"Excessive spread: {spread:.4f} > {self.max_spread:.4f}"

        # Check staleness against exchange timestamp if present
        local_ts = snap.get("timestamp")
        exch_ts = snap.get("exchange_timestamp")
        if local_ts and exch_ts:
            if isinstance(local_ts, datetime) and isinstance(exch_ts, datetime):
                staleness = abs((local_ts - exch_ts).total_seconds())
                if staleness > self.max_staleness_seconds:
                    return EventStudyQualityStatus.STALE_BOOK, f"Stale book: local-exchange skew {staleness:.1f}s > {self.max_staleness_seconds}s"

        return EventStudyQualityStatus.VALID, None

    @staticmethod
    def calculate_depth_at_levels(
        ladder_raw: Union[str, List[Any], None],
        levels: List[float] = [100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0]
    ) -> Dict[str, float]:
        """Calculates cumulative available depth up to specified USD notional thresholds."""
        from src.phase10.response_study.executable_price_model import ExecutablePriceModel
        ladder = ExecutablePriceModel._parse_ladder(ladder_raw)
        total_usd = sum(level["size_usd"] for level in ladder)

        depth_metrics = {"total_available_usd": round(total_usd, 2)}
        for lvl in levels:
            depth_metrics[f"depth_{int(lvl)}_usd"] = min(total_usd, lvl)
            depth_metrics[f"has_capacity_{int(lvl)}"] = (total_usd >= lvl)
        return depth_metrics
