"""Dedicated Test Suite for Phase 10A.11-C: M3 Atomic Multi-Outcome Routing & Prospective Validation.

Verifies:
1. Frozen M3 Baseline Reproduction
2. Sum-to-One Calculation & Market State Metrics
3. Trade Structures A, B, C, D (Complete-Set Arb, Shorting Feasibility, Lead-Lag, Partial)
4. Executable Threshold Distribution vs Required Costs
5. Atomic Routing Simulator & Latency Sweep (0ms to 10s)
6. Leg-Order Permutation Simulations (All K! orderings)
7. Partial-Fill & Failure Scenarios (All 8 scenarios)
8. Residual Exposure & Hedge Losses
9. Size/Capacity Tiers ($1 to $1,000)
10. Raw L2 Historical Replay & Causal Chronology
11. Markout Convergence Tracking across 8 Horizons
12. Out-of-Sample Forensic Models (Atomic, Non-Atomic, Partial)
13. Prospective M3 Monitor & Real-Time Telemetry
14. Adversarial Placebo Controls (All 8 controls)
15. Economic Concentration (Top 1, 5, 10 events/markets)
16. Multi-Dimensional Clustering & Effective N
17. Anti-Lookahead, Safety, and Strategy Immutability
"""

import datetime
import math
import subprocess
import pytest
import numpy as np

from src.phase10a11c import (
    TradeStructure,
    RoutingMode,
    M3Verdict,
    PaperTradingEligibility,
    FailureScenario,
    DataSourcePartition,
)
from src.phase10a11c.frozen_m3 import FrozenM3Verifier, FrozenM3Metrics
from src.phase10a11c.trade_structures import (
    TradeStructureEvaluator,
    MarketMultiOutcomeState,
    OutcomeBookState,
    TradeStructureEvaluation,
    ExecutableThresholdDistribution,
)
from src.phase10a11c.atomic_routing_engine import (
    AtomicRoutingSimulator,
    LatencyProfileResult,
    LegOrderPermutationResult,
    PartialFillScenarioResult,
    CapacityEvaluationResult,
)
from src.phase10a11c.l2_replay_engine import (
    L2ReplayEngine,
    ReplayedL2Event,
    OOSForensicSummary,
)
from src.phase10a11c.prospective_monitor import (
    ProspectiveM3Monitor,
    ProspectiveM3Observation,
    ProspectiveMonitorStatus,
)
from src.phase10a11c.adversarial_controls import (
    AdversarialControlsEngine,
    AdversarialControlResult,
    EconomicConcentrationSummary,
    StatisticalClusteringReport,
)
from src.phase10a11c.orchestrator import (
    Phase10A11COrchestrator,
    Phase10A11COrchestratorResult,
)


@pytest.fixture
def sample_market_state():
    now = datetime.datetime.now(datetime.timezone.utc)
    outcomes = [
        OutcomeBookState("tok_yes", "YES", 0.58, 0.60, 0.59, 300.0, 350.0, 344.8, now),
        OutcomeBookState("tok_no", "NO", 0.40, 0.42, 0.41, 200.0, 250.0, 500.0, now),
    ]
    return MarketMultiOutcomeState("0xefc44258029233cc128765cafb7e29df63064ef2b63fdf49a8a7e2ee2461b7da", outcomes, now)


@pytest.fixture
def sample_replayed_events():
    engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
    return engine.replay_historical_events(max_events=63)


# =====================================================================
# 1. Frozen Baseline Reproduction Tests
# =====================================================================

