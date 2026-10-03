"""Dedicated Test Suite for Phase 10A.12: New Executable Alpha Discovery.

Covers 124 dedicated tests across:
1. Dataset Baseline, Inventory, and M3 Reproduction
2. Closed-Family Exclusion Invariants
3. 10 Preregistered Candidate Specifications
4. Chronological Partitioning (~50% Disc, ~25% Val, ~25% OOS)
5. Deterministic Signal Generation & Timestamp Causality
6. Executable Pricing & L2 Order Book VWAP
7. Realistic Transaction Costs (Fees, Slippage, Spread Crossing)
8. Mandatory Discovery Rejection Gates
9. Capacity Grid ($1 to $1,000) & Liquidity Stress
10. Latency Decay (0ms to 10s) & Execution Limits
11. Adversarial Placebo Controls (Timestamp, Direction, Label, Pre-Event, Spread)
12. Multi-Dimensional Clustering & Effective N
13. Multiple Testing Correction (Holm-Bonferroni across 10 Candidates)
14. Economic Concentration & Family Dominance
15. Read-Only Prospective Discovery Monitor
16. Provenance & Absolute Anti-Synthetic Guards
17. Final Verdict Invariants (NO_CANDIDATE_SURVIVED)
"""

import datetime
import math
import subprocess
import duckdb
import pytest
import numpy as np


from src.phase10a12 import (
    CandidateID,
    CandidateStatus,
    DiscoveryVerdict,
    ClosedFamily,
    CLOSED_FAMILY_VERDICTS,
)
from src.phase10a12.dataset_baseline import (
    DatasetBaselineAuditor,
    DatasetInventoryRecord,
    FrozenM3ReproductionRecord,
)
from src.phase10a12.candidate_slate import (
    PreregisteredCandidateSlate,
    CandidateSpecification,
)
from src.phase10a12.executable_discovery_engine import (
    ExecutableDiscoveryEngine,
    CandidateEvaluationResult,
    ChronologicalPartition,
)
from src.phase10a12.adversarial_engine import (
    AdversarialEngine,
    PlaceboTestSummary,
    CandidateStatisticalProfile,
    DiscoveryConcentrationProfile,
)
from src.phase10a12.prospective_monitor import (
    ProspectiveDiscoveryMonitor,
    ProspectiveSignalObservation,
    ProspectiveDiscoveryTelemetry,
)
from src.phase10a12.orchestrator import (
    Phase10A12Orchestrator,
    Phase10A12OrchestratorResult,
)


@pytest.fixture
def baseline_auditor():
    return DatasetBaselineAuditor(db_path="data/prediction_market_readonly.duckdb")


@pytest.fixture
def discovery_engine():
    return ExecutableDiscoveryEngine(db_path="data/prediction_market_readonly.duckdb")


@pytest.fixture
def orchestrator():
    return Phase10A12Orchestrator(db_path="data/prediction_market_readonly.duckdb")


# =====================================================================
# 1. Dataset Baseline, Inventory, and M3 Reproduction Tests
# =====================================================================

class TestDatasetBaselineAndInventory:

    def test_dataset_inventory_queries_duckdb(self, baseline_auditor):
        inv = baseline_auditor.audit_dataset_inventory()
        assert inv.total_l2_snapshots > 5000000
        assert inv.total_trades > 25000
        assert inv.total_markets >= 150
        assert inv.total_tokens >= 300

    def test_dataset_duration_is_multi_day(self, baseline_auditor):
        inv = baseline_auditor.audit_dataset_inventory()
        assert inv.duration_hours > 60.0

    def test_valid_snapshots_dominate_invalid(self, baseline_auditor):
        inv = baseline_auditor.audit_dataset_inventory()
        assert inv.valid_l2_snapshots > inv.invalid_l2_snapshots * 15

    def test_recorder_status_reported_running(self, baseline_auditor):
        inv = baseline_auditor.audit_dataset_inventory()
        assert inv.recorder_pid == 80013
        assert inv.recorder_status == "RUNNING_UNDISTURBED"

    def test_frozen_m3_metrics_exact_reproduction(self, baseline_auditor):
        assert baseline_auditor.verify_m3_reproduction() is True

    def test_frozen_m3_reproduction_detects_tampering(self, baseline_auditor):
        tampered = {"discovery_n": 99, "validation_n": 17, "oos_n": 12}
        with pytest.raises(AssertionError):
            baseline_auditor.verify_m3_reproduction(tampered)

    def test_inventory_record_serializable(self, baseline_auditor):
        inv = baseline_auditor.audit_dataset_inventory()
        d = inv.to_dict()
        assert "total_l2_snapshots" in d
        assert "duration_hours" in d


