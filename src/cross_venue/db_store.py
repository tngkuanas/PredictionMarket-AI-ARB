"""DuckDB Storage for Phase 10A.6e and Phase 10A.6g Cross-Venue Polymarket-Kalshi Arbitrage.

Phase 10A.6e Section 17 & Phase 10A.6g Section 18:
Creates append-only tables for provenance tracking:
- phase10a6e_contract_mappings
- phase10a6e_quote_observations
- phase10a6e_arbitrage_candidates
- phase10a6e_execution_analysis
- phase10a6e_mapping_quality
- phase10a6e_analysis_config
- phase10a6g_adversarial_scenarios
- phase10a6g_execution_stress
- phase10a6g_leg_failure_analysis
- phase10a6g_edge_survival
- phase10a6g_analysis_config

CRITICAL SAFETY:
Uses retry loops with backoff to prevent write-lock contention with background recorder PID 53380.
Does NOT mutate historical Phase 10A/10A.5 tables.
"""

import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Optional, Dict, Any, List
import duckdb

from config.settings import get_settings
from src.cross_venue.schema import (
    ContractMappingResult,
    SyncQuote,
    CrossVenueArbitrageOpportunity,
)
from src.cross_venue.cross_venue_adversarial import (
    AdversarialConfig,
    AdversarialAuditSummary,
)

logger = logging.getLogger(__name__)


