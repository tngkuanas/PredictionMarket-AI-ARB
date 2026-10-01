"""Deterministic Price & Time Synchronization and Stale-Quote Detection Layer.

Phase 10A.6e Sections 9, 10:
Provides deterministic time-alignment across asynchronous Polymarket and Kalshi quotes
within explicit analysis buckets (10ms, 50ms, 100ms, 250ms, 500ms, 1s, 5s).
Detects stale quotes and prevents temporal matching leakage.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import logging

from src.cross_venue.schema import (
    SyncQuote,
    QuoteState,
    StaleStatus,
    CategoryStatus,
)

logger = logging.getLogger(__name__)


class CrossVenueSynchronizer:
    """Synchronizes multi-venue quotes and evaluates quote freshness."""

    # Fixed analysis buckets in milliseconds (Section 9)
    ANALYSIS_WINDOWS_MS = [10, 50, 100, 250, 500, 1000, 5000]

    def __init__(
        self,
        default_stale_threshold_ms: float = 5000.0,  # Quotes older than 5s are considered stale
    ):
        self.default_stale_threshold_ms = default_stale_threshold_ms

    def evaluate_quote_state(
        self,
        quote: Optional[SyncQuote],
        evaluation_timestamp: datetime,
        stale_threshold_ms: Optional[float] = None,
    ) -> QuoteState:
        """Evaluates quote freshness, latency age, and availability."""
        thresh_ms = stale_threshold_ms if stale_threshold_ms is not None else self.default_stale_threshold_ms

        if not quote:
            return QuoteState(
                venue="UNKNOWN",
                age_ms=float("inf"),
                last_update_timestamp=evaluation_timestamp,
                update_frequency_hz=0.0,
                stale_status=StaleStatus.UNAVAILABLE,
                is_available=False,
            )

        # Use exchange_timestamp if available, otherwise local_receive_timestamp
        ref_time = quote.exchange_timestamp or quote.venue_timestamp or quote.local_receive_timestamp

        # Ensure both datetimes are timezone-aware
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        if evaluation_timestamp.tzinfo is None:
            evaluation_timestamp = evaluation_timestamp.replace(tzinfo=timezone.utc)

        age_sec = (evaluation_timestamp - ref_time).total_seconds()
        age_ms = max(0.0, age_sec * 1000.0)

        # Check orderbook depth availability
        has_depth = (len(quote.bids) > 0 or len(quote.asks) > 0 or quote.price > 0.0)
        if not has_depth:
            status = StaleStatus.UNAVAILABLE
            is_avail = False
        elif age_ms > thresh_ms:
            status = StaleStatus.STALE
            is_avail = False
        else:
            status = StaleStatus.FRESH
            is_avail = True

        return QuoteState(
            venue=quote.venue,
            age_ms=age_ms,
            last_update_timestamp=ref_time,
            update_frequency_hz=1000.0 / age_ms if age_ms > 0 else 0.0,
            stale_status=status,
            is_available=is_avail,
        )

    def synchronize_quotes(
        self,
        quote_a: Optional[SyncQuote],
        quote_b: Optional[SyncQuote],
        window_ms: int,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> Tuple[bool, CategoryStatus, QuoteState, QuoteState, str]:
        """Evaluates whether two quotes fall within the designated analysis synchronization window.
        
        Returns:
            (is_synchronized, sync_status, state_a, state_b, reason)
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)

        state_a = self.evaluate_quote_state(quote_a, now)
        state_b = self.evaluate_quote_state(quote_b, now)

        # Availability Gate
        if not state_a.is_available or not state_b.is_available:
            if state_a.stale_status == StaleStatus.UNAVAILABLE or state_b.stale_status == StaleStatus.UNAVAILABLE:
                return False, CategoryStatus.FAIL, state_a, state_b, "QUOTE_UNAVAILABLE: One or both venue books empty."
            elif state_a.stale_status == StaleStatus.STALE and state_b.stale_status == StaleStatus.STALE:
                return False, CategoryStatus.FAIL, state_a, state_b, "DUAL_STALE: Both venue quotes exceed stale threshold."
            else:
                return False, CategoryStatus.FAIL, state_a, state_b, "ONE_SIDED_STALE: One venue is stale while other updated."

        # Time difference between quotes
        time_a = state_a.last_update_timestamp
        time_b = state_b.last_update_timestamp
        time_diff_ms = abs((time_a - time_b).total_seconds() * 1000.0)

        if time_diff_ms > float(window_ms):
            reason = (
                f"DESYNCHRONIZED: Quote time delta {time_diff_ms:.1f}ms exceeds "
                f"designated analysis window {window_ms}ms."
            )
            return False, CategoryStatus.FAIL, state_a, state_b, reason

        reason = (
            f"SYNCHRONIZED: Quotes time delta {time_diff_ms:.1f}ms within "
            f"analysis window {window_ms}ms (Age A: {state_a.age_ms:.1f}ms, Age B: {state_b.age_ms:.1f}ms)."
        )
        return True, CategoryStatus.PASS, state_a, state_b, reason