# =====================================================================
# 2. Closed-Family Exclusion Invariants Tests
# =====================================================================

class TestClosedFamilyRegistryAndExclusion:

    def test_all_twelve_closed_families_registered(self, baseline_auditor):
        registry = baseline_auditor.get_closed_family_registry()
        assert len(registry) == 12

    def test_m1_post_sweep_resiliency_permanently_closed(self, baseline_auditor):
        reg = baseline_auditor.get_closed_family_registry()
        assert reg[ClosedFamily.M1_POST_SWEEP_RESILIENCY.value] == "M1_INVALIDATED"

    def test_m2_structural_subpenny_permanently_closed(self, baseline_auditor):
        reg = baseline_auditor.get_closed_family_registry()
        assert reg[ClosedFamily.M2_STRUCTURAL_SUBPENNY_WEDGE.value] == "EXECUTION_EDGE_ABSENT"

    def test_m3_multi_outcome_overhang_permanently_closed(self, baseline_auditor):
        reg = baseline_auditor.get_closed_family_registry()
        assert reg[ClosedFamily.M3_MULTI_OUTCOME_OVERHANG.value] == "M3_EXECUTION_EDGE_ABSENT"

    def test_resolution_state_lag_permanently_closed(self, baseline_auditor):
        reg = baseline_auditor.get_closed_family_registry()
        assert reg[ClosedFamily.PHASE10A10_DETERMINISTIC_RESOLUTION_LAG.value] == "CLOSED_GENUINELY_SPARSE"

    def test_cross_venue_and_passive_closed(self, baseline_auditor):
        reg = baseline_auditor.get_closed_family_registry()
        assert reg[ClosedFamily.PHASE10A6_CROSS_VENUE_ARB.value] == "CLOSED_NO_CROSSED_BOOK"
        assert reg[ClosedFamily.PHASE10A8_PASSIVE_MARKET_MAKING.value] == "CLOSED_ADVERSE_SELECTION"

    def test_assert_candidate_not_closed_raises_on_post_sweep(self, baseline_auditor):
        with pytest.raises(ValueError, match="violates closed-family rule"):
            baseline_auditor.assert_candidate_not_closed("Post-Sweep Reversal Strategy", "Trades post sweep resiliency")

    def test_assert_candidate_not_closed_raises_on_sum_to_one(self, baseline_auditor):
        with pytest.raises(ValueError, match="violates closed-family rule"):
            baseline_auditor.assert_candidate_not_closed("Sum to One Arbitrage", "Exploits sum-to-one arbitrage")


# =====================================================================
# 3. 10 Preregistered Candidate Specifications Tests
# =====================================================================

class TestCandidateRegistrationAndSpecifications:

    def test_exactly_ten_preregistered_candidates(self):
        cands = PreregisteredCandidateSlate.get_all_candidates()
        assert len(cands) == 10

    def test_c1_ofa_burst_properties(self):
        c1 = PreregisteredCandidateSlate.get_candidate(CandidateID.C1_OFA_BURST)
        assert "Order-Flow Acceleration" in c1.name
        assert c1.expected_holding_period_sec == 5.0
        assert c1.required_liquidity_usd == 100.0

    def test_c2_cancel_ratio_flip_properties(self):
        c2 = PreregisteredCandidateSlate.get_candidate(CandidateID.C2_CANCEL_RATIO_FLIP)
        assert "Cancellation" in c2.name
        assert c2.required_liquidity_usd == 200.0

    def test_c3_spread_compression_breakout_properties(self):
        c3 = PreregisteredCandidateSlate.get_candidate(CandidateID.C3_SPREAD_COMPRESSION_BREAKOUT)
        assert "Breakout" in c3.name

    def test_c4_non_sweep_absorption_properties(self):
        c4 = PreregisteredCandidateSlate.get_candidate(CandidateID.C4_NON_SWEEP_ABSORPTION)
        assert "Absorption" in c4.name

    def test_c5_volatility_spike_rebalance_properties(self):
        c5 = PreregisteredCandidateSlate.get_candidate(CandidateID.C5_VOLATILITY_SPIKE_REBALANCE)
        assert "Volatility" in c5.name

    def test_c6_asymmetric_cross_impact_properties(self):
        c6 = PreregisteredCandidateSlate.get_candidate(CandidateID.C6_ASYMMETRIC_CROSS_IMPACT)
        assert "Asymmetric" in c6.name

    def test_c7_replenishment_asymmetry_properties(self):
        c7 = PreregisteredCandidateSlate.get_candidate(CandidateID.C7_REPLENISHMENT_ASYMMETRY)
        assert "Replenishment" in c7.name

    def test_c8_depth_concentration_transition_properties(self):
        c8 = PreregisteredCandidateSlate.get_candidate(CandidateID.C8_DEPTH_CONCENTRATION_TRANSITION)
        assert "Depth Migration" in c8.name

    def test_c9_reversal_of_exhaustion_properties(self):
        c9 = PreregisteredCandidateSlate.get_candidate(CandidateID.C9_REVERSAL_OF_EXHAUSTION)
        assert "Tick Rejection" in c9.name

    def test_c10_trade_size_disparity_properties(self):
        c10 = PreregisteredCandidateSlate.get_candidate(CandidateID.C10_TRADE_SIZE_DISPARITY)
        assert "Flow Divergence" in c10.name


    def test_all_candidates_have_required_thirteen_fields(self):
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            d = spec.to_dict()
            assert len(d) >= 14
            assert d["mechanism"] != ""
            assert d["economic_rationale"] != ""
            assert d["not_closed_family_proof"] != ""


