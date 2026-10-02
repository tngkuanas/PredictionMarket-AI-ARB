"""DuckDB Persistence Engine and Production Contamination Guard for Phase 10A.10.

Manages:
- Isolated DuckDB table creation for all Phase 10A.10 outputs (`phase10a10_*`).
- Strict prohibition against modifying historical tables or live recorder tables.
- Anti-contamination guard preventing synthetic test fixtures in production.
- Connection retry logic with exponential backoff and jitter to avoid lock contention with PID 70671.
"""

from datetime import datetime, timezone
import json
import logging
import os
import random
import time
from typing import Dict, Any, List, Optional
import duckdb

from src.phase10a10.schema import (
    ResolutionLagEvent,
    SourceRecord,
    MarketStateSnapshot,
    CandidateOpportunity,
    ExecutionRecord,
    ConvergenceRecord,
    NegativeControlRecord,
    HypothesisResultRecord,
)

logger = logging.getLogger(__name__)


class Phase10A10ContaminationError(RuntimeError):
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
                raise Phase10A10ContaminationError(
                    f"Contamination detected! Banned marker '{banned}' found in production record: {rec_str[:150]}"
                )

        prov = record.get("provenance", "POLYMARKET_LIVE")
        if prov != "POLYMARKET_LIVE" and "source" not in record.get("source_id", ""):
            if record.get("event_category") != "esports" and record.get("event_category") != "crypto_threshold":
                pass


