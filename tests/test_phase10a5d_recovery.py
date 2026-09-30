"""Tests for Phase 10A.5d Sequence Gap Diagnosis, Order-Book Recovery, and Reconnect Logging."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import duckdb
import pytest

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    DataQualityStatus,
    ReconnectEventRecord,
    ConnectionSessionRecord,
)
from src.phase10.acquisition.order_book_reconstructor import OrderBookReconstructor
from src.phase10.acquisition.multi_session_recorder import MultiSessionContinuousRecorder
from src.phase10.acquisition.db_store import Phase10A5DbStore


def test_sequence_continuity_no_false_positives(tmp_path):
    """Verifies that sequential frames and multi-record batches produce zero false positive gaps."""
    recorder = MultiSessionContinuousRecorder(
        db_path=str(tmp_path / "test.duckdb"),
        raw_storage_dir=str(tmp_path / "raw")
    )

    t0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)

    # Simulate frame 1 with 3 batch items (same message_seq=1)
    rec1a = RawMessageRecord(
        message_id="msg_1a", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_A", message_type="book",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h1", raw_file_path="/tmp/f", message_seq=1
    )
    rec1b = RawMessageRecord(
        message_id="msg_1b", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_B", message_type="book",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h2", raw_file_path="/tmp/f", message_seq=1
    )
    rec1c = RawMessageRecord(
        message_id="msg_1c", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_A", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h3", raw_file_path="/tmp/f", message_seq=1
    )

    # Frame 2: Token B
    rec2 = RawMessageRecord(
        message_id="msg_2", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_B", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h4", raw_file_path="/tmp/f", message_seq=2
    )

    # Frame 3: Token A
    rec3 = RawMessageRecord(
        message_id="msg_3", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_A", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h5", raw_file_path="/tmp/f", message_seq=3
    )

    for r in [rec1a, rec1b, rec1c, rec2, rec3]:
        gap = recorder.check_sequence_gap(r)
        assert gap is None, f"Unexpected sequence gap flagged: {gap}"

    assert recorder.total_sequence_gaps == 0


def test_genuine_sequence_gap_detection(tmp_path):
    """Verifies that an actual skipped frame in the stream is properly detected as a gap."""
    recorder = MultiSessionContinuousRecorder(
        db_path=str(tmp_path / "test.duckdb"),
        raw_storage_dir=str(tmp_path / "raw")
    )

    t0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)

    # Frame 1
    r1 = RawMessageRecord(
        message_id="msg_1", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_A", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h1", raw_file_path="/tmp/f", message_seq=1
    )
    # Frame 4 (frames 2 and 3 dropped)
    r4 = RawMessageRecord(
        message_id="msg_4", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_A", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json="{}", sha256_hash="h4", raw_file_path="/tmp/f", message_seq=4
    )

    assert recorder.check_sequence_gap(r1) is None
    gap = recorder.check_sequence_gap(r4)
    assert gap is not None
    assert gap.status == DataQualityStatus.INVALID_SEQUENCE
    assert "dropped 2" in gap.details
    assert recorder.total_sequence_gaps == 1


def test_order_book_anti_stale_delta_gating():
    """Verifies Phase 10A.5d Section 8: deltas are never applied to uninitialized or disconnected stale books."""
    reconstructor = OrderBookReconstructor()

    t0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Initialize book with initial snapshot
    snap_raw = RawMessageRecord(
        message_id="snap_1", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_1", message_type="book",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json=json.dumps({
            "asset_id": "tok_1",
            "market": "mkt_1",
            "bids": [{"price": "0.50", "size": "100"}],
            "asks": [{"price": "0.52", "size": "100"}]
        }),
        sha256_hash="h_snap", raw_file_path="/tmp/f", message_seq=1
    )
    upds1, snap1 = reconstructor.process_raw_record(snap_raw)
    assert snap1 is not None
    assert snap1.best_bid == 0.50
    assert snap1.best_ask == 0.52
    assert reconstructor._books["tok_1"]["initialized"] is True

    # 2. Apply a valid delta while initialized
    delta_raw = RawMessageRecord(
        message_id="delta_1", ingestion_session_id="sess_1", venue="polymarket",
        market_id="mkt_1", token_id="tok_1", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json=json.dumps({
            "asset_id": "tok_1",
            "market": "mkt_1",
            "price_changes": [{"side": "BUY", "price": "0.51", "size": "200"}]
        }),
        sha256_hash="h_delta1", raw_file_path="/tmp/f", message_seq=2
    )
    upds2, snap2 = reconstructor.process_raw_record(delta_raw)
    assert snap2 is not None
    assert snap2.best_bid == 0.51

    # 3. Disconnect happens -> call mark_disconnected()
    reconstructor.mark_disconnected()
    assert reconstructor._books["tok_1"]["initialized"] is False

    # 4. An incremental delta arrives BEFORE fresh snapshot -> MUST BE GATED / DROPPED
    stale_delta_raw = RawMessageRecord(
        message_id="stale_delta", ingestion_session_id="sess_2", venue="polymarket",
        market_id="mkt_1", token_id="tok_1", message_type="price_change",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json=json.dumps({
            "asset_id": "tok_1",
            "market": "mkt_1",
            "price_changes": [{"side": "BUY", "price": "0.55", "size": "500"}]
        }),
        sha256_hash="h_stale", raw_file_path="/tmp/f", message_seq=1
    )
    upds3, snap3 = reconstructor.process_raw_record(stale_delta_raw)
    assert upds3 == []
    assert snap3 is None
    # Verify book was NOT updated to 0.55
    assert reconstructor._books["tok_1"]["bids"].get(0.55) is None

    # 5. Fresh snapshot arrives after reconnection -> reinitializes book
    fresh_snap_raw = RawMessageRecord(
        message_id="fresh_snap", ingestion_session_id="sess_2", venue="polymarket",
        market_id="mkt_1", token_id="tok_1", message_type="book",
        receive_timestamp=t0, exchange_timestamp=t0,
        raw_message_json=json.dumps({
            "asset_id": "tok_1",
            "market": "mkt_1",
            "bids": [{"price": "0.48", "size": "300"}],
            "asks": [{"price": "0.50", "size": "300"}]
        }),
        sha256_hash="h_fresh", raw_file_path="/tmp/f", message_seq=2
    )
    upds4, snap4 = reconstructor.process_raw_record(fresh_snap_raw)
    assert snap4 is not None
    assert snap4.best_bid == 0.48
    assert snap4.best_ask == 0.50
    assert reconstructor._books["tok_1"]["initialized"] is True


def test_reconnect_event_schema_and_db_store(tmp_path):
    """Verifies that ReconnectEventRecord can be created and persisted to phase10a5_reconnect_events table."""
    db_file = tmp_path / "rec_test.duckdb"
    store = Phase10A5DbStore(db_path=str(db_file))
    conn = duckdb.connect(str(db_file))
    try:
        store.init_schema(conn)

        event = ReconnectEventRecord(
            reconnect_id="rec_test_1",
            session_id="sess_test_1",
            disconnect_timestamp=datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc),
            reconnect_attempt=1,
            reconnect_timestamp=datetime(2026, 9, 30, 12, 0, 2, tzinfo=timezone.utc),
            reconnect_reason="ConnectionResetError",
            reconnect_latency_seconds=2.15,
            subscription_success=True,
            snapshot_success=True
        )
        persisted = store.persist_reconnect_events(conn, [event])
        assert persisted == 1

        rows = conn.execute("SELECT reconnect_id, reconnect_attempt, reconnect_reason FROM phase10a5_reconnect_events").fetchall()
        assert len(rows) == 1
        assert rows[0] == ("rec_test_1", 1, "ConnectionResetError")
    finally:
        conn.close()