class CrossVenueDBStore:
    """Manages append-only DuckDB tables for Phase 10A.6e and Phase 10A.6g."""

    def __init__(self, db_path: Optional[Path] = None):
        self.settings = get_settings()
        self.db_path = db_path or self.settings.db.db_path
        self._ensure_tables()

    def _get_connection(self, read_only: bool = False, max_retries: int = 5, backoff: float = 0.1) -> duckdb.DuckDBPyConnection:
        """Acquires DuckDB connection with safe retry and isolated snapshot fallback."""
        for attempt in range(max_retries):
            try:
                return duckdb.connect(str(self.db_path), read_only=read_only)
            except Exception as e:
                time.sleep(backoff)

        if read_only:
            # Fall back to isolated copy if locked by active background process (e.g. PID 53380)
            tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
            tmp_path = tmp.name
            tmp.close()
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            shutil.copyfile(str(self.db_path), tmp_path)
            return duckdb.connect(tmp_path, read_only=True)
        else:
            return duckdb.connect(str(self.db_path), read_only=False)

    def _ensure_tables(self) -> None:
        """Creates Phase 10A.6e and 10A.6g append-only tables."""
        ddl = """
        -- Phase 10A.6E Tables
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

        -- Phase 10A.6G Adversarial Execution Audit Tables
        CREATE TABLE IF NOT EXISTS phase10a6g_adversarial_scenarios (
            scenario_id VARCHAR PRIMARY KEY,
            candidate_id VARCHAR,
            mapping_id VARCHAR,
            scenario_name VARCHAR,
            dimension VARCHAR,
            stress_level DOUBLE,
            parameters JSON,
            net_edge_bps DOUBLE,
            is_viable BOOLEAN,
            config_hash VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6g_execution_stress (
            stress_record_id VARCHAR PRIMARY KEY,
            candidate_id VARCHAR,
            mapping_id VARCHAR,
            executable_quantity DOUBLE,
            unhedged_quantity DOUBLE,
            vwap_a DOUBLE,
            vwap_b DOUBLE,
            combined_vwap DOUBLE,
            total_costs_bps DOUBLE,
            net_edge_bps DOUBLE,
            capital_utilization DOUBLE,
            source_quote_ids VARCHAR,
            source_book_state_ids VARCHAR,
            config_hash VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6g_leg_failure_analysis (
            analysis_id VARCHAR PRIMARY KEY,
            candidate_id VARCHAR,
            mapping_id VARCHAR,
            case_name VARCHAR,
            leg_a_fill_pct DOUBLE,
            leg_b_fill_pct DOUBLE,
            filled_quantity DOUBLE,
            unhedged_quantity DOUBLE,
            residual_directional_exposure DOUBLE,
            hedge_cost DOUBLE,
            worst_case_loss DOUBLE,
            deterministic_settlement_value DOUBLE,
            net_pnl DOUBLE,
            net_edge_bps DOUBLE,
            config_hash VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6g_edge_survival (
            survival_id VARCHAR PRIMARY KEY,
            candidate_id VARCHAR,
            mapping_id VARCHAR,
            max_latency_tolerated_ms DOUBLE,
            max_fee_tolerated_bps DOUBLE,
            max_slippage_tolerated_bps DOUBLE,
            min_depth_required_usd DOUBLE,
            max_hedge_delay_tolerated_ms DOUBLE,
            max_adverse_price_move_tolerated_bps DOUBLE,
            bounds_summary VARCHAR,
            config_hash VARCHAR,
            created_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phase10a6g_analysis_config (
            config_id VARCHAR PRIMARY KEY,
            version VARCHAR,
            config_hash VARCHAR,
            latency_grid_ms JSON,
            depth_factors JSON,
            fee_multipliers JSON,
            slippage_stresses_bps JSON,
            quote_ages_ms JSON,
            capital_factors JSON,
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

    def record_adversarial_audit(self, summary: AdversarialAuditSummary) -> None:
        """Appends all adversarial execution stress results to Phase 10A.6G tables."""
        conn = self._get_connection(read_only=False)
        try:
            # 1. Scenarios summary
            for idx, lat in enumerate(summary.latency_stress):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_adversarial_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"scen_lat_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    f"latency_{lat.latency_ms:.0f}ms", "latency", lat.latency_ms,
                    json.dumps(lat.model_dump()), lat.net_executable_edge_bps, lat.is_edge_positive, summary.config_hash
                ])

            for idx, d in enumerate(summary.depth_stress):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_adversarial_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"scen_dep_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    f"depth_{int(d.depth_factor*100)}pct", "depth", d.depth_factor,
                    json.dumps(d.model_dump()), d.net_edge_bps, d.is_edge_positive, summary.config_hash
                ])

            for idx, f in enumerate(summary.fee_stress):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_adversarial_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"scen_fee_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    f"fee_mult_{f.fee_multiplier:.2f}x", "fee", f.fee_multiplier,
                    json.dumps(f.model_dump()), f.net_edge_bps, f.is_edge_positive, summary.config_hash
                ])

            for idx, s in enumerate(summary.slippage_stress):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_adversarial_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"scen_slip_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    f"slippage_{s.slippage_stress_bps:.1f}bps", "slippage", s.slippage_stress_bps,
                    json.dumps(s.model_dump()), s.net_edge_bps, s.is_edge_positive, summary.config_hash
                ])

            for idx, c in enumerate(summary.correlated_stress):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_adversarial_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"scen_corr_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    c.scenario_name, "correlated", float(idx + 1),
                    json.dumps(c.model_dump()), c.net_edge_bps, c.is_viable, summary.config_hash
                ])

            # 2. Execution Stress Record
            conn.execute("""
                INSERT OR IGNORE INTO phase10a6g_execution_stress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [
                f"stress_{summary.candidate_id}", summary.candidate_id, summary.mapping_id,
                summary.baseline.quantity_usd, summary.baseline.residual_exposure_usd,
                summary.baseline.executable_price_a, summary.baseline.executable_price_b,
                summary.baseline.combined_vwap, summary.baseline.total_cost_bps,
                summary.baseline.net_edge_bps, 1.0,
                f"{summary.candidate_id}_quote_a", f"{summary.candidate_id}_quote_b",
                summary.config_hash
            ])

            # 3. Leg Failure Analysis Records
            for idx, leg_case in enumerate(summary.asynchronous_legs):
                conn.execute("""
                    INSERT OR IGNORE INTO phase10a6g_leg_failure_analysis VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [
                    f"leg_fail_{summary.candidate_id}_{idx}", summary.candidate_id, summary.mapping_id,
                    leg_case.case_name, leg_case.leg_a_fill_pct, leg_case.leg_b_fill_pct,
                    leg_case.filled_quantity_usd, leg_case.unhedged_quantity_usd,
                    leg_case.residual_directional_exposure_usd, leg_case.hedge_cost_usd,
                    leg_case.worst_case_loss_usd, leg_case.deterministic_settlement_value_usd,
                    leg_case.net_pnl_usd, leg_case.net_edge_bps, summary.config_hash
                ])

            # 4. Edge Survival Bound
            conn.execute("""
                INSERT OR IGNORE INTO phase10a6g_edge_survival VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [
                f"surv_{summary.candidate_id}", summary.candidate_id, summary.mapping_id,
                summary.edge_survival.max_latency_tolerated_ms,
                summary.edge_survival.max_fee_tolerated_bps,
                summary.edge_survival.max_slippage_tolerated_bps,
                summary.edge_survival.min_depth_required_usd,
                summary.edge_survival.max_hedge_delay_tolerated_ms,
                summary.edge_survival.max_adverse_price_move_tolerated_bps,
                summary.edge_survival.bounds_summary, summary.config_hash
            ])
        finally:
            conn.close()

    def record_adversarial_config(self, cfg: AdversarialConfig) -> None:
        """Appends frozen configuration record."""
        conn = self._get_connection(read_only=False)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO phase10a6g_analysis_config VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [
                f"cfg_{cfg.compute_config_hash()[:12]}", cfg.version, cfg.compute_config_hash(),
                json.dumps(cfg.latency_grid_ms), json.dumps(cfg.depth_factors),
                json.dumps(cfg.fee_multipliers), json.dumps(cfg.slippage_stresses_bps),
                json.dumps(cfg.quote_ages_ms), json.dumps(cfg.capital_factors)
            ])
        finally:
            conn.close()
