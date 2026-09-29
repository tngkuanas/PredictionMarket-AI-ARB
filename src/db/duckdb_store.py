"""DuckDB database store for markets, snapshots, trades, relationships, validation, and executions."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import duckdb
import pandas as pd

from config.settings import get_settings
from src.normalization.schema import (
    Market,
    Observation,
    Trade,
    CanonicalMarket,
    CandidateRelationship,
    ValidationResult,
    Signal,
    PaperOrder,
    PaperFill,
    PortfolioSnapshot,
    ShadowCandidate,
    ShadowOrder,
    ShadowFill,
    ShadowRunRecord,
)

logger = logging.getLogger(__name__)

class DuckDBStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.settings = get_settings()
        self.db_path = str(db_path or self.settings.db.db_path)
        self._init_schema()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def _init_schema(self) -> None:
        """Initializes tables for all entities."""
        with self.get_connection() as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                platform VARCHAR,
                market_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                title VARCHAR,
                description VARCHAR,
                resolution_rules VARCHAR,
                outcome_labels JSON,
                category VARCHAR,
                open_time TIMESTAMP,
                close_time TIMESTAMP,
                resolution_time TIMESTAMP,
                status VARCHAR,
                clob_token_ids JSON,
                condition_id VARCHAR,
                volume DOUBLE,
                liquidity DOUBLE,
                metadata JSON,
                updated_at TIMESTAMP
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS canonical_markets (
                market_id VARCHAR PRIMARY KEY,
                platform VARCHAR,
                title VARCHAR,
                underlying_event VARCHAR,
                entities JSON,
                geographic_scope VARCHAR,
                time_horizon VARCHAR,
                event_type VARCHAR,
                threshold VARCHAR,
                direction VARCHAR,
                numerical_conditions JSON,
                resolution_date VARCHAR,
                resolution_source VARCHAR,
                resolution_methodology VARCHAR,
                ambiguity_flags JSON,
                updated_at TIMESTAMP
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                timestamp TIMESTAMP,
                market_id VARCHAR,
                platform VARCHAR,
                yes_bid DOUBLE,
                yes_ask DOUBLE,
                yes_mid DOUBLE,
                no_bid DOUBLE,
                no_ask DOUBLE,
                volume DOUBLE,
                liquidity DOUBLE
            );
            CREATE INDEX IF NOT EXISTS idx_snapshot_mkt_time ON market_snapshots(market_id, timestamp);
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                timestamp TIMESTAMP,
                market_id VARCHAR,
                platform VARCHAR,
                side VARCHAR,
                price DOUBLE,
                quantity DOUBLE
            );
            CREATE INDEX IF NOT EXISTS idx_trades_mkt_time ON trades(market_id, timestamp);
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                discovery_id VARCHAR PRIMARY KEY,
                constraint_id VARCHAR,
                market_a VARCHAR,
                market_b VARCHAR,
                opportunity_class VARCHAR,
                relationship_type VARCHAR,
                constraint_type VARCHAR,
                economic_mechanism VARCHAR,
                domain_cluster VARCHAR,
                why_embedding_misses VARCHAR,
                confidence DOUBLE,
                trigger_threshold DOUBLE,
                expected_delta_b DOUBLE,
                lead_time_hours DOUBLE,
                testable_null_hypothesis VARCHAR,
                mathematical_expression VARCHAR,
                invalidation_criteria JSON,
                discovery_timestamp TIMESTAMP,
                hop_count INTEGER
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS falsification_reports (
                constraint_id VARCHAR PRIMARY KEY,
                market_a VARCHAR,
                market_b VARCHAR,
                opportunity_class VARCHAR,
                sample_size_n INTEGER,
                is_sample_size_n INTEGER,
                oos_sample_size_n INTEGER,
                observed_effect_pp DOUBLE,
                baseline_drift_pp DOUBLE,
                net_effect_pp DOUBLE,
                ci_95_low_pp DOUBLE,
                ci_95_high_pp DOUBLE,
                p_value DOUBLE,
                oos_observed_effect_pp DOUBLE,
                oos_net_effect_pp DOUBLE,
                oos_p_value DOUBLE,
                lead_time_hours DOUBLE,
                is_cointegrated BOOLEAN,
                is_spurious_drift BOOLEAN,
                resolution_divergence_prob DOUBLE,
                basis_risk_score DOUBLE,
                raw_edge_pp DOUBLE,
                friction_costs_pp DOUBLE,
                net_expected_edge_pp DOUBLE,
                verdict VARCHAR,
                kill_reason VARCHAR,
                evidence_summary VARCHAR,
                test_timestamp TIMESTAMP
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP,
                strategy_name VARCHAR,
                market_target VARCHAR,
                market_anchor VARCHAR,
                side VARCHAR,
                model_fair_value DOUBLE,
                market_implied_value DOUBLE,
                raw_edge DOUBLE,
                net_expected_value DOUBLE,
                recommended_size_usd DOUBLE,
                confidence DOUBLE,
                metadata JSON
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP,
                signal_id VARCHAR,
                market_id VARCHAR,
                platform VARCHAR,
                side VARCHAR,
                order_type VARCHAR,
                limit_price DOUBLE,
                quantity DOUBLE,
                status VARCHAR
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS paper_fills (
                fill_id VARCHAR PRIMARY KEY,
                order_id VARCHAR,
                timestamp TIMESTAMP,
                market_id VARCHAR,
                platform VARCHAR,
                side VARCHAR,
                fill_price DOUBLE,
                quantity DOUBLE,
                fee DOUBLE,
                slippage DOUBLE,
                net_pnl DOUBLE
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_pnl (
                timestamp TIMESTAMP PRIMARY KEY,
                cash DOUBLE,
                portfolio_value DOUBLE,
                total_realized_pnl DOUBLE,
                total_unrealized_pnl DOUBLE,
                total_fees_paid DOUBLE,
                total_slippage_paid DOUBLE,
                open_positions_count INTEGER,
                exposure_usd DOUBLE,
                daily_drawdown_pct DOUBLE,
                max_drawdown_pct DOUBLE
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS shadow_candidates (
                candidate_id VARCHAR PRIMARY KEY,
                t0_timestamp TIMESTAMP,
                market_id VARCHAR,
                token_id VARCHAR,
                title VARCHAR,
                opportunity_class VARCHAR,
                predicted_fair_value DOUBLE,
                market_mid_price DOUBLE,
                raw_edge DOUBLE,
                frozen_min_edge_threshold DOUBLE,
                status VARCHAR,
                rejection_reason VARCHAR,
                target_horizon_hours DOUBLE,
                target_timestamp TIMESTAMP
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS shadow_orders (
                order_id VARCHAR PRIMARY KEY,
                candidate_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                side VARCHAR,
                placed_at TIMESTAMP,
                limit_price DOUBLE,
                target_size_usd DOUBLE,
                status VARCHAR,
                simulated_latency_ms DOUBLE
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS shadow_fills (
                fill_id VARCHAR PRIMARY KEY,
                order_id VARCHAR,
                candidate_id VARCHAR,
                market_id VARCHAR,
                filled_at TIMESTAMP,
                side VARCHAR,
                fill_price DOUBLE,
                size_usd DOUBLE,
                fee_usd DOUBLE,
                slippage_usd DOUBLE,
                levels_swept INTEGER,
                status VARCHAR,
                realized_edge DOUBLE
            );
            """)

            con.execute("""
            CREATE TABLE IF NOT EXISTS shadow_runs (
                run_id VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP,
                config_version VARCHAR,
                config_hash VARCHAR,
                candidate_generator_version VARCHAR,
                execution_model_version VARCHAR,
                markets_scanned INTEGER,
                candidates_generated INTEGER,
                filtered_out_count INTEGER,
                active_candidates_count INTEGER,
                orders_placed INTEGER,
                fills_executed INTEGER,
                rejections_json JSON
            );
            """)

    def save_markets(self, markets: List[Market]) -> None:
        """Upsert markets into DuckDB."""
        if not markets:
            return
        now = datetime.utcnow()
        rows = [
            (
                m.platform.value,
                m.market_id,
                m.event_id,
                m.title,
                m.description,
                m.resolution_rules,
                json.dumps(m.outcome_labels),
                m.category,
                m.open_time,
                m.close_time,
                m.resolution_time,
                m.status.value,
                json.dumps(m.clob_token_ids or []),
                m.condition_id,
                m.volume,
                m.liquidity,
                json.dumps(m.metadata),
                now
            )
            for m in markets
        ]
        df = pd.DataFrame(rows, columns=[
            "platform", "market_id", "event_id", "title", "description",
            "resolution_rules", "outcome_labels", "category", "open_time",
            "close_time", "resolution_time", "status", "clob_token_ids", "condition_id",
            "volume", "liquidity", "metadata", "updated_at"
        ])
        with self.get_connection() as con:
            con.register("df_markets", df)
            con.execute("""
            INSERT OR REPLACE INTO markets
            SELECT * FROM df_markets;
            """)

    def save_canonical_markets(self, canonicals: List[CanonicalMarket]) -> None:
        if not canonicals:
            return
        now = datetime.utcnow()
        rows = [
            (
                c.market_id,
                c.platform.value,
                c.title,
                c.underlying_event,
                json.dumps(c.entities),
                c.geographic_scope,
                c.time_horizon,
                c.event_type,
                c.threshold,
                c.direction,
                json.dumps(c.numerical_conditions or {}),
                c.resolution_date,
                c.resolution_source,
                c.resolution_methodology,
                json.dumps(c.ambiguity_flags),
                now
            )
            for c in canonicals
        ]
        df = pd.DataFrame(rows, columns=[
            "market_id", "platform", "title", "underlying_event", "entities",
            "geographic_scope", "time_horizon", "event_type", "threshold",
            "direction", "numerical_conditions", "resolution_date",
            "resolution_source", "resolution_methodology", "ambiguity_flags", "updated_at"
        ])
        with self.get_connection() as con:
            con.register("df_canon", df)
            con.execute("""
            INSERT OR REPLACE INTO canonical_markets
            SELECT * FROM df_canon;
            """)

    def save_observations(self, observations: List[Observation]) -> None:
        """Append observations to DuckDB. Never overwrites historical snapshots."""
        if not observations:
            return
        rows = [
            (
                o.timestamp,
                o.market_id,
                o.platform.value,
                o.yes_bid,
                o.yes_ask,
                o.yes_mid,
                o.no_bid,
                o.no_ask,
                o.volume,
                o.liquidity
            )
            for o in observations
        ]
        df = pd.DataFrame(rows, columns=[
            "timestamp", "market_id", "platform", "yes_bid", "yes_ask",
            "yes_mid", "no_bid", "no_ask", "volume", "liquidity"
        ])
        with self.get_connection() as con:
            con.register("df_obs", df)
            con.execute("""
            INSERT INTO market_snapshots 
            SELECT df.* FROM df_obs df 
            ANTI JOIN market_snapshots ms 
              ON df.market_id = ms.market_id AND df.timestamp = ms.timestamp;
            """)

    def save_trades(self, trades: List[Trade]) -> None:
        if not trades:
            return
        rows = [
            (
                t.timestamp,
                t.market_id,
                t.platform.value,
                t.side.value,
                t.price,
                t.quantity
            )
            for t in trades
        ]
        df = pd.DataFrame(rows, columns=[
            "timestamp", "market_id", "platform", "side", "price", "quantity"
        ])
        with self.get_connection() as con:
            con.register("df_trades", df)
            con.execute("INSERT INTO trades SELECT * FROM df_trades;")

    def save_relationships(self, rels: List[CandidateRelationship]) -> None:
        if not rels:
            return
        rows = [
            (
                r.discovery.discovery_id,
                r.constraint.constraint_id,
                r.discovery.market_a_id,
                r.discovery.market_b_id,
                r.discovery.opportunity_class.value if hasattr(r.discovery.opportunity_class, "value") else str(r.discovery.opportunity_class),
                r.discovery.relationship_type.value,
                r.constraint.constraint_type.value,
                r.discovery.economic_mechanism,
                r.discovery.domain_cluster,
                r.discovery.why_embedding_misses,
                r.discovery.confidence,
                r.constraint.trigger_threshold_delta_a,
                r.constraint.expected_delta_b,
                r.constraint.lead_time_hours,
                r.constraint.testable_null_hypothesis,
                r.constraint.mathematical_expression,
                json.dumps(r.constraint.invalidation_criteria),
                r.discovery.discovery_timestamp,
                r.hop_count
            )
            for r in rels
        ]
        df = pd.DataFrame(rows, columns=[
            "discovery_id", "constraint_id", "market_a", "market_b",
            "opportunity_class", "relationship_type", "constraint_type",
            "economic_mechanism", "domain_cluster", "why_embedding_misses",
            "confidence", "trigger_threshold", "expected_delta_b",
            "lead_time_hours", "testable_null_hypothesis", "mathematical_expression",
            "invalidation_criteria", "discovery_timestamp", "hop_count"
        ])
        with self.get_connection() as con:
            con.register("df_rels", df)
            con.execute("INSERT OR REPLACE INTO relationships SELECT * FROM df_rels;")

    def save_falsification_reports(self, reports: List[Any]) -> None:
        if not reports:
            return
        rows = [
            (
                rep.constraint_id,
                rep.market_a,
                rep.market_b,
                rep.opportunity_class.value if hasattr(rep.opportunity_class, "value") else str(rep.opportunity_class),
                rep.sample_size_n,
                rep.is_sample_size_n,
                rep.oos_sample_size_n,
                rep.observed_effect_pp,
                rep.baseline_drift_pp,
                rep.net_effect_pp,
                rep.ci_95_low_pp,
                rep.ci_95_high_pp,
                rep.p_value,
                rep.oos_observed_effect_pp,
                rep.oos_net_effect_pp,
                rep.oos_p_value,
                rep.lead_time_hours,
                rep.is_cointegrated,
                rep.is_spurious_drift,
                rep.resolution_divergence_prob,
                rep.basis_risk_score,
                rep.raw_edge_pp,
                rep.friction_costs_pp,
                rep.net_expected_edge_pp,
                rep.verdict.value if hasattr(rep.verdict, "value") else str(rep.verdict),
                rep.kill_reason,
                rep.evidence_summary,
                rep.test_timestamp
            )
            for rep in reports
        ]
        df = pd.DataFrame(rows, columns=[
            "constraint_id", "market_a", "market_b", "opportunity_class",
            "sample_size_n", "is_sample_size_n", "oos_sample_size_n",
            "observed_effect_pp", "baseline_drift_pp", "net_effect_pp",
            "ci_95_low_pp", "ci_95_high_pp", "p_value",
            "oos_observed_effect_pp", "oos_net_effect_pp", "oos_p_value",
            "lead_time_hours", "is_cointegrated", "is_spurious_drift",
            "resolution_divergence_prob", "basis_risk_score",
            "raw_edge_pp", "friction_costs_pp", "net_expected_edge_pp",
            "verdict", "kill_reason", "evidence_summary", "test_timestamp"
        ])
        with self.get_connection() as con:
            con.register("df_falsify", df)
            con.execute("INSERT OR REPLACE INTO falsification_reports SELECT * FROM df_falsify;")

    def save_validations(self, validations: List[ValidationResult]) -> None:
        if not validations:
            return
        rows = [
            (
                f"{v.market_a}_{v.market_b}_{v.relationship_type.value}_{int(v.validation_timestamp.timestamp())}",
                v.market_a,
                v.market_b,
                v.relationship_type.value,
                v.price_correlation,
                v.return_correlation,
                v.rolling_correlation_mean,
                v.lead_lag_correlation_peak,
                v.optimal_lag_steps,
                v.p_b_given_a,
                v.p_b_given_not_a,
                v.market_implied_p_b,
                v.conditional_mispricing,
                v.spread_zscore,
                v.is_cointegrated,
                v.resolution_analysis.basis_risk_score if v.resolution_analysis else 0.0,
                v.is_statistically_valid,
                v.validation_timestamp,
                v.evidence_summary
            )
            for v in validations
        ]
        df = pd.DataFrame(rows, columns=[
            "validation_id", "market_a", "market_b", "relationship_type",
            "price_correlation", "return_correlation", "rolling_correlation_mean",
            "lead_lag_peak", "optimal_lag_steps", "p_b_given_a", "p_b_given_not_a",
            "market_implied_p_b", "conditional_mispricing", "spread_zscore",
            "is_cointegrated", "basis_risk_score", "is_statistically_valid",
            "validation_timestamp", "evidence_summary"
        ])
        with self.get_connection() as con:
            con.register("df_val", df)
            con.execute("INSERT OR REPLACE INTO relationship_validation SELECT * FROM df_val;")

    def save_signals(self, signals: List[Signal]) -> None:
        if not signals:
            return
        rows = [
            (
                s.signal_id,
                s.timestamp,
                s.strategy_name,
                s.market_target,
                s.market_anchor,
                s.side.value,
                s.model_fair_value,
                s.market_implied_value,
                s.raw_edge,
                s.net_expected_value,
                s.recommended_size_usd,
                s.confidence,
                json.dumps(s.metadata)
            )
            for s in signals
        ]
        df = pd.DataFrame(rows, columns=[
            "signal_id", "timestamp", "strategy_name", "market_target",
            "market_anchor", "side", "model_fair_value", "market_implied_value",
            "raw_edge", "net_expected_value", "recommended_size_usd", "confidence", "metadata"
        ])
        with self.get_connection() as con:
            con.register("df_sig", df)
            con.execute("INSERT OR REPLACE INTO signals SELECT * FROM df_sig;")

    def save_paper_orders(self, orders: List[PaperOrder]) -> None:
        if not orders:
            return
        df_o = pd.DataFrame([
            (o.order_id, o.timestamp, o.signal_id, o.market_id, o.platform.value if hasattr(o.platform, "value") else str(o.platform),
             o.side.value if hasattr(o.side, "value") else str(o.side), o.order_type, o.limit_price, o.quantity, o.status)
            for o in orders
        ], columns=["order_id", "timestamp", "signal_id", "market_id", "platform", "side", "order_type", "limit_price", "quantity", "status"])
        with self.get_connection() as con:
            con.register("df_o", df_o)
            con.execute("INSERT OR REPLACE INTO paper_orders SELECT * FROM df_o;")

    def save_paper_fills(self, fills: List[PaperFill]) -> None:
        if not fills:
            return
        df_f = pd.DataFrame([
            (f.fill_id, f.order_id, f.timestamp, f.market_id, f.platform.value if hasattr(f.platform, "value") else str(f.platform),
             f.side.value if hasattr(f.side, "value") else str(f.side), f.fill_price, f.quantity, f.fee, f.slippage, f.net_pnl)
            for f in fills
        ], columns=["fill_id", "order_id", "timestamp", "market_id", "platform", "side", "fill_price", "quantity", "fee", "slippage", "net_pnl"])
        with self.get_connection() as con:
            con.register("df_f", df_f)
            con.execute("INSERT OR REPLACE INTO paper_fills SELECT * FROM df_f;")

    def save_portfolio_snapshots(self, snapshots: List[PortfolioSnapshot]) -> None:
        if not snapshots:
            return
        df_p = pd.DataFrame([
            (s.timestamp, s.cash, s.portfolio_value, s.total_realized_pnl, s.total_unrealized_pnl,
             s.total_fees_paid, s.total_slippage_paid, s.open_positions_count, s.exposure_usd,
             s.daily_drawdown_pct, s.max_drawdown_pct)
            for s in snapshots
        ], columns=["timestamp", "cash", "portfolio_value", "total_realized_pnl", "total_unrealized_pnl",
                    "total_fees_paid", "total_slippage_paid", "open_positions_count", "exposure_usd",
                    "daily_drawdown_pct", "max_drawdown_pct"])
        with self.get_connection() as con:
            con.register("df_p", df_p)
            con.execute("INSERT OR REPLACE INTO portfolio_pnl SELECT * FROM df_p;")

    def save_orders_and_fills(self, orders: List[PaperOrder], fills: List[PaperFill]) -> None:
        self.save_paper_orders(orders)
        self.save_paper_fills(fills)

    def get_all_markets(self, active_only: bool = False) -> pd.DataFrame:
        with self.get_connection() as con:
            query = "SELECT * FROM markets"
            if active_only:
                query += " WHERE status = 'active'"
            return con.execute(query).df()

    def get_all_canonical_markets(self) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute("SELECT * FROM canonical_markets").df()

    def get_market_snapshots(self, market_id: str) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute(
                "SELECT * FROM market_snapshots WHERE market_id = ? ORDER BY timestamp ASC",
                [market_id]
            ).df()

    def get_snapshots_for_markets(self, market_ids: List[str]) -> pd.DataFrame:
        with self.get_connection() as con:
            placeholders = ",".join(["?"] * len(market_ids))
            return con.execute(
                f"SELECT * FROM market_snapshots WHERE market_id IN ({placeholders}) ORDER BY timestamp ASC",
                market_ids
            ).df()

    def save_shadow_candidates(self, candidates: List[ShadowCandidate]) -> None:
        if not candidates:
            return
        df_c = pd.DataFrame([
            (
                c.candidate_id,
                c.t0_timestamp,
                c.market_id,
                c.token_id,
                c.title,
                c.opportunity_class.value if hasattr(c.opportunity_class, "value") else str(c.opportunity_class),
                c.predicted_fair_value,
                c.market_mid_price,
                c.raw_edge,
                c.frozen_min_edge_threshold,
                c.status,
                c.rejection_reason,
                c.target_horizon_hours,
                c.target_timestamp
            )
            for c in candidates
        ], columns=[
            "candidate_id", "t0_timestamp", "market_id", "token_id", "title",
            "opportunity_class", "predicted_fair_value", "market_mid_price",
            "raw_edge", "frozen_min_edge_threshold", "status", "rejection_reason",
            "target_horizon_hours", "target_timestamp"
        ])
        with self.get_connection() as con:
            con.register("df_c", df_c)
            con.execute("INSERT OR REPLACE INTO shadow_candidates SELECT * FROM df_c;")

    def save_shadow_orders(self, orders: List[ShadowOrder]) -> None:
        if not orders:
            return
        df_o = pd.DataFrame([
            (
                o.order_id,
                o.candidate_id,
                o.market_id,
                o.token_id,
                o.side.value if hasattr(o.side, "value") else str(o.side),
                o.placed_at,
                o.limit_price,
                o.target_size_usd,
                o.status,
                o.simulated_latency_ms
            )
            for o in orders
        ], columns=[
            "order_id", "candidate_id", "market_id", "token_id", "side",
            "placed_at", "limit_price", "target_size_usd", "status", "simulated_latency_ms"
        ])
        with self.get_connection() as con:
            con.register("df_o", df_o)
            con.execute("INSERT OR REPLACE INTO shadow_orders SELECT * FROM df_o;")

    def save_shadow_fills(self, fills: List[ShadowFill]) -> None:
        if not fills:
            return
        df_f = pd.DataFrame([
            (
                f.fill_id,
                f.order_id,
                f.candidate_id,
                f.market_id,
                f.filled_at,
                f.side.value if hasattr(f.side, "value") else str(f.side),
                f.fill_price,
                f.size_usd,
                f.fee_usd,
                f.slippage_usd,
                f.levels_swept,
                f.status,
                f.realized_edge
            )
            for f in fills
        ], columns=[
            "fill_id", "order_id", "candidate_id", "market_id", "filled_at",
            "side", "fill_price", "size_usd", "fee_usd", "slippage_usd",
            "levels_swept", "status", "realized_edge"
        ])
        with self.get_connection() as con:
            con.register("df_f", df_f)
            con.execute("INSERT OR REPLACE INTO shadow_fills SELECT * FROM df_f;")

    def get_shadow_candidates(self) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute("SELECT * FROM shadow_candidates ORDER BY t0_timestamp DESC").df()

    def get_shadow_orders(self) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute("SELECT * FROM shadow_orders ORDER BY placed_at DESC").df()

    def get_shadow_fills(self) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute("SELECT * FROM shadow_fills ORDER BY filled_at DESC").df()

    def save_shadow_run(self, run: ShadowRunRecord) -> None:
        df_r = pd.DataFrame([
            (
                run.run_id,
                run.timestamp,
                run.config_version,
                run.config_hash,
                run.candidate_generator_version,
                run.execution_model_version,
                run.markets_scanned,
                run.candidates_generated,
                run.filtered_out_count,
                run.active_candidates_count,
                run.orders_placed,
                run.fills_executed,
                json.dumps(run.rejections_json)
            )
        ], columns=[
            "run_id", "timestamp", "config_version", "config_hash",
            "candidate_generator_version", "execution_model_version",
            "markets_scanned", "candidates_generated", "filtered_out_count",
            "active_candidates_count", "orders_placed", "fills_executed", "rejections_json"
        ])
        with self.get_connection() as con:
            con.register("df_r", df_r)
            con.execute("INSERT OR REPLACE INTO shadow_runs SELECT * FROM df_r;")

    def get_shadow_runs(self) -> pd.DataFrame:
        with self.get_connection() as con:
            return con.execute("SELECT * FROM shadow_runs ORDER BY timestamp DESC").df()

_db_instance: Optional[DuckDBStore] = None

def get_db() -> DuckDBStore:
    global _db_instance
    if _db_instance is None:
        _db_instance = DuckDBStore()
    return _db_instance
