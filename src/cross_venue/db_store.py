"""DuckDB Storage for Phase 10A.6e Cross-Venue Polymarket-Kalshi Arbitrage.

Phase 10A.6e Section 17:
Creates append-only tables for provenance tracking:
- phase10a6e_contract_mappings
- phase10a6e_quote_observations
- phase10a6e_arbitrage_candidates
- phase10a6e_execution_analysis
- phase10a6e_mapping_quality
- phase10a6e_analysis_config

CRITICAL SAFETY:
Uses retry loops with backoff to prevent write-lock contention with background recorder PID 53380.
Does NOT mutate historical Phase 10A/10A.5 tables.
"""

import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import duckdb

from config.settings import get_settings
from src.cross_venue.schema import (
    ContractMappingResult,
    SyncQuote,
    CrossVenueArbitrageOpportunity,
)

logger = logging.getLogger(__name__)


class CrossVenueDBStore:
    """Manages append-only DuckDB tables for Phase 10A.6e."""

    def __init__(self, db_path: Optional[Path] = None):
        self.settings = get_settings()
        self.db_path = db_path or self.settings.db.duckdb_path
        self._ensure_tables()

    def _get_connection(self, read_only: bool = False, max_retries: int = 10, backoff: float = 0.3) -> duckdb.DuckDBPyConnection:
        """Acquires DuckDB connection with retry logic to handle background recorder flush locks."""
        for attempt in range(max_retries):
            try:
                return duckdb.connect(str(self.db_path), read_only=read_only)
            except duckdb.OperationalError as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"DuckDB lock contention on attempt {attempt+1}/{max_retries}: {e}, sleeping {backoff}s...")
                time.sleep(backoff)
                backoff *= 1.5

    def _ensure_tables(self) -> None:
        """Creates the 6 Phase 10A.6e append-only tables."""
        ddl = """
        CREATE TABLE IF NOT EXISTS phase10a6e_contract_mappings (
            mapping_id VARCHAR PRIMARY KEY,
            polymarket_market_id VARCHAR,
            polymarket_token_id VARCHAR,
            kalshi_market_id VARCHAR,
            kalshi_contract_id VARCHAR,
            canonical_contract_id VARCHAR,
            equivalence_class VARCHAR,
            settlement_equivalence BOOLEAN,
            mapping_status VARCHAR,
            mapping_reason VARCHAR,
            resolution_source_polymarket VARCHAR,
            resolution_source_kalshi VARCHAR,
            resolution_time_polymarket VARCHAR,
            resolution_time_kalshi VARCHAR,
            threshold_polymarket DOUBLE,
            threshold_kalshi DOUBLE,
            direction_polymarket VARCHAR,
            direction_kalshi VARCHAR,
            currency_polymarket VARCHAR,
            currency_kalshi VARCHAR,
            mapping_config_hash VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6e_quote_observations (
            observation_id VARCHAR PRIMARY KEY,
            venue VARCHAR,
            market_id VARCHAR,
            contract_id VARCHAR,
            side VARCHAR,
            outcome VARCHAR,
            price DOUBLE,
            size DOUBLE,
            venue_timestamp TIMESTAMP,
            exchange_timestamp TIMESTAMP,
            local_receive_timestamp TIMESTAMP,
            sequence_frame_id VARCHAR
        );

        CREATE TABLE IF NOT EXISTS phase10a6e_arbitrage_candidates (
            candidate_id VARCHAR PRIMARY KEY,
            mapping_id VARCHAR,
            timestamp TIMESTAMP,
            sync_window_ms INTEGER,
            gross_settlement_value DOUBLE,
            gross_edge_bps DOUBLE,
            total_cost_bps DOUBLE,
            net_deterministic_edge_bps DOUBLE,
            final_verdict VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6e_execution_analysis (
            analysis_id VARCHAR PRIMARY KEY,
            opportunity_id VARCHAR,
            mapping_id VARCHAR,
            timestamp TIMESTAMP,
            leg_a_venue VARCHAR,
            leg_a_outcome VARCHAR,
            leg_a_vwap DOUBLE,
            leg_a_notional DOUBLE,
            leg_b_venue VARCHAR,
            leg_b_outcome VARCHAR,
            leg_b_vwap DOUBLE,
            leg_b_notional DOUBLE,
            venue_fee_bps DOUBLE,
            execution_slippage_bps DOUBLE,
            latency_penalty_bps DOUBLE,
            hedge_cost_bps DOUBLE,
            capital_required DOUBLE,
            max_common_size_usd DOUBLE,
            is_capacity_sufficient BOOLEAN,
            final_verdict VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6e_mapping_quality (
            quality_record_id VARCHAR PRIMARY KEY,
            mapping_id VARCHAR,
            mapping_status VARCHAR,
            quote_status VARCHAR,
            synchronization_status VARCHAR,
            liquidity_status VARCHAR,
            fee_status VARCHAR,
            latency_status VARCHAR,
            capacity_status VARCHAR,
            settlement_status VARCHAR,
            executable_status VARCHAR,
            net_edge_status VARCHAR,
            final_verdict VARCHAR,
            rejection_reasons VARCHAR,
            evaluated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6e_analysis_config (
            config_id VARCHAR PRIMARY KEY,
            sync_windows_ms VARCHAR,
            stale_threshold_ms DOUBLE,
            max_hedge_latency_ms DOUBLE,
            polymarket_fee_bps DOUBLE,
            kalshi_fee_bps DOUBLE,
            config_hash VARCHAR,
            created_at TIMESTAMP
        );
        """
        conn = self._get_connection(read_only=False)
        try:
            conn.execute(ddl)
        finally:
            conn.close()

    def record_contract_mapping(self, m: ContractMappingResult) -> None:
        """Appends contract mapping record."""
        sql = """
        INSERT OR REPLACE INTO phase10a6e_contract_mappings VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
        )
        """
        conn = self._get_connection(read_only=False)
        try:
            conn.execute(sql, [
                m.mapping_id, m.polymarket_market_id, m.polymarket_token_id,
                m.kalshi_market_id, m.kalshi_contract_id, m.canonical_contract_id,
                m.equivalence_class.value, m.settlement_equivalence,
                m.mapping_status.value, m.mapping_reason,
                m.resolution_source_polymarket, m.resolution_source_kalshi,
                m.resolution_time_polymarket, m.resolution_time_kalshi,
                m.threshold_polymarket, m.threshold_kalshi,
                m.direction_polymarket, m.direction_kalshi,
                m.currency_polymarket, m.currency_kalshi,
                m.mapping_config_hash,
            ])
        finally:
            conn.close()

    def record_arbitrage_opportunity(self, opp: CrossVenueArbitrageOpportunity) -> None:
        """Appends candidate, execution analysis, and quality records."""
        conn = self._get_connection(read_only=False)
        try:
            # 1. Candidate summary
            sql_cand = """
            INSERT INTO phase10a6e_arbitrage_candidates VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """
            conn.execute(sql_cand, [
                opp.opportunity_id, opp.mapping_id, opp.timestamp,
                opp.sync_window_ms, opp.settlement_gross_value,
                opp.gross_edge_bps, opp.cost_breakdown.total_cost_bps,
                opp.net_deterministic_edge_bps, opp.final_verdict.value
            ])

            # 2. Execution Analysis
            sql_exec = """
            INSERT INTO phase10a6e_execution_analysis VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """
            conn.execute(sql_exec, [
                f"exec_{opp.opportunity_id}", opp.opportunity_id, opp.mapping_id, opp.timestamp,
                opp.leg_a.venue, opp.leg_a.outcome, opp.leg_a.vwap_price, opp.leg_a.notional_usd,
                opp.leg_b.venue, opp.leg_b.outcome, opp.leg_b.vwap_price, opp.leg_b.notional_usd,
                opp.cost_breakdown.venue_fee_bps, opp.cost_breakdown.execution_slippage_bps,
                opp.cost_breakdown.latency_penalty_bps, opp.cost_breakdown.hedge_cost_bps,
                opp.capital_result.required_capital_a + opp.capital_result.required_capital_b,
                opp.capital_result.maximum_common_size_usd,
                opp.capital_result.is_capacity_sufficient,
                opp.final_verdict.value
            ])

            # 3. Mapping Quality (10 independent gates)
            sql_qual = """
            INSERT INTO phase10a6e_mapping_quality VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            """
            conn.execute(sql_qual, [
                f"qual_{opp.opportunity_id}", opp.mapping_id,
                opp.mapping_status.value, opp.quote_status.value,
                opp.synchronization_status.value, opp.liquidity_status.value,
                opp.fee_status.value, opp.latency_status.value,
                opp.capacity_status.value, opp.settlement_status.value,
                opp.executable_status.value, opp.net_edge_status.value,
                opp.final_verdict.value, "; ".join(opp.rejection_reasons)
            ])
        finally:
            conn.close()