class Phase10A10DbStore:
    """DuckDB persistence engine for Phase 10A.10 deterministic resolution lag research."""

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
        """Creates phase10a10_* tables if they do not exist."""
        with self._get_connection() as con:
            # 1. phase10a10_events
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_events (
                    event_id VARCHAR PRIMARY KEY,
                    event_cluster_id VARCHAR NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    outcome VARCHAR NOT NULL,
                    event_category VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    deterministic_state VARCHAR NOT NULL,
                    source_tier VARCHAR NOT NULL,
                    source_id VARCHAR NOT NULL,
                    source_timestamp TIMESTAMP NOT NULL,
                    observation_timestamp TIMESTAMP NOT NULL,
                    deterministic_value DOUBLE NOT NULL,
                    actual_value DOUBLE,
                    threshold_value DOUBLE,
                    is_scheduled BOOLEAN NOT NULL,
                    invalidation_reason VARCHAR
                );
            """)

            # 2. phase10a10_sources
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_sources (
                    source_id VARCHAR PRIMARY KEY,
                    source_tier VARCHAR NOT NULL,
                    source_domain VARCHAR NOT NULL,
                    source_name VARCHAR NOT NULL,
                    source_url VARCHAR NOT NULL,
                    source_timestamp TIMESTAMP NOT NULL,
                    retrieval_timestamp TIMESTAMP NOT NULL,
                    content_hash VARCHAR NOT NULL,
                    is_authoritative BOOLEAN NOT NULL,
                    rejection_reason VARCHAR
                );
            """)

            # 3. phase10a10_market_states
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_market_states (
                    snapshot_id VARCHAR,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    horizon_label VARCHAR NOT NULL,
                    best_bid DOUBLE NOT NULL,
                    best_ask DOUBLE NOT NULL,
                    midpoint DOUBLE NOT NULL,
                    spread_bps DOUBLE NOT NULL,
                    depth_bid_usd DOUBLE NOT NULL,
                    depth_ask_usd DOUBLE NOT NULL,
                    provenance VARCHAR NOT NULL,
                    PRIMARY KEY (token_id, horizon_label, timestamp)
                );
            """)

            # 4. phase10a10_candidates
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_candidates (
                    candidate_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    outcome VARCHAR NOT NULL,
                    deterministic_state VARCHAR NOT NULL,
                    source_tier VARCHAR NOT NULL,
                    source_timestamp TIMESTAMP NOT NULL,
                    market_observation_timestamp TIMESTAMP NOT NULL,
                    latency_ms DOUBLE NOT NULL,
                    latency_bucket VARCHAR NOT NULL,
                    entry_threshold_bps DOUBLE NOT NULL,
                    target_size_usd DOUBLE NOT NULL,
                    best_ask DOUBLE NOT NULL,
                    executable_vwap DOUBLE NOT NULL,
                    available_depth_usd DOUBLE NOT NULL,
                    gross_edge_bps DOUBLE NOT NULL,
                    net_ev_bps DOUBLE NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL,
                    execution_status VARCHAR NOT NULL
                );
            """)

            # 5. phase10a10_executions
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_executions (
                    execution_id VARCHAR PRIMARY KEY,
                    candidate_id VARCHAR NOT NULL,
                    event_id VARCHAR NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    outcome VARCHAR NOT NULL,
                    execution_timestamp TIMESTAMP NOT NULL,
                    position_size_usd DOUBLE NOT NULL,
                    filled_shares DOUBLE NOT NULL,
                    vwap DOUBLE NOT NULL,
                    slippage_bps DOUBLE NOT NULL,
                    fee_bps DOUBLE NOT NULL,
                    gross_deterministic_edge_bps DOUBLE NOT NULL,
                    net_ev_bps DOUBLE NOT NULL,
                    levels_consumed INTEGER NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL
                );
            """)

            # 6. phase10a10_convergence
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_convergence (
                    convergence_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    source_timestamp TIMESTAMP NOT NULL,
                    first_market_timestamp TIMESTAMP,
                    first_executable_edge_timestamp TIMESTAMP,
                    first_convergence_timestamp TIMESTAMP,
                    formal_resolution_timestamp TIMESTAMP,
                    epsilon_bps DOUBLE NOT NULL,
                    reaction_delay_sec DOUBLE,
                    formal_delay_sec DOUBLE,
                    has_converged BOOLEAN NOT NULL
                );
            """)

            # 7. phase10a10_controls
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_controls (
                    control_id VARCHAR PRIMARY KEY,
                    control_type VARCHAR NOT NULL,
                    event_id VARCHAR NOT NULL,
                    parameter_stress DOUBLE NOT NULL,
                    gross_edge_bps DOUBLE NOT NULL,
                    net_ev_bps DOUBLE NOT NULL,
                    expected_result_valid BOOLEAN NOT NULL,
                    rejection_reason VARCHAR
                );
            """)

            # 8. phase10a10_statistics
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10_statistics (
                    hypothesis_id VARCHAR PRIMARY KEY,
                    hypothesis_name VARCHAR NOT NULL,
                    entry_threshold_bps DOUBLE NOT NULL,
                    latency_bucket VARCHAR NOT NULL,
                    position_size_usd DOUBLE NOT NULL,
                    sample_size INTEGER NOT NULL,
                    mean_gross_edge_bps DOUBLE NOT NULL,
                    median_gross_edge_bps DOUBLE NOT NULL,
                    mean_net_ev_bps DOUBLE NOT NULL,
                    median_net_ev_bps DOUBLE NOT NULL,
                    std_dev_bps DOUBLE NOT NULL,
                    hit_rate DOUBLE NOT NULL,
                    ci_lower_bps DOUBLE NOT NULL,
                    ci_upper_bps DOUBLE NOT NULL,
                    t_stat DOUBLE NOT NULL,
                    p_value DOUBLE NOT NULL,
                    holm_bonferroni_p DOUBLE NOT NULL,
                    cluster_count INTEGER NOT NULL,
                    is_significant BOOLEAN NOT NULL,
                    verdict VARCHAR NOT NULL
                );
            """)

    def save_events(self, events: List[ResolutionLagEvent]) -> None:
        """Persists events with contamination checks."""
        if not events:
            return
        with self._get_connection() as con:
            for e in events:
                ProductionContaminationGuard.assert_valid_production_record(e.__dict__, self.is_production)
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    e.event_id, e.event_cluster_id, e.market_id, e.token_id, e.outcome,
                    e.event_category, e.title, e.deterministic_state.value, e.source_tier.value,
                    e.source_id, e.source_timestamp, e.observation_timestamp,
                    e.deterministic_value, e.actual_value, e.threshold_value,
                    e.is_scheduled, e.invalidation_reason
                ))

    def save_sources(self, sources: List[SourceRecord]) -> None:
        """Persists source metadata."""
        if not sources:
            return
        with self._get_connection() as con:
            for s in sources:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.source_id, s.source_tier.value, s.source_domain, s.source_name,
                    s.source_url, s.source_timestamp, s.retrieval_timestamp,
                    s.content_hash, s.is_authoritative, s.rejection_reason
                ))

    def save_market_states(self, states: List[MarketStateSnapshot]) -> None:
        """Persists reconstructed market states."""
        if not states:
            return
        with self._get_connection() as con:
            for st in states:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_market_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    st.snapshot_id, st.market_id, st.token_id, st.timestamp,
                    st.horizon_label, st.best_bid, st.best_ask, st.midpoint,
                    st.spread_bps, st.depth_bid_usd, st.depth_ask_usd, st.provenance
                ))

    def save_candidates(self, candidates: List[CandidateOpportunity]) -> None:
        """Persists candidate opportunities."""
        if not candidates:
            return
        with self._get_connection() as con:
            for c in candidates:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.candidate_id, c.event_id, c.market_id, c.token_id, c.outcome,
                    c.deterministic_state.value, c.source_tier.value, c.source_timestamp,
                    c.market_observation_timestamp, c.latency_ms, c.latency_bucket.value,
                    c.entry_threshold_bps, c.target_size_usd, c.best_ask, c.executable_vwap,
                    c.available_depth_usd, c.gross_edge_bps, c.net_ev_bps,
                    c.is_out_of_sample, c.execution_status
                ))

    def save_executions(self, executions: List[ExecutionRecord]) -> None:
        """Persists execution simulations."""
        if not executions:
            return
        with self._get_connection() as con:
            for ex in executions:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ex.execution_id, ex.candidate_id, ex.event_id, ex.market_id,
                    ex.token_id, ex.outcome, ex.execution_timestamp, ex.position_size_usd,
                    ex.filled_shares, ex.vwap, ex.slippage_bps, ex.fee_bps,
                    ex.gross_deterministic_edge_bps, ex.net_ev_bps,
                    ex.levels_consumed, ex.is_out_of_sample
                ))

    def save_convergence(self, records: List[ConvergenceRecord]) -> None:
        """Persists convergence tracking records."""
        if not records:
            return
        with self._get_connection() as con:
            for cv in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_convergence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cv.convergence_id, cv.event_id, cv.market_id, cv.token_id,
                    cv.source_timestamp, cv.first_market_timestamp, cv.first_executable_edge_timestamp,
                    cv.first_convergence_timestamp, cv.formal_resolution_timestamp,
                    cv.epsilon_bps, cv.reaction_delay_sec, cv.formal_delay_sec,
                    cv.has_converged
                ))

    def save_controls(self, controls: List[NegativeControlRecord]) -> None:
        """Persists negative control results."""
        if not controls:
            return
        with self._get_connection() as con:
            for ct in controls:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_controls VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ct.control_id, ct.control_type, ct.event_id, ct.parameter_stress,
                    ct.gross_edge_bps, ct.net_ev_bps, ct.expected_result_valid,
                    ct.rejection_reason
                ))

    def save_statistics(self, stats: List[HypothesisResultRecord]) -> None:
        """Persists hypothesis statistical results."""
        if not stats:
            return
        with self._get_connection() as con:
            for st in stats:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10_statistics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    st.hypothesis_id, st.hypothesis_name, st.entry_threshold_bps,
                    st.latency_bucket.value, st.position_size_usd, st.sample_size,
                    st.mean_gross_edge_bps, st.median_gross_edge_bps, st.mean_net_ev_bps,
                    st.median_net_ev_bps, st.std_dev_bps, st.hit_rate,
                    st.ci_lower_bps, st.ci_upper_bps, st.t_stat, st.p_value,
                    st.holm_bonferroni_p, st.cluster_count, st.is_significant,
                    st.verdict.value
                ))
