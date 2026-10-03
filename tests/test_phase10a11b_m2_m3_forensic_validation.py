"""Comprehensive Dedicated Test Suite for Phase 10A.11-B Forensic Validation.

Validates:
1. Continuous Live Recorder Monitoring (PID active, correct arguments, unmodified DB)
2. Frozen Candidate Reproduction for M2 and M3 verbatim from Phase 10A.11
3. M2 Price-Grid Partitions, Tick Boundary Dynamics, and Fee Sensitivity
4. M2 Temporal Persistence, Latency Stress, and Capacity Ladder Walking
5. M2 Placebo Permutations
6. M3 Multi-Outcome Mechanical Consistency (True vs Spread-Induced vs Midpoint)
7. M3 Asynchronous Lead-Lag and Multi-Leg Independent Execution
8. M3 Dependency, Pseudoreplication, and Effective Sample Constraints
9. Shared Anti-Lookahead, Provenance, and Concentration Audits
10. End-to-End Orchestrator Execution and Preregistered Final Verdicts
"""

import datetime
import subprocess
import pytest
import numpy as np

from src.phase10a11b import (
    ForensicVerdict, PriceGridRegion, TickBoundaryPosition, ConsistencyType
)
from src.phase10a11b.frozen_reproduction import (
    FrozenReproductionEngine, FrozenCandidateRecord
)
from src.phase10a11b.m2_forensic_engine import (
    M2ForensicEngine, M2EventRow, PriceGridPartitionResult, FeeAuditResult,
    TemporalPersistenceResult, LatencyStressResult, M2CapacityTierResult, M2PlaceboSummary
)
from src.phase10a11b.m3_forensic_engine import (
    M3ForensicEngine, M3EventRow, M3OutcomeLeg, MechanicalConsistencySummary,
    LeadLagHorizonResult, M3PseudoreplicationSummary
)
from src.phase10a11b.shared_controls import (
    SharedControlsEngine, LookaheadAuditSummary, ProvenanceAuditSummary, ConcentrationSummary
)
from src.phase10a11b.forensic_orchestrator import (
    ForensicValidationOrchestrator, MasterValidationResult, RecorderStatusRecord
)
from src.phase10a11b.report import ForensicReportGenerator


class TestRecorderContinuity:
    """Verifies that the live Polymarket recorder daemon is running continuously."""

    def test_recorder_daemon_is_running(self):
        res = subprocess.run(["pgrep", "-fl", "run_phase10a5e_daemon.py"], capture_output=True, text=True)
        pids = [int(line.split()[0]) for line in res.stdout.strip().split("\n") if line.strip()]
        assert len(pids) > 0, "CRITICAL: Live recorder daemon is NOT running! Must remain active."

    def test_recorder_target_config(self):
        orchestrator = ForensicValidationOrchestrator()
        status = orchestrator.get_recorder_status()
        assert status.is_running is True
        assert status.pid is not None
        assert "72.0" in status.target_config
        assert status.was_modified is False


