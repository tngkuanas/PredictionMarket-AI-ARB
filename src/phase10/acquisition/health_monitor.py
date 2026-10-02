"""Long-Run Health Monitor for Phase 10A.5c Continuous Data Acquisition.

Monitors real-time and longitudinal health metrics required by Phase 10A.5c Section 8:
- messages/hour
- books/hour
- trades/hour
- active markets & tokens
- disconnects & reconnects
- cumulative downtime
- sequence gaps & malformed messages
- one-sided and crossed book states
- clock skew percentiles (mean, median, P95, P99, negative skews)
- storage disk usage
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
import time
import random
import duckdb

from src.phase10.acquisition.schema import (
    HealthHeartbeatRecord,
    ReconstructedBookSnapshot,
    DataQualityStatus,
)
from src.phase10.acquisition.db_store import Phase10A5DbStore

logger = logging.getLogger(__name__)


class LongRunHealthMonitor:
    """Continuously aggregates system health telemetry and persists heartbeats."""

    def __init__(
        self,
        db_path: str = "data/prediction_market.duckdb",
        raw_storage_dir: str = "data/phase10a5_raw",
        status_json_path: str = "data/phase10a5c_health_monitor.json",
    ):
        self.db_path = db_path
        self.raw_storage_dir = Path(raw_storage_dir)
        self.status_json_path = Path(status_json_path)
        self.db_store = Phase10A5DbStore(db_path=db_path)

        self.start_time: Optional[datetime] = None
        self.total_messages = 0
        self.total_snapshots = 0
        self.total_trades = 0
        self.total_disconnects = 0
        self.total_reconnects = 0
        self.total_downtime_seconds = 0.0
        self.total_sequence_gaps = 0
        self.total_malformed_messages = 0
        self.total_one_sided_books = 0
        self.total_crossed_books = 0

        self.clock_skews_ms: List[float] = []
        self.current_markets_count = 0
        self.current_tokens_count = 0
        self._heartbeat_counter = 0

    def start(self) -> None:
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)

    def record_skew(self, skew_ms: float) -> None:
        self.clock_skews_ms.append(skew_ms)
        # Keep a rolling buffer of 100,000 skews to manage memory
        if len(self.clock_skews_ms) > 100_000:
            self.clock_skews_ms = self.clock_skews_ms[-50_000:]

    def record_snapshot(self, snap: ReconstructedBookSnapshot) -> None:
        self.total_snapshots += 1
        if snap.quality_status == DataQualityStatus.CROSSED_BOOK:
            self.total_crossed_books += 1
        elif snap.quality_status == DataQualityStatus.MISSING_DATA:
            self.total_one_sided_books += 1

    def record_connection_event(self, event_type: str, downtime_sec: float = 0.0) -> None:
        if event_type == "DISCONNECT":
            self.total_disconnects += 1
        elif event_type == "RECONNECT":
            self.total_reconnects += 1
            self.total_downtime_seconds += max(0.0, downtime_sec)

    def calculate_disk_storage_bytes(self) -> int:
        total_bytes = 0
        if self.raw_storage_dir.exists():
            for p in self.raw_storage_dir.rglob("*"):
                if p.is_file():
                    total_bytes += p.stat().st_size
        duck_p = Path(self.db_path)
        if duck_p.exists():
            total_bytes += duck_p.stat().st_size
        return total_bytes

    def generate_heartbeat(self, session_id: str) -> HealthHeartbeatRecord:
        now = datetime.now(timezone.utc)
        self.start()
        elapsed = max(0.1, (now - self.start_time).total_seconds())
        elapsed_hours = elapsed / 3600.0

        msgs_per_hr = self.total_messages / max(0.001, elapsed_hours)
        books_per_hr = self.total_snapshots / max(0.001, elapsed_hours)
        trades_per_hr = self.total_trades / max(0.001, elapsed_hours)

        skews = np.array(self.clock_skews_ms) if self.clock_skews_ms else np.array([0.0])
        mean_skew = float(np.mean(skews)) if len(skews) > 0 else 0.0
        median_skew = float(np.median(skews)) if len(skews) > 0 else 0.0
        p95_skew = float(np.percentile(skews, 95)) if len(skews) > 0 else 0.0
        p99_skew = float(np.percentile(skews, 99)) if len(skews) > 0 else 0.0
        negative_skews = int(np.sum(skews < 0))

        disk_bytes = self.calculate_disk_storage_bytes()
        self._heartbeat_counter += 1

        hb = HealthHeartbeatRecord(
            heartbeat_id=f"hb_{session_id}_{self._heartbeat_counter}_{int(now.timestamp())}",
            timestamp=now,
            session_id=session_id,
            elapsed_seconds=elapsed,
            messages_per_hour=round(msgs_per_hr, 2),
            books_per_hour=round(books_per_hr, 2),
            trades_per_hour=round(trades_per_hr, 2),
            active_markets=self.current_markets_count,
            active_tokens=self.current_tokens_count,
            disconnects=self.total_disconnects,
            reconnects=self.total_reconnects,
            downtime_seconds=round(self.total_downtime_seconds, 2),
            sequence_gaps=self.total_sequence_gaps,
            malformed_messages=self.total_malformed_messages,
            one_sided_books=self.total_one_sided_books,
            crossed_books=self.total_crossed_books,
            skew_mean_ms=round(mean_skew, 2),
            skew_median_ms=round(median_skew, 2),
            skew_p95_ms=round(p95_skew, 2),
            skew_p99_ms=round(p99_skew, 2),
            negative_skew_count=negative_skews,
            disk_storage_bytes=disk_bytes,
        )

        # Persist heartbeat to DB with retry and backoff
        max_retries = 10
        for attempt in range(max_retries):
            try:
                conn = duckdb.connect(self.db_path)
                try:
                    self.db_store.persist_health_heartbeat(conn, hb)
                    break
                finally:
                    conn.close()
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning(f"Could not persist health heartbeat to DuckDB after {max_retries} attempts: {e}")
                else:
                    time.sleep(min(1.0, 0.05 * (1.5 ** attempt)) + random.uniform(0.01, 0.05))

        # Persist status JSON file for external observability
        try:
            self.status_json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.status_json_path, "w", encoding="utf-8") as f:
                json.dump(hb.__dict__, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Could not write status JSON: {e}")

        return hb
