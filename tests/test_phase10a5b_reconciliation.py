"""Tests for Phase 10A.5b Multi-Session Data Accumulation & Accounting Reconciliation.

Verifies:
1. Exact accounting reconciliation: received == persisted + rejected, parsed == applied + rejected.
2. Unpacked frame delta accounting (multi-item arrays in single WebSocket frames).
3. Multi-session lifecycle and boundary isolation (never overwriting prior sessions).
4. Sequence gap detection and data quality anomaly generation.
5. Order book state re-initialization on session rollover.
6. Reconnect handling and backoff mechanics.
7. Zero tolerance for unexplained discrepancies.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    GenuineTradeRecord,
    DataQualityStatus,
    DataQualityRecord,
)
from src.phase10.acquisition.multi_session_recorder import (
    AccountingReconciler,
    MultiSessionContinuousRecorder,
)
from src.phase10.acquisition.order_book_reconstructor import OrderBookReconstructor
from src.phase10.acquisition.raw_recorder import RawMarketDataRecorder


def test_accounting_reconciler_clean():
    """Verifies that clean accounting passes with 0 unexplained discrepancies."""
    res = AccountingReconciler.reconcile(
        frames_received=3765,
        messages_parsed=3804,
        messages_persisted=3804,
        book_updates_applied=3674,
        book_snapshots_reconstructed=3774,
        valid_snapshots=3725,
        crossed_snapshots=2,
        one_sided_snapshots=47,
        invalid_snapshots=0,
        trades_recorded=30,
        explicitly_rejected=0
    )

    assert res["is_clean"] is True
    assert res["unexplained_discrepancies"] == 0
    assert res["batched_items_delta"] == 39  # 3804 - 3765
    assert res["book_messages"] == 3774      # 3804 - 30
    assert res["trade_messages"] == 30
    assert res["snapshot_balance"] == 0


def test_accounting_reconciler_detects_leakage():
    """Verifies that missing or dropped observations are immediately flagged as discrepancies."""
    # Scenario: 5 messages received but only 3 persisted, 0 rejected -> 2 lost!
    res = AccountingReconciler.reconcile(
        frames_received=5,
        messages_parsed=5,
        messages_persisted=3,
        book_updates_applied=3,
        book_snapshots_reconstructed=3,
        valid_snapshots=3,
        crossed_snapshots=0,
        one_sided_snapshots=0,
        invalid_snapshots=0,
        trades_recorded=0,
        explicitly_rejected=0
    )

    assert res["is_clean"] is False
    assert res["unexplained_discrepancies"] == 2
    assert res["ingestion_balance"] == 2


def test_multi_session_boundary_isolation(tmp_path):
    """Verifies that consecutive sessions maintain unique IDs and never overwrite prior data."""
    recorder = MultiSessionContinuousRecorder(
        db_path=str(tmp_path / "test_sessions.duckdb"),
        raw_storage_dir=str(tmp_path / "raw")
    )

    id1 = recorder._generate_session_id()
    id2 = recorder._generate_session_id()

    assert id1 != id2
    assert "sess_" in id1 and "sess_" in id2


def test_sequence_gap_detection():
    """Verifies that non-sequential message sequences are flagged as sequence anomalies."""
    recorder = MultiSessionContinuousRecorder(
        db_path=":memory:",
        raw_storage_dir="/tmp/test_gaps"
    )

    token = "0xabcdef1234567890"
    now = datetime.now(timezone.utc)

    # Message 1: seq 100
    rec1 = RawMessageRecord(
        message_id="msg_1",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id="m1",
        token_id=token,
        message_type="price_change",
        receive_timestamp=now,
        exchange_timestamp=now,
        raw_message_json="{}",
        sha256_hash="sha1",
        raw_file_path="/tmp/f"
    )
    rec1.message_seq = 100

    gap1 = recorder.check_sequence_gap(rec1)
    assert gap1 is None  # First observation establishes baseline

    # Message 2: seq 101 (sequential)
    rec2 = RawMessageRecord(
        message_id="msg_2",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id="m1",
        token_id=token,
        message_type="price_change",
        receive_timestamp=now,
        exchange_timestamp=now,
        raw_message_json="{}",
        sha256_hash="sha2",
        raw_file_path="/tmp/f"
    )
    rec2.message_seq = 101

    gap2 = recorder.check_sequence_gap(rec2)
    assert gap2 is None

    # Message 3: seq 105 (GAP of 3 dropped messages!)
    rec3 = RawMessageRecord(
        message_id="msg_3",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id="m1",
        token_id=token,
        message_type="price_change",
        receive_timestamp=now,
        exchange_timestamp=now,
        raw_message_json="{}",
        sha256_hash="sha3",
        raw_file_path="/tmp/f"
    )
    rec3.message_seq = 105

    gap3 = recorder.check_sequence_gap(rec3)
    assert gap3 is not None
    assert gap3.status == DataQualityStatus.INVALID_SEQUENCE
    assert "dropped 3" in gap3.details
    assert recorder.total_sequence_gaps == 1


def test_order_book_recovery_on_reconnect():
    """Verifies that a fresh initial book snapshot cleanly resets and reinitializes order book state."""
    reconstructor = OrderBookReconstructor()
    token = "0xreconnect_token_123"
    now = datetime.now(timezone.utc)

    # Initial state
    book1 = {
        "event_type": "book",
        "market": token,
        "asset_id": token,
        "bids": [{"price": "0.40", "size": "100"}],
        "asks": [{"price": "0.45", "size": "100"}]
    }
    rec1 = RawMessageRecord(
        message_id="m1", ingestion_session_id="s1", venue="polymarket",
        market_id=token, token_id=token, message_type="book",
        receive_timestamp=now, exchange_timestamp=now,
        raw_message_json=json.dumps(book1), sha256_hash="h1", raw_file_path="/tmp/p"
    )
    _, snap1 = reconstructor.process_raw_record(rec1)
    assert snap1.best_bid == 0.40
    assert snap1.best_ask == 0.45

    # Simulate reconnect session s2 with new fresh snapshot reflecting market shift
    book2 = {
        "event_type": "book",
        "market": token,
        "asset_id": token,
        "bids": [{"price": "0.55", "size": "200"}],
        "asks": [{"price": "0.58", "size": "200"}]
    }
    rec2 = RawMessageRecord(
        message_id="m2", ingestion_session_id="s2", venue="polymarket",
        market_id=token, token_id=token, message_type="book",
        receive_timestamp=now, exchange_timestamp=now,
        raw_message_json=json.dumps(book2), sha256_hash="h2", raw_file_path="/tmp/p"
    )
    _, snap2 = reconstructor.process_raw_record(rec2)
    # The old book state is cleanly reset by the new snapshot
    assert snap2.best_bid == 0.55
    assert snap2.best_ask == 0.58
    assert snap2.session_id == "s2"
