"""Database Storage and Persistence Engine for Phase 10A.9-B Revalidation.

Handles:
- Isolated DuckDB table creation for all Phase 10A.9-B outputs (`phase10a9b_*`).
- Hard prohibition against modifying or overwriting `phase10a9_*` or Phase 10A.5 data.
- Strict anti-contamination guard preventing synthetic or mock data in production.
- Connection retry logic to avoid lock contention with live recorder PID 70671.
"""

from datetime import datetime, timezone
import json
import logging
import os
import random
import time
from typing import Dict, Any, List, Optional
import duckdb

from src.phase10a9b.schema import (
    CausalHedgeExecutionRecord,
    CausalHedgedEconomicsRecord,
    CausalLatencyGridRecord,
    CausalAdversarialControlRecord,
    CausalHypothesisResultRecord,
)

logger = logging.getLogger(__name__)


class Phase10A9BContaminationError(RuntimeError):
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
                raise Phase10A9BContaminationError(
                    f"Contamination detected! Banned marker '{banned}' found in production record: {rec_str[:150]}"
                )

        prov = record.get("provenance", "POLYMARKET_LIVE")
        if prov != "POLYMARKET_LIVE":
            raise Phase10A9BContaminationError(
                f"Invalid provenance for production database: {prov}. Expected 'POLYMARKET_LIVE'."
            )


