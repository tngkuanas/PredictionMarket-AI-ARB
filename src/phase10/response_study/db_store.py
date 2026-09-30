"""DuckDB Persistence Store for Phase 10A.6 Information-Response Study.

Manages schema initialization and persistence for Phase 10A.6 append-only research tables:
1. phase10a6_event_study
2. phase10a6_executable_responses
3. phase10a6_event_clusters
4. phase10a6_contract_mappings
5. phase10a6_placebos
6. phase10a6_statistical_results
7. phase10a6_data_quality
8. phase10a6_analysis_config
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
        """Initializes all Phase 10A.6 tables."""
        conn.execute("""
            -- 1. Event Study Observations Table
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

            -- 2. Executable Responses Table (Depth & Latency grid)
            CREATE TABLE IF NOT EXISTS phase10a6_executable_responses (
                response_id VARCHAR PRIMARY KEY,
                observation_id VARCHAR,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                horizon VARCHAR,
                latency_ms INTEGER,
                order_size_usd DOUBLE,
                direction VARCHAR,
                is_fillable BOOLEAN,
                fill_price_vwap DOUBLE,
                gross_notional_filled DOUBLE,
                filled_shares DOUBLE,
                depth_consumed_usd DOUBLE,
                spread_cost_usd DOUBLE,
                spread_cost_bps DOUBLE,
                slippage_usd DOUBLE,
                slippage_bps DOUBLE,
                fee_usd DOUBLE,
                fee_bps DOUBLE,
                gross_pnl_usd DOUBLE,
                gross_return_bps DOUBLE,
                net_pnl_usd DOUBLE,
                net_return_bps DOUBLE,
                capacity_limit_usd DOUBLE,
                status VARCHAR,
                status_reason VARCHAR
            );

            -- 3. Event Clusters Table
            CREATE TABLE IF NOT EXISTS phase10a6_event_clusters (
                cluster_id VARCHAR PRIMARY KEY,
                canonical_event_id VARCHAR,
                cluster_title VARCHAR,
                cluster_category VARCHAR,
                first_publication_utc TIMESTAMP,
                contracts_count INTEGER,
                independent_catalyst VARCHAR
            );

            -- 4. Contract Mappings Table
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

            -- 5. Placebos Table
            CREATE TABLE IF NOT EXISTS phase10a6_placebos (
                placebo_id VARCHAR PRIMARY KEY,
                placebo_type VARCHAR,           -- RANDOM_TIMESTAMPS, TIME_SHIFTED, WRONG_MARKET, DIRECTION_PERMUTATION
                horizon VARCHAR,
                n_iterations INTEGER,
                mean_signed_response_bps DOUBLE,
                p_value DOUBLE,
                status VARCHAR
            );

            -- 6. Statistical Results Table
            CREATE TABLE IF NOT EXISTS phase10a6_statistical_results (
                result_id VARCHAR PRIMARY KEY,
                metric_name VARCHAR,
                sample_size INTEGER,
                mean DOUBLE,
                median DOUBLE,
                std_dev DOUBLE,
                hit_rate DOUBLE,
                ci_lower DOUBLE,
                ci_upper DOUBLE,
                bootstrap_ci_lower DOUBLE,
                bootstrap_ci_upper DOUBLE,
                p_value DOUBLE,
                adjusted_p_value DOUBLE,
                test_type VARCHAR,
                is_significant BOOLEAN,
                tested_at_utc TIMESTAMP
            );

            -- 7. Data Quality Table
            CREATE TABLE IF NOT EXISTS phase10a6_data_quality (
                record_id VARCHAR PRIMARY KEY,
                component VARCHAR,              -- DATA_SPAN, PRE_EVENT_WINDOW, LATENCY, BOOK_STATE
                check_name VARCHAR,
                status VARCHAR,                 -- PASS, FAIL, INCONCLUSIVE
                details VARCHAR,
                checked_at_utc TIMESTAMP
            );

            -- 8. Analysis Configuration Table
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

    def record_executable_responses(
        self,
        conn: duckdb.DuckDBPyConnection,
        responses: List[Any]
    ) -> int:
        """Inserts executable response evaluation records."""
        if not responses:
            return 0
        rows = [
            (
                r.response_id, r.observation_id, r.event_id, r.event_cluster_id,
                r.market_id, r.token_id, r.horizon_name, r.latency_ms,
                r.order_size_usd, r.direction, r.is_fillable, r.fill_price_vwap,
                r.gross_notional_filled, r.filled_shares, r.depth_consumed_usd,
                r.spread_cost_usd, r.spread_cost_bps, r.slippage_usd, r.slippage_bps,
                r.fee_usd, r.fee_bps, r.gross_pnl_usd, r.gross_return_bps,
                r.net_pnl_usd, r.net_return_bps, r.capacity_limit_usd,
                str(r.status.value if hasattr(r.status, 'value') else r.status),
                r.status_reason
            )
            for r in responses
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a6_executable_responses VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, rows)
        return len(rows)

    def record_event_study_observations(
        self,
        conn: duckdb.DuckDBPyConnection,
        observations: List[Any]
    ) -> int:
        """Inserts event study observations."""
        if not observations:
            return 0
        rows = [
            (
                o.observation_id, o.event_cluster_id, o.event_id, o.market_id,
                o.token_id, o.horizon_name, o.event_timestamp, o.pre_timestamp,
                o.post_timestamp, o.pre_mid, o.post_mid, o.signed_mid_movement_bps,
                o.pre_bid, o.pre_ask, o.pre_spread_bps, o.post_spread_bps,
                o.pre_bid_depth_usd, o.post_bid_depth_usd, 20.0,
                o.signed_mid_movement_bps, o.direction,
                str(o.status.value if hasattr(o.status, 'value') else o.status)
            )
            for o in observations
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a6_event_study VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, rows)
        return len(rows)

    def record_statistical_results(
        self,
        conn: duckdb.DuckDBPyConnection,
        results: List[Any]
    ) -> int:
        """Inserts statistical hypothesis test results."""
        if not results:
            return 0
        now = datetime.now(timezone.utc)
        rows = [
            (
                f"stat_{res.metric_name}_{i}", res.metric_name, res.sample_size,
                res.mean, res.median, res.std_dev, res.hit_rate,
                res.ci_lower, res.ci_upper, res.bootstrap_ci_lower, res.bootstrap_ci_upper,
                res.p_value, res.adjusted_p_value, res.test_type, res.is_significant,
                now
            )
            for i, res in enumerate(results)
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a6_statistical_results VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, rows)
        return len(rows)
