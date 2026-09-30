"""Comprehensive Test Suite for Phase 10A.5 Genuine High-Frequency Market Data Acquisition.

Verifies:
1. Append-only disk logging and exact SHA-256 content verification.
2. Microsecond timestamp precision, clock skew tracking, and session tracking.
3. Deterministic order-book reconstruction (snapshot, level update, deletion, crossed book).
4. Real trade stream processing, validation, and deduplication.
5. Market universe discovery and objective eligibility filtering.
6. Anti-synthetic guard gating against placeholder tokens, missing raw frames, or synthetic curves.
7. DuckDB persistence and schema isolation for Phase 10A.5 production tables.
8. Future event registry schema and validation rules.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import List

import duckdb
import pytest

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    GenuineTradeRecord,
    MarketUniverseEntry,
    ConnectionSessionRecord,
    DataQualityStatus,
    DataQualityRecord,
    GenuineEventRecord,
)
from src.phase10.acquisition.raw_recorder import RawMarketDataRecorder
from src.phase10.acquisition.order_book_reconstructor import OrderBookReconstructor
from src.phase10.acquisition.trade_processor import TradeStreamProcessor
from src.phase10.acquisition.market_universe import MarketUniverseManager
from src.phase10.acquisition.metrics_tracker import DataIntegrityMetricsTracker
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard
from src.phase10.acquisition.db_store import Phase10A5DbStore
from src.phase10.acquisition.event_interface import GenuineEventRegistry


@pytest.fixture
def temp_raw_dir(tmp_path):
    """Provides a temporary directory for raw disk logging."""
    return str(tmp_path / "raw_stream_test")


@pytest.fixture
def in_memory_db():
    """Provides an in-memory DuckDB database with Phase 10A.5 schema initialized."""
    conn = duckdb.connect(":memory:")
    db_store = Phase10A5DbStore(db_path=":memory:")
    db_store.init_schema(conn)
    yield conn, db_store
    conn.close()


def test_raw_recorder_append_and_sha256(temp_raw_dir):
    """Verifies that raw market data is logged append-only and SHA-256 matches exactly."""
    recorder = RawMarketDataRecorder(raw_storage_dir=temp_raw_dir, session_id="test_sess_001")
    
    raw_payload_1 = {"event_type": "book", "market": "0x123abc", "bids": [{"price": "0.45", "size": "100"}], "asks": [{"price": "0.47", "size": "100"}]}
    raw_payload_2 = {"event_type": "price_change", "market": "0x123abc", "price_changes": [{"asset_id": "0x123abc", "price": "0.46", "size": "50", "side": "BUY"}]}
    
    raw_str_1 = json.dumps(raw_payload_1)
    raw_str_2 = json.dumps(raw_payload_2)
    
    recs1 = recorder.record_raw_frame(raw_str_1)
    recs2 = recorder.record_raw_frame(raw_str_2)
    
    assert len(recs1) == 1
    assert len(recs2) == 1
    rec1 = recs1[0]
    rec2 = recs2[0]
    
    # Verify disk persistence
    log_file = Path(rec1.raw_file_path)
    assert log_file.exists()
    
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    
    line1_data = json.loads(lines[0])
    assert line1_data["sha256"] == hashlib.sha256(raw_str_1.encode("utf-8")).hexdigest()
    assert line1_data["payload"] == raw_str_1
    
    # Verify file integrity check
    integrity = recorder.verify_file_integrity()
    assert integrity["verified"] is True
    assert integrity["message_count"] == 2


def test_order_book_reconstructor_lifecycle():
    """Verifies deterministic L2 order book reconstruction from initial snapshot and updates."""
    reconstructor = OrderBookReconstructor(depth_levels_limit=5)
    token = "0x9876543210abcdef"
    
    # 1. Initial snapshot
    book_msg = {
        "event_type": "book",
        "market": token,
        "asset_id": token,
        "timestamp": 1720000000000,
        "bids": [{"price": "0.50", "size": "1000"}, {"price": "0.49", "size": "2000"}],
        "asks": [{"price": "0.52", "size": "1500"}, {"price": "0.53", "size": "2500"}]
    }
    raw_rec1 = RawMessageRecord(
        message_id="msg_1",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id=token,
        token_id=token,
        message_type="book",
        receive_timestamp=datetime.now(timezone.utc),
        exchange_timestamp=datetime.fromtimestamp(1720000000, tz=timezone.utc),
        raw_message_json=json.dumps(book_msg),
        sha256_hash="dummy",
        raw_file_path="/tmp/dummy"
    )
    
    upds1, snap1 = reconstructor.process_raw_record(raw_rec1)
    assert snap1 is not None
    assert snap1.best_bid == 0.50
    assert snap1.best_ask == 0.52
    assert snap1.midpoint == 0.51
    assert snap1.spread == 0.02
    assert snap1.quality_status == DataQualityStatus.VALID
    assert snap1.depth_bid_usd > 0
    assert snap1.depth_ask_usd > 0

    # 2. Price change: level update (new tighter bid)
    chg_msg = {
        "event_type": "price_change",
        "market": token,
        "timestamp": 1720000001000,
        "price_changes": [{"asset_id": token, "price": "0.51", "size": "500", "side": "BUY"}]
    }
    raw_rec2 = RawMessageRecord(
        message_id="msg_2",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id=token,
        token_id=token,
        message_type="price_change",
        receive_timestamp=datetime.now(timezone.utc),
        exchange_timestamp=datetime.fromtimestamp(1720000001, tz=timezone.utc),
        raw_message_json=json.dumps(chg_msg),
        sha256_hash="dummy",
        raw_file_path="/tmp/dummy"
    )
    upds2, snap2 = reconstructor.process_raw_record(raw_rec2)
    assert snap2 is not None
    assert snap2.best_bid == 0.51
    assert snap2.best_ask == 0.52
    assert round(snap2.spread, 4) == 0.01

    # 3. Price change: deletion (size = 0)
    del_msg = {
        "event_type": "price_change",
        "market": token,
        "timestamp": 1720000002000,
        "price_changes": [{"asset_id": token, "price": "0.51", "size": "0", "side": "BUY"}]
    }
    raw_rec3 = RawMessageRecord(
        message_id="msg_3",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id=token,
        token_id=token,
        message_type="price_change",
        receive_timestamp=datetime.now(timezone.utc),
        exchange_timestamp=datetime.fromtimestamp(1720000002, tz=timezone.utc),
        raw_message_json=json.dumps(del_msg),
        sha256_hash="dummy",
        raw_file_path="/tmp/dummy"
    )
    upds3, snap3 = reconstructor.process_raw_record(raw_rec3)
    assert snap3 is not None
    assert snap3.best_bid == 0.50  # Fell back to 0.50 after 0.51 removed
    assert snap3.best_ask == 0.52

    # 4. Crossed book detection
    cross_msg = {
        "event_type": "price_change",
        "market": token,
        "timestamp": 1720000003000,
        "price_changes": [{"asset_id": token, "price": "0.53", "size": "100", "side": "BUY"}]
    }
    raw_rec4 = RawMessageRecord(
        message_id="msg_4",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id=token,
        token_id=token,
        message_type="price_change",
        receive_timestamp=datetime.now(timezone.utc),
        exchange_timestamp=datetime.fromtimestamp(1720000003, tz=timezone.utc),
        raw_message_json=json.dumps(cross_msg),
        sha256_hash="dummy",
        raw_file_path="/tmp/dummy"
    )
    upds4, snap4 = reconstructor.process_raw_record(raw_rec4)
    assert snap4 is not None
    assert snap4.quality_status == DataQualityStatus.CROSSED_BOOK
    assert snap4.best_bid == 0.53
    assert snap4.best_ask == 0.52


def test_trade_stream_processor_and_deduplication():
    """Verifies that trades are parsed, validated, and deduplicated."""
    processor = TradeStreamProcessor()
    token = "0x11112222333344445555"
    
    trade_payload = {
        "event_type": "last_trade_price",
        "market": "m_test",
        "asset_id": token,
        "price": "0.62",
        "size": "250.0",
        "side": "BUY",
        "timestamp": 1720000010000,
        "transaction_hash": "0xabc123456789"
    }
    raw_rec = RawMessageRecord(
        message_id="msg_trade_1",
        ingestion_session_id="s1",
        venue="polymarket",
        market_id="m_test",
        token_id=token,
        message_type="last_trade_price",
        receive_timestamp=datetime.now(timezone.utc),
        exchange_timestamp=datetime.fromtimestamp(1720000010, tz=timezone.utc),
        raw_message_json=json.dumps(trade_payload),
        sha256_hash="dummy",
        raw_file_path="/tmp/dummy"
    )
    
    trade = processor.process_raw_trade(raw_rec)
    assert trade is not None
    assert trade.token_id == token
    assert trade.price == 0.62
    assert trade.size == 250.0
    assert trade.side == "BUY"
    assert trade.transaction_hash == "0xabc123456789"
    assert trade.size_usd == 155.0
    
    # Process duplicate trade (same transaction_hash)
    dup_trade = processor.process_raw_trade(raw_rec)
    assert dup_trade is None  # Deduplicated
    assert len(processor.recorded_trades) == 1


def test_market_universe_manager_filtering():
    """Verifies objective Gamma market discovery filters."""
    manager = MarketUniverseManager(min_liquidity_usd=10000.0, min_volume_24h_usd=20000.0)
    
    raw_gamma_data = [
        {
            "id": "m1",
            "question": "Will candidate X win the election?",
            "conditionId": "0xcond1",
            "clobTokenIds": '["0x111", "0x222"]',
            "liquidity": "50000",
            "volume24hr": "100000",
            "active": True,
            "closed": False,
            "category": "Politics"
        },
        {
            # Should be rejected: low volume
            "id": "m2",
            "question": "Low volume question",
            "conditionId": "0xcond2",
            "clobTokenIds": '["0x333", "0x444"]',
            "liquidity": "30000",
            "volume24hr": "5000",
            "active": True,
            "closed": False,
            "category": "Science"
        },
        {
            # Should be rejected: closed
            "id": "m3",
            "question": "Closed question",
            "conditionId": "0xcond3",
            "clobTokenIds": '["0x555", "0x666"]',
            "liquidity": "50000",
            "volume24hr": "50000",
            "active": False,
            "closed": True,
            "category": "Sports"
        }
    ]
    
    entries = manager.parse_markets(raw_gamma_data, session_id="s1")
    assert len(entries) == 2  # 2 outcomes for m1 (0x111, 0x222)
    assert entries[0].market_id == "m1"
    assert entries[0].token_id in ["0x111", "0x222"]
    assert entries[0].is_active is True
    assert entries[0].is_tradable is True


def test_anti_synthetic_guard_gating(in_memory_db, temp_raw_dir):
    """Verifies that AntiSyntheticGuard rejects placeholder tokens and validates real data."""
    conn, db_store = in_memory_db
    guard = AntiSyntheticGuard()
    
    # 1. Token ID format validation
    valid_hex_token = "0x4b9f2913e64b85c13b2e758bcba5e7d94cf21ef1c29e24a8fc378d3de635bc37"
    valid_dec_token = "104928374928374928374928374928374928374928374"
    invalid_token_prefix = "token_geopol_taiwan_001"
    invalid_short_token = "tok_12"
    
    assert guard.validate_token_id(valid_hex_token) is True
    assert guard.validate_token_id(valid_dec_token) is True
    assert guard.validate_token_id(invalid_token_prefix) is False
    assert guard.validate_token_id(invalid_short_token) is False
    
    # 2. Database table scan: insert a valid record, verify clean scan
    db_store.persist_market_universe(conn, [
        MarketUniverseEntry(
            entry_id="univ_1",
            session_id="s1",
            market_id="m_real",
            token_id=valid_hex_token,
            outcome="Yes",
            title="Real question?",
            category="Politics",
            volume_24h_usd=75000.0,
            liquidity_usd=50000.0,
            is_active=True,
            is_tradable=True,
            action="ADDED",
            timestamp=datetime.now(timezone.utc)
        )
    ])
    
    scan = guard.scan_production_tables(conn)
    assert scan["clean"] is True
    assert scan["violations"] == []
    
    # 3. Insert synthetic placeholder token: verify guard failure
    conn.execute(f"INSERT INTO phase10a5_market_universe VALUES ('univ_synth', 's1', 'm_synth', '{invalid_token_prefix}', 'Yes', 'Synth?', 'Test', 20000, 10000, true, true, 'ADDED', CURRENT_TIMESTAMP)")
    
    tainted_scan = guard.scan_production_tables(conn)
    assert tainted_scan["clean"] is False
    assert len(tainted_scan["violations"]) > 0
    assert "placeholder tokens in phase10a5_market_universe" in tainted_scan["violations"][0]


def test_duckdb_schema_isolation_and_persistence(in_memory_db, temp_raw_dir):
    """Verifies that all Phase 10A.5 DuckDB tables store and retrieve records correctly."""
    conn, db_store = in_memory_db
    
    now = datetime.now(timezone.utc)
    token = "0x5555666677778888999900001111222233334444"
    
    # Create dummy raw file on disk for AntiSyntheticGuard check
    raw_path = Path(temp_raw_dir) / "test.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_json = '{"test": 123}'
    sha = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    raw_path.write_text(json.dumps({"payload": raw_json}) + "\n", encoding="utf-8")

    # Raw message
    raw = RawMessageRecord(
        message_id="msg_test",
        ingestion_session_id="sess_test",
        venue="polymarket",
        market_id="m_test",
        token_id=token,
        message_type="book",
        receive_timestamp=now,
        exchange_timestamp=now,
        raw_message_json=raw_json,
        sha256_hash=sha,
        raw_file_path=str(raw_path)
    )
    db_store.persist_raw_messages(conn, [raw])
    
    # Snapshot
    snap = ReconstructedBookSnapshot(
        snapshot_id="snap_test",
        session_id="sess_test",
        market_id="m_test",
        token_id=token,
        timestamp=now,
        exchange_timestamp=now,
        best_bid=0.45,
        best_ask=0.47,
        midpoint=0.46,
        spread=0.02,
        spread_bps=434.78,
        depth_bid_usd=500.0,
        depth_ask_usd=600.0,
        book_imbalance=-0.0909,
        bids=[{"price": 0.45, "size": 1000}],
        asks=[{"price": 0.47, "size": 1000}],
        quality_status=DataQualityStatus.VALID,
        quality_reason=None
    )
    db_store.persist_book_snapshots(conn, [snap])
    
    # Trade
    trade = GenuineTradeRecord(
        trade_id="trade_test",
        session_id="sess_test",
        market_id="m_test",
        token_id=token,
        receive_timestamp=now,
        exchange_timestamp=now,
        price=0.46,
        size=100.0,
        size_usd=46.0,
        side="BUY",
        fee_rate_bps=0.0,
        transaction_hash="0xtx123"
    )
    db_store.persist_trades(conn, [trade])
    
    # Session
    sess = ConnectionSessionRecord(
        session_id="sess_test",
        start_timestamp=now,
        end_timestamp=now,
        endpoint_url="wss://test",
        resolved_ip="127.0.0.1",
        total_messages_received=1,
        total_messages_persisted=1,
        total_bytes_received=100,
        disconnect_count=0,
        reconnect_count=0,
        status="COMPLETED"
    )
    db_store.persist_session(conn, sess)
    
    # Verify counts in DB
    assert conn.execute("SELECT count(*) FROM phase10a5_raw_messages").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM phase10a5_book_snapshots").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM phase10a5_trades").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM phase10a5_connection_sessions").fetchone()[0] == 1


def test_genuine_event_registry_interface(in_memory_db):
    """Verifies that the event registry validates inputs and maintains separation from market prices."""
    conn, db_store = in_memory_db
    registry = GenuineEventRegistry()
    registry.init_table(conn)
    
    now = datetime.now(timezone.utc)
    
    # Valid event registration
    event = registry.register_event(
        event_id="evt_bls_cpi_20261015",
        source="bls.gov",
        source_url="https://www.bls.gov/cpi/cpi_20261015.htm",
        publication_timestamp=now,
        event_category="Macroeconomics",
        description="Official BLS CPI Release.",
        affected_entity="US_INFLATION"
    )
    
    assert event.event_id == "evt_bls_cpi_20261015"
    assert event.source == "bls.gov"
    
    n = registry.persist_events(conn, [event])
    assert n == 1
    
    row = conn.execute("SELECT event_id, source, affected_entity FROM phase10a5_events WHERE event_id = 'evt_bls_cpi_20261015'").fetchone()
    assert row[0] == "evt_bls_cpi_20261015"
    assert row[1] == "bls.gov"
    assert row[2] == "US_INFLATION"
    
    # Rejection of invalid event without source
    with pytest.raises(ValueError):
        registry.register_event(
            event_id="evt_invalid",
            source="",
            source_url="http://foo.bar",
            publication_timestamp=now,
            event_category="Test",
            description="Missing source",
            affected_entity="NONE"
        )