class TestFrozenReproduction:
    """Verifies that Phase 10A.11 discovery results are reproduced verbatim."""

    def setup_method(self):
        self.engine = FrozenReproductionEngine()

    def test_m2_frozen_reproduction(self):
        repro = self.engine.reproduce_candidates()
        m2 = repro["M2_STRUCTURAL_FEE_SUBPENNY_WEDGE"]
        assert m2.discovery_n == 89
        assert m2.gross_ev_bps == 31.2
        assert m2.fees_bps == 5.0
        assert m2.net_ev_bps == 26.2
        assert m2.clustered_t_stat == 2.14
        assert m2.unadjusted_p_value == 0.032
        assert m2.holm_adjusted_p_value == 0.288
        assert m2.market_clusters == 18

    def test_m3_frozen_reproduction(self):
        repro = self.engine.reproduce_candidates()
        m3 = repro["M3_MULTI_OUTCOME_OVERHANG"]
        assert m3.discovery_n == 34
        assert m3.gross_ev_bps == 16.5
        assert m3.fees_bps == 5.0
        assert m3.net_ev_bps == 11.5
        assert m3.clustered_t_stat == 1.08
        assert m3.unadjusted_p_value == 0.280
        assert m3.holm_adjusted_p_value == 1.000
        assert m3.market_clusters == 8

    def test_verify_reproduction_passes(self):
        repro = self.engine.reproduce_candidates()
        assert self.engine.verify_reproduction("M2_STRUCTURAL_FEE_SUBPENNY_WEDGE", repro["M2_STRUCTURAL_FEE_SUBPENNY_WEDGE"]) is True
        assert self.engine.verify_reproduction("M3_MULTI_OUTCOME_OVERHANG", repro["M3_MULTI_OUTCOME_OVERHANG"]) is True

    def test_verify_reproduction_raises_on_unknown(self):
        with pytest.raises(ValueError):
            self.engine.verify_reproduction("M99_UNKNOWN", self.engine.FROZEN_M2)

    def test_frozen_record_to_dict(self):
        d = self.engine.FROZEN_M2.to_dict()
        assert d["candidate_id"] == "M2_STRUCTURAL_FEE_SUBPENNY_WEDGE"
        assert d["net_ev_bps"] == 26.2


class TestM2PriceGridAndBoundary:
    """Tests M2 price-grid regions and tick boundary classification."""

    def setup_method(self):
        self.engine = M2ForensicEngine()

    def test_assign_price_region_near_0(self):
        assert self.engine.assign_price_region(0.02) == PriceGridRegion.NEAR_0

    def test_assign_price_region_near_10(self):
        assert self.engine.assign_price_region(0.09) == PriceGridRegion.NEAR_10

    def test_assign_price_region_near_25(self):
        assert self.engine.assign_price_region(0.24) == PriceGridRegion.NEAR_25

    def test_assign_price_region_near_50(self):
        assert self.engine.assign_price_region(0.50) == PriceGridRegion.NEAR_50

    def test_assign_price_region_near_75(self):
        assert self.engine.assign_price_region(0.76) == PriceGridRegion.NEAR_75

    def test_assign_price_region_near_90(self):
        assert self.engine.assign_price_region(0.91) == PriceGridRegion.NEAR_90

    def test_assign_price_region_near_100(self):
        assert self.engine.assign_price_region(0.98) == PriceGridRegion.NEAR_100

    def test_tick_boundary_exact(self):
        assert self.engine.assign_boundary_position(0.010, tick_size=0.001) == TickBoundaryPosition.EXACT_BOUNDARY

    def test_tick_boundary_inside(self):
        assert self.engine.assign_boundary_position(0.0102, tick_size=0.001) == TickBoundaryPosition.ONE_TICK_INSIDE

    def test_tick_boundary_outside(self):
        assert self.engine.assign_boundary_position(0.0108, tick_size=0.001) == TickBoundaryPosition.ONE_TICK_OUTSIDE

    def test_evaluate_price_grid_partitions_empty(self):
        res = self.engine.evaluate_price_grid_partitions([])
        assert len(res) == len(PriceGridRegion)
        for r in res.values():
            assert r.sample_count == 0

    def test_evaluate_price_grid_partitions_with_events(self):
        events = [
            M2EventRow(
                event_id="e1", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=35.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            )
        ]
        res = self.engine.evaluate_price_grid_partitions(events)
        assert res[PriceGridRegion.NEAR_0].sample_count == 1
        assert res[PriceGridRegion.NEAR_0].mean_executable_net_ev_bps < 0.0

    def test_m2_event_row_to_dict(self):
        e = M2EventRow(
            event_id="e1", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
            best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
            price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
            candidate_wedge_bps=35.0, executable_entry=0.02, executable_exit_30s=0.04,
            gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
            diagnostic_midpoint_pnl_bps=0.0
        )
        d = e.to_dict()
        assert d["event_id"] == "e1"
        assert d["price_region"] == "NEAR_0"


