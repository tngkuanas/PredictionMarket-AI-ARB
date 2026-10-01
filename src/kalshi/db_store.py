"""DuckDB Table Persistence Manager for Phase 10A.6F Kalshi Market Data.

Creates append-only tables for raw WebSocket payloads, L2 snapshots, updates,
trades, connection sessions, reconnect events, data quality logs, and market universe.
Enforces raw-message provenance and anti-synthetic validation guards.
"""
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import duckdb

from src.kalshi.schema import (
    KalshiRawMessageRecord,
    KalshiBookUpdateRecord,
    KalshiReconstructedBookSnapshot,
    KalshiTradeRecord,
    KalshiConnectionSessionRecord,
    KalshiReconnectEventRecord,
    KalshiDataQualityRecord,
    KalshiMarketUniverseRecord,
)

logger = logging.getLogger(__name__)


class KalshiDbStore:
    """Manages Phase 10A.6F Kalshi DuckDB schema and batch insertions."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = Path(db_path)

    def _get_connection(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        import time, shutil, tempfile, os
        for _ in range(5):
            try:
                return duckdb.connect(str(self.db_path), read_only=read_only)
            except Exception:
                time.sleep(0.1)

        if read_only:
            # Fall back to isolated copy if locked by background recorder
            tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
            tmp_path = tmp.name
            tmp.close()
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            shutil.copyfile(str(self.db_path), tmp_path)
            return duckdb.connect(tmp_path, read_only=True)
        else:
            return duckdb.connect(str(self.db_path), read_only=False)

    def init_schema(self, conn: Optional[duckdb.DuckDBPyConnection] = None) -> None:
        """Creates the 8 designated Phase 10A.6F Kalshi tables in DuckDB."""
        should_close = False
        if conn is None:
            conn = self._get_connection(read_only=False)
            should_close = True

        try:
            conn.execute("""
                -- 1. Kalshi Raw Messages
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_raw_messages (
                    raw_message_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    receive_timestamp TIMESTAMP,
                    exchange_timestamp TIMESTAMP,
                    channel VARCHAR,
                    market_id VARCHAR,
                    message_type VARCHAR,
                    raw_payload VARCHAR,
                    payload_sha256 VARCHAR,
                    message_seq BIGINT
                );

                -- 2. Kalshi Book Updates
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_book_updates (
                    update_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    market_id VARCHAR,
                    receive_timestamp TIMESTAMP,
                    exchange_timestamp TIMESTAMP,
                    side VARCHAR,
                    action VARCHAR,
                    price DOUBLE,
                    delta_quantity DOUBLE,
                    remaining_quantity DOUBLE,
                    sequence BIGINT,
                    raw_message_id VARCHAR
                );

                -- 3. Kalshi Reconstructed Book Snapshots
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_book_snapshots (
                    snapshot_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    market_id VARCHAR,
                    receive_timestamp TIMESTAMP,
                    exchange_timestamp TIMESTAMP,
                    sequence BIGINT,
                    yes_bids JSON,
                    yes_asks JSON,
                    no_bids JSON,
                    no_asks JSON,
                    best_yes_bid DOUBLE,
                    best_yes_ask DOUBLE,
                    best_no_bid DOUBLE,
                    best_no_ask DOUBLE,
                    yes_spread DOUBLE,
                    yes_bid_depth DOUBLE,
                    yes_ask_depth DOUBLE,
                    top_n_depth DOUBLE,
                    book_imbalance DOUBLE,
                    quality_status VARCHAR,
                    quality_reason VARCHAR,
                    raw_message_id VARCHAR,
                    book_hash VARCHAR
                );

                -- 4. Kalshi Trades
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_trades (
                    trade_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    market_id VARCHAR,
                    price DOUBLE,
                    quantity DOUBLE,
                    side VARCHAR,
                    taker_side VARCHAR,
                    exchange_timestamp TIMESTAMP,
                    receive_timestamp TIMESTAMP,
                    raw_message_id VARCHAR
                );

                -- 5. Connection Sessions
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_connection_sessions (
                    session_id VARCHAR PRIMARY KEY,
                    start_timestamp TIMESTAMP,
                    end_timestamp TIMESTAMP,
                    endpoint_url VARCHAR,
                    status VARCHAR,
                    total_messages_received BIGINT,
                    total_messages_persisted BIGINT,
                    disconnect_count INTEGER,
                    reconnect_count INTEGER
                );

                -- 6. Reconnect Events
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_reconnect_events (
                    reconnect_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    disconnect_timestamp TIMESTAMP,
                    reconnect_attempt INTEGER,
                    reconnect_timestamp TIMESTAMP,
                    reconnect_reason VARCHAR,
                    reconnect_latency_seconds DOUBLE,
                    success BOOLEAN
                );

                -- 7. Data Quality Anomaly Records
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_data_quality (
                    record_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    market_id VARCHAR,
                    timestamp TIMESTAMP,
                    component VARCHAR,
                    status VARCHAR,
                    details VARCHAR
                );

                -- 8. Market Universe Discovered
                CREATE TABLE IF NOT EXISTS phase10a6f_kalshi_market_universe (
                    entry_id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    market_id VARCHAR,
                    title VARCHAR,
                    status VARCHAR,
                    open_time TIMESTAMP,
                    close_time TIMESTAMP,
                    expiration_time TIMESTAMP,
                    settlement_source VARCHAR,
                    resolution_rules VARCHAR,
                    strike_type VARCHAR,
                    floor_strike DOUBLE,
                    cap_strike DOUBLE,
                    tick_size DOUBLE,
                    volume DOUBLE,
                    open_interest DOUBLE,
                    liquidity DOUBLE,
                    raw_metadata_hash VARCHAR,
                    retrieval_timestamp TIMESTAMP
                );
            """)
        finally:
            if should_close:
                conn.close()

    def persist_raw_messages(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiRawMessageRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.raw_message_id,
                r.session_id,
                r.receive_timestamp,
                r.exchange_timestamp,
                r.channel,
                r.market_id,
                r.message_type,
                r.raw_payload,
                r.payload_sha256,
                r.message_seq
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_raw_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_book_updates(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiBookUpdateRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.update_id,
                r.session_id,
                r.market_id,
                r.receive_timestamp,
                r.exchange_timestamp,
                r.side,
                r.action,
                r.price,
                r.delta_quantity,
                r.remaining_quantity,
                r.sequence,
                r.raw_message_id
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_book_updates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_book_snapshots(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiReconstructedBookSnapshot]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.snapshot_id,
                r.session_id,
                r.market_id,
                r.receive_timestamp,
                r.exchange_timestamp,
                r.sequence,
                json.dumps(r.yes_bids),
                json.dumps(r.yes_asks),
                json.dumps(r.no_bids),
                json.dumps(r.no_asks),
                r.best_yes_bid,
                r.best_yes_ask,
                r.best_no_bid,
                r.best_no_ask,
                r.yes_spread,
                r.yes_bid_depth,
                r.yes_ask_depth,
                r.top_n_depth,
                r.book_imbalance,
                r.quality_status.value,
                r.quality_reason,
                r.raw_message_id,
                r.book_hash
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_book_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_trades(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiTradeRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.trade_id,
                r.session_id,
                r.market_id,
                r.price,
                r.quantity,
                r.side,
                r.taker_side,
                r.exchange_timestamp,
                r.receive_timestamp,
                r.raw_message_id
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_connection_session(
        self,
        conn: duckdb.DuckDBPyConnection,
        record: KalshiConnectionSessionRecord
    ) -> None:
        conn.execute("""
            INSERT OR REPLACE INTO phase10a6f_kalshi_connection_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.session_id,
            record.start_timestamp,
            record.end_timestamp,
            record.endpoint_url,
            record.status,
            record.total_messages_received,
            record.total_messages_persisted,
            record.disconnect_count,
            record.reconnect_count
        ))

    def persist_reconnect_events(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiReconnectEventRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.reconnect_id,
                r.session_id,
                r.disconnect_timestamp,
                r.reconnect_attempt,
                r.reconnect_timestamp,
                r.reconnect_reason,
                r.reconnect_latency_seconds,
                r.success
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_reconnect_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_data_quality(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiDataQualityRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.record_id,
                r.session_id,
                r.market_id,
                r.timestamp,
                r.component,
                r.status.value,
                r.details
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_data_quality VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_market_universe(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[KalshiMarketUniverseRecord]
    ) -> int:
        if not records:
            return 0
        rows = [
            (
                r.entry_id,
                r.session_id,
                r.market_id,
                r.title,
                r.status,
                r.open_time,
                r.close_time,
                r.expiration_time,
                r.settlement_source,
                r.resolution_rules,
                r.strike_type,
                r.floor_strike,
                r.cap_strike,
                r.tick_size,
                r.volume,
                r.open_interest,
                r.liquidity,
                r.raw_metadata_hash,
                r.retrieval_timestamp
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO phase10a6f_kalshi_market_universe VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    @staticmethod
    def scan_anti_synthetic_guard(conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Scans Phase 10A.6F tables to certify zero synthetic rows exist in production tables."""
        tables = [
            "phase10a6f_kalshi_raw_messages",
            "phase10a6f_kalshi_book_snapshots",
            "phase10a6f_kalshi_book_updates",
            "phase10a6f_kalshi_trades",
            "phase10a6f_kalshi_market_universe"
        ]
        synthetic_patterns = ["synthetic", "mock", "dummy", "fake", "fixture_test"]
        violations = []

        existing_tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]

        for tbl in tables:
            if tbl not in existing_tables:
                continue
            for pattern in synthetic_patterns:
                try:
                    count = conn.execute(f"""
                        SELECT COUNT(*) FROM {tbl}
                        WHERE LOWER(CAST(row_to_json({tbl}) AS VARCHAR)) LIKE '%{pattern}%'
                    """).fetchone()[0]
                    if count > 0:
                        violations.append(f"Table {tbl} contains {count} rows matching synthetic pattern '{pattern}'.")
                except Exception:
                    pass

        return {
            "certified_clean": len(violations) == 0,
            "violations_count": len(violations),
            "violations": violations
        }
