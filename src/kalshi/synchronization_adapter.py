"""Cross-Venue Timestamp Normalizer and Synchronization Adapter for Kalshi.

Adapts reconstructed Kalshi order book snapshots and trades into canonical
SyncQuote structures directly consumable by Phase 10A.6E synchronizer.py.
Preserves exchange timestamps and quantifies clock skew against local monotonic clocks.
"""
from datetime import datetime, timezone
import logging
from typing import Optional, List

from src.kalshi.schema import (
    KalshiReconstructedBookSnapshot,
    KalshiNormalizedTimestamp,
)
from src.cross_venue.schema import SyncQuote

logger = logging.getLogger(__name__)


class KalshiSynchronizationAdapter:
    """Adapts Kalshi book snapshots into Phase 10A.6E cross-venue synchronized observations."""

    @staticmethod
    def normalize_timestamp(
        receive_ts: datetime,
        exchange_ts: Optional[datetime] = None
    ) -> KalshiNormalizedTimestamp:
        """Computes clock skew estimate and normalizes timestamp metadata."""
        if exchange_ts:
            r_ts = receive_ts if receive_ts.tzinfo else receive_ts.replace(tzinfo=timezone.utc)
            e_ts = exchange_ts if exchange_ts.tzinfo else exchange_ts.replace(tzinfo=timezone.utc)
            skew_ms = (r_ts - e_ts).total_seconds() * 1000.0
            source = "exchange"
            precision = "microsecond" if exchange_ts.microsecond > 0 else "millisecond"
        else:
            skew_ms = 0.0
            source = "local_receipt"
            precision = "microsecond"

        return KalshiNormalizedTimestamp(
            exchange_timestamp=exchange_ts,
            receive_timestamp=receive_ts,
            timestamp_source=source,
            timestamp_precision=precision,
            clock_skew_estimate_ms=round(skew_ms, 2)
        )

    @classmethod
    def to_sync_quotes(
        cls,
        snapshot: KalshiReconstructedBookSnapshot
    ) -> List[SyncQuote]:
        """Converts a Kalshi reconstructed snapshot into Phase 10A.6E SyncQuote records."""
        quotes: List[SyncQuote] = []

        # Formatted bids and asks lists: [{'price': p, 'size': q}]
        formatted_bids = [{"price": b["price"], "size": b["quantity"]} for b in snapshot.yes_bids]
        formatted_asks = [{"price": a["price"], "size": a["quantity"]} for a in snapshot.yes_asks]

        seq_str = str(snapshot.sequence) if snapshot.sequence is not None else None

        # YES Bid quote
        if snapshot.best_yes_bid is not None and snapshot.yes_bid_depth > 0:
            quotes.append(SyncQuote(
                venue="kalshi",
                market_id=snapshot.market_id,
                contract_id=snapshot.market_id,
                side="bid",
                outcome="YES",
                price=snapshot.best_yes_bid,
                size=snapshot.yes_bid_depth,
                bids=formatted_bids,
                asks=formatted_asks,
                venue_timestamp=snapshot.exchange_timestamp,
                exchange_timestamp=snapshot.exchange_timestamp,
                local_receive_timestamp=snapshot.receive_timestamp,
                sequence_frame_id=seq_str
            ))

        # YES Ask quote
        if snapshot.best_yes_ask is not None and snapshot.yes_ask_depth > 0:
            quotes.append(SyncQuote(
                venue="kalshi",
                market_id=snapshot.market_id,
                contract_id=snapshot.market_id,
                side="ask",
                outcome="YES",
                price=snapshot.best_yes_ask,
                size=snapshot.yes_ask_depth,
                bids=formatted_bids,
                asks=formatted_asks,
                venue_timestamp=snapshot.exchange_timestamp,
                exchange_timestamp=snapshot.exchange_timestamp,
                local_receive_timestamp=snapshot.receive_timestamp,
                sequence_frame_id=seq_str
            ))

        return quotes