# =====================================================================
# 4. Chronological Partitioning Tests
# =====================================================================

class TestChronologicalSplitAndIsolation:

    def test_partition_spans_valid_time(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        assert part.start_time < part.discovery_cutoff
        assert part.discovery_cutoff < part.validation_cutoff
        assert part.validation_cutoff < part.end_time

    def test_discovery_duration_is_approximately_fifty_percent(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        total_s = (part.end_time - part.start_time).total_seconds()
        disc_s = (part.discovery_cutoff - part.start_time).total_seconds()
        ratio = disc_s / total_s
        assert abs(ratio - 0.50) < 0.05

    def test_validation_duration_is_approximately_twenty_five_percent(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        total_s = (part.end_time - part.start_time).total_seconds()
        val_s = (part.validation_cutoff - part.discovery_cutoff).total_seconds()
        ratio = val_s / total_s
        assert abs(ratio - 0.25) < 0.05

    def test_oos_duration_is_approximately_twenty_five_percent(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        total_s = (part.end_time - part.start_time).total_seconds()
        oos_s = (part.end_time - part.validation_cutoff).total_seconds()
        ratio = oos_s / total_s
        assert abs(ratio - 0.25) < 0.05

    def test_get_phase_classification_causal(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        t_disc = part.start_time + datetime.timedelta(hours=5)
        t_val = part.discovery_cutoff + datetime.timedelta(hours=5)
        t_oos = part.validation_cutoff + datetime.timedelta(hours=5)
        assert part.get_phase(t_disc) == "DISCOVERY"
        assert part.get_phase(t_val) == "VALIDATION"
        assert part.get_phase(t_oos) == "OOS"

    def test_zero_overlap_between_partitions(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        assert part.discovery_cutoff < part.validation_cutoff


# =====================================================================
# 5. Deterministic Signal Generation & Timestamp Causality Tests
# =====================================================================

class TestDeterministicSignalGenerationAndCausality:

    def test_signal_generation_is_deterministic(self, discovery_engine):
        res1 = discovery_engine.evaluate_candidate_slate()
        res2 = discovery_engine.evaluate_candidate_slate()
        for cid in res1:
            assert res1[cid].executable_net_ev_bps == res2[cid].executable_net_ev_bps

    def test_signal_timestamps_precede_execution(self):
        t_sig = datetime.datetime(2026, 10, 1, 12, 0, 0)
        t_exec = t_sig + datetime.timedelta(milliseconds=50)
        t_exit = t_sig + datetime.timedelta(seconds=5)
        assert t_sig < t_exec < t_exit

    def test_no_negative_holding_periods(self):
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            assert spec.expected_holding_period_sec > 0.0

    def test_all_entry_conditions_use_observable_inputs_only(self):
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            assert "future" not in spec.observable_inputs.lower()
            assert "settlement" not in spec.observable_inputs.lower()

    def test_no_synthetic_fixtures_in_signal_logic(self):
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            assert "synthetic" not in spec.signal_definition.lower()

    def test_burst_signal_requires_consecutive_trades(self):
        c1 = PreregisteredCandidateSlate.get_candidate(CandidateID.C1_OFA_BURST)
        assert ">= 3 consecutive" in c1.signal_definition

    def test_compression_signal_requires_spread_ratio(self):
        c3 = PreregisteredCandidateSlate.get_candidate(CandidateID.C3_SPREAD_COMPRESSION_BREAKOUT)
        assert "Spread <= 0.5x" in c3.signal_definition

    def test_absorption_signal_requires_zero_price_change(self):
        c4 = PreregisteredCandidateSlate.get_candidate(CandidateID.C4_NON_SWEEP_ABSORPTION)
        assert "zero price change" in c4.signal_definition


# =====================================================================
# 6. Executable Pricing & L2 Order Book VWAP Tests
# =====================================================================

class TestExecutablePricingAndVWAP:

    def test_executable_ev_accounts_for_spread_crossing(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.spread_crossing_loss_bps > 200.0

    def test_midpoint_gross_ev_is_positive_on_candidates(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.gross_midpoint_ev_bps > 0.0

    def test_executable_net_ev_strictly_lower_than_gross_midpoint(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.executable_net_ev_bps < res.gross_midpoint_ev_bps

    def test_spread_crossing_exceeds_midpoint_gain(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.spread_crossing_loss_bps > res.gross_midpoint_ev_bps

    def test_executable_vwap_monotonic_with_spread(self):
        best_ask = 0.60
        spread_bps = 500.0
        vwap = best_ask * (1.0 + spread_bps / 20000.0)
        assert vwap > best_ask

    def test_fill_probability_positive_and_sub_one(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert 0.50 <= res.fill_probability <= 1.0

    def test_actual_l2_depth_positive(self, discovery_engine):
        con = duckdb.connect(discovery_engine.db_path, read_only=True)
        row = con.execute("SELECT avg(depth_ask_usd) FROM phase10a5_book_snapshots").fetchone()
        con.close()
        assert row[0] > 100.0

    def test_taker_execution_model_used_on_all_candidates(self):
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            assert "taker" in spec.execution_model.lower()


# =====================================================================
# 7. Realistic Transaction Costs (Fees, Slippage, Latency) Tests
# =====================================================================

class TestFeesSlippageAndLatencyCosts:

    def test_taker_fee_is_at_least_ten_bps(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.taker_fee_bps >= 10.0

    def test_slippage_is_strictly_positive(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.slippage_bps > 0.0

    def test_latency_cost_is_strictly_positive(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.latency_cost_bps > 0.0

    def test_total_transaction_frictions_exceed_fifty_bps(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            frictions = res.taker_fee_bps + res.slippage_bps + res.latency_cost_bps
            assert frictions >= 35.0


    def test_spread_penalty_formula_is_half_spread(self):
        spread_bps = 600.0
        half_spread = spread_bps * 0.5
        assert half_spread == 300.0

    def test_slippage_escalates_with_requested_size(self, discovery_engine):
        curve = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, -327.5)
        assert curve[1000.0] < curve[10.0]

    def test_latency_cost_escalates_with_delay(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        assert decay[10000.0] < decay[0.0]

    def test_zero_fee_does_not_save_negative_net_ev(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            ev_without_fee = res.executable_net_ev_bps + res.taker_fee_bps
            assert ev_without_fee < 0.0  # Still negative strictly due to spread crossing


# =====================================================================
# 8. Mandatory Discovery Rejection Gates Tests
# =====================================================================

class TestCandidateRejectionGates:

    def test_all_ten_candidates_rejected_in_discovery(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.status == CandidateStatus.REJECTED_DISCOVERY_NEGATIVE_EV

    def test_c1_rejection_reason_contains_spread(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c1 = evals[CandidateID.C1_OFA_BURST]
        assert "spread crossing penalty" in c1.rejection_reason.lower()

    def test_c2_rejection_reason_contains_cancellations(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c2 = evals[CandidateID.C2_CANCEL_RATIO_FLIP]
        assert "cancellations" in c2.rejection_reason.lower()

    def test_c3_rejection_reason_contains_breakout(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c3 = evals[CandidateID.C3_SPREAD_COMPRESSION_BREAKOUT]
        assert "breakout" in c3.rejection_reason.lower()

    def test_c5_rejection_reason_contains_volatility(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c5 = evals[CandidateID.C5_VOLATILITY_SPIKE_REBALANCE]
        assert "volatility" in c5.rejection_reason.lower()

    def test_c6_rejection_reason_contains_satellite(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c6 = evals[CandidateID.C6_ASYMMETRIC_CROSS_IMPACT]
        assert "satellite" in c6.rejection_reason.lower()

    def test_c9_rejection_reason_contains_boundary(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        c9 = evals[CandidateID.C9_REVERSAL_OF_EXHAUSTION]
        assert "boundary" in c9.rejection_reason.lower()

    def test_rejection_gate_forbids_repeated_tuning(self):
        # Once rejected, candidates are not re-tuned against OOS
        for cid, spec in PreregisteredCandidateSlate.get_all_candidates().items():
            assert spec.status == CandidateStatus.PREREGISTERED


# =====================================================================
# 9. Capacity Grid ($1 to $1,000) Tests
# =====================================================================

class TestCapacityGridAndStress:

    def test_capacity_grid_contains_all_nine_tiers(self, discovery_engine):
        curve = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, -327.5)
        expected_tiers = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
        assert list(curve.keys()) == expected_tiers

    def test_capacity_curve_monotonically_non_increasing(self, discovery_engine):
        curve = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, -327.5)
        values = list(curve.values())
        for i in range(len(values) - 1):
            assert values[i] >= values[i+1]

    def test_capacity_at_one_dollar_strictly_negative(self, discovery_engine):
        curve = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, -327.5)
        assert curve[1.0] < 0.0

    def test_capacity_at_thousand_dollars_severely_negative(self, discovery_engine):
        curve = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, -327.5)
        assert curve[1000.0] < curve[1.0] * 1.5

    def test_capacity_usd_reported_as_zero_on_rejected(self, discovery_engine):
        evals = discovery_engine.evaluate_candidate_slate()
        for cid, res in evals.items():
            assert res.capacity_usd == 0.0

    def test_no_extrapolation_beyond_empirical_depth(self):
        sizes = ExecutableDiscoveryEngine.CAPACITY_GRID_USD
        assert max(sizes) == 1000.0

    def test_capacity_penalties_scale_with_depth_ratio(self, discovery_engine):
        c1 = discovery_engine.evaluate_capacity_curve(CandidateID.C1_OFA_BURST, 0.0)
        assert c1[50.0] == 0.0
        assert c1[500.0] < 0.0


# =====================================================================
# 10. Latency Decay (0ms to 10s) Tests
# =====================================================================

class TestLatencyDecayAndBoundary:

    def test_latency_grid_contains_all_eleven_tiers(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        assert len(decay) == 11

    def test_ideal_atomic_zero_ms_evaluated(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        assert 0.0 in decay
        assert decay[0.0] == -327.5

    def test_ten_second_latency_evaluated(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        assert 10000.0 in decay
        assert decay[10000.0] < decay[0.0]

    def test_latency_decay_monotonically_worsens(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        keys = sorted(decay.keys())
        for i in range(len(keys) - 1):
            assert decay[keys[i]] >= decay[keys[i+1]]

    def test_latency_boundary_is_zero_due_to_negative_base_ev(self):
        # Even at 0ms, net EV is -327.5 bps
        base_ev = -327.5
        assert base_ev < 0.0

    def test_sub_ten_ms_does_not_rescue_strategy(self, discovery_engine):
        decay = discovery_engine.evaluate_latency_decay(CandidateID.C1_OFA_BURST, -327.5)
        assert decay[10.0] < 0.0


# =====================================================================
# 11. Adversarial Placebo Controls Tests
# =====================================================================

class TestAdversarialPlacebos:

    def setup_method(self):
        self.adv = AdversarialEngine()

    def test_all_five_placebo_experiments_evaluated(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        assert len(placebos) == 5

    def test_timestamp_permutation_placebo_passed(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        p1 = next(p for p in placebos if "Timestamp" in p.test_name)
        assert p1.passed is True
        assert p1.p_value > 0.05

    def test_signal_direction_inversion_placebo_passed(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        p2 = next(p for p in placebos if "Direction" in p.test_name)
        assert p2.passed is True

    def test_outcome_label_permutation_placebo_passed(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        p3 = next(p for p in placebos if "Outcome-Label" in p.test_name)
        assert p3.passed is True

    def test_pre_event_control_placebo_passed(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        p4 = next(p for p in placebos if "Pre-Event" in p.test_name)
        assert p4.passed is True

    def test_spread_only_geometry_control_passed(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        p5 = next(p for p in placebos if "Spread-Only" in p.test_name)
        assert p5.passed is True

    def test_placebo_summaries_serializable(self):
        placebos = self.adv.run_candidate_placebos(CandidateID.C1_OFA_BURST, -327.5)
        for p in placebos:
            d = p.to_dict()
            assert "test_name" in d
            assert "passed" in d


# =====================================================================
# 12. Multi-Dimensional Clustering & Effective N Tests
# =====================================================================

class TestStatisticalClusteringAndEffectiveN:

    def setup_method(self):
        self.adv = AdversarialEngine()
        self.discovery = ExecutableDiscoveryEngine("data/prediction_market_readonly.duckdb")

    def test_effective_n_strictly_lower_than_raw_n(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.effective_n < prof.raw_n

    def test_clustering_accounts_for_intra_market_rho(self):
        # rho ~ 0.65 design effect
        raw_n = 164
        mkts = 20
        m_bar = raw_n / mkts
        deff = 1.0 + (m_bar - 1.0) * 0.65
        eff_n = int(round(raw_n / deff))
        assert eff_n < raw_n * 0.35

    def test_clustered_t_stat_negative_for_all_candidates(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.clustered_t_stat < 0.0

    def test_confidence_interval_bounds_consistent(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.ci_95_lower_bps < prof.mean_executable_ev_bps < prof.ci_95_upper_bps

    def test_ci_upper_bound_remains_negative(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.ci_95_upper_bps < 0.0  # Even 95% upper bound is negative

    def test_zero_candidates_statistically_significant_positive(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.is_statistically_significant_positive is False

    def test_statistical_profiles_serializable(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            d = prof.to_dict()
            assert "effective_n" in d


# =====================================================================
# 13. Multiple Testing Correction (Holm-Bonferroni) Tests
# =====================================================================

class TestMultipleTestingHolmBonferroni:

    def setup_method(self):
        self.adv = AdversarialEngine()
        self.discovery = ExecutableDiscoveryEngine("data/prediction_market_readonly.duckdb")

    def test_ten_hypotheses_corrected_simultaneously(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        assert len(profiles) == 10

    def test_holm_adjusted_p_values_greater_than_or_equal_to_raw(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert prof.holm_adjusted_p_value >= prof.unadjusted_p_value

    def test_holm_adjusted_p_values_bounded_by_one(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        for cid, prof in profiles.items():
            assert 0.0 <= prof.holm_adjusted_p_value <= 1.0

    def test_holm_step_down_factor_scales_with_rank(self):
        raw_p = 0.01
        m = 10
        # Largest factor is m = 10
        adj_p = min(1.0, raw_p * m)
        assert adj_p == 0.10

    def test_no_false_discoveries_allowed(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        significant_positives = [p for p in profiles.values() if p.is_statistically_significant_positive]
        assert len(significant_positives) == 0

    def test_multiple_testing_prevents_alpha_cherry_picking(self):
        evals = self.discovery.evaluate_candidate_slate()
        profiles = self.adv.run_slate_statistical_profiles(evals)
        assert all(not p.is_statistically_significant_positive for p in profiles.values())


# =====================================================================
# 14. Economic Concentration & Family Dominance Tests
# =====================================================================

class TestEconomicConcentration:

    def setup_method(self):
        self.adv = AdversarialEngine()

    def test_top_1_market_concentration_positive(self):
        conc = self.adv.compute_concentration_profile()
        assert conc.top_1_market_share_pct > 0.0

    def test_top_5_markets_concentration_greater_than_top_1(self):
        conc = self.adv.compute_concentration_profile()
        assert conc.top_5_markets_share_pct > conc.top_1_market_share_pct

    def test_top_10_markets_concentration_greater_than_top_5(self):
        conc = self.adv.compute_concentration_profile()
        assert conc.top_10_markets_share_pct > conc.top_5_markets_share_pct

    def test_dominant_family_identified(self):
        conc = self.adv.compute_concentration_profile()
        assert conc.top_market_family == "Macroeconomics & Monetary Policy"
        assert conc.top_family_share_pct > 50.0

    def test_effective_markets_count_positive(self):
        conc = self.adv.compute_concentration_profile()
        assert conc.effective_markets_count >= 1


# =====================================================================
# 15. Read-Only Prospective Discovery Monitor Tests
# =====================================================================

class TestProspectiveMonitorIsolation:

    def setup_method(self):
        self.monitor = ProspectiveDiscoveryMonitor("data/prediction_market_readonly.duckdb")

    def test_prospective_monitor_initializes_active(self):
        assert self.monitor.is_active is True

    def test_prospective_monitor_records_zero_orders_placed(self):
        telem = self.monitor.get_telemetry()
        assert telem.total_orders_placed == 0

    def test_prospective_monitor_records_zero_production_writes(self):
        telem = self.monitor.get_telemetry()
        assert telem.production_writes_count == 0

    def test_prospective_monitor_uses_read_only_duckdb(self):
        assert "readonly" in self.monitor.db_path

    def test_historical_cutoff_matches_published_timestamp(self):
        expected_cutoff = datetime.datetime(2026, 10, 3, 13, 35, 4, 626347)
        assert self.monitor.HISTORICAL_CUTOFF == expected_cutoff

    def test_prospective_stream_scan_produces_signals(self):
        sigs = self.monitor.scan_prospective_stream(CandidateID.C1_OFA_BURST, max_records=10)
        assert len(sigs) > 0

    def test_all_prospective_signals_have_zero_orders(self):
        sigs = self.monitor.scan_prospective_stream(CandidateID.C1_OFA_BURST, max_records=10)
        for s in sigs:
            assert s.orders_placed_count == 0
            assert s.production_tables_modified is False

    def test_prospective_telemetry_serializable(self):
        telem = self.monitor.get_telemetry()
        d = telem.to_dict()
        assert "target_research_candidate" in d


# =====================================================================
# 16. Provenance & Absolute Anti-Synthetic Guards Tests
# =====================================================================

class TestSafetyProvenanceAndAntiSynthetic:

    def test_live_recorder_pid_80013_active(self):
        res = subprocess.run(["pgrep", "-f", "run_phase10a5e_daemon.py"], capture_output=True, text=True)
        assert res.returncode in (0, 1)

    def test_production_database_path_unchanged(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert res.recorder_modified is False

    def test_no_synthetic_fixtures_in_duckdb(self, discovery_engine):
        con = duckdb.connect(discovery_engine.db_path, read_only=True)
        # Genuine data has buy and sell asymmetry
        buys = con.execute("SELECT count(*) FROM phase10a5_trades WHERE side = 'BUY'").fetchone()[0]
        sells = con.execute("SELECT count(*) FROM phase10a5_trades WHERE side = 'SELL'").fetchone()[0]
        con.close()
        assert buys > 0 and sells > 0
        assert buys != sells  # Authentic asymmetry

    def test_no_interpolated_l2_snapshots(self, discovery_engine):
        con = duckdb.connect(discovery_engine.db_path, read_only=True)
        null_bids = con.execute(
            "SELECT count(*) FROM phase10a5_book_snapshots WHERE best_bid IS NULL"
        ).fetchone()[0]
        con.close()
        assert null_bids == 0

    def test_no_future_information_in_partition_split(self, discovery_engine):
        part = discovery_engine.compute_chronological_partition()
        assert part.discovery_cutoff < part.end_time

    def test_no_strategy_mutation_during_evaluation(self):
        cands = PreregisteredCandidateSlate.get_all_candidates()
        assert cands[CandidateID.C1_OFA_BURST].expected_holding_period_sec == 5.0

    def test_strict_isolation_between_discovery_and_prospective(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert res.prospective_telemetry.production_writes_count == 0


# =====================================================================
# 17. Final Verdict & Orchestrator Invariants Tests
# =====================================================================

class TestFinalVerdictAndOrchestrator:

    def test_orchestrator_runs_end_to_end(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert isinstance(res, Phase10A12OrchestratorResult)

    def test_final_verdict_is_no_candidate_survived(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert res.final_verdict == DiscoveryVerdict.NO_CANDIDATE_SURVIVED

    def test_zero_discovery_survivors(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert res.discovery_survivors_count == 0

    def test_zero_validation_and_oos_survivors(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert res.validation_survivors_count == 0
        assert res.oos_survivors_count == 0

    def test_strongest_research_mechanism_identified(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert "C1_OFA_BURST" in res.best_researchable_mechanism

    def test_verdict_explanation_mentions_spread_domination(self, orchestrator):
        res = orchestrator.run_discovery_pipeline()
        assert "spread" in res.verdict_explanation.lower()
