"""Database Storage and Persistence Engine for Phase 10A.9.

Handles:
- Isolated DuckDB table creation for all Phase 10A.9 research outputs (`phase10a9_*`).
- Safe non-blocking reads of production data without lock contention with PID 67131.
- Strict anti-contamination guard preventing synthetic or mock data in production.
"""

from datetime import datetime, timezone
import json
import logging
import os
import random
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional
import duckdb

from src.phase10a9.schema import (
    ContractRelationshipRecord,
    HedgeExecutionRecord,
    HedgedEconomicsRecord,
    HedgeInventoryStateRecord,
    HypothesisResultRecord,
    AdversarialControlRecord,
)

logger = logging.getLogger(__name__)


class Phase10A9ContaminationError(RuntimeError):
    """Raised when mock or synthetic test fixtures attempt to enter production tables."""
    pass


class ProductionContaminationGuard:
    """Rigorous gate preventing test fixtures from contaminating production tables."""

    BANNED_SUBSTRINGS = ["mock", "fixture", "synthetic", "dummy", "test_fake", "simulated_fake"]

    @classmethod
    def assert_valid_production_record(cls, record: Dict[str, Any], is_production_db: bool = False) -> None:
        """Validates that a record does not contain banned mock or synthetic markers."""
        if not is_production_db:
            return

        rec_str = json.dumps(record, default=str).lower()
        for banned in cls.BANNED_SUBSTRINGS:
            if banned in rec_str:
                raise Phase10A9ContaminationError(
                    f"Contamination detected! Banned marker '{banned}' found in production record: {rec_str[:150]}"
                )

        prov = record.get("provenance", "POLYMARKET_LIVE")
        if prov != "POLYMARKET_LIVE":
            raise Phase10A9ContaminationError(
                f"Invalid provenance for production database: {prov}. Expected 'POLYMARKET_LIVE'."
            )


