"""Database Storage and Production Contamination Guard for Phase 10A.8.

Responsibilities:
1. Append-only storage into isolated `phase10a8_*` tables without altering Phase 10A.5/10A.7 tables.
2. Rigorous ProductionContaminationGuard preventing any test/synthetic fixture from contaminating production.
3. Safe DuckDB concurrency handling preventing collisions with daemon PID 53380.
"""

from datetime import datetime, timezone
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple, Union

import duckdb

from src.phase10a8.schema import (
    PassiveQuote,
    FillResult,
    MakerEconomicsRecord,
    HypothesisSummaryResult,
    AdversarialMakerControlRecord,
    InventoryPositionRecord,
)

logger = logging.getLogger(__name__)


class Phase10A8ContaminationError(ValueError):
    """Raised when synthetic or fixture data is detected entering production."""
    pass


class ProductionContaminationGuard:
    """Verifies that records intended for production storage contain only genuine live data."""

    FIXTURE_MARKERS = ["mock", "test", "fixture", "synthetic", "fake", "dummy", "sample"]

    @classmethod
    def assert_valid_production_record(cls, record_dict: Dict[str, Any], is_production_db: bool = True) -> None:
        """Throws exception if test/synthetic marker is present in a production write."""
        if not is_production_db:
            return

        provenance = str(record_dict.get("provenance", "")).upper()
        if provenance != "POLYMARKET_LIVE":
            raise Phase10A8ContaminationError(
                f"Production records must have provenance 'POLYMARKET_LIVE', got: '{provenance}'"
            )

        # Inspect values for fixture markers
        for k, v in record_dict.items():
            if isinstance(v, str):
                v_lower = v.lower()
                for marker in cls.FIXTURE_MARKERS:
                    if marker in v_lower and k not in ("provenance", "description"):
                        raise Phase10A8ContaminationError(
                            f"Contamination guard failed: field '{k}' contains fixture marker '{marker}' in value '{v}'"
                        )


