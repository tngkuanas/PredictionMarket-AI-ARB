"""DuckDB Persistence Store for Phase 10A.6 Information-Response Study.

Manages schema initialization and persistence for the 6 required output tables:
1. phase10a6_event_study
2. phase10a6_event_clusters
3. phase10a6_contract_mappings
4. phase10a6_placebos
5. phase10a6_data_quality
6. phase10a6_analysis_config
"""

from datetime import datetime, timezone
import json
import logging
from typing import Dict, Any, List

import duckdb

logger = logging.getLogger(__name__)


class Phase10A6DbStore:
    """Manages DuckDB tables for Phase 10A.6."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def init_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initializes all 6 required Phase 10A.6 tables."""
        conn.execute("""
            -- 1. Event Study Table
            CREATE TABLE IF NOT EXISTS phase10a6_event_study (
                study_id VARCHAR PRIMARY KEY,
                event_cluster_id VARCHAR,
                event_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                horizon VARCHAR,
                t0_utc TIMESTAMP,
                t_pre_utc TIMESTAMP,
                t_post_utc TIMESTAMP,
                mid_pre DOUBLE,
                mid_post DOUBLE,
                signed_mid_change_bps DOUBLE,
                executable_bid_change_bps DOUBLE,
                executable_ask_change_bps DOUBLE,
                spread_pre_bps DOUBLE,
                spread_post_bps DOUBLE,
                depth_pre_usd DOUBLE,
                depth_post_usd DOUBLE,
                fee_bps DOUBLE,
                net_executable_markout_bps DOUBLE,
                direction_expected VARCHAR,
                status VARCHAR
            );

            -- 2. Event Clusters Table
            CREATE TABLE IF NOT EXISTS phase10a6_event_clusters (
                cluster_id VARCHAR PRIMARY KEY,
                canonical_event_id VARCHAR,
                cluster_title VARCHAR,
                cluster_category VARCHAR,
                first_publication_utc TIMESTAMP,
                contracts_count INTEGER,
                independent_catalyst VARCHAR
            );

            -- 3. Contract Mappings Table
            CREATE TABLE IF NOT EXISTS phase10a6_contract_mappings (
                mapping_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                mapping_status VARCHAR,         -- ACCEPTED, AMBIGUOUS, REJECTED
                rejection_reason VARCHAR,
                direction_expected VARCHAR,     -- LONG, SHORT, UNKNOWN
                mapped_at_utc TIMESTAMP
            );

            -- 4. Placebos Table
            CREATE TABLE IF NOT EXISTS phase10a6_placebos (
                placebo_id VARCHAR PRIMARY KEY,
                placebo_type VARCHAR,           -- RANDOM_TIMESTAMPS, TIME_SHIFTED, WRONG_MARKET, DIRECTION_PERMUTATION
                horizon VARCHAR,
                n_iterations INTEGER,
                mean_signed_response_bps DOUBLE,
                p_value DOUBLE,
                status VARCHAR
            );

            -- 5. Data Quality Table
            CREATE TABLE IF NOT EXISTS phase10a6_data_quality (
                record_id VARCHAR PRIMARY KEY,
                component VARCHAR,              -- DATA_SPAN, PRE_EVENT_WINDOW, LATENCY, BOOK_STATE
                check_name VARCHAR,
                status VARCHAR,                 -- PASS, FAIL, INCONCLUSIVE
                details VARCHAR,
                checked_at_utc TIMESTAMP
            );

            -- 6. Analysis Configuration Table
            CREATE TABLE IF NOT EXISTS phase10a6_analysis_config (
                config_id VARCHAR PRIMARY KEY,
                analysis_version VARCHAR,
                min_span_hours DOUBLE,
                actual_wall_clock_span_sec DOUBLE,
                active_recording_time_sec DOUBLE,
                classification VARCHAR,         -- A, B, C
                execution_permitted BOOLEAN,
                git_commit VARCHAR,
                created_at_utc TIMESTAMP,
                parameters JSON
            );
        """)
        logger.info("Phase 10A.6 DuckDB schema initialized successfully.")

    def record_config(
        self,
        conn: duckdb.DuckDBPyConnection,
        config_id: str,
        wall_clock_span_sec: float,
        active_rec_sec: float,
        classification: str,
        execution_permitted: bool,
        git_commit: str,
        parameters: Dict[str, Any]
    ) -> None:
        """Stores the frozen analysis configuration record."""
        now = datetime.now(timezone.utc)
        conn.execute("""
            INSERT OR REPLACE INTO phase10a6_analysis_config VALUES (
                ?, '10A.6-v1.0', 72.0, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            config_id,
            wall_clock_span_sec,
            active_rec_sec,
            classification,
            execution_permitted,
            git_commit,
            now,
            json.dumps(parameters)
        ))

    def record_data_quality(
        self,
        conn: duckdb.DuckDBPyConnection,
        records: List[Dict[str, Any]]
    ) -> int:
        """Inserts data quality audit findings."""
        if not records:
            return 0
        now = datetime.now(timezone.utc)
        rows = [
            (
                r["record_id"],
                r["component"],
                r["check_name"],
                r["status"],
                r["details"],
                now
            )
            for r in records
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a6_data_quality VALUES (?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)
