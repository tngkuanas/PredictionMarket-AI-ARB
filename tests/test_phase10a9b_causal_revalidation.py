"""Comprehensive Test Suite for Phase 10A.9-B Strict Forward-Causal Revalidation.

Covers at least 18 dedicated tests:
1. test_no_pre_target_snapshot_selected
2. test_exact_target_timestamp_allowed
3. test_next_forward_snapshot_selected
4. test_previous_snapshot_rejected
5. test_no_forward_snapshot_fails
6. test_insufficient_forward_depth_partial
7. test_insufficient_forward_depth_zero
8. test_forward_latency_changes_book
9. test_zero_latency_is_forward_causal
10. test_all_completed_hedges_are_forward_causal
11. test_hard_causality_assertion_raises_on_retroactive_snapshot
12. test_adversarial_controls_are_forward_causal
13. test_pre_target_rejected_count_tracked
14. test_max_forward_horizon_exceeded_fails
15. test_factor_pnl_reconciliation_zero_error
16. test_cluster_fallback_artifact_eliminated
17. test_contamination_guard_blocks_synthetic
18. test_isolated_duckdb_persistence
"""

from datetime import datetime, timezone, timedelta
import tempfile
import os
import pytest
import numpy as np

from src.phase10a9b.schema import (
    CausalHedgeExecutionStatus,
    CausalHedgeExecutionRecord,
    CausalHedgedEconomicsRecord,
    CausalLatencyGridRecord,
    CausalAdversarialControlRecord,
    CausalHypothesisResultRecord,
)
from src.phase10a9b.hedge_executor import StrictForwardCausalHedgeExecutor
from src.phase10a9b.economics_engine import CausalHedgedEconomicsEngine
from src.phase10a9b.statistical_engine import CausalStatisticalEngine
from src.phase10a9b.db_store import (
    Phase10A9BDbStore,
    ProductionContaminationGuard,
    Phase10A9BContaminationError,
)


class DummyRelationship:
    def __init__(self, rel_id="rel_01", tok_a="tok_yes", tok_b="tok_no", ratio=1.0):
        self.relationship_id = rel_id
        self.contract_a = tok_a
        self.contract_b = tok_b
        self.hedge_ratio = ratio


@pytest.fixture
def base_time():
    return datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def executor():
    return StrictForwardCausalHedgeExecutor(default_fee_bps=0.0, max_forward_horizon_sec=30.0)


@pytest.fixture
def sample_fill(base_time):
    return {
        "fill_id": "fill_test_001",
        "token_id": "tok_yes",
        "fill_timestamp": base_time,
        "fill_price": 0.50,
        "fill_shares": 100.0,
        "fill_size_usd": 50.0,
        "side": "BUY",
        "gross_spread_bps": 400.0,
        "adverse_selection_bps": 850.0,
        "liquidation_cost_bps": 200.0,
        "unhedged_net_ev_bps": -450.0,
        "is_out_of_sample": True,
        "event_cluster_id": "cluster_oos_1",
    }


