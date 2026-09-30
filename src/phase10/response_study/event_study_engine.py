"""Deterministic High-Frequency Event-Study Engine for Phase 10A.6.

Consumes genuine Phase 10A.5 high-frequency L2 order-book snapshots and trades.
Guarantees:
1. Strict causal alignment: pre-event states strictly precede event timestamp.
2. Latency gating: post-event orders execute strictly at/after event_timestamp + latency.
3. No synthetic data: zero manufactured order books, zero simulated price paths.
4. Depth-aware execution: traverses actual L2 ask/bid ladders to calculate VWAP and slippage.
5. Capacity failure enforcement: rejects executions exceeding available depth.
6. Empirical control batteries: Placebo timestamps, Reverse direction, Pre-event leakage.
7. Multiple-testing correction: Holm-Bonferroni adjustment across tested hypotheses.
8. Cluster-level aggregation: independent catalysts grouped to prevent false significance.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple

import duckdb
import numpy as np

from src.phase10.response_study.schema import (
    EventStudyConfig,
    EventStudyObservation,
    ExecutableResponse,
    StatisticalResult,
    ControlResult,
    EventStudyQualityStatus,
)
from src.phase10.response_study.executable_price_model import ExecutablePriceModel
from src.phase10.response_study.l2_book_extractor import L2BookExtractor
from src.phase10.response_study.event_validator import EventValidatorAndMapper
from src.phase10.response_study.controls import EventStudyControlBatteries
from src.phase10.response_study.statistical_engine import DeterministicStatisticalEngine
from src.phase10.response_study.db_store import Phase10A6DbStore
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard
from src.phase10.response_study.data_span_auditor import DataSpanAuditor

logger = logging.getLogger(__name__)


class DeterministicEventStudyEngine:
    """Master engine orchestrating the Phase 10A.6 deterministic event study."""

    def __init__(
        self,
        db_path: str = "data/prediction_market.duckdb",
        config: Optional[EventStudyConfig] = None,
        git_commit: str = "04c720e"
    ):
        self.db_path = db_path
        self.config = config or EventStudyConfig()
        self.git_commit = git_commit

        self.db_store = Phase10A6DbStore(db_path=db_path)
        self.extractor = L2BookExtractor(
            db_path=db_path,
            max_staleness_seconds=self.config.max_staleness_seconds,
            max_spread=self.config.max_spread
        )
        self.exec_model = ExecutablePriceModel(default_fee_bps=self.config.fee_rate_bps)
        self.validator = EventValidatorAndMapper()
        self.controls = EventStudyControlBatteries(
            random_seed=self.config.random_seed,
            default_fee_bps=self.config.fee_rate_bps
        )
        self.stats_engine = DeterministicStatisticalEngine(
            random_seed=self.config.random_seed,
            alpha=1.0 - self.config.confidence_level
        )
        self.data_span_auditor = DataSpanAuditor(db_path=db_path)

    def _get_read_conn(self) -> duckdb.DuckDBPyConnection:
        """Connects in read_only mode with backoff retries to tolerate concurrent background writes."""
        for attempt in range(15):
            try:
                return duckdb.connect(self.db_path, read_only=True)
            except Exception:
                time.sleep(0.3)
        return duckdb.connect(self.db_path, read_only=True)

    def load_active_market_universe(self, conn: Optional[duckdb.DuckDBPyConnection] = None) -> List[Dict[str, Any]]:
        """Loads tradable contracts from phase10a5_market_universe."""
        local_conn = False
        if conn is None:
            conn = self._get_read_conn()
            local_conn = True

        try:
            # Check if table exists
            tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
            if "phase10a5_market_universe" not in tables:
                return []

            rows = conn.execute("""
                SELECT market_id, token_id, outcome, title, category, volume_24h_usd, liquidity_usd, is_active
                FROM phase10a5_market_universe
                WHERE is_active = true
            """).fetchall()

            cols = ["market_id", "token_id", "outcome", "title", "category", "volume_24h_usd", "liquidity_usd", "is_active"]
            return [dict(zip(cols, r)) for r in rows]
        finally:
            if local_conn:
                conn.close()

    def load_registered_events(self, conn: Optional[duckdb.DuckDBPyConnection] = None) -> List[Dict[str, Any]]:
        """Loads objectively registered events from phase10a5_events."""
        local_conn = False
        if conn is None:
            conn = self._get_read_conn()
            local_conn = True

        try:
            tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
            if "phase10a5_events" not in tables:
                return []

            rows = conn.execute("""
                SELECT event_id, source, source_url, publication_timestamp, event_category, description, affected_entity
                FROM phase10a5_events
            """).fetchall()

            cols = ["event_id", "source", "source_url", "publication_timestamp", "event_category", "description", "affected_entity"]
            return [dict(zip(cols, r)) for r in rows]
        finally:
            if local_conn:
                conn.close()

    def process_event(
        self,
        event: Dict[str, Any],
        market_universe: List[Dict[str, Any]],
        conn: Optional[duckdb.DuckDBPyConnection] = None
    ) -> Tuple[List[EventStudyObservation], List[ExecutableResponse]]:
        """Evaluates an event across pre/post horizons, latencies, and order sizes."""
        observations: List[EventStudyObservation] = []
        executable_responses: List[ExecutableResponse] = []

        event_id = event["event_id"]
        event_cluster_id = event.get("event_cluster_id") or f"cluster_{event_id}"

        # 1. Map event to market
        market_id, token_id, trade_dir, map_status, map_reason = self.validator.map_event_to_market(event, market_universe)
        if map_status != EventStudyQualityStatus.VALID or not market_id or not token_id:
            obs = EventStudyObservation(
                observation_id=f"obs_{event_id}_unmapped",
                event_id=event_id,
                event_cluster_id=event_cluster_id,
                market_id=market_id or "unmapped",
                token_id=token_id or "unmapped",
                direction="UNKNOWN",
                event_timestamp=event.get("publication_timestamp", datetime.now(timezone.utc)),
                horizon_name="ALL",
                target_offset_sec=0,
                status=map_status,
                status_reason=map_reason
            )
            observations.append(obs)
            return observations, executable_responses

        event_ts = event["publication_timestamp"]

        # 2. Iterate across configured post-event horizons
        for horiz_name, offset_sec, tol_sec in self.config.post_horizons:
            obs_id = f"obs_{event_id}_{token_id[:8]}_{horiz_name}"

            # Pre-event lookup (T-1m default baseline)
            pre_snap, pre_status, pre_reason = self.extractor.find_pre_event_snapshot(
                token_id=token_id,
                event_timestamp=event_ts,
                target_offset_sec=-60,
                tolerance_sec=15,
                conn=conn
            )

            # Post-event lookup (T+horiz)
            post_snap, post_status, post_reason = self.extractor.find_post_event_snapshot(
                token_id=token_id,
                event_timestamp=event_ts,
                target_offset_sec=offset_sec,
                tolerance_sec=tol_sec,
                latency_ms=0,
                conn=conn
            )

            if pre_status != EventStudyQualityStatus.VALID:
                obs = EventStudyObservation(
                    observation_id=obs_id,
                    event_id=event_id,
                    event_cluster_id=event_cluster_id,
                    market_id=market_id,
                    token_id=token_id,
                    direction=trade_dir,
                    event_timestamp=event_ts,
                    horizon_name=horiz_name,
                    target_offset_sec=offset_sec,
                    status=pre_status,
                    status_reason=f"Pre-event: {pre_reason}"
                )
                observations.append(obs)
                continue

            if post_status != EventStudyQualityStatus.VALID:
                obs = EventStudyObservation(
                    observation_id=obs_id,
                    event_id=event_id,
                    event_cluster_id=event_cluster_id,
                    market_id=market_id,
                    token_id=token_id,
                    direction=trade_dir,
                    event_timestamp=event_ts,
                    horizon_name=horiz_name,
                    target_offset_sec=offset_sec,
                    status=post_status,
                    status_reason=f"Post-event: {post_reason}",
                    pre_timestamp=pre_snap.get("timestamp"),
                    pre_mid=pre_snap.get("midpoint")
                )
                observations.append(obs)
                continue

            # Both pre and post snapshots are VALID
            pre_mid = pre_snap["midpoint"]
            post_mid = post_snap["midpoint"]
            raw_mid_change_bps = round(((post_mid - pre_mid) / pre_mid) * 10000.0, 2) if pre_mid > 0 else 0.0
            signed_mid_change_bps = raw_mid_change_bps if trade_dir == "BUY" else -raw_mid_change_bps

            obs = EventStudyObservation(
                observation_id=obs_id,
                event_id=event_id,
                event_cluster_id=event_cluster_id,
                market_id=market_id,
                token_id=token_id,
                direction=trade_dir,
                event_timestamp=event_ts,
                horizon_name=horiz_name,
                target_offset_sec=offset_sec,
                status=EventStudyQualityStatus.VALID,
                pre_timestamp=pre_snap["timestamp"],
                pre_exchange_timestamp=pre_snap.get("exchange_timestamp"),
                pre_mid=pre_mid,
                pre_bid=pre_snap["best_bid"],
                pre_ask=pre_snap["best_ask"],
                pre_spread=pre_snap["spread"],
                pre_spread_bps=pre_snap["spread_bps"],
                pre_bid_depth_usd=pre_snap["depth_bid_usd"],
                pre_ask_depth_usd=pre_snap["depth_ask_usd"],
                pre_imbalance=pre_snap["book_imbalance"],
                post_timestamp=post_snap["timestamp"],
                post_exchange_timestamp=post_snap.get("exchange_timestamp"),
                post_mid=post_mid,
                post_bid=post_snap["best_bid"],
                post_ask=post_snap["best_ask"],
                post_spread=post_snap["spread"],
                post_spread_bps=post_snap["spread_bps"],
                post_bid_depth_usd=post_snap["depth_bid_usd"],
                post_ask_depth_usd=post_snap["depth_ask_usd"],
                post_imbalance=post_snap["book_imbalance"],
                gross_mid_movement_bps=raw_mid_change_bps,
                signed_mid_movement_bps=signed_mid_change_bps,
                pre_snapshot_id=pre_snap["snapshot_id"],
                post_snapshot_id=post_snap["snapshot_id"],
                pre_session_id=pre_snap.get("session_id"),
                post_session_id=post_snap.get("session_id"),
                engine_version=self.config.engine_version
            )
            observations.append(obs)

            # 3. Simulate executable taker responses across Latencies and Order Sizes
            for lat_ms in self.config.latencies_ms:
                # Post-event book snapshot arriving at (event_ts + latency_ms)
                lat_snap, lat_status, lat_reason = self.extractor.find_post_event_snapshot(
                    token_id=token_id,
                    event_timestamp=event_ts,
                    target_offset_sec=0,
                    tolerance_sec=max(2, int(lat_ms / 1000) + 1),
                    latency_ms=lat_ms,
                    conn=conn
                )

                if lat_status != EventStudyQualityStatus.VALID or not lat_snap:
                    continue

                for size_usd in self.config.order_sizes_usd:
                    resp_id = f"exec_{obs_id}_{lat_ms}ms_{int(size_usd)}usd"

                    # Entry execution at arrival book
                    entry_fill = self.exec_model.execute_taker_order(
                        bids_raw=lat_snap.get("bids"),
                        asks_raw=lat_snap.get("asks"),
                        direction=trade_dir,
                        order_size_usd=size_usd
                    )

                    # Exit execution at target horizon book (opposite direction)
                    exit_dir = "SELL" if trade_dir == "BUY" else "BUY"
                    exit_fill = self.exec_model.execute_taker_order(
                        bids_raw=post_snap.get("bids"),
                        asks_raw=post_snap.get("asks"),
                        direction=exit_dir,
                        order_size_usd=size_usd
                    )

                    pnl_metrics = self.exec_model.calculate_net_response(entry_fill, exit_fill)

                    resp = ExecutableResponse(
                        response_id=resp_id,
                        observation_id=obs_id,
                        event_id=event_id,
                        event_cluster_id=event_cluster_id,
                        market_id=market_id,
                        token_id=token_id,
                        horizon_name=horiz_name,
                        latency_ms=lat_ms,
                        order_size_usd=size_usd,
                        direction=trade_dir,
                        is_fillable=entry_fill.is_fillable and exit_fill.is_fillable,
                        fill_price_vwap=entry_fill.fill_price_vwap if entry_fill.is_fillable else None,
                        gross_notional_filled=entry_fill.gross_notional_filled if entry_fill.is_fillable else None,
                        filled_shares=entry_fill.total_shares_filled if entry_fill.is_fillable else None,
                        depth_consumed_usd=entry_fill.gross_notional_filled if entry_fill.is_fillable else None,
                        spread_cost_usd=entry_fill.spread_cost_usd,
                        spread_cost_bps=entry_fill.spread_cost_bps,
                        slippage_usd=entry_fill.slippage_usd,
                        slippage_bps=entry_fill.slippage_bps,
                        fee_usd=entry_fill.exchange_fee_usd,
                        fee_bps=entry_fill.exchange_fee_bps,
                        gross_pnl_usd=pnl_metrics["gross_pnl_usd"],
                        gross_return_bps=pnl_metrics["gross_return_bps"],
                        net_pnl_usd=pnl_metrics["net_pnl_usd"],
                        net_return_bps=pnl_metrics["net_return_bps"],
                        capacity_limit_usd=min(entry_fill.capacity_limit_usd, exit_fill.capacity_limit_usd),
                        status=EventStudyQualityStatus.VALID if (entry_fill.is_fillable and exit_fill.is_fillable) else EventStudyQualityStatus.INSUFFICIENT_DEPTH,
                        status_reason=entry_fill.rejection_reason or exit_fill.rejection_reason
                    )
                    executable_responses.append(resp)

        return observations, executable_responses

    def run_study(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        market_universe: Optional[List[Dict[str, Any]]] = None,
        persist_results: bool = False,
        is_dry_run: bool = True
    ) -> Dict[str, Any]:
        """Executes the complete deterministic Phase 10A.6 event study pipeline."""
        logger.info("================================================================================")
        logger.info("PHASE 10A.6 DETERMINISTIC EXECUTABLE EVENT STUDY")
        logger.info(f"Engine Version: {self.config.engine_version} | Dry-Run Mode: {is_dry_run}")
        logger.info("================================================================================")

        # 1. Anti-Synthetic Verification
        conn = self._get_read_conn()
        try:
            guard_scan = AntiSyntheticGuard.scan_production_tables(conn)
            if not guard_scan["clean"]:
                raise RuntimeError(f"Anti-synthetic guard failed: {guard_scan['violations']}")
        finally:
            conn.close()

        # 2. Inspect Dataset Span
        span_result = self.data_span_auditor.inspect_dataset_span()
        is_72h_complete = span_result.wall_clock_span_seconds >= 72.0 * 3600.0
        suitability_label = "SUFFICIENT (72h+)" if is_72h_complete else "INCOMPLETE / INFRASTRUCTURE DRY-RUN"

        # 3. Load Market Universe & Events
        conn = self._get_read_conn()
        try:
            mkt_universe = market_universe if market_universe is not None else self.load_active_market_universe(conn)
            event_list = events if events is not None else self.load_registered_events(conn)
        finally:
            conn.close()

        # 4. Cluster Events
        clustered_events = self.validator.cluster_events_and_detect_overlap(event_list)

        # 5. Process Observations & Executable Responses
        all_observations: List[EventStudyObservation] = []
        all_responses: List[ExecutableResponse] = []

        conn = self._get_read_conn()
        try:
            for ev in clustered_events:
                obs_list, resp_list = self.process_event(ev, mkt_universe, conn=conn)
                all_observations.extend(obs_list)
                all_responses.extend(resp_list)
        finally:
            conn.close()

        # 6. Apply Liquidity Controls
        valid_obs_dicts = [o.__dict__ for o in all_observations if o.status == EventStudyQualityStatus.VALID]
        liquid_obs, liquidity_attrition = self.controls.apply_liquidity_controls(
            valid_obs_dicts,
            min_depth_usd=self.config.min_depth_usd,
            max_spread_bps=self.config.max_spread * 10000.0
        )

        # 7. Run Empirical Control Batteries
        valid_resp_dicts = [r.__dict__ for r in all_responses if r.is_fillable]
        placebo_ctrl = self.controls.run_placebo_timestamp_control(liquid_obs)
        reverse_ctrl = self.controls.run_reverse_direction_control(valid_resp_dicts)
        leakage_ctrl = self.controls.run_pre_event_leakage_check(liquid_obs)

        # 8. Deterministic Statistical Analysis
        net_returns_15s = [
            r.net_return_bps for r in all_responses
            if r.is_fillable and r.horizon_name == "T+15s" and r.latency_ms == 100 and r.order_size_usd == 1000.0
        ]
        stat_15s = self.stats_engine.compute_distribution_statistics(net_returns_15s, metric_name="net_return_t15s_100ms_1kusd")

        net_returns_60s = [
            r.net_return_bps for r in all_responses
            if r.is_fillable and r.horizon_name == "T+60s" and r.latency_ms == 100 and r.order_size_usd == 1000.0
        ]
        stat_60s = self.stats_engine.compute_distribution_statistics(net_returns_60s, metric_name="net_return_t60s_100ms_1kusd")

        raw_stats = [stat_15s, stat_60s]
        corrected_stats = self.stats_engine.apply_holm_bonferroni(raw_stats)

        # Cluster-level aggregation
        cluster_summaries = self.stats_engine.aggregate_by_cluster(valid_resp_dicts)

        # 9. Summary Assembly
        summary = {
            "status": "COMPLETE",
            "study_type": "INFRASTRUCTURE_DRY_RUN" if is_dry_run else "PRODUCTION_RUN",
            "dataset_suitability": suitability_label,
            "wall_clock_span_seconds": round(span_result.wall_clock_span_seconds, 2),
            "calendar_days_spanned": span_result.calendar_days_spanned,
            "events_input_count": len(event_list),
            "event_clusters_count": len(set(e.get("event_cluster_id") for e in clustered_events)),
            "active_markets_monitored": len(set(m["market_id"] for m in mkt_universe)),
            "active_tokens_monitored": len(mkt_universe),
            "observations_generated": len(all_observations),
            "valid_observations_count": len(valid_obs_dicts),
            "executable_responses_generated": len(all_responses),
            "fillable_responses_count": len(valid_resp_dicts),
            "anti_synthetic_clean": True,
            "synthetic_observations_count": 0,
            "liquidity_attrition": liquidity_attrition,
            "control_results": {
                "placebo_timestamps": placebo_ctrl.__dict__,
                "reverse_direction": reverse_ctrl.__dict__,
                "pre_event_leakage": leakage_ctrl.__dict__
            },
            "statistical_results": [s.__dict__ for s in corrected_stats],
            "cluster_summaries_count": len(cluster_summaries),
            "engine_version": self.config.engine_version,
            "git_commit": self.git_commit
        }

        # 10. Persist if requested
        if persist_results:
            conn = self._get_read_conn()
            try:
                self.db_store.init_schema(conn)
                self.db_store.record_event_study_observations(conn, all_observations)
                self.db_store.record_executable_responses(conn, all_responses)
                self.db_store.record_statistical_results(conn, corrected_stats)
            finally:
                conn.close()

        return summary
