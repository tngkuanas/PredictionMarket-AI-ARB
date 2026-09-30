"""DuckDB Table Persistence Manager for Phase 10A.5 Genuine Market Data Acquisition."""
from datetime import datetime
import json
import logging
from typing import List, Dict, Any, Optional

import duckdb

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    GenuineTradeRecord,
    MarketUniverseEntry,
    ConnectionSessionRecord,
    DataQualityRecord,
    GenuineEventRecord,
)
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard

logger = logging.getLogger(__name__)


class Phase10A5DbStore:
    """Manages Phase 10A.5 DuckDB schema and batch insertions with anti-synthetic gating."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Creates the 8 designated Phase 10A.5 tables in DuckDB."""
        conn.execute("""
            -- 1. Raw Messages Table
            CREATE TABLE IF NOT EXISTS phase10a5_raw_messages (
                message_id VARCHAR PRIMARY KEY,
                ingestion_session_id VARCHAR,
                venue VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                message_type VARCHAR,
                receive_timestamp TIMESTAMP,
                exchange_timestamp TIMESTAMP,
                raw_message_json VARCHAR,
                sha256_hash VARCHAR,
                raw_file_path VARCHAR
            );

            -- 2. Book Updates Table
            CREATE TABLE IF NOT EXISTS phase10a5_book_updates (
                update_id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                receive_timestamp TIMESTAMP,
                exchange_timestamp TIMESTAMP,
                side VARCHAR,
                price DOUBLE,
                size DOUBLE,
                delta_type VARCHAR,
                best_bid DOUBLE,
                best_ask DOUBLE,
                hash VARCHAR
            );

            -- 3. Reconstructed Book Snapshots Table
            CREATE TABLE IF NOT EXISTS phase10a5_book_snapshots (
                snapshot_id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                timestamp TIMESTAMP,
                exchange_timestamp TIMESTAMP,
                best_bid DOUBLE,
                best_ask DOUBLE,
                midpoint DOUBLE,
                spread DOUBLE,
                spread_bps DOUBLE,
                depth_bid_usd DOUBLE,
                depth_ask_usd DOUBLE,
                book_imbalance DOUBLE,
                bids JSON,
                asks JSON,
                quality_status VARCHAR,
                quality_reason VARCHAR
            );

            -- 4. Trades Table
            CREATE TABLE IF NOT EXISTS phase10a5_trades (
                trade_id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                receive_timestamp TIMESTAMP,
                exchange_timestamp TIMESTAMP,
                price DOUBLE,
                size DOUBLE,
                size_usd DOUBLE,
                side VARCHAR,
                fee_rate_bps DOUBLE,
                transaction_hash VARCHAR
            );

            -- 5. Market Universe Table
            CREATE TABLE IF NOT EXISTS phase10a5_market_universe (
                entry_id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                outcome VARCHAR,
                title VARCHAR,
                category VARCHAR,
                volume_24h_usd DOUBLE,
                liquidity_usd DOUBLE,
                is_active BOOLEAN,
                is_tradable BOOLEAN,
                action VARCHAR,
                timestamp TIMESTAMP
            );

            -- 6. Connection Sessions Table
            CREATE TABLE IF NOT EXISTS phase10a5_connection_sessions (
                session_id VARCHAR PRIMARY KEY,
                start_timestamp TIMESTAMP,
                end_timestamp TIMESTAMP,
                endpoint_url VARCHAR,
                resolved_ip VARCHAR,
                total_messages_received INTEGER,
                total_messages_persisted INTEGER,
                total_bytes_received BIGINT,
                disconnect_count INTEGER,
                reconnect_count INTEGER,
                status VARCHAR
            );

            -- 7. Data Quality Records Table
            CREATE TABLE IF NOT EXISTS phase10a5_data_quality (
                record_id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                timestamp TIMESTAMP,
                status VARCHAR,
                component VARCHAR,
                details VARCHAR
            );

            -- 8. Future Events Table
            CREATE TABLE IF NOT EXISTS phase10a5_events (
                event_id VARCHAR PRIMARY KEY,
                source VARCHAR,
                source_url VARCHAR,
                publication_timestamp TIMESTAMP,
                event_category VARCHAR,
                description VARCHAR,
                affected_entity VARCHAR,
                event_created_timestamp TIMESTAMP
            );
        """)
        logger.info("Phase 10A.5 DuckDB schema initialized successfully.")

    def persist_raw_messages(self, conn: duckdb.DuckDBPyConnection, records: List[RawMessageRecord]) -> int:
        if not records:
            return 0
        rows = []
        for r in records:
            AntiSyntheticGuard.validate_raw_message(r)
            rows.append((
                r.message_id, r.ingestion_session_id, r.venue, r.market_id,
                r.token_id, r.message_type, r.receive_timestamp, r.exchange_timestamp,
                r.raw_message_json, r.sha256_hash, r.raw_file_path
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_raw_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_book_updates(self, conn: duckdb.DuckDBPyConnection, updates: List[BookUpdateRecord]) -> int:
        if not updates:
            return 0
        rows = []
        for u in updates:
            rows.append((
                u.update_id, u.session_id, u.market_id, u.token_id,
                u.receive_timestamp, u.exchange_timestamp, u.side,
                float(u.price), float(u.size), u.delta_type,
                float(u.best_bid) if u.best_bid is not None else None,
                float(u.best_ask) if u.best_ask is not None else None,
                u.hash
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_book_updates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_book_snapshots(self, conn: duckdb.DuckDBPyConnection, snapshots: List[ReconstructedBookSnapshot]) -> int:
        if not snapshots:
            return 0
        rows = []
        for s in snapshots:
            AntiSyntheticGuard.validate_book_snapshot(s)
            rows.append((
                s.snapshot_id, s.session_id, s.market_id, s.token_id,
                s.timestamp, s.exchange_timestamp, float(s.best_bid), float(s.best_ask),
                float(s.midpoint), float(s.spread), float(s.spread_bps),
                float(s.depth_bid_usd), float(s.depth_ask_usd), float(s.book_imbalance),
                json.dumps(s.bids), json.dumps(s.asks), s.quality_status.value, s.quality_reason
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_book_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_trades(self, conn: duckdb.DuckDBPyConnection, trades: List[GenuineTradeRecord]) -> int:
        if not trades:
            return 0
        rows = []
        for t in trades:
            AntiSyntheticGuard.validate_trade(t)
            rows.append((
                t.trade_id, t.session_id, t.market_id, t.token_id,
                t.receive_timestamp, t.exchange_timestamp, float(t.price),
                float(t.size), float(t.size_usd), t.side, float(t.fee_rate_bps),
                t.transaction_hash
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_market_universe(self, conn: duckdb.DuckDBPyConnection, universe: List[MarketUniverseEntry]) -> int:
        if not universe:
            return 0
        rows = []
        for u in universe:
            rows.append((
                u.entry_id, u.session_id, u.market_id, u.token_id,
                u.outcome, u.title, u.category, float(u.volume_24h_usd),
                float(u.liquidity_usd), bool(u.is_active), bool(u.is_tradable),
                u.action, u.timestamp
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_market_universe VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_session(self, conn: duckdb.DuckDBPyConnection, session: ConnectionSessionRecord) -> None:
        conn.execute("""
            INSERT OR REPLACE INTO phase10a5_connection_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session.session_id, session.start_timestamp, session.end_timestamp,
            session.endpoint_url, session.resolved_ip, int(session.total_messages_received),
            int(session.total_messages_persisted), int(session.total_bytes_received),
            int(session.disconnect_count), int(session.reconnect_count), session.status
        ))

    def persist_data_quality(self, conn: duckdb.DuckDBPyConnection, dq_records: List[DataQualityRecord]) -> int:
        if not dq_records:
            return 0
        rows = []
        for d in dq_records:
            rows.append((
                d.record_id, d.session_id, d.market_id, d.token_id,
                d.timestamp, d.status.value, d.component, d.details
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_data_quality VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)