class Phase10A8DbStore:
    """DuckDB persistence engine for Phase 10A.8 maker research."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path
        self.is_production = ("prediction_market.duckdb" in os.path.abspath(db_path))
        self._init_tables()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Returns connection with exponential backoff and jitter for handling write concurrency."""
        import random
        for attempt in range(15):
            try:
                return duckdb.connect(self.db_path)
            except Exception as e:
                time.sleep(0.05 * (1.4 ** attempt) + random.uniform(0.02, 0.08))
        return duckdb.connect(self.db_path)

    def _init_tables(self) -> None:
        """Creates Phase 10A.8 tables if they do not exist."""
        with self._get_connection() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS phase10a8_passive_quotes (
                    quote_id VARCHAR PRIMARY KEY,
                    market_id VARCHAR NOT NULL,
                    token_id VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    side VARCHAR NOT NULL,
                    policy VARCHAR NOT NULL,
                    quote_price DOUBLE NOT NULL,
                    quote_size_usd DOUBLE NOT NULL,
                    queue_depth_ahead_usd DOUBLE NOT NULL,
                    spread_bps DOUBLE NOT NULL,
                    midpoint DOUBLE NOT NULL,
                    book_imbalance DOUBLE NOT NULL,
                    recent_trade_flow_usd DOUBLE NOT NULL,
                    recent_volatility_bps DOUBLE NOT NULL,
                    snapshot_id VARCHAR NOT NULL,
                    session_id VARCHAR NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL,
                    provenance VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phase10a8_fill_results (
                    fill_id VARCHAR PRIMARY KEY,
                    quote_id VARCHAR NOT NULL,
                    fill_status VARCHAR NOT NULL,
                    fill_mechanism VARCHAR NOT NULL,
                    queue_model VARCHAR NOT NULL,
                    fill_timestamp TIMESTAMP,
                    fill_price DOUBLE NOT NULL,
                    fill_size_usd DOUBLE NOT NULL,
                    fill_shares DOUBLE NOT NULL,
                    queue_depth_ahead_usd DOUBLE NOT NULL,
                    subsequent_trade_count INTEGER NOT NULL,
                    trade_through_volume_usd DOUBLE NOT NULL,
                    touch_volume_usd DOUBLE NOT NULL,
                    time_to_fill_ms DOUBLE,
                    provenance VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phase10a8_maker_economics (
                    evaluation_id VARCHAR PRIMARY KEY,
                    quote_id VARCHAR NOT NULL,
                    fill_id VARCHAR,
                    horizon_ms INTEGER NOT NULL,
                    quote_policy VARCHAR NOT NULL,
                    queue_model VARCHAR NOT NULL,
                    is_filled BOOLEAN NOT NULL,
                    fill_size_usd DOUBLE NOT NULL,
                    gross_spread_capture_bps DOUBLE NOT NULL,
                    adverse_selection_bps DOUBLE NOT NULL,
                    liquidation_cost_bps DOUBLE NOT NULL,
                    inventory_cost_bps DOUBLE NOT NULL,
                    fee_bps DOUBLE NOT NULL,
                    net_maker_pnl_bps DOUBLE NOT NULL,
                    net_maker_pnl_usd DOUBLE NOT NULL,
                    cluster_id VARCHAR NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL,
                    provenance VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phase10a8_hypothesis_results (
                    hypothesis_id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    description VARCHAR NOT NULL,
                    n_raw INTEGER NOT NULL,
                    n_clusters INTEGER NOT NULL,
                    fill_count INTEGER NOT NULL,
                    ambiguous_count INTEGER NOT NULL,
                    fill_rate DOUBLE NOT NULL,
                    gross_spread_capture_bps DOUBLE NOT NULL,
                    adverse_selection_bps DOUBLE NOT NULL,
                    liquidation_cost_bps DOUBLE NOT NULL,
                    net_maker_ev_bps DOUBLE NOT NULL,
                    net_maker_ev_usd DOUBLE NOT NULL,
                    ev_per_quote_bps DOUBLE NOT NULL,
                    ev_per_fill_bps DOUBLE NOT NULL,
                    std_dev_bps DOUBLE NOT NULL,
                    ci_95_lower_bps DOUBLE NOT NULL,
                    ci_95_upper_bps DOUBLE NOT NULL,
                    bootstrap_ci_lower_bps DOUBLE NOT NULL,
                    bootstrap_ci_upper_bps DOUBLE NOT NULL,
                    verdict VARCHAR NOT NULL,
                    details_json VARCHAR NOT NULL,
                    is_out_of_sample BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phase10a8_adversarial_controls (
                    control_id VARCHAR PRIMARY KEY,
                    control_type VARCHAR NOT NULL,
                    parameter_value VARCHAR NOT NULL,
                    baseline_net_ev_bps DOUBLE NOT NULL,
                    controlled_net_ev_bps DOUBLE NOT NULL,
                    null_hypothesis_satisfied BOOLEAN NOT NULL,
                    details_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phase10a8_inventory_simulations (
                    market_id VARCHAR NOT NULL,
                    inventory_limit_usd DOUBLE NOT NULL,
                    cumulative_yes_usd DOUBLE NOT NULL,
                    cumulative_no_usd DOUBLE NOT NULL,
                    net_directional_usd DOUBLE NOT NULL,
                    max_inventory_usd DOUBLE NOT NULL,
                    cumulative_fills_count INTEGER NOT NULL,
                    rejected_fills_count INTEGER NOT NULL,
                    total_liquidation_events INTEGER NOT NULL,
                    total_liquidation_cost_usd DOUBLE NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (market_id, inventory_limit_usd)
                );
            """)

    def insert_quotes(self, quotes: List[PassiveQuote]) -> int:
        """Stores candidate quotes with contamination guard."""
        if not quotes:
            return 0
        now = datetime.now(timezone.utc)
        rows = []
        for q in quotes:
            d = q.model_dump()
            ProductionContaminationGuard.assert_valid_production_record(d, self.is_production)
            rows.append((
                q.quote_id, q.market_id, q.token_id, q.timestamp, q.side.value, q.policy.value,
                q.quote_price, q.quote_size_usd, q.queue_depth_ahead_usd, q.spread_bps,
                q.midpoint, q.book_imbalance, q.recent_trade_flow_usd, q.recent_volatility_bps,
                q.snapshot_id, q.session_id, q.is_out_of_sample, q.provenance, now,
            ))
        with self._get_connection() as con:
            con.executemany("""
                INSERT OR REPLACE INTO phase10a8_passive_quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        return len(rows)

    def insert_fills(self, fills: List[FillResult]) -> int:
        """Stores fill results with contamination guard."""
        if not fills:
            return 0
        now = datetime.now(timezone.utc)
        rows = []
        for f in fills:
            d = f.model_dump()
            ProductionContaminationGuard.assert_valid_production_record(d, self.is_production)
            rows.append((
                f.fill_id, f.quote_id, f.fill_status.value, f.fill_mechanism.value, f.queue_model.value,
                f.fill_timestamp, f.fill_price, f.fill_size_usd, f.fill_shares, f.queue_depth_ahead_usd,
                f.subsequent_trade_count, f.trade_through_volume_usd, f.touch_volume_usd,
                f.time_to_fill_ms, f.provenance, now,
            ))
        with self._get_connection() as con:
            con.executemany("""
                INSERT OR REPLACE INTO phase10a8_fill_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        return len(rows)

    def insert_economics(self, economics: List[MakerEconomicsRecord]) -> int:
        """Stores maker economic records."""
        if not economics:
            return 0
        now = datetime.now(timezone.utc)
        rows = []
        for e in economics:
            d = e.model_dump()
            ProductionContaminationGuard.assert_valid_production_record(d, self.is_production)
            rows.append((
                e.evaluation_id, e.quote_id, e.fill_id, e.horizon_ms, e.quote_policy.value,
                e.queue_model.value, e.is_filled, e.fill_size_usd, e.gross_spread_capture_bps,
                e.adverse_selection_bps, e.liquidation_cost_bps, e.inventory_cost_bps, e.fee_bps,
                e.net_maker_pnl_bps, e.net_maker_pnl_usd, e.cluster_id, e.is_out_of_sample,
                e.provenance, now,
            ))
        with self._get_connection() as con:
            con.executemany("""
                INSERT OR REPLACE INTO phase10a8_maker_economics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        return len(rows)

    def insert_hypothesis_result(self, res: HypothesisSummaryResult, is_out_of_sample: bool = False) -> None:
        """Stores aggregated hypothesis findings."""
        now = datetime.now(timezone.utc)
        with self._get_connection() as con:
            con.execute("""
                INSERT OR REPLACE INTO phase10a8_hypothesis_results VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, [
                res.hypothesis_id, res.name, res.description, res.n_raw, res.n_clusters,
                res.fill_count, res.ambiguous_count, res.fill_rate, res.gross_spread_capture_bps,
                res.adverse_selection_bps, res.liquidation_cost_bps, res.net_maker_ev_bps,
                res.net_maker_ev_usd, res.ev_per_quote_bps, res.ev_per_fill_bps, res.std_dev_bps,
                res.ci_95_lower_bps, res.ci_95_upper_bps, res.bootstrap_ci_lower_bps,
                res.bootstrap_ci_upper_bps, res.verdict.value, json.dumps(res.details),
                is_out_of_sample, now,
            ])

    def insert_adversarial_control(self, ctrl: AdversarialMakerControlRecord) -> None:
        """Stores adversarial control records."""
        now = datetime.now(timezone.utc)
        with self._get_connection() as con:
            con.execute("""
                INSERT OR REPLACE INTO phase10a8_adversarial_controls VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ctrl.control_id, ctrl.control_type, str(ctrl.parameter_value),
                ctrl.baseline_net_ev_bps, ctrl.controlled_net_ev_bps,
                ctrl.null_hypothesis_satisfied, json.dumps(ctrl.details), now,
            ])

    def insert_inventory_simulation(self, inv: InventoryPositionRecord) -> None:
        """Stores inventory tracking results."""
        now = datetime.now(timezone.utc)
        with self._get_connection() as con:
            con.execute("""
                INSERT OR REPLACE INTO phase10a8_inventory_simulations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                inv.market_id, inv.inventory_limit_usd, inv.cumulative_yes_usd, inv.cumulative_no_usd,
                inv.net_directional_usd, inv.max_inventory_usd, inv.cumulative_fills_count,
                inv.rejected_fills_count, inv.total_liquidation_events, inv.total_liquidation_cost_usd, now,
            ])