class TestPhase10A9BForwardCausalRevalidation:
    """Dedicated tests validating strict forward causality and error resolution."""

    # 1. No pre-target snapshot selected
    def test_01_no_pre_target_snapshot_selected(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        # Snapshot 1 is closer in absolute distance (50ms before target)
        # Snapshot 2 is 80ms after target
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=50), "asks": [{"price": 0.50, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=80), "asks": [{"price": 0.51, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.COMPLETED
        assert rec.selected_snapshot_timestamp == t_target + timedelta(milliseconds=80)
        assert rec.selected_snapshot_timestamp >= t_target
        assert rec.snapshot_was_forward is True

    # 2. Exact target timestamp allowed
    def test_02_exact_target_timestamp_allowed(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target, "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.COMPLETED
        assert rec.selected_snapshot_timestamp == t_target
        assert rec.snapshot_delta_ms == 0.0

    # 3. Next forward snapshot selected
    def test_03_next_forward_snapshot_selected(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snap_ts = t_target + timedelta(milliseconds=25)
        snaps = [
            {"token_id": "tok_no", "timestamp": snap_ts, "asks": [{"price": 0.50, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": snap_ts + timedelta(seconds=2), "asks": [{"price": 0.52, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.selected_snapshot_timestamp == snap_ts
        assert rec.hedge_status == CausalHedgeExecutionStatus.COMPLETED

    # 4. Previous snapshot rejected even if 1ms earlier
    def test_04_previous_snapshot_rejected(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        # Snapshot 1ms before target vs snapshot 500ms after target
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=1), "asks": [{"price": 0.50, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=500), "asks": [{"price": 0.53, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.selected_snapshot_timestamp == t_target + timedelta(milliseconds=500)
        assert rec.pre_target_rejected_count == 1

    # 5. No forward snapshot fails
    def test_05_no_forward_snapshot_fails(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        # All snapshots are before target
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target - timedelta(seconds=1), "asks": [{"price": 0.50, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=10), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.FAILED_NO_FORWARD_BOOK
        assert rec.selected_snapshot_timestamp is None
        assert rec.filled_quantity == 0.0
        assert rec.residual_unhedged_shares == 100.0

    # 6. Insufficient forward depth partial
    def test_06_insufficient_forward_depth_partial(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        # Required is 100 shares, book only has 40 shares
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=10), "asks": [{"price": 0.50, "size": 40.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.PARTIAL
        assert rec.filled_quantity == 40.0
        assert rec.residual_unhedged_shares == 60.0

    # 7. Insufficient forward depth zero
    def test_07_insufficient_forward_depth_zero(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=10), "asks": []},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.FAILED_INSUFFICIENT_DEPTH
        assert rec.filled_quantity == 0.0

    # 8. Forward latency changes book
    def test_08_forward_latency_changes_book(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=50), "asks": [{"price": 0.50, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=300), "asks": [{"price": 0.52, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=1500), "asks": [{"price": 0.55, "size": 200.0}]},
        ]
        # At 25ms latency -> target 25ms -> selects 50ms snap
        r25 = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=25)
        assert r25.selected_snapshot_timestamp == base_time + timedelta(milliseconds=50)

        # At 100ms latency -> target 100ms -> selects 300ms snap
        r100 = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert r100.selected_snapshot_timestamp == base_time + timedelta(milliseconds=300)

        # At 1000ms latency -> target 1000ms -> selects 1500ms snap
        r1000 = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=1000)
        assert r1000.selected_snapshot_timestamp == base_time + timedelta(milliseconds=1500)

        assert r25.selected_snapshot_timestamp < r100.selected_snapshot_timestamp < r1000.selected_snapshot_timestamp

    # 9. Zero latency is forward causal
    def test_09_zero_latency_is_forward_causal(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        # Pre-fill snapshot vs post-fill snapshot
        snaps = [
            {"token_id": "tok_no", "timestamp": base_time - timedelta(milliseconds=10), "asks": [{"price": 0.49, "size": 200.0}]},
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=5), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=0)
        assert rec.selected_snapshot_timestamp == base_time + timedelta(milliseconds=5)
        assert rec.selected_snapshot_timestamp >= base_time
        assert rec.pre_target_rejected_count == 1

    # 10. All completed hedges are forward causal
    def test_10_all_completed_hedges_are_forward_causal(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=120), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.COMPLETED
        assert rec.selected_snapshot_timestamp >= rec.hedge_target_timestamp

    # 11. Hard causality assertion raises on retroactive snapshot
    def test_11_hard_causality_assertion_raises_on_retroactive_snapshot(self, base_time):
        t_target = base_time + timedelta(milliseconds=100)
        t_retro = base_time + timedelta(milliseconds=50)  # 50ms before target!

        with pytest.raises((AssertionError, Exception), match="CRITICAL CAUSALITY VIOLATION"):
            CausalHedgeExecutionRecord(
                hedge_id="hdg_err",
                relationship_id="rel_01",
                passive_fill_id="fill_01",
                passive_token_id="tok_yes",
                hedge_token_id="tok_no",
                passive_fill_timestamp=base_time,
                hedge_latency_ms=100,
                hedge_target_timestamp=t_target,
                selected_snapshot_timestamp=t_retro,
                snapshot_delta_ms=-50.0,
                snapshot_was_forward=True,
                passive_fill_side="BUY",
                hedge_side="BUY",
                passive_fill_price=0.50,
                passive_filled_shares=100.0,
                passive_filled_usd=50.0,
                required_quantity=100.0,
                available_quantity=200.0,
                filled_quantity=100.0,
                VWAP=0.50,
                hedge_status=CausalHedgeExecutionStatus.COMPLETED,
            )

    # 12. Adversarial controls are forward causal
    def test_12_adversarial_controls_are_forward_causal(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=150), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        # Test C3 (5000ms latency)
        c3_target = base_time + timedelta(milliseconds=5000)
        snaps_c3 = [
            {"token_id": "tok_no", "timestamp": c3_target + timedelta(milliseconds=10), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec_c3 = executor.execute_causal_hedge(sample_fill, rel, snaps_c3, latency_ms=5000)
        assert rec_c3.selected_snapshot_timestamp >= c3_target

        # Test C4 (10% depth scaling)
        rec_c4 = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100, depth_scaling_factor=0.10)
        assert rec_c4.selected_snapshot_timestamp >= rec_c4.hedge_target_timestamp

    # 13. Pre-target rejected count correctly tracked
    def test_13_pre_target_rejected_count_tracked(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target - timedelta(seconds=5), "asks": [{"price": 0.50, "size": 100.0}]},
            {"token_id": "tok_no", "timestamp": t_target - timedelta(seconds=2), "asks": [{"price": 0.50, "size": 100.0}]},
            {"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=10), "asks": [{"price": 0.50, "size": 100.0}]},
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=20), "asks": [{"price": 0.50, "size": 100.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.pre_target_rejected_count == 3

    # 14. Max forward horizon exceeded fails
    def test_14_max_forward_horizon_exceeded_fails(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        # Snapshot is at t_target + 35s (exceeds default 30.0s horizon)
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target + timedelta(seconds=35), "asks": [{"price": 0.50, "size": 100.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.FAILED_NO_FORWARD_BOOK

    # 15. Factor P&L reconciliation zero error
    def test_15_factor_pnl_reconciliation_zero_error(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [
            {"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=150), "asks": [{"price": 0.50, "size": 200.0}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        econ_eng = CausalHedgedEconomicsEngine()
        econ_rec = econ_eng.evaluate_paired_economics(sample_fill, rec)

        # Factor accounting identity check
        recon = (
            econ_rec.passive_gross_spread_bps
            - (econ_rec.residual_inventory_cost_bps if not econ_rec.is_fully_hedged else 0.0)
            - (econ_rec.hedge_spread_cost_bps if econ_rec.is_fully_hedged else 0.0)
            - (econ_rec.hedge_slippage_bps if econ_rec.is_fully_hedged else 0.0)
            - (econ_rec.hedge_fee_bps if econ_rec.is_fully_hedged else 0.0)
            - (econ_rec.hedge_latency_cost_bps if econ_rec.is_fully_hedged else 0.0)
            - econ_rec.residual_liquidation_cost_bps
        )
        assert abs(econ_rec.hedged_net_ev_bps - recon) < 1e-4

    # 16. Cluster fallback artifact eliminated
    def test_16_cluster_fallback_artifact_eliminated(self):
        stat_eng = CausalStatisticalEngine()
        rng = np.random.default_rng(42)
        recs = []
        for i in range(219):
            recs.append(CausalHedgedEconomicsRecord(
                evaluation_id=f"eval_{i}",
                relationship_id="rel_01",
                passive_fill_id=f"fill_{i}",
                hedge_id=f"hdg_{i}",
                hedge_latency_ms=100,
                quote_policy="M1",
                queue_model="Q1",
                hedge_status=CausalHedgeExecutionStatus.COMPLETED,
                is_fully_hedged=True,
                passive_gross_spread_bps=400.0,
                passive_adverse_selection_bps=850.0,
                hedge_spread_cost_bps=200.0,
                hedge_slippage_bps=10.0,
                hedge_fee_bps=0.0,
                hedge_latency_cost_bps=2.0,
                residual_inventory_cost_bps=0.0,
                residual_liquidation_cost_bps=0.0,
                unhedged_net_ev_bps=-450.0,
                hedged_net_ev_bps=float(rng.normal(-75.0, 15.0)),
                ev_improvement_bps=375.0,
                hedged_pnl_usd=-0.375,
                is_out_of_sample=True,
                event_cluster_id="single_cluster",  # N_clusters = 1!
                provenance="POLYMARKET_LIVE"
            ))

        res = stat_eng.compute_causal_statistics(recs)
        assert res["n_clusters"] == 1
        assert res["cluster_inference_available"] is False
        # Must NOT return p=1.0000 fallback
        assert res["p_value"] < 1e-4
        assert res["t_stat"] < -10.0

    # 17. Contamination guard blocks synthetic
    def test_17_contamination_guard_blocks_synthetic(self):
        fake_rec = {"token_id": "tok_test", "provenance": "POLYMARKET_LIVE", "tag": "mock_data"}
        with pytest.raises(Phase10A9BContaminationError, match="Banned marker 'mock'"):
            ProductionContaminationGuard.assert_valid_production_record(fake_rec, is_production_db=True)

    # 18. Isolated DuckDB persistence
    def test_18_isolated_duckdb_persistence(self, base_time):
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "test.duckdb")
        try:
            store = Phase10A9BDbStore(db_path=tmp_path)
            t_target = base_time + timedelta(milliseconds=100)
            rec = CausalHedgeExecutionRecord(
                hedge_id="hdg_db_test",
                relationship_id="rel_01",
                passive_fill_id="fill_01",
                passive_token_id="tok_yes",
                hedge_token_id="tok_no",
                passive_fill_timestamp=base_time,
                hedge_latency_ms=100,
                hedge_target_timestamp=t_target,
                selected_snapshot_timestamp=t_target + timedelta(milliseconds=10),
                snapshot_delta_ms=10.0,
                snapshot_was_forward=True,
                passive_fill_side="BUY",
                hedge_side="BUY",
                passive_fill_price=0.50,
                passive_filled_shares=100.0,
                passive_filled_usd=50.0,
                required_quantity=100.0,
                available_quantity=200.0,
                filled_quantity=100.0,
                VWAP=0.50,
                hedge_slippage_bps=0.0,
                hedge_spread_bps=200.0,
                hedge_status=CausalHedgeExecutionStatus.COMPLETED,
                residual_unhedged_shares=0.0,
                residual_unhedged_usd=0.0,
                pre_target_rejected_count=5,
                provenance="POLYMARKET_LIVE"
            )
            store.persist_causal_executions([rec])

            with store._get_connection() as con:
                rows = con.execute("SELECT hedge_id, hedge_status, pre_target_rejected_count FROM phase10a9b_hedged_executions").fetchall()
                assert len(rows) == 1
                assert rows[0][0] == "hdg_db_test"
                assert rows[0][1] == "COMPLETED"
                assert rows[0][2] == 5
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