class Phase10A9BDbStore:
    """DuckDB persistence engine for Phase 10A.9-B forward-causal revalidation."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path
        self.is_production = ("prediction_market.duckdb" in os.path.abspath(db_path))
        self._init_tables()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Returns connection with exponential backoff and jitter."""
        for attempt in range(15):
            try:
                return duckdb.connect(self.db_path)
            except Exception:
                time.sleep(0.05 * (1.4 ** attempt) + random.uniform(0.02, 0.08))
        return duckdb.connect(self.db_path)

    def _init_tables(self) -> None:
        """Creates phase10a9b_* tables if they do not exist."""
        with self._get_connection() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9b_hedged_executions (
                    hedge_id VARCHAR PRIMARY KEY,
                    relationship_id VARCHAR NOT NULL,
                    passive_fill_id VARCHAR NOT NULL,
                    passive_token_id VARCHAR NOT NULL,
                    hedge_token_id VARCHAR NOT NULL,
                    passive_fill_timestamp TIMESTAMP NOT NULL,
                    hedge_latency_ms INTEGER NOT NULL,
                    hedge_target_timestamp TIMESTAMP NOT NULL,
                    selected_snapshot_timestamp TIMESTAMP,
                    snapshot_delta_ms DOUBLE NOT NULL,
                    snapshot_was_forward BOOLEAN NOT NULL,
                    passive_fill_side VARCHAR NOT NULL,
                    hedge_side VARCHAR NOT NULL,
                    passive_fill_price DOUBLE NOT NULL,
                    passive_filled_shares DOUBLE NOT NULL,
                    passive_filled_usd DOUBLE NOT NULL,
                    required_quantity DOUBLE NOT NULL,
                    available_quantity DOUBLE NOT NULL,
                    filled_quantity DOUBLE NOT NULL,
                    VWAP DOUBLE NOT NULL,
                    hedge_slippage_bps DOUBLE NOT NULL,
                    hedge_spread_bps DOUBLE NOT NULL,
                    hedge_status VARCHAR NOT NULL,
                    residual_unhedged_shares DOUBLE NOT NULL,
                    residual_unhedged_usd DOUBLE NOT NULL,
                    pre_target_rejected_count INTEGER NOT NULL,
                    provenance VARCHAR NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9b_hedged_economics (
                    evaluation_id VARCHAR PRIMARY KEY,
                    relationship_id VARCHAR NOT NULL,
                    passive_fill_id VARCHAR NOT NULL,
                    hedge_id VARCHAR NOT NULL,
                    hedge_latency_ms INTEGER NOT NULL,
                    quote_policy VARCHAR NOT NULL,
                    queue_model VARCHAR NOT NULL,
                    hedge_status VARCHAR NOT NULL,
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
                CREATE TABLE IF NOT EXISTS phase10a9b_latency_grid (
                    latency_ms INTEGER PRIMARY KEY,
                    n_passive_fills INTEGER NOT NULL,
                    completed_count INTEGER NOT NULL,
                    partial_count INTEGER NOT NULL,
                    failed_no_book_count INTEGER NOT NULL,
                    failed_depth_count INTEGER NOT NULL,
                    completion_rate_pct DOUBLE NOT NULL,
                    mean_hedge_vwap DOUBLE NOT NULL,
                    mean_hedge_cost_bps DOUBLE NOT NULL,
                    mean_residual_cost_bps DOUBLE NOT NULL,
                    net_hedged_ev_bps DOUBLE NOT NULL
                )
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a9b_hypothesis_results (
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
                CREATE TABLE IF NOT EXISTS phase10a9b_adversarial_controls (
                    control VARCHAR,
                    stress_parameter VARCHAR,
                    n_observations INTEGER NOT NULL,
                    mean_hedged_ev_bps DOUBLE NOT NULL,
                    delta_vs_baseline_bps DOUBLE NOT NULL,
                    behavior_matches_expectation BOOLEAN NOT NULL,
                    notes VARCHAR NOT NULL
                )
            """)

    def persist_causal_executions(self, records: List[CausalHedgeExecutionRecord]) -> None:
        """Persists causal hedge execution records with anti-contamination validation."""
        if not records:
            return
        for r in records:
            ProductionContaminationGuard.assert_valid_production_record(r.model_dump(), self.is_production)

        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9b_hedged_executions VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.hedge_id, r.relationship_id, r.passive_fill_id, r.passive_token_id,
                    r.hedge_token_id, r.passive_fill_timestamp, r.hedge_latency_ms,
                    r.hedge_target_timestamp, r.selected_snapshot_timestamp,
                    r.snapshot_delta_ms, r.snapshot_was_forward, r.passive_fill_side,
                    r.hedge_side, r.passive_fill_price, r.passive_filled_shares,
                    r.passive_filled_usd, r.required_quantity, r.available_quantity,
                    r.filled_quantity, r.VWAP, r.hedge_slippage_bps, r.hedge_spread_bps,
                    r.hedge_status.value, r.residual_unhedged_shares, r.residual_unhedged_usd,
                    r.pre_target_rejected_count, r.provenance
                ])

    def persist_causal_economics(self, records: List[CausalHedgedEconomicsRecord]) -> None:
        """Persists hedged economics records with anti-contamination validation."""
        if not records:
            return
        for r in records:
            ProductionContaminationGuard.assert_valid_production_record(r.model_dump(), self.is_production)

        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9b_hedged_economics VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.evaluation_id, r.relationship_id, r.passive_fill_id, r.hedge_id,
                    r.hedge_latency_ms, r.quote_policy, r.queue_model, r.hedge_status.value,
                    r.is_fully_hedged, r.passive_gross_spread_bps, r.passive_adverse_selection_bps,
                    r.hedge_spread_cost_bps, r.hedge_slippage_bps, r.hedge_fee_bps,
                    r.hedge_latency_cost_bps, r.residual_inventory_cost_bps,
                    r.residual_liquidation_cost_bps, r.unhedged_net_ev_bps,
                    r.hedged_net_ev_bps, r.ev_improvement_bps, r.hedged_pnl_usd,
                    r.is_out_of_sample, r.event_cluster_id, r.provenance
                ])

    def persist_latency_grid(self, records: List[CausalLatencyGridRecord]) -> None:
        """Persists latency grid records."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9b_latency_grid VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.latency_ms, r.n_passive_fills, r.completed_count, r.partial_count,
                    r.failed_no_book_count, r.failed_depth_count, r.completion_rate_pct,
                    r.mean_hedge_vwap, r.mean_hedge_cost_bps, r.mean_residual_cost_bps,
                    r.net_hedged_ev_bps
                ])

    def persist_hypothesis_results(self, records: List[CausalHypothesisResultRecord]) -> None:
        """Persists hypothesis test results."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a9b_hypothesis_results VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.hypothesis, r.n_observations, r.n_clusters, r.mean_hedged_ev_bps,
                    r.median_hedged_ev_bps, r.cluster_robust_se, r.t_stat, r.p_value,
                    r.ci_95_lower_bps, r.ci_95_upper_bps, r.hedge_completion_rate_pct,
                    r.mean_ev_improvement_bps, r.is_supported, r.summary
                ])

    def persist_adversarial_controls(self, records: List[CausalAdversarialControlRecord]) -> None:
        """Persists adversarial controls results."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT INTO phase10a9b_adversarial_controls VALUES (
                        ?, ?, ?, ?, ?, ?, ?
                    )
                """, [
                    r.control, r.stress_parameter, r.n_observations,
                    r.mean_hedged_ev_bps, r.delta_vs_baseline_bps,
                    r.behavior_matches_expectation, r.notes
                ])
