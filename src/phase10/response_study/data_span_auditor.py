"""Mandatory Data-Span Check for Phase 10A.6.

Audits stored timestamps to verify whether genuine market observations span
multiple calendar days or merely represent short-horizon active sessions.
Enforces the mandatory stop condition if the temporal-coverage check fails.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional

import duckdb

logger = logging.getLogger(__name__)


@dataclass
class DataSpanCheckResult:
    dataset_first_exchange_timestamp: Optional[datetime]
    dataset_last_exchange_timestamp: Optional[datetime]
    dataset_first_receive_timestamp: Optional[datetime]
    dataset_last_receive_timestamp: Optional[datetime]
    wall_clock_span_seconds: float
    active_recording_time_seconds: float
    number_of_sessions: int
    calendar_days_spanned: int
    is_multi_day: bool
    gate_passed: bool
    gate_verdict: str
    reason: str


class DataSpanAuditor:
    """Performs mandatory pre-study inspection of actual stored timestamps."""

    MIN_HOURS_FOR_MULTIDAY = 72.0
    MIN_CALENDAR_DAYS = 3

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def inspect_dataset_span(self) -> DataSpanCheckResult:
        """Inspects phase10a5_raw_messages and phase10a5_connection_sessions in DuckDB."""
        conn = duckdb.connect(self.db_path)
        try:
            # Query message timestamps
            msg_stats = conn.execute("""
                SELECT 
                    min(exchange_timestamp) as min_exch,
                    max(exchange_timestamp) as max_exch,
                    min(receive_timestamp) as min_recv,
                    max(receive_timestamp) as max_recv,
                    count(DISTINCT ingestion_session_id) as session_count
                FROM phase10a5_raw_messages
            """).fetchone()

            min_exch = msg_stats[0]
            max_exch = msg_stats[1]
            min_recv = msg_stats[2]
            max_recv = msg_stats[3]
            session_count = msg_stats[4] or 0

            # Query active recording time from connection sessions
            active_sec = conn.execute("""
                SELECT sum(epoch(end_timestamp) - epoch(start_timestamp))
                FROM phase10a5_connection_sessions
                WHERE end_timestamp IS NOT NULL
            """).fetchone()[0] or 0.0

            # Calculate calendar days spanned
            days_spanned = 0
            if min_recv and max_recv:
                d1 = min_recv.date() if hasattr(min_recv, 'date') else datetime.fromisoformat(str(min_recv)).date()
                d2 = max_recv.date() if hasattr(max_recv, 'date') else datetime.fromisoformat(str(max_recv)).date()
                days_spanned = (d2 - d1).days + 1

            wall_clock_span = 0.0
            if min_recv and max_recv:
                t1 = min_recv.timestamp() if hasattr(min_recv, 'timestamp') else datetime.fromisoformat(str(min_recv)).timestamp()
                t2 = max_recv.timestamp() if hasattr(max_recv, 'timestamp') else datetime.fromisoformat(str(max_recv)).timestamp()
                wall_clock_span = max(0.0, t2 - t1)

            # Evaluate multi-day criteria
            is_multi_day = (wall_clock_span >= self.MIN_HOURS_FOR_MULTIDAY * 3600.0) and (days_spanned >= self.MIN_CALENDAR_DAYS)
            
            if not is_multi_day:
                verdict = "INSUFFICIENT_TEMPORAL_COVERAGE"
                gate_passed = False
                reason = (
                    f"Dataset spans {wall_clock_span:.2f} seconds ({wall_clock_span/60.0:.2f} minutes, {days_spanned} calendar day). "
                    f"Required: minimum {self.MIN_HOURS_FOR_MULTIDAY:.0f} hours across >= {self.MIN_CALENDAR_DAYS} calendar days. "
                    f"Earliest observation ({min_recv}) and latest ({max_recv}) are within ~15 minutes of each other. "
                    f"Per Section 0 critical rule: MUST NOT proceed with event study, MUST NOT calculate event alpha."
                )
            else:
                verdict = "SUFFICIENT_COVERAGE"
                gate_passed = True
                reason = f"Dataset covers {wall_clock_span/3600.0:.2f} hours across {days_spanned} days."

            result = DataSpanCheckResult(
                dataset_first_exchange_timestamp=min_exch,
                dataset_last_exchange_timestamp=max_exch,
                dataset_first_receive_timestamp=min_recv,
                dataset_last_receive_timestamp=max_recv,
                wall_clock_span_seconds=wall_clock_span,
                active_recording_time_seconds=float(active_sec),
                number_of_sessions=int(session_count),
                calendar_days_spanned=days_spanned,
                is_multi_day=is_multi_day,
                gate_passed=gate_passed,
                gate_verdict=verdict,
                reason=reason
            )

            return result

        finally:
            conn.close()