class TestM2FeeAndTemporal:
    """Tests fee accounting sensitivity and temporal persistence for M2."""

    def setup_method(self):
        self.engine = M2ForensicEngine()

    def test_fee_audit_scenarios_present(self):
        res = self.engine.audit_fee_sensitivity([])
        assert "Zero Fee Diagnostic" in res
        assert "Baseline Fee (5 bps)" in res
        assert "2x Fee Stress (10 bps)" in res
        assert "3x Fee Stress (15 bps)" in res

    def test_zero_fee_diagnostic_verdict(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=35.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(10)
        ]
        res = self.engine.audit_fee_sensitivity(events)
        assert res["Zero Fee Diagnostic"].verdict == "NON_EXECUTABLE_SPREAD_CROSSING_FAILURE"
        assert res["Zero Fee Diagnostic"].mean_net_ev_bps < 0.0

    def test_fee_stress_worsens_net_ev(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=35.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(10)
        ]
        res = self.engine.audit_fee_sensitivity(events)
        assert res["3x Fee Stress (15 bps)"].mean_net_ev_bps < res["Baseline Fee (5 bps)"].mean_net_ev_bps

    def test_temporal_persistence_horizons(self):
        res = self.engine.evaluate_temporal_persistence([])
        assert len(res) == 9
        assert "Signal (0s)" in res
        assert "30 sec" in res

    def test_temporal_persistence_wedge_decays(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=50.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(5)
        ]
        res = self.engine.evaluate_temporal_persistence(events)
        assert res["30 sec"].mean_midpoint_wedge_bps < res["Signal (0s)"].mean_midpoint_wedge_bps

    def test_latency_stress_monotonic_degradation(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=50.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(5)
        ]
        res = self.engine.evaluate_latency_stress(events)
        assert res[2000].executable_net_ev_bps < res[0].executable_net_ev_bps


class TestM2CapacityAndPlacebos:
    """Tests L2 order book capacity and placebo permutations for M2."""

    def setup_method(self):
        self.engine = M2ForensicEngine()

    def test_capacity_tiers_all_present(self):
        res = self.engine.evaluate_capacity([])
        assert len(res) == 9
        for tier in [1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]:
            assert tier in res

    def test_capacity_max_profitable_order_size_is_zero(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=50.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(5)
        ]
        res = self.engine.evaluate_capacity(events)
        for tier, r in res.items():
            assert r.net_ev_bps < 0.0

    def test_placebo_suite_empty(self):
        p = self.engine.run_placebos([])
        assert p.overall_verdict == "NO_DATA"

    def test_placebo_suite_detects_negative_edge(self):
        events = [
            M2EventRow(
                event_id=f"e_{i}", market_id="m", token_id="t", timestamp=datetime.datetime.now(),
                best_bid=0.02, best_ask=0.04, spread_bps=5000.0, midpoint=0.03, tick_size=0.001,
                price_region=PriceGridRegion.NEAR_0, boundary_position=TickBoundaryPosition.EXACT_BOUNDARY,
                candidate_wedge_bps=50.0, executable_entry=0.02, executable_exit_30s=0.04,
                gross_pnl_bps=-5000.0, fee_bps=10.0, slippage_bps=5.0, net_pnl_bps=-5015.0,
                diagnostic_midpoint_pnl_bps=0.0
            ) for i in range(20)
        ]
        p = self.engine.run_placebos(events, n_permutations=50)
        assert p.overall_verdict == "FAILED_PLACEBOS_NEGATIVE_EDGE"


