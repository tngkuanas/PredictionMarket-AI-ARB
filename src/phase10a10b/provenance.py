"""Persistence and Anti-Contamination Engine for Phase 10A.10-B.

Manages:
- Creation and persistence of new tables:
  - phase10a10b_event_universe
  - phase10a10b_source_evidence
  - phase10a10b_market_mapping
  - phase10a10b_event_independence
  - phase10a10b_config
  - phase10a10b_rejections
- Strict prohibition against modifying previous Phase 10A.x tables or live recorder tables.
- ProductionContaminationGuard checking all records before write.
- Retry connection with backoff to prevent locking conflicts with live daemon PID 70671.
"""

from datetime import datetime, timezone
import json
import logging
import os
import random
import time
from typing import Dict, Any, List, Optional
import duckdb

from src.phase10a10b.universe import (
    ExpandedEventRecord,
    SourceEvidenceRecord,
    MarketMappingRecord,
    EventIndependenceRecord,
    CandidateRejectionRecord,
)
from src.phase10a10b.config_freeze import PHASE10A10B_CONFIG_HASH, FROZEN_PHASE10A10_CONFIG
from src.phase10a10.db_store import ProductionContaminationGuard, Phase10A10ContaminationError

logger = logging.getLogger(__name__)


class Phase10A10BDbStore:
    """DuckDB store managing all phase10a10b_* tables."""

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
        """Creates phase10a10b_* tables."""
        with self._get_connection() as con:
            # 1. phase10a10b_event_universe
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_event_universe (
                    event_id VARCHAR PRIMARY KEY,
                    source_event_id VARCHAR NOT NULL,
                    event_family VARCHAR NOT NULL,
                    category VARCHAR NOT NULL,
                    title VARCHAR NOT NULL,
                    source_tier VARCHAR NOT NULL,
                    source_timestamp TIMESTAMP NOT NULL,
                    source_observation_timestamp TIMESTAMP NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    winning_outcome VARCHAR NOT NULL,
                    deterministic_state VARCHAR NOT NULL,
                    deterministic_settlement_value DOUBLE NOT NULL,
                    actual_value DOUBLE,
                    threshold_value DOUBLE,
                    is_out_of_sample BOOLEAN NOT NULL,
                    cluster_5m_id VARCHAR NOT NULL,
                    cluster_1m_id VARCHAR NOT NULL,
                    provenance VARCHAR NOT NULL
                );
            """)

            # 2. phase10a10b_source_evidence
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_source_evidence (
                    source_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    source_url VARCHAR NOT NULL,
                    source_domain VARCHAR NOT NULL,
                    source_tier VARCHAR NOT NULL,
                    published_at TIMESTAMP NOT NULL,
                    source_observation_timestamp TIMESTAMP NOT NULL,
                    retrieved_at TIMESTAMP NOT NULL,
                    content_hash VARCHAR NOT NULL,
                    raw_payload_snippet VARCHAR NOT NULL,
                    is_verified BOOLEAN NOT NULL
                );
            """)

            # 3. phase10a10b_market_mapping
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_market_mapping (
                    mapping_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    market_title VARCHAR NOT NULL,
                    condition_text VARCHAR NOT NULL,
                    resolved_outcome VARCHAR NOT NULL,
                    mapping_confidence DOUBLE NOT NULL,
                    is_exact_match BOOLEAN NOT NULL
                );
            """)

            # 4. phase10a10b_event_independence
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_event_independence (
                    event_id VARCHAR PRIMARY KEY,
                    market_id VARCHAR NOT NULL,
                    source_event_id VARCHAR NOT NULL,
                    event_family VARCHAR NOT NULL,
                    event_date VARCHAR NOT NULL,
                    cluster_5m VARCHAR NOT NULL,
                    cluster_1m VARCHAR NOT NULL,
                    is_independent_event BOOLEAN NOT NULL
                );
            """)

            # 5. phase10a10b_config
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_config (
                    config_key VARCHAR PRIMARY KEY,
                    config_hash VARCHAR NOT NULL,
                    frozen_config_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );
            """)

            # 6. phase10a10b_rejections
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a10b_rejections (
                    candidate_id VARCHAR PRIMARY KEY,
                    market_id VARCHAR NOT NULL,
                    event_type VARCHAR NOT NULL,
                    rejection_reason VARCHAR NOT NULL,
                    rejection_stage VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    detail VARCHAR
                );
            """)

            # Save frozen configuration
            con.execute("""
                INSERT OR REPLACE INTO phase10a10b_config VALUES (?, ?, ?, ?)
            """, (
                "phase10a10_frozen_strategy",
                PHASE10A10B_CONFIG_HASH,
                json.dumps(FROZEN_PHASE10A10_CONFIG, sort_keys=True),
                datetime.now(timezone.utc)
            ))

    def save_events(self, events: List[ExpandedEventRecord]) -> None:
        """Saves expanded events with anti-contamination assertion."""
        if not events:
            return
        with self._get_connection() as con:
            for e in events:
                ProductionContaminationGuard.assert_valid_production_record(e.__dict__, self.is_production)
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10b_event_universe VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    e.event_id, e.source_event_id, e.event_family, e.category.value,
                    e.title, e.source_tier, e.source_timestamp, e.source_observation_timestamp,
                    e.market_id, e.token_id, e.winning_outcome, e.deterministic_state,
                    e.deterministic_settlement_value, e.actual_value, e.threshold_value,
                    e.is_out_of_sample, e.cluster_5m_id, e.cluster_1m_id, e.provenance
                ))

    def save_sources(self, sources: List[SourceEvidenceRecord]) -> None:
        """Saves source evidence records."""
        if not sources:
            return
        with self._get_connection() as con:
            for s in sources:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10b_source_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.source_id, s.event_id, s.source_url, s.source_domain, s.source_tier,
                    s.published_at, s.source_observation_timestamp, s.retrieved_at,
                    s.content_hash, s.raw_payload_snippet, s.is_verified
                ))

    def save_mappings(self, mappings: List[MarketMappingRecord]) -> None:
        """Saves market mapping records."""
        if not mappings:
            return
        with self._get_connection() as con:
            for m in mappings:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10b_market_mapping VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    m.mapping_id, m.event_id, m.market_id, m.token_id, m.market_title,
                    m.condition_text, m.resolved_outcome, m.mapping_confidence, m.is_exact_match
                ))

    def save_independence(self, records: List[EventIndependenceRecord]) -> None:
        """Saves event independence records."""
        if not records:
            return
        with self._get_connection() as con:
            for r in records:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10b_event_independence VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.event_id, r.market_id, r.source_event_id, r.event_family,
                    r.event_date, r.cluster_5m, r.cluster_1m, r.is_independent_event
                ))

    def save_rejections(self, rejections: List[CandidateRejectionRecord]) -> None:
        """Saves candidate rejections."""
        if not rejections:
            return
        with self._get_connection() as con:
            for r in rejections:
                con.execute("""
                    INSERT OR REPLACE INTO phase10a10b_rejections VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    r.candidate_id, r.market_id, r.event_type, r.rejection_reason.value,
                    r.rejection_stage, r.timestamp, r.detail
                ))