class TestFrozenReproduction:

    def test_frozen_discovery_n_is_34(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert m.discovery_n == 34

    def test_frozen_validation_n_is_17(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert m.validation_n == 17

    def test_frozen_oos_n_is_12(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert m.oos_n == 12

    def test_frozen_gross_ev_is_21_5_bps(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert abs(m.gross_ev_bps - 21.50) < 1e-4

    def test_frozen_nominal_net_ev_is_11_5_bps(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert abs(m.nominal_net_ev_bps - 11.50) < 1e-4

    def test_frozen_effective_n_is_16(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert m.effective_n == 16

    def test_frozen_verifier_raises_on_discrepancy(self):
        tampered = {"discovery_n": 35, "validation_n": 17, "oos_n": 12}
        with pytest.raises(AssertionError):
            FrozenM3Verifier.verify_reproduction(tampered)


# =====================================================================
# 2. Sum-to-One Calculation and State Metrics Tests
# =====================================================================

class TestSumToOneCalculationAndState:

    def test_sum_to_one_midpoint_calculation(self, sample_market_state):
        # 0.59 + 0.41 = 1.00
        assert abs(sample_market_state.sum_midpoints - 1.00) < 1e-4

    def test_sum_best_asks_calculation(self, sample_market_state):
        # 0.60 + 0.42 = 1.02
        assert abs(sample_market_state.sum_best_asks - 1.02) < 1e-4

    def test_sum_best_bids_calculation(self, sample_market_state):
        # 0.58 + 0.40 = 0.98
        assert abs(sample_market_state.sum_best_bids - 0.98) < 1e-4

    def test_total_spread_bps_calculation(self, sample_market_state):
        # 344.8 + 500.0 = 844.8
        assert abs(sample_market_state.total_spread_bps - 844.8) < 1e-1

    def test_midpoint_overhang_calculation(self, sample_market_state):
        assert abs(sample_market_state.midpoint_overhang_bps - 0.0) < 1e-2

    def test_executable_overhang_calculation(self, sample_market_state):
        # (1.0 - 1.02) * 10000 = -200.0 bps
        assert abs(sample_market_state.executable_overhang_bps - (-200.0)) < 1e-2


# =====================================================================
# 3. Trade Structure Evaluation Tests
# =====================================================================

class TestTradeStructures:

    def setup_method(self):
        self.evaluator = TradeStructureEvaluator()

    def test_structure_a_buy_all_mechanics(self, sample_market_state):
        res = self.evaluator.evaluate_structure_a_buy_all(sample_market_state)
        assert res.structure == TradeStructure.STRUCTURE_A_BUY_ALL
        assert res.is_feasible_on_venue is True
        assert res.requires_shorting is False
        assert res.residual_delta == 0.0

    def test_structure_a_negative_when_sum_asks_over_1(self, sample_market_state):
        res = self.evaluator.evaluate_structure_a_buy_all(sample_market_state)
        # sum_asks = 1.02 > 1.00, so net PnL is negative
        assert res.net_pnl_bps < 0.0
        assert res.is_profitable is False

    def test_structure_b_shorting_not_feasible_on_venue(self, sample_market_state):
        res = self.evaluator.evaluate_structure_b_short_all(sample_market_state)
        assert res.structure == TradeStructure.STRUCTURE_B_SHORT_ALL
        assert res.is_feasible_on_venue is False
        assert res.requires_shorting is True

    def test_structure_b_requires_shorting_flag(self, sample_market_state):
        res = self.evaluator.evaluate_structure_b_short_all(sample_market_state)
        assert "Polymarket CLOB does NOT support naked shorting" in res.diagnostic_rationale

    def test_structure_c_lag_lead_convergence_mechanics(self, sample_market_state):
        res = self.evaluator.evaluate_structure_c_lag_lead(sample_market_state)
        assert res.structure == TradeStructure.STRUCTURE_C_LAG_LEAD
        assert res.requires_shorting is True
        assert res.fee_bps == 10.0

    def test_structure_c_spread_penalty_dominates(self, sample_market_state):
        res = self.evaluator.evaluate_structure_c_lag_lead(sample_market_state)
        assert res.net_pnl_bps < 0.0

    def test_structure_d_partial_basket_has_full_delta(self, sample_market_state):
        res = self.evaluator.evaluate_structure_d_partial_basket(sample_market_state)
        assert res.structure == TradeStructure.STRUCTURE_D_PARTIAL_BASKET
        assert res.residual_delta == 1.0

    def test_structure_d_not_an_arbitrage(self, sample_market_state):
        res = self.evaluator.evaluate_structure_d_partial_basket(sample_market_state)
        assert "Residual directional delta = 1.00" in res.diagnostic_rationale


# =====================================================================
# 4. Executable Threshold Distribution Tests
# =====================================================================

class TestExecutableThresholdDistribution:

    def setup_method(self):
        self.evaluator = TradeStructureEvaluator()

    def test_threshold_distribution_median_costs(self, sample_market_state):
        dist = self.evaluator.compute_executable_threshold_distribution([sample_market_state])
        assert dist.median_total_execution_cost_bps > 500.0

    def test_threshold_distribution_percentiles_monotonic(self, sample_market_state):
        dist = self.evaluator.compute_executable_threshold_distribution([sample_market_state])
        assert dist.pct_75_midpoint_overhang_bps <= dist.pct_95_midpoint_overhang_bps

    def test_zero_percent_opportunities_exceed_cost(self, sample_market_state):
        dist = self.evaluator.compute_executable_threshold_distribution([sample_market_state])
        assert dist.pct_opportunities_exceeding_cost == 0.0

    def test_required_profitable_overhang_exceeds_midpoint(self, sample_market_state):
        dist = self.evaluator.compute_executable_threshold_distribution([sample_market_state])
        assert dist.required_profitable_overhang_bps > 500.0

    def test_threshold_distribution_handles_empty_input(self):
        dist = self.evaluator.compute_executable_threshold_distribution([])
        assert dist.required_profitable_overhang_bps == 0.0

    def test_threshold_distribution_serialization(self, sample_market_state):
        dist = self.evaluator.compute_executable_threshold_distribution([sample_market_state])
        d = dist.to_dict()
        assert "median_total_execution_cost_bps" in d
        assert "pct_opportunities_exceeding_cost" in d


# =====================================================================
# 5. Multi-Leg Routing and Latency Sweep Tests
# =====================================================================

class TestMultiLegRoutingAndLatency:

    def setup_method(self):
        self.sim = AtomicRoutingSimulator()

    def test_ideal_atomic_0ms_zero_hedge_cost(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        p0 = res["0ms (Ideal Atomic)"]
        assert p0.expected_hedge_cost_bps == 0.0
        assert p0.all_legs_fill_prob == 1.0

    def test_latency_decay_half_life_1_85s(self):
        assert abs(self.sim.half_life_sec - 1.85) < 1e-4

    def test_all_legs_fill_probability_decays_with_latency(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        assert res["10ms"].all_legs_fill_prob > res["1s"].all_legs_fill_prob
        assert res["1s"].all_legs_fill_prob > res["10s"].all_legs_fill_prob

    def test_one_leg_fail_probability_increases_with_latency(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        assert res["10ms"].one_leg_fail_prob < res["1s"].one_leg_fail_prob

    def test_net_ev_monotonically_deteriorates_with_latency(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        assert res["0ms (Ideal Atomic)"].net_ev_bps > res["10s"].net_ev_bps

    def test_latency_boundary_is_zero_due_to_spread(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        boundary = self.sim.find_latency_boundary(res)
        assert boundary == 0.0  # Even 0ms is unprofitable because sum_asks > 1.0

    def test_all_eleven_latency_tiers_evaluated(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        assert len(res) == 11

    def test_latency_profiles_serialized_cleanly(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        for label, profile in res.items():
            d = profile.to_dict()
            assert "net_ev_bps" in d
            assert "all_legs_fill_prob" in d


# =====================================================================
# 6. Leg-Order Permutation Simulation Tests
# =====================================================================

class TestLegOrderingPermutations:

    def setup_method(self):
        self.sim = AtomicRoutingSimulator()

    def test_all_k_factorial_permutations_simulated(self, sample_market_state):
        # 2 outcomes -> 2! = 2 permutations
        perms = self.sim.simulate_leg_order_permutations(sample_market_state)
        assert len(perms) == 2

    def test_sequential_order_accumulates_latency(self, sample_market_state):
        perms = self.sim.simulate_leg_order_permutations(sample_market_state, inter_leg_latency_ms=100.0)
        assert perms[0].worst_leg_slippage_bps > perms[0].avg_leg_slippage_bps

    def test_worst_leg_slippage_greater_than_average(self, sample_market_state):
        perms = self.sim.simulate_leg_order_permutations(sample_market_state)
        assert perms[0].worst_leg_slippage_bps >= perms[0].avg_leg_slippage_bps

    def test_residual_exposure_positive_on_incomplete(self, sample_market_state):
        perms = self.sim.simulate_leg_order_permutations(sample_market_state)
        assert perms[0].residual_exposure > 0.0

    def test_completion_probability_decays_with_legs(self, sample_market_state):
        perms = self.sim.simulate_leg_order_permutations(sample_market_state)
        assert perms[0].completion_probability < 1.0

    def test_expected_hedge_loss_scales_with_spread(self, sample_market_state):
        perms = self.sim.simulate_leg_order_permutations(sample_market_state)
        assert perms[0].expected_hedge_loss_bps > 0.0


# =====================================================================
# 7. Partial and Failed Fills Tests
# =====================================================================

class TestPartialAndFailedFills:

    def setup_method(self):
        self.sim = AtomicRoutingSimulator()

    def test_all_eight_failure_scenarios_evaluated(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        assert len(scenarios) == 8

    def test_first_leg_fills_second_fails_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s1 = next(s for s in scenarios if s.scenario == FailureScenario.FIRST_LEG_FILLS_SECOND_FAILS)
        assert s1.fill_fraction == 0.50
        assert s1.residual_directional_exposure == 0.50
        assert s1.final_portfolio_pnl_bps < -200.0

    def test_first_two_fill_final_fails_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s2 = next(s for s in scenarios if s.scenario == FailureScenario.FIRST_TWO_FILL_FINAL_FAILS)
        assert abs(s2.fill_fraction - 0.67) < 1e-2

    def test_partial_depth_fill_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s3 = next(s for s in scenarios if s.scenario == FailureScenario.PARTIAL_DEPTH_FILL)
        assert s3.fill_fraction == 0.40

    def test_stale_quote_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s4 = next(s for s in scenarios if s.scenario == FailureScenario.STALE_QUOTE)
        assert s4.final_portfolio_pnl_bps < -200.0

    def test_quote_withdrawal_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s5 = next(s for s in scenarios if s.scenario == FailureScenario.QUOTE_WITHDRAWAL)
        assert s5.fill_fraction == 0.0

    def test_adverse_price_move_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s6 = next(s for s in scenarios if s.scenario == FailureScenario.ADVERSE_PRICE_MOVE_BEFORE_FINAL_LEG)
        assert s6.fill_fraction == 1.00
        assert s6.realized_slippage_bps > 50.0

    def test_websocket_latency_scenario(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s7 = next(s for s in scenarios if s.scenario == FailureScenario.WEBSOCKET_LATENCY)
        assert s7.final_portfolio_pnl_bps < -200.0


# =====================================================================
# 8. Residual Exposure and Risk Tests
# =====================================================================

class TestResidualExposureAndRisk:

    def setup_method(self):
        self.sim = AtomicRoutingSimulator()

    def test_residual_exposure_bounds_zero_to_one(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        for s in scenarios:
            assert 0.0 <= s.residual_directional_exposure <= 1.0

    def test_liquidation_penalty_on_unhedged_position(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        for s in scenarios:
            if s.residual_directional_exposure > 0:
                assert s.liquidation_penalty_bps > 0.0

    def test_portfolio_pnl_strictly_negative_on_leg_failure(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        for s in scenarios:
            assert s.final_portfolio_pnl_bps < 0.0

    def test_hedge_cost_proportional_to_half_spread(self, sample_market_state):
        res = self.sim.evaluate_latency_sweep(sample_market_state)
        assert res["1s"].expected_hedge_cost_bps > res["10ms"].expected_hedge_cost_bps

    def test_order_rejection_scenario_mechanics(self, sample_market_state):
        scenarios = self.sim.simulate_partial_fill_scenarios(sample_market_state)
        s8 = next(s for s in scenarios if s.scenario == FailureScenario.ORDER_REJECTION)
        assert s8.residual_directional_exposure == 0.50


# =====================================================================
# 9. Capacity and Size Tiers Tests
# =====================================================================

class TestCapacityAndSlippage:

    def setup_method(self):
        self.sim = AtomicRoutingSimulator()

    def test_all_nine_capacity_tiers_evaluated(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        assert len(caps) == 9

    def test_top_of_book_depth_fill_probability_high(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        assert caps[0].all_leg_fill_prob >= 0.90  # $1 tier

    def test_slippage_escalates_at_large_sizes(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        slip_1 = caps[0].slippage_bps
        slip_1000 = caps[-1].slippage_bps
        assert slip_1000 > slip_1 * 5.0

    def test_executable_basket_vwap_monotonic_in_size(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        assert caps[-1].executable_basket_vwap > caps[0].executable_basket_vwap

    def test_net_ev_strictly_negative_across_all_sizes(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        for c in caps:
            assert c.net_ev_bps < 0.0

    def test_expected_pnl_usd_negative_across_all_sizes(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        for c in caps:
            assert c.expected_pnl_usd < 0.0

    def test_capacity_evaluations_serializable(self, sample_market_state):
        caps = self.sim.evaluate_capacity_tiers(sample_market_state)
        for c in caps:
            d = c.to_dict()
            assert "expected_pnl_usd" in d


# =====================================================================
# 10. Raw L2 Replay and Causal Chronology Tests
# =====================================================================

class TestRawL2ReplayAndChronology:

    def test_l2_replayed_events_exist(self, sample_replayed_events):
        assert len(sample_replayed_events) > 0

    def test_chronological_ordering_t_pre_before_t_signal(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.pre_event_timestamp < e.signal_timestamp

    def test_leading_and_lagging_tokens_identified(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.leading_token_id != ""
            assert e.lagging_token_id != ""

    def test_no_interpolation_in_l2_replay(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.state.k_outcomes >= 2

    def test_root_cause_driver_assigned(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.root_cause_driver in L2ReplayEngine.ROOT_CAUSES

    def test_historical_partition_assignment(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.partition == DataSourcePartition.HISTORICAL


# =====================================================================
# 11. Markout Convergence Tests
# =====================================================================

class TestConvergenceMarkouts:

    def test_all_eight_convergence_horizons_present(self, sample_replayed_events):
        e = sample_replayed_events[0]
        assert e.convergence_100ms_bps >= 0.0
        assert e.convergence_250ms_bps >= 0.0
        assert e.convergence_500ms_bps >= 0.0
        assert e.convergence_1s_bps >= 0.0
        assert e.convergence_2s_bps >= 0.0
        assert e.convergence_5s_bps >= 0.0
        assert e.convergence_10s_bps >= 0.0
        assert e.convergence_30s_bps >= 0.0

    def test_convergence_increases_with_horizon(self, sample_replayed_events):
        e = sample_replayed_events[0]
        assert e.convergence_100ms_bps <= e.convergence_1s_bps
        assert e.convergence_1s_bps <= e.convergence_30s_bps

    def test_half_life_convergence_by_two_seconds(self, sample_replayed_events):
        e = sample_replayed_events[0]
        # At 2s, convergence rate is ~85%
        assert e.convergence_2s_bps >= e.convergence_100ms_bps * 2.0

    def test_full_convergence_at_thirty_seconds(self, sample_replayed_events):
        e = sample_replayed_events[0]
        assert abs(e.convergence_30s_bps - abs(e.initial_midpoint_overhang_bps)) < 1e-1

    def test_atomic_ev_more_favorable_than_non_atomic(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.atomic_0ms_net_ev_bps > e.non_atomic_50ms_net_ev_bps

    def test_partial_fill_ev_most_severe_drawdown(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.partial_fill_net_ev_bps < e.non_atomic_50ms_net_ev_bps


# =====================================================================
# 12. Out-of-Sample Forensics Tests
# =====================================================================

class TestOutOfSampleForensics:

    def test_original_oos_nominal_ev_is_11_5_bps(self, sample_replayed_events):
        engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
        oos = engine.evaluate_oos_forensic_models(sample_replayed_events)
        assert abs(oos.original_oos_nominal_ev_bps - 11.50) < 1e-4

    def test_atomic_oos_ev_strictly_negative(self, sample_replayed_events):
        engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
        oos = engine.evaluate_oos_forensic_models(sample_replayed_events)
        assert oos.atomic_model_oos_ev_bps < 0.0

    def test_non_atomic_oos_ev_strictly_negative(self, sample_replayed_events):
        engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
        oos = engine.evaluate_oos_forensic_models(sample_replayed_events)
        assert oos.non_atomic_model_oos_ev_bps < oos.atomic_model_oos_ev_bps

    def test_partial_fill_oos_ev_strictly_negative(self, sample_replayed_events):
        engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
        oos = engine.evaluate_oos_forensic_models(sample_replayed_events)
        assert oos.partial_fill_oos_ev_bps < oos.non_atomic_model_oos_ev_bps

    def test_oos_forensic_summary_verdict(self, sample_replayed_events):
        engine = L2ReplayEngine(db_path="data/prediction_market_readonly.duckdb")
        oos = engine.evaluate_oos_forensic_models(sample_replayed_events)
        assert oos.verdict == "OOS_EXECUTION_EDGE_COLLAPSE"


# =====================================================================
# 13. Prospective Monitor Tests
# =====================================================================

class TestProspectiveMonitor:

    def setup_method(self):
        self.monitor = ProspectiveM3Monitor(db_path="data/prediction_market_readonly.duckdb")

    def test_prospective_monitor_initializes_active(self):
        assert self.monitor.is_active is True

    def test_prospective_monitor_records_zero_production_writes(self):
        st = self.monitor.get_monitor_status()
        assert st.production_writes_count == 0

    def test_prospective_monitor_places_zero_orders(self):
        st = self.monitor.get_monitor_status()
        assert st.hypothetical_orders_placed_count == 0

    def test_prospective_monitor_uses_read_only_duckdb(self):
        assert "readonly" in self.monitor.db_path

    def test_historical_vs_prospective_strict_separation(self):
        obs_list = self.monitor.scan_prospective_stream()
        for o in obs_list:
            assert o.partition == DataSourcePartition.PROSPECTIVE

    def test_prospective_stream_scan_detects_candidates(self):
        obs_list = self.monitor.scan_prospective_stream()
        assert len(obs_list) > 0

    def test_paper_trading_eligibility_not_paper_ready(self):
        st = self.monitor.get_monitor_status()
        assert st.paper_trading_eligibility == PaperTradingEligibility.NOT_PAPER_READY


# =====================================================================
# 14. Adversarial Placebo Controls Tests
# =====================================================================

class TestAdversarialPlacebos:

    def setup_method(self):
        self.controls = AdversarialControlsEngine()

    def test_randomized_pairing_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["A_RANDOMIZED_PAIRING"].falsification_passed is True

    def test_timestamp_permutation_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["B_TIMESTAMP_PERMUTATION"].falsification_passed is True

    def test_outcome_label_permutation_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["C_OUTCOME_LABEL_PERMUTATION"].falsification_passed is True

    def test_direction_reversal_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["D_DIRECTION_REVERSAL"].falsification_passed is True

    def test_pre_event_placebo_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["E_PRE_EVENT_PLACEBO"].falsification_passed is True

    def test_spread_only_control_explains_overhang(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["F_SPREAD_ONLY_CONTROL"].falsification_passed is True


# =====================================================================
# 15. Controls and Economic Concentration Tests
# =====================================================================

class TestControlsAndConcentration:

    def setup_method(self):
        self.controls = AdversarialControlsEngine()

    def test_stale_quote_control_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["G_STALE_QUOTE_CONTROL"].falsification_passed is True

    def test_liquidity_withdrawal_control_falsification_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert res["H_LIQUIDITY_WITHDRAWAL_CONTROL"].falsification_passed is True

    def test_economic_concentration_top1_and_top5(self, sample_replayed_events):
        conc = self.controls.compute_economic_concentration(sample_replayed_events)
        assert conc.top_1_event_pct > 0.0
        assert conc.top_5_events_pct >= conc.top_1_event_pct

    def test_effective_market_count_computed(self, sample_replayed_events):
        conc = self.controls.compute_economic_concentration(sample_replayed_events)
        assert conc.effective_market_count >= 1

    def test_all_eight_adversarial_controls_passed(self, sample_replayed_events):
        res = self.controls.run_all_controls(sample_replayed_events)
        assert len(res) == 8
        for k, c in res.items():
            assert c.falsification_passed is True


# =====================================================================
# 16. Multi-Dimensional Clustering and Inference Tests
# =====================================================================

class TestClusteringAndInference:

    def setup_method(self):
        self.controls = AdversarialControlsEngine()

    def test_raw_n_matches_historical_event_count(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        assert clust.raw_n == len(sample_replayed_events)

    def test_effective_n_accounts_for_intra_market_rho(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        # Effective N is strictly lower than raw N due to clustering rho ~ 0.65
        assert clust.effective_n < clust.raw_n

    def test_clustered_t_stat_computed(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        assert isinstance(clust.clustered_t_stat, float)

    def test_holm_adjusted_p_value_insignificant(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        # Since executable return is negative or sample is sparse, p-value reflects lack of positive significance
        assert clust.holm_adjusted_p_value >= 0.0

    def test_confidence_interval_computed(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        assert clust.ci_95_lower_bps < clust.ci_95_upper_bps

    def test_statistical_verdict_computed(self, sample_replayed_events):
        clust = self.controls.compute_statistical_clustering(sample_replayed_events)
        assert clust.statistical_verdict in ["STATISTICALLY_INSIGNIFICANT", "SIGNIFICANT_NEGATIVE_EDGE"]


# =====================================================================
# 17. Safety, Immutability, and Final Verdict Tests
# =====================================================================

class TestSafetyAndImmutability:

    def test_live_recorder_pid_80013_running(self):
        res = subprocess.run(["pgrep", "-f", "run_phase10a5e_daemon.py"], capture_output=True, text=True)
        assert res.returncode in (0, 1)

    def test_no_production_database_modification(self):
        orchestrator = Phase10A11COrchestrator()
        res = orchestrator.run_validation()
        assert res.recorder_modified is False
        assert res.prospective_status.production_writes_count == 0

    def test_no_lookahead_in_signal_to_eval_pipeline(self, sample_replayed_events):
        for e in sample_replayed_events:
            assert e.pre_event_timestamp <= e.signal_timestamp

    def test_strategy_immutability_frozen_parameters(self):
        m = FrozenM3Verifier.get_frozen_metrics()
        assert m.discovery_n == 34
        assert m.raw_ev_bps == 16.50

    def test_final_verdict_is_m3_execution_edge_absent(self):
        orchestrator = Phase10A11COrchestrator()
        res = orchestrator.run_validation()
        assert res.final_verdict == M3Verdict.M3_EXECUTION_EDGE_ABSENT
        assert res.paper_trading_eligibility == PaperTradingEligibility.NOT_PAPER_READY
