"""End-to-End Orchestration Pipeline for Phase 10A.10-B Genuine Event-Universe Expansion.

Orchestrates:
1. Frozen strategy configuration hash verification.
2. Broad discovery of deterministic events across 10 preregistered categories (A-J).
3. Historical source validation, exact market matching, and rejection ledger recording.
4. Multi-scale event independence and clustering (1m, 5m, event family).
5. Chronological 60/40 mechanical Discovery/OOS partitioning.
6. Execution simulation across the exact frozen Phase 10A.10 parameter grid.
7. Convergence tracking, capital lockup, and adversarial controls C1-C6.
8. Multiple testing (Holm-Bonferroni) and cluster-robust statistical inference.
9. Persistence to phase10a10b_* tables in DuckDB.
10. Generation of the 20-section report phase10a10b_event_universe_expansion.md.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import os
import random
import time
from typing import Dict, Any, List, Optional, Tuple
import duckdb

from src.phase10a10b.universe import (
    Phase10A10BVerdict,
    ExpandedEventRecord,
    SourceEvidenceRecord,
    MarketMappingRecord,
    EventIndependenceRecord,
    CandidateRejectionRecord,
)
from src.phase10a10b.config_freeze import PHASE10A10B_CONFIG_HASH, FROZEN_PHASE10A10_CONFIG, assert_config_unmodified
from src.phase10a10b.event_discovery import CandidateEventDiscoveryEngine
from src.phase10a10b.independence import EventIndependenceTracker
from src.phase10a10b.chronology import ChronologyManager
from src.phase10a10b.provenance import Phase10A10BDbStore
from src.phase10a10b.report import Phase10A10BReportGenerator

# Reuse frozen Phase 10A.10 execution & statistical modules
from src.phase10a10.schema import (
    CandidateOpportunity,
    ExecutionRecord,
    ConvergenceRecord,
    CapitalLockupRecord,
    NegativeControlRecord,
    HypothesisResultRecord,
    DeterministicState,
    SourceTier,
    LatencyBucket,
)
from src.phase10a10.market_reconstructor import MarketStateReconstructor
from src.phase10a10.execution_model import ExecutionSimulator
from src.phase10a10.convergence import ConvergenceTracker
from src.phase10a10.capital_lockup import CapitalLockupModel
from src.phase10a10.controls import AdversarialControlsEvaluator
from src.phase10a10.statistical_engine import StatisticalEngine

logger = logging.getLogger(__name__)


class Phase10A10BPipeline:
    """Orchestrates Phase 10A.10-B event-universe expansion and frozen re-evaluation."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path
        self.db_store = Phase10A10BDbStore(db_path=db_path)
        # Verify strategy immutability
        assert_config_unmodified(FROZEN_PHASE10A10_CONFIG)

    def _execute_query_safe(self, query: str, params: Tuple = ()) -> List[Tuple]:
        """Reads DuckDB safely with exponential retry backoff."""
        for attempt in range(15):
            try:
                with duckdb.connect(self.db_path, read_only=True) as con:
                    return con.execute(query, params).fetchall()
            except Exception:
                time.sleep(0.05 * (1.3 ** attempt) + random.uniform(0.02, 0.05))
        with duckdb.connect(self.db_path, read_only=True) as con:
            return con.execute(query, params).fetchall()

    def load_market_universe(self) -> List[Dict[str, Any]]:
        """Loads all recorded Polymarket contracts."""
        rows = self._execute_query_safe("""
            SELECT DISTINCT market_id, token_id, outcome, title, category
            FROM phase10a5_market_universe
        """)
        return [
            {
                "market_id": str(r[0]),
                "token_id": str(r[1]),
                "outcome": str(r[2]),
                "title": str(r[3]),
                "category": str(r[4]),
            }
            for r in rows
        ]

    def load_historical_hf_events(self) -> List[Dict[str, Any]]:
        """Loads historical high-frequency events."""
        rows = self._execute_query_safe("""
            SELECT event_id, event_category, event_type, source, source_url,
                   timestamp_publication, mapped_market_id, mapped_token_id, direction, numerical_surprise
            FROM phase10a4_events
        """)
        return [
            {
                "event_id": str(r[0]),
                "event_category": str(r[1]),
                "event_type": str(r[2]),
                "source": str(r[3]),
                "source_url": str(r[4]),
                "timestamp_publication": r[5],
                "mapped_market_id": str(r[6]),
                "mapped_token_id": str(r[7]),
                "direction": str(r[8]),
                "numerical_surprise": float(r[9] or 0.0),
            }
            for r in rows
        ]

    def load_snapshots_for_tokens(self, token_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Loads snapshots for tokens from phase10a5 and phase10a4."""
        if not token_ids:
            return {}

        tok_list = ", ".join([f"'{t}'" for t in token_ids])
        # Try phase10a5 first
        rows_a5 = self._execute_query_safe(f"""
            SELECT snapshot_id, token_id, market_id, timestamp, best_bid, best_ask, midpoint, spread_bps, bids, asks
            FROM phase10a5_book_snapshots
            WHERE token_id IN ({tok_list})
            ORDER BY timestamp ASC
        """)

        # Also load from phase10a4 for historical contracts
        rows_a4 = self._execute_query_safe(f"""
            SELECT snapshot_id, token_id, market_id, timestamp_local_receive, best_bid, best_ask, midpoint, spread_bps, bids_l2, asks_l2
            FROM phase10a4_book_snapshots
            WHERE token_id IN ({tok_list})
            ORDER BY timestamp_local_receive ASC
        """)

        grouped: Dict[str, List[Dict[str, Any]]] = {t: [] for t in token_ids}
        for r in rows_a5:
            t_id = str(r[1])
            if t_id in grouped:
                grouped[t_id].append({
                    "snapshot_id": str(r[0]), "token_id": t_id, "market_id": str(r[2]),
                    "timestamp": r[3], "best_bid": float(r[4] or 0.0), "best_ask": float(r[5] or 1.0),
                    "midpoint": float(r[6] or 0.5), "spread_bps": float(r[7] or 0.0),
                    "bids": r[8], "asks": r[9],
                })

        for r in rows_a4:
            t_id = str(r[1])
            if t_id in grouped:
                grouped[t_id].append({
                    "snapshot_id": str(r[0]), "token_id": t_id, "market_id": str(r[2]),
                    "timestamp": r[3], "best_bid": float(r[4] or 0.0), "best_ask": float(r[5] or 1.0),
                    "midpoint": float(r[6] or 0.5), "spread_bps": float(r[7] or 0.0),
                    "bids": r[8], "asks": r[9],
                })

        for t_id in grouped:
            grouped[t_id].sort(key=lambda s: s["timestamp"])

        return grouped

    def run(self) -> Dict[str, Any]:
        """Executes full Phase 10A.10-B expansion and frozen re-evaluation."""
        logger.info("Starting Phase 10A.10-B Genuine Event-Universe Expansion...")
        logger.info(f"Verified Frozen Strategy Configuration Hash: {PHASE10A10B_CONFIG_HASH}")

        # 1. Ingest Data
        market_universe = self.load_market_universe()
        historical_hf_events = self.load_historical_hf_events()
        logger.info(f"Loaded {len(market_universe)} universe contract rows and {len(historical_hf_events)} historical events.")

        # 2. Discover Candidates across 10 Preregistered Categories
        accepted_events, source_evidences, market_mappings, rejections = CandidateEventDiscoveryEngine.discover_all_candidates(
            market_universe=market_universe,
            historical_hf_events=historical_hf_events
        )
        logger.info(f"Discovery Results: {len(accepted_events)} accepted events, {len(rejections)} rejected candidates.")

        # 3. Multi-Scale Clustering and Independence
        independence_records = EventIndependenceTracker.assign_clusters(accepted_events)
        self.db_store.save_independence(independence_records)

        # 4. Mechanical Chronological Discovery / OOS Split (60% / 40%)
        discovery_events, oos_events, split_summary = ChronologyManager.apply_chronological_split(accepted_events, discovery_pct=0.60)
        logger.info(f"Chronological Split: {len(discovery_events)} Discovery, {len(oos_events)} OOS events.")

        # Persist events, sources, mappings, and rejections
        self.db_store.save_events(accepted_events)
        self.db_store.save_sources(source_evidences)
        self.db_store.save_mappings(market_mappings)
        self.db_store.save_rejections(rejections)

        # 5. Load L2 Snapshots for Event Tokens
        token_ids = [e.token_id for e in accepted_events]
        token_snapshots = self.load_snapshots_for_tokens(token_ids)

        # 6. Execute Simulations across Frozen Parameter Grid
        candidates: List[CandidateOpportunity] = []
        executions: List[ExecutionRecord] = []
        controls: List[NegativeControlRecord] = []

        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        for ev in accepted_events:
            snaps = token_snapshots.get(ev.token_id, [])
            ev_src_utc = to_utc(ev.source_timestamp)
            post_snaps = [s for s in snaps if to_utc(s["timestamp"]) >= ev_src_utc]
            if not post_snaps:
                continue

            for target_size in ExecutionSimulator.POSITION_SIZES_USD:
                for threshold_bps in ExecutionSimulator.ENTRY_THRESHOLDS_BPS:
                    for label, lat_bucket, offset_sec in [
                        ("T+500ms", LatencyBucket.B_500MS_1S, 0.5),
                        ("T+1s", LatencyBucket.B_1_2S, 1.0),
                        ("T+5s", LatencyBucket.B_2_5S, 5.0)
                    ]:
                        exec_snap = MarketStateReconstructor.find_nearest_snapshot(
                            snapshots=post_snaps,
                            target_dt=ev.source_timestamp + timedelta(seconds=offset_sec),
                            require_forward=True,
                            max_delta_sec=180.0
                        )
                        if not exec_snap:
                            continue

                        best_ask = float(exec_snap.get("best_ask") or 1.0)
                        asks_raw = exec_snap.get("asks", [])
                        if isinstance(asks_raw, str):
                            try:
                                asks_raw = json.loads(asks_raw)
                            except Exception:
                                asks_raw = []

                        # Filter out non-tradable or collapsed/halted order books
                        if best_ask < 0.01 or best_ask >= 0.999:
                            gross_edge_bps = 0.0
                        else:
                            gross_edge_bps = ((1.0 - best_ask) / best_ask) * 10000.0

                        def parse_det_state(s: str) -> DeterministicState:
                            if isinstance(s, DeterministicState):
                                return s
                            if s in DeterministicState.__members__:
                                return DeterministicState[s]
                            try:
                                return DeterministicState(s)
                            except Exception:
                                return DeterministicState.STATE_A if "A" in s else (DeterministicState.STATE_B if "B" in s else DeterministicState.STATE_D)

                        def parse_src_tier(s: str) -> SourceTier:
                            if isinstance(s, SourceTier):
                                return s
                            if s in SourceTier.__members__:
                                return SourceTier[s]
                            try:
                                return SourceTier(s)
                            except Exception:
                                return SourceTier.TIER_1 if "1" in s else (SourceTier.TIER_2 if "2" in s else SourceTier.TIER_3)

                        det_state = parse_det_state(ev.deterministic_state)
                        src_tier = parse_src_tier(ev.source_tier)

                        cand = CandidateOpportunity(
                            candidate_id=f"exp_{ev.event_id}_{lat_bucket.value}_{int(threshold_bps)}_{int(target_size)}",
                            event_id=ev.event_id,
                            market_id=ev.market_id,
                            token_id=ev.token_id,
                            outcome=ev.winning_outcome,
                            deterministic_state=det_state,
                            source_tier=src_tier,
                            source_timestamp=ev.source_timestamp,
                            market_observation_timestamp=exec_snap["timestamp"],
                            latency_ms=offset_sec * 1000.0,
                            latency_bucket=lat_bucket,
                            entry_threshold_bps=threshold_bps,
                            target_size_usd=target_size,
                            best_ask=best_ask,
                            executable_vwap=best_ask,
                            available_depth_usd=sum(float(a.get("size_usd", float(a.get("price", 0))*float(a.get("size", 0)))) for a in asks_raw),
                            gross_edge_bps=gross_edge_bps,
                            net_ev_bps=gross_edge_bps - 5.0,
                            is_out_of_sample=ev.is_out_of_sample,
                            execution_status="EXECUTED" if gross_edge_bps >= threshold_bps else "THRESHOLD_NOT_MET"
                        )
                        candidates.append(cand)

                        if cand.execution_status == "EXECUTED":
                            exec_rec = ExecutionSimulator.simulate_execution(
                                candidate=cand,
                                asks=asks_raw,
                                settlement_value=1.0,
                                fee_stress_multiplier=1.0
                            )
                            if exec_rec is not None:
                                executions.append(exec_rec)

                                # Controls C1, C2, C3, C5, C6
                                c1 = AdversarialControlsEvaluator.evaluate_c1_pre_event_placebo(cand, 0.50, asks_raw)
                                c2 = AdversarialControlsEvaluator.evaluate_c2_random_timestamp(cand, 0.50)
                                c3 = AdversarialControlsEvaluator.evaluate_c3_reverse_outcome(cand, 0.99)
                                c5 = AdversarialControlsEvaluator.evaluate_c5_non_deterministic(ev.event_id, det_state)
                                c6_list = AdversarialControlsEvaluator.evaluate_c6_cost_stress(cand, asks_raw)

                                controls.extend([c1, c2, c3, c5] + c6_list)

        # C4 Shuffle control
        c4_list = AdversarialControlsEvaluator.evaluate_c4_source_shuffle(candidates[:30])
        controls.extend(c4_list)

        # 7. Statistical Evaluation across H1 - H5
        n_oos_events = len(oos_events)
        is_sparse = (n_oos_events < 30)

        h1_execs = [e for e in executions if any(c.candidate_id == e.candidate_id and c.deterministic_state == DeterministicState.STATE_A for c in candidates)]
        h1_cands = [c for c in candidates if c.deterministic_state == DeterministicState.STATE_A]
        h1_res = StatisticalEngine.evaluate_hypothesis(
            hypothesis_id="H1_OFFICIAL_RESULT", hypothesis_name="Official result lag",
            executions=h1_execs, candidates=h1_cands, threshold_bps=25.0,
            latency_bucket=LatencyBucket.B_1_2S, position_size_usd=50.0, is_sparse_universe=is_sparse
        )

        h2_execs = [e for e in executions if any(c.candidate_id == e.candidate_id and c.deterministic_state == DeterministicState.STATE_B for c in candidates)]
        h2_cands = [c for c in candidates if c.deterministic_state == DeterministicState.STATE_B]
        h2_res = StatisticalEngine.evaluate_hypothesis(
            hypothesis_id="H2_MECHANICAL_VALUE", hypothesis_name="Mechanical-value lag",
            executions=h2_execs, candidates=h2_cands, threshold_bps=25.0,
            latency_bucket=LatencyBucket.B_1_2S, position_size_usd=50.0, is_sparse_universe=is_sparse
        )

        h3_res = StatisticalEngine.evaluate_hypothesis(
            hypothesis_id="H3_EVENT_COMPLETION", hypothesis_name="Event-completion lag",
            executions=executions, candidates=candidates, threshold_bps=50.0,
            latency_bucket=LatencyBucket.B_500MS_1S, position_size_usd=50.0, is_sparse_universe=is_sparse
        )

        h4_res = StatisticalEngine.evaluate_hypothesis(
            hypothesis_id="H4_RESOLUTION_SOURCE", hypothesis_name="Resolution-source lag",
            executions=executions, candidates=candidates, threshold_bps=100.0,
            latency_bucket=LatencyBucket.B_1_2S, position_size_usd=100.0, is_sparse_universe=is_sparse
        )

        h5_res = StatisticalEngine.evaluate_hypothesis(
            hypothesis_id="H5_CROSS_SOURCE", hypothesis_name="Cross-source confirmation lag",
            executions=h1_execs, candidates=h1_cands, threshold_bps=50.0,
            latency_bucket=LatencyBucket.B_2_5S, position_size_usd=50.0, is_sparse_universe=is_sparse
        )

        hypotheses = [h1_res, h2_res, h3_res, h4_res, h5_res]
        p_vals = [h.p_value for h in hypotheses]
        adj_p_vals = StatisticalEngine.apply_holm_bonferroni(p_vals)
        for h, adj_p in zip(hypotheses, adj_p_vals):
            h.holm_bonferroni_p = adj_p

        # 8. Independence Metrics & Funnel
        indep_metrics = EventIndependenceTracker.compute_independence_metrics(accepted_events, len(candidates))
        funnel_metrics = {
            "raw_candidates": len(accepted_events) + len(rejections),
            "passed_source": len(accepted_events) + len([r for r in rejections if r.rejection_stage in ('MARKET_DISCOVERY_GATE', 'OUTCOME_TOKEN_GATE', 'EXACT_MATCH_GATE')]),
        }

        # 9. Verdict Determination (Section 8 & 29)
        # Required minimum: >= 30 independent OOS events to declare EVENT_UNIVERSE_NOW_SUFFICIENT
        if n_oos_events >= 30:
            final_verdict = Phase10A10BVerdict.EVENT_UNIVERSE_NOW_SUFFICIENT
            verdict_summary = (
                f"The expanded event universe contains {n_oos_events} independent OOS events (>= 30). "
                f"The statistical universe target is now satisfied."
            )
        else:
            final_verdict = Phase10A10BVerdict.EVENT_UNIVERSE_STILL_SPARSE
            verdict_summary = (
                f"The expanded event universe yielded {len(accepted_events)} total independent events and {n_oos_events} "
                f"independent OOS events. While independent events increased from 16 to {len(accepted_events)}, "
                f"the number of independent OOS events remains below the strict preregistered threshold of 30 "
                f"(N_OOS = {n_oos_events} < 30). Under Section 8 and Section 29, inclusion criteria were not relaxed, "
                f"and no synthetic events were manufactured. Therefore, the scientific verdict is EVENT_UNIVERSE_STILL_SPARSE."
            )

        # 10. Generate Report
        report_md = Phase10A10BReportGenerator.generate_report(
            events=accepted_events,
            executions=executions,
            controls=controls,
            hypotheses=hypotheses,
            rejections=rejections,
            funnel_metrics=funnel_metrics,
            independence_metrics=indep_metrics,
            split_summary=split_summary,
            verdict=final_verdict,
            verdict_summary=verdict_summary
        )

        report_path = "artifacts/phase10a10b_event_universe_expansion.md"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w") as f:
            f.write(report_md)

        brain_report_path = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170/phase10a10b_event_universe_expansion.md"
        with open(brain_report_path, "w") as f:
            f.write(report_md)

        oos_execs = [e for e in executions if e.is_out_of_sample]
        mean_oos_net = (sum(e.net_ev_bps for e in oos_execs) / len(oos_execs)) if oos_execs else 0.0

        return {
            "status": "COMPLETE",
            "verdict": final_verdict.value,
            "config_hash": PHASE10A10B_CONFIG_HASH,
            "raw_candidates": funnel_metrics["raw_candidates"],
            "total_events": len(accepted_events),
            "oos_events": n_oos_events,
            "total_candidates": len(candidates),
            "total_executions": len(executions),
            "oos_executions": len(oos_execs),
            "mean_oos_net_ev": mean_oos_net,
            "rejections_count": len(rejections),
            "report_path": report_path,
        }
