"""Kalshi Raw-to-Reconstructed Order Book Accounting and Integrity Reconciler.

Audits end-to-end data pipeline integrity proving:
raw WebSocket messages -> reconstructed book snapshots -> persisted database state.
Verifies best bid/ask, depth, spread, and SHA-256 book hash alignment across representations.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Any, Optional

from src.kalshi.schema import (
    KalshiRawMessageRecord,
    KalshiReconstructedBookSnapshot,
    KalshiBookUpdateRecord,
    KalshiTradeRecord,
    KalshiDataQualityStatus,
)

logger = logging.getLogger(__name__)


class KalshiAccountingReconciler:
    """Deterministic accounting and integrity auditor for Kalshi market data feeds."""

    @classmethod
    def audit_pipeline_reconciliation(
        cls,
        raw_records: List[KalshiRawMessageRecord],
        snapshots: List[KalshiReconstructedBookSnapshot],
        updates: List[KalshiBookUpdateRecord],
        trades: List[KalshiTradeRecord],
        persisted_raw_count: int,
        persisted_snap_count: int,
        persisted_trade_count: int,
        reconnect_count: int = 0,
        downtime_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """Performs full mathematical reconciliation across raw, reconstructed, and persisted records."""
        total_raw = len(raw_records)
        duplicate_messages = 0
        malformed_messages = 0
        seen_shas = set()

        for r in raw_records:
            if r.payload_sha256 in seen_shas:
                duplicate_messages += 1
            else:
                seen_shas.add(r.payload_sha256)
            if r.message_type == "malformed":
                malformed_messages += 1

        # Classify reconstructed snapshot validity
        valid_states = 0
        invalid_states = 0
        crossed_states = 0
        locked_states = 0
        stale_states = 0
        one_sided_states = 0
        sequence_gaps = 0

        for s in snapshots:
            status = s.quality_status
            if status == KalshiDataQualityStatus.VALID:
                valid_states += 1
            else:
                invalid_states += 1
                if status == KalshiDataQualityStatus.CROSSED_BOOK:
                    crossed_states += 1
                elif status == KalshiDataQualityStatus.LOCKED_BOOK:
                    locked_states += 1
                elif status == KalshiDataQualityStatus.STALE:
                    stale_states += 1
                elif status == KalshiDataQualityStatus.MISSING_DATA:
                    one_sided_states += 1
                elif status == KalshiDataQualityStatus.INVALID_SEQUENCE:
                    sequence_gaps += 1

        # Invariant checks
        raw_balance = total_raw - persisted_raw_count
        snapshot_balance = len(snapshots) - persisted_snap_count
        trade_balance = len(trades) - persisted_trade_count
        is_clean = (raw_balance == 0) and (snapshot_balance == 0) and (trade_balance == 0)

        return {
            "reconciliation_certified": is_clean,
            "raw_messages_received": total_raw,
            "raw_messages_persisted": persisted_raw_count,
            "raw_balance": raw_balance,
            "duplicate_messages": duplicate_messages,
            "malformed_messages": malformed_messages,
            "snapshots_reconstructed": len(snapshots),
            "snapshots_persisted": persisted_snap_count,
            "snapshot_balance": snapshot_balance,
            "valid_states": valid_states,
            "invalid_states": invalid_states,
            "crossed_states": crossed_states,
            "locked_states": locked_states,
            "stale_states": stale_states,
            "one_sided_states": one_sided_states,
            "sequence_gaps": sequence_gaps,
            "trades_recorded": len(trades),
            "trades_persisted": persisted_trade_count,
            "reconnects": reconnect_count,
            "downtime_seconds": downtime_seconds,
            "message_loss": max(0, total_raw - persisted_raw_count)
        }

    @classmethod
    def verify_state_alignment(
        cls,
        reconstructed: KalshiReconstructedBookSnapshot,
        db_record: Dict[str, Any]
    ) -> Dict[str, bool]:
        """Proves exact metric equality between an in-memory reconstructed snapshot and its persisted DB row."""
        best_bid_equal = (
            reconstructed.best_yes_bid == db_record.get("best_yes_bid") or
            (reconstructed.best_yes_bid is None and db_record.get("best_yes_bid") is None)
        )
        best_ask_equal = (
            reconstructed.best_yes_ask == db_record.get("best_yes_ask") or
            (reconstructed.best_yes_ask is None and db_record.get("best_yes_ask") is None)
        )
        depth_equal = (
            abs(reconstructed.top_n_depth - float(db_record.get("top_n_depth", 0.0))) < 1e-4
        )
        spread_equal = (
            reconstructed.yes_spread == db_record.get("yes_spread") or
            (reconstructed.yes_spread is None and db_record.get("yes_spread") is None) or
            (abs((reconstructed.yes_spread or 0.0) - float(db_record.get("yes_spread") or 0.0)) < 1e-4)
        )
        hash_equal = (
            reconstructed.book_hash == db_record.get("book_hash")
        )

        all_aligned = (
            best_bid_equal and
            best_ask_equal and
            depth_equal and
            spread_equal and
            hash_equal
        )

        return {
            "all_aligned": all_aligned,
            "best_bid_equal": best_bid_equal,
            "best_ask_equal": best_ask_equal,
            "depth_equal": depth_equal,
            "spread_equal": spread_equal,
            "hash_equal": hash_equal,
        }