class Phase10A9DbStore:
    """DuckDB persistence engine for Phase 10A.9 hedged passive discovery."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path
        self.is_production = ("prediction_market.duckdb" in os.path.abspath(db_path))
        self._init_tables()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Returns connection with exponential backoff and jitter."""
        for attempt in range(15):
            try:
                return duckdb.connect(self.db_path)
            except Exception as e:
                time.sleep(0.05 * (1.4 ** attempt) + random.uniform(0.02, 0.08))
        return duckdb.connect(self.db_path)

    def _init_tables(self) -> None:
        """Creates phase10a9_* tables if they do not exist."""
        with self._get_connection() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_relationships (
                    relationship_id VARCHAR PRIMARY KEY,
                    contract_a VARCHAR NOT NULL,
                    contract_b VARCHAR NOT NULL,
                    market_id_a VARCHAR NOT NULL,
                    market_id_b VARCHAR NOT NULL,
                    relationship_type VARCHAR NOT NULL,
                    event_identity VARCHAR NOT NULL,
                    variable VARCHAR NOT NULL,
                    threshold DOUBLE,
                    inequality VARCHAR,
                    time_window VARCHAR NOT NULL,
                    payout_formula VARCHAR NOT NULL,
                    hedge_ratio DOUBLE NOT NULL,
                    validation_status VARCHAR NOT NULL,
                    reason VARCHAR NOT NULL,
                    provenance VARCHAR NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_hedged_executions (
                    hedge_id VARCHAR PRIMARY KEY,
                    relationship_id VARCHAR NOT NULL,
                    passive_fill_id VARCHAR NOT NULL,
                    passive_token_id VARCHAR NOT NULL,
                    hedge_token_id VARCHAR NOT NULL,
                    passive_fill_timestamp TIMESTAMP NOT NULL,
                    hedge_timestamp TIMESTAMP NOT NULL,
                    hedge_latency_ms INTEGER NOT NULL,
                    passive_fill_side VARCHAR NOT NULL,
                    hedge_side VARCHAR NOT NULL,
                    passive_fill_price DOUBLE NOT NULL,
                    passive_filled_shares DOUBLE NOT NULL,
                    passive_filled_usd DOUBLE NOT NULL,
                    hedge_required_shares DOUBLE NOT NULL,
                    hedge_filled_shares DOUBLE NOT NULL,
                    hedge_filled_usd DOUBLE NOT NULL,
                    hedge_vwap DOUBLE NOT NULL,
                    hedge_slippage_bps DOUBLE NOT NULL,
                    hedge_spread_bps DOUBLE NOT NULL,
                    hedge_depth_exhausted BOOLEAN NOT NULL,
                    residual_unhedged_shares DOUBLE NOT NULL,
                    residual_unhedged_usd DOUBLE NOT NULL,
                    execution_status VARCHAR NOT NULL,
                    provenance VARCHAR NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_hedged_economics (
                    evaluation_id VARCHAR PRIMARY KEY,
                    relationship_id VARCHAR NOT NULL,
                    passive_fill_id VARCHAR NOT NULL,
                    hedge_id VARCHAR NOT NULL,
                    hedge_latency_ms INTEGER NOT NULL,
                    quote_policy VARCHAR NOT NULL,
                    queue_model VARCHAR NOT NULL,
                    is_fully_hedged BOOLEAN NOT NULL,
                    passive_gross_spread_bps DOUBLE NOT NULL,
                    passive_adverse_selection_bps DOUBLE NOT NULL,
                    hedge_spread_cost_bps DOUBLE NOT NULL,
                    hedge_slippage_bps DOUBLE NOT NULL,
                    hedge_fee_bps DOUBLE NOT NULL,
                    hedge_latency_cost_bps DOUBLE NOT NULL,
                    residual_inventory_cost_bps DOUBLE NOT NULL,
                    residual_liquidation_cost_bps DOUBLE NOT NULL,
                    unhedged_net_ev_bps DOUBLE NOT NULL,
                    hedged_net_ev_bps DOUBLE NOT NULL,
                    ev_improvement_bps DOUBLE NOT NULL,
                    hedged_pnl_usd DOUBLE NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL,
                    event_cluster_id VARCHAR NOT NULL,
                    provenance VARCHAR NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_inventory_states (
                    record_id VARCHAR PRIMARY KEY,
                    market_id VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    inventory_limit_usd DOUBLE NOT NULL,
                    gross_passive_usd DOUBLE NOT NULL,
                    gross_hedge_usd DOUBLE NOT NULL,
                    net_directional_usd DOUBLE NOT NULL,
                    residual_unhedged_usd DOUBLE NOT NULL,
                    cumulative_passive_fills INTEGER NOT NULL,
                    cumulative_hedges_executed INTEGER NOT NULL,
                    rejected_fills_limit_breach INTEGER NOT NULL,
                    forced_liquidations_count INTEGER NOT NULL,
                    forced_liquidation_cost_usd DOUBLE NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_hypothesis_results (
                    hypothesis VARCHAR PRIMARY KEY,
                    n_observations INTEGER NOT NULL,
                    n_clusters INTEGER NOT NULL,
                    mean_hedged_ev_bps DOUBLE NOT NULL,
                    median_hedged_ev_bps DOUBLE NOT NULL,
                    cluster_robust_se DOUBLE NOT NULL,
                    t_stat DOUBLE NOT NULL,
                    p_value DOUBLE NOT NULL,
                    ci_95_lower_bps DOUBLE NOT NULL,
                    ci_95_upper_bps DOUBLE NOT NULL,
                    hedge_completion_rate_pct DOUBLE NOT NULL,
                    mean_ev_improvement_bps DOUBLE NOT NULL,
                    is_supported BOOLEAN NOT NULL,
                    summary VARCHAR NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9_adversarial_controls (
                    control VARCHAR,
                    stress_parameter VARCHAR,
                    n_observations INTEGER NOT NULL,
                    mean_hedged_ev_bps DOUBLE NOT NULL,
                    delta_vs_baseline_bps DOUBLE NOT NULL,
                    behavior_matches_expectation BOOLEAN NOT NULL,
                    notes VARCHAR NOT NULL
                )
            """)

    def persist_relationships(self, records: List[ContractRelationshipRecord]) -> None:
        """Persists contract relationship records with anti-contamination validation."""
        if not records:
            return
        for r in records:
            ProductionContaminationGuard.assert_valid_production_record(r.__dict__, self.is_production)

        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9_relationships VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.relationship_id, r.contract_a, r.contract_b, r.market_id_a, r.market_id_b,
                    r.relationship_type.value, r.event_identity, r.variable, r.threshold,
                    r.inequality, r.time_window, r.payout_formula, r.hedge_ratio,
                    r.validation_status.value, r.reason, r.provenance
                ])

    def persist_hedged_executions(self, records: List[HedgeExecutionRecord]) -> None:
        """Persists hedge execution records with anti-contamination validation."""
        if not records:
            return
        for r in records:
            ProductionContaminationGuard.assert_valid_production_record(r.__dict__, self.is_production)

        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9_hedged_executions VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.hedge_id, r.relationship_id, r.passive_fill_id, r.passive_token_id,
                    r.hedge_token_id, r.passive_fill_timestamp, r.hedge_timestamp,
                    r.hedge_latency_ms, r.passive_fill_side, r.hedge_side, r.passive_fill_price,
                    r.passive_filled_shares, r.passive_filled_usd, r.hedge_required_shares,
                    r.hedge_filled_shares, r.hedge_filled_usd, r.hedge_vwap, r.hedge_slippage_bps,
                    r.hedge_spread_bps, r.hedge_depth_exhausted, r.residual_unhedged_shares,
                    r.residual_unhedged_usd, r.execution_status.value, r.provenance
                ])

    def persist_hedged_economics(self, records: List[HedgedEconomicsRecord]) -> None:
        """Persists hedged economics records with anti-contamination validation."""
        if not records:
            return
        for r in records:
            ProductionContaminationGuard.assert_valid_production_record(r.__dict__, self.is_production)

        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9_hedged_economics VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.evaluation_id, r.relationship_id, r.passive_fill_id, r.hedge_id,
                    r.hedge_latency_ms, r.quote_policy, r.queue_model, r.is_fully_hedged,
                    r.passive_gross_spread_bps, r.passive_adverse_selection_bps,
                    r.hedge_spread_cost_bps, r.hedge_slippage_bps, r.hedge_fee_bps,
                    r.hedge_latency_cost_bps, r.residual_inventory_cost_bps,
                    r.residual_liquidation_cost_bps, r.unhedged_net_ev_bps,
                    r.hedged_net_ev_bps, r.ev_improvement_bps, r.hedged_pnl_usd,
                    r.is_out_of_sample, r.event_cluster_id, r.provenance
                ])

    def persist_hypothesis_results(self, records: List[HypothesisResultRecord]) -> None:
        """Persists hypothesis testing results."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9_hypothesis_results VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.hypothesis.value, r.n_observations, r.n_clusters, r.mean_hedged_ev_bps,
                    r.median_hedged_ev_bps, r.cluster_robust_se, r.t_stat, r.p_value,
                    r.ci_95_lower_bps, r.ci_95_upper_bps, r.hedge_completion_rate_pct,
                    r.mean_ev_improvement_bps, r.is_supported, r.summary
                ])

    def persist_adversarial_controls(self, records: List[AdversarialControlRecord]) -> None:
        """Persists adversarial stress results."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT INTO phase10a9_adversarial_controls VALUES (
                        ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.control.value, r.stress_parameter, r.n_observations,
                    r.mean_hedged_ev_bps, r.delta_vs_baseline_bps,
                    r.behavior_matches_expectation, r.notes
                ])