class TestM3MechanicalConsistency:
    """Tests M3 multi-outcome mechanical consistency classification."""

    def setup_method(self):
        self.engine = M3ForensicEngine()

    def test_consistency_types_present(self):
        assert ConsistencyType.TRUE_EXECUTABLE_INCONSISTENCY.value == "TRUE_EXECUTABLE_INCONSISTENCY"
        assert ConsistencyType.SPREAD_INDUCED_INCONSISTENCY.value == "SPREAD_INDUCED_INCONSISTENCY"
        assert ConsistencyType.APPARENT_MIDPOINT_INCONSISTENCY.value == "APPARENT_MIDPOINT_INCONSISTENCY"

    def test_evaluate_consistency_empty(self):
        res = self.engine.evaluate_mechanical_consistency([])
        assert res.total_observations == 0
        assert res.verdict == "NO_DATA"

    def test_spread_induced_dominance(self):
        legs = [
            M3OutcomeLeg("t1", "YES", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
            M3OutcomeLeg("t2", "NO", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
        ]
        events = [
            M3EventRow(
                event_id=f"m3_{i}", market_id="m", timestamp=datetime.datetime.now(), n_outcomes=2,
                legs=legs, sum_midpoints=1.00, sum_best_asks=1.04, sum_best_bids=0.96,
                consistency_type=ConsistencyType.SPREAD_INDUCED_INCONSISTENCY,
                leading_token_id="t1", lagging_token_id="t2", lead_lag_latency_ms=250.0,
                executable_entry_vwap=0.52, executable_exit_vwap_30s=0.48,
                gross_pnl_bps=-800.0, total_fee_bps=20.0, total_slippage_bps=10.0, net_pnl_bps=-830.0,
                is_true_executable_arb=False
            ) for i in range(10)
        ]
        res = self.engine.evaluate_mechanical_consistency(events)
        assert res.total_observations == 10
        assert res.spread_induced_count == 10
        assert res.pct_spread_induced == 100.0
        assert res.verdict == "NON_EXECUTABLE_SPREAD_DOMINATED"


class TestM3LeadLagAndExecution:
    """Tests M3 lead-lag horizon evaluation and multi-leg execution."""

    def setup_method(self):
        self.engine = M3ForensicEngine()

    def test_lead_lag_horizons_empty(self):
        res = self.engine.evaluate_lead_lag_horizons([])
        assert len(res) == 9
        assert "100 ms" in res
        assert "60 sec" in res

    def test_lead_lag_horizons_monotonic_convergence(self):
        legs = [
            M3OutcomeLeg("t1", "YES", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
            M3OutcomeLeg("t2", "NO", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
        ]
        events = [
            M3EventRow(
                event_id="e", market_id="m", timestamp=datetime.datetime.now(), n_outcomes=2,
                legs=legs, sum_midpoints=1.00, sum_best_asks=1.04, sum_best_bids=0.96,
                consistency_type=ConsistencyType.SPREAD_INDUCED_INCONSISTENCY,
                leading_token_id="t1", lagging_token_id="t2", lead_lag_latency_ms=250.0,
                executable_entry_vwap=0.52, executable_exit_vwap_30s=0.48,
                gross_pnl_bps=-800.0, total_fee_bps=20.0, total_slippage_bps=10.0, net_pnl_bps=-830.0,
                is_true_executable_arb=False
            )
        ]
        res = self.engine.evaluate_lead_lag_horizons(events)
        assert res["60 sec"].convergence_rate_pct >= res["100 ms"].convergence_rate_pct

    def test_multi_leg_fee_deductions_applied(self):
        legs = [
            M3OutcomeLeg("t1", "YES", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
            M3OutcomeLeg("t2", "NO", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
        ]
        e = M3EventRow(
            event_id="e", market_id="m", timestamp=datetime.datetime.now(), n_outcomes=2,
            legs=legs, sum_midpoints=1.00, sum_best_asks=1.04, sum_best_bids=0.96,
            consistency_type=ConsistencyType.SPREAD_INDUCED_INCONSISTENCY,
            leading_token_id="t1", lagging_token_id="t2", lead_lag_latency_ms=250.0,
            executable_entry_vwap=0.52, executable_exit_vwap_30s=0.48,
            gross_pnl_bps=-800.0, total_fee_bps=20.0, total_slippage_bps=10.0, net_pnl_bps=-830.0,
            is_true_executable_arb=False
        )
        assert e.total_fee_bps == 20.0
        assert e.net_pnl_bps == e.gross_pnl_bps - e.total_fee_bps - e.total_slippage_bps


class TestM3PseudoreplicationAndControls:
    """Tests clustering, effective sample constraints, and shared controls for M3."""

    def setup_method(self):
        self.engine = M3ForensicEngine()

    def test_pseudoreplication_empty(self):
        res = self.engine.audit_pseudoreplication([])
        assert res.raw_n == 0
        assert res.insufficient_evidence_flag is True

    def test_pseudoreplication_small_sample_flag(self):
        legs = [
            M3OutcomeLeg("t1", "YES", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
            M3OutcomeLeg("t2", "NO", 0.48, 0.52, 0.50, 1000.0, 1000.0, 800.0),
        ]
        events = [
            M3EventRow(
                event_id=f"m3_{i}", market_id=f"m_{i % 5}", timestamp=datetime.datetime.now(), n_outcomes=2,
                legs=legs, sum_midpoints=1.00, sum_best_asks=1.04, sum_best_bids=0.96,
                consistency_type=ConsistencyType.SPREAD_INDUCED_INCONSISTENCY,
                leading_token_id="t1", lagging_token_id="t2", lead_lag_latency_ms=250.0,
                executable_entry_vwap=0.52, executable_exit_vwap_30s=0.48,
                gross_pnl_bps=-800.0, total_fee_bps=20.0, total_slippage_bps=10.0, net_pnl_bps=-830.0,
                is_true_executable_arb=False, episode_id=f"ep_{i % 3}"
            ) for i in range(34)
        ]
        res = self.engine.audit_pseudoreplication(events)
        assert res.raw_n == 34
        assert res.insufficient_evidence_flag is True
        assert res.effective_n < 34


class TestSharedControlsAndOrchestrator:
    """Tests shared controls, master orchestrator, and report generation."""

    def setup_method(self):
        self.shared = SharedControlsEngine()

    def test_lookahead_audit_clean(self):
        res = self.shared.audit_lookahead([])
        assert res.verdict == "PASS_NO_DATA"

    def test_provenance_audit_clean(self):
        res = self.shared.audit_provenance(100)
        assert res.synthetic_records_found == 0
        assert res.interpolated_quotes_found == 0
        assert res.verdict == "PASS_PROVENANCE_INTEGRITY"

    def test_concentration_empty(self):
        res = self.shared.evaluate_concentration([])
        assert res.top1_pct == 0.0
        assert res.is_concentrated is False

    def test_orchestrator_end_to_end(self):
        orchestrator = ForensicValidationOrchestrator(db_path="data/prediction_market_readonly.duckdb")
        master_res = orchestrator.run_validation()
        assert master_res.m2_verdict == ForensicVerdict.EXECUTION_EDGE_ABSENT
        assert master_res.m3_verdict == ForensicVerdict.PROMISING_BUT_INSUFFICIENT_EVIDENCE
        assert master_res.paper_trading_eligible is False
        assert master_res.recorder_status.is_running is True

    def test_report_generator_contains_all_sections(self):
        orchestrator = ForensicValidationOrchestrator(db_path="data/prediction_market_readonly.duckdb")
        master_res = orchestrator.run_validation()
        gen = ForensicReportGenerator()
        report = gen.generate_report(master_res)
        assert "# PHASE 10A.11-B" in report
        assert "EXECUTION_EDGE_ABSENT" in report
        assert "PROMISING_BUT_INSUFFICIENT_EVIDENCE" in report
        assert "CRITICAL RECORDER AUDIT" in report
        assert "M2: PRICE-GRID PARTITION ANALYSIS" in report
        assert "M3: MECHANICAL CONSISTENCY TEST" in report

    def test_lookahead_audit_summary_to_dict(self):
        summary = LookaheadAuditSummary(10, 0, 0.0, "PASS_LOOKAHEAD_INTEGRITY")
        d = summary.to_dict()
        assert d["total_events_checked"] == 10
        assert d["verdict"] == "PASS_LOOKAHEAD_INTEGRITY"

    def test_provenance_audit_summary_to_dict(self):
        summary = ProvenanceAuditSummary(100, 0, 0, 0, "PASS_PROVENANCE_INTEGRITY")
        d = summary.to_dict()
        assert d["total_records_checked"] == 100
        assert d["verdict"] == "PASS_PROVENANCE_INTEGRITY"

    def test_concentration_summary_to_dict(self):
        summary = ConcentrationSummary(10.0, 30.0, 50.0, "mkt_1", 25.0, "General", 100.0, "2026-10-01", 60.0, True)
        d = summary.to_dict()
        assert d["top1_pct"] == 10.0
        assert d["is_concentrated"] is True

    def test_concentration_with_custom_events(self):
        class MockEv:
            def __init__(self, net_pnl, market_id):
                self.net_pnl_bps = net_pnl
                self.market_id = market_id
        events = [MockEv(-100.0, "mkt_A"), MockEv(-50.0, "mkt_B"), MockEv(-25.0, "mkt_A")]
        res = self.shared.evaluate_concentration(events)
        assert res.top1_pct > 0.0
        assert res.top_market_name == "mkt_A"

    def test_recorder_status_record_fields(self):
        status = RecorderStatusRecord(pid=12345, is_running=True, start_timestamp="2026-10-03 12:00:00", target_config="cfg", was_modified=False)
        assert status.pid == 12345
        assert status.is_running is True

    def test_master_validation_result_types(self):
        orchestrator = ForensicValidationOrchestrator(db_path="data/prediction_market_readonly.duckdb")
        master_res = orchestrator.run_validation()
        assert isinstance(master_res.m2_events, list)
        assert isinstance(master_res.m3_events, list)
        assert master_res.m2_partitions.discovery_n > 0
        assert master_res.m3_partitions.discovery_n > 0


class TestAdditionalCoverageAndEdgeCases:
    """Additional dedicated tests for serializations, edge cases, and stress bounds."""

    def test_m2_capacity_tier_to_dict(self):
        tier = M2CapacityTierResult(100.0, 1.0, 0.50, 200.0, 10.0, 5.0, -215.0)
        d = tier.to_dict()
        assert d["tier_usd"] == 100.0
        assert d["net_ev_bps"] == -215.0

    def test_m2_placebo_to_dict(self):
        p = M2PlaceboSummary(0.5, 0.4, 0.6, 0.7, 10.0, 0.3, 0.8, "PASSED_PLACEBOS")
        d = p.to_dict()
        assert d["overall_verdict"] == "PASSED_PLACEBOS"
        assert d["pre_event_wedge_bps"] == 10.0

    def test_price_grid_partition_to_dict(self):
        part = PriceGridPartitionResult(PriceGridRegion.NEAR_10, 5, 25.0, -450.0, 1200.0, 0.0)
        d = part.to_dict()
        assert d["region"] == "NEAR_10"
        assert d["sample_count"] == 5

    def test_fee_audit_result_to_dict(self):
        fee_res = FeeAuditResult("Baseline Fee (5 bps)", 5.0, -510.0, -500.0, 0.0, "ELIMINATED_BY_FEES")
        d = fee_res.to_dict()
        assert d["scenario"] == "Baseline Fee (5 bps)"
        assert d["verdict"] == "ELIMINATED_BY_FEES"

    def test_temporal_persistence_to_dict(self):
        temp = TemporalPersistenceResult("1 sec", 1.0, 20, 30.0, -520.0)
        d = temp.to_dict()
        assert d["horizon"] == "1 sec"
        assert d["horizon_sec"] == 1.0

    def test_latency_stress_to_dict(self):
        lat = LatencyStressResult(100, -550.0, -8.5)
        d = lat.to_dict()
        assert d["latency_ms"] == 100
        assert d["degradation_vs_0ms_bps"] == -8.5

    def test_m3_outcome_leg_dataclass(self):
        leg = M3OutcomeLeg("tok_1", "YES", 0.49, 0.51, 0.50, 5000.0, 5000.0, 400.0)
        assert leg.token_id == "tok_1"
        assert leg.midpoint == 0.50

    def test_m3_event_row_to_dict(self):
        leg = M3OutcomeLeg("tok_1", "YES", 0.49, 0.51, 0.50, 5000.0, 5000.0, 400.0)
        ev = M3EventRow(
            event_id="ev_m3", market_id="mkt_1", timestamp=datetime.datetime.now(), n_outcomes=2,
            legs=[leg], sum_midpoints=1.00, sum_best_asks=1.02, sum_best_bids=0.98,
            consistency_type=ConsistencyType.SPREAD_INDUCED_INCONSISTENCY,
            leading_token_id="tok_1", lagging_token_id="tok_2", lead_lag_latency_ms=100.0,
            executable_entry_vwap=0.51, executable_exit_vwap_30s=0.49, gross_pnl_bps=-400.0,
            total_fee_bps=20.0, total_slippage_bps=10.0, net_pnl_bps=-430.0, is_true_executable_arb=False
        )
        d = ev.to_dict()
        assert d["event_id"] == "ev_m3"
        assert d["is_true_executable_arb"] is False

    def test_mechanical_consistency_summary_to_dict(self):
        summ = MechanicalConsistencySummary(50, 0, 5, 45, 0, 0, 90.0, 15.0, 800.0, "NON_EXECUTABLE_SPREAD_DOMINATED")
        d = summ.to_dict()
        assert d["total_observations"] == 50
        assert d["verdict"] == "NON_EXECUTABLE_SPREAD_DOMINATED"

    def test_lead_lag_horizon_to_dict(self):
        ll = LeadLagHorizonResult("250 ms", 250.0, 30, 15.0, 40.0, -350.0)
        d = ll.to_dict()
        assert d["horizon_str"] == "250 ms"
        assert d["convergence_rate_pct"] == 40.0

    def test_m3_pseudoreplication_summary_to_dict(self):
        pseudo = M3PseudoreplicationSummary(34, 8, 8, 12, 18, 1.08, 0.28, True)
        d = pseudo.to_dict()
        assert d["raw_n"] == 34
        assert d["effective_n"] == 18
        assert d["insufficient_evidence_flag"] is True

    def test_m2_reconstruct_events_schema(self):
        engine = M2ForensicEngine()
        events = engine.reconstruct_m2_events(sample_limit=5)
        assert len(events) <= 5
        if events:
            assert isinstance(events[0], M2EventRow)

    def test_m3_reconstruct_events_schema(self):
        engine = M3ForensicEngine()
        events = engine.reconstruct_m3_events(sample_limit=5)
        assert len(events) <= 5
        if events:
            assert isinstance(events[0], M3EventRow)

    def test_frozen_reproduction_engine_singleton_values(self):
        engine = FrozenReproductionEngine()
        repro = engine.reproduce_candidates()
        assert "M2_STRUCTURAL_FEE_SUBPENNY_WEDGE" in repro
        assert "M3_MULTI_OUTCOME_OVERHANG" in repro
        assert repro["M2_STRUCTURAL_FEE_SUBPENNY_WEDGE"].discovery_n == 89
        assert repro["M3_MULTI_OUTCOME_OVERHANG"].discovery_n == 34

    def test_m2_tick_boundary_positions_exhaustiveness(self):
        engine = M2ForensicEngine()
        b_exact = engine.assign_boundary_position(0.0100, 0.001)
        b_in = engine.assign_boundary_position(0.0102, 0.001)
        b_out = engine.assign_boundary_position(0.0108, 0.001)
        assert b_exact == TickBoundaryPosition.EXACT_BOUNDARY
        assert b_in == TickBoundaryPosition.ONE_TICK_INSIDE
        assert b_out == TickBoundaryPosition.ONE_TICK_OUTSIDE

    def test_paper_trading_eligibility_invariant(self):
        orchestrator = ForensicValidationOrchestrator(db_path="data/prediction_market_readonly.duckdb")
        master_res = orchestrator.run_validation()
        # Invariant: Neither M2 nor M3 can be eligible for paper trading
        assert master_res.paper_trading_eligible is False

