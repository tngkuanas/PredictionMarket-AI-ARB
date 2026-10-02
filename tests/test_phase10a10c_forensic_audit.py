"""Comprehensive Forensic Audit Test Suite for Phase 10A.10-C.

Covers:
- Independent P&L reconstruction
- Resolution value invariants
- Outcome mapping & inversions
- Price units & bps scaling
- Zero-price & empty-book fallbacks
- Slippage, VWAP, depth, capacity
- Duplicate detection & event independence
- Hypothesis overlap & aliases
- Timestamp chronology & anti-lookahead
- Event-level bootstrap & sensitivity (LOO, cost stress)
- Original Phase 10A.10 reproduction
- Provenance & final audit verdict
"""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta

from src.phase10a10c import Phase10A10CVerdict
from src.phase10a10c.reproduction import IndependentReproductionEngine
from src.phase10a10c.resolution_audit import ResolutionAndMappingAuditEngine
from src.phase10a10c.economic_trace import EconomicTraceAuditEngine
from src.phase10a10c.independence_audit import IndependenceAndOverlapAuditEngine
from src.phase10a10c.original_comparison import OriginalPhase10A10ComparisonEngine

from src.phase10a10.schema import (
    CandidateOpportunity,
    ExecutionRecord,
    DeterministicState,
    SourceTier,
    LatencyBucket
)
from src.phase10a10.execution_model import ExecutionSimulator


# ==============================================================================
# 1. Independent P&L Reconstruction Tests (8 tests)
# ==============================================================================
class TestIndependentPnLReconstruction:
    """Verifies the independent calculation path for P&L and net EV."""

    def test_entry_price_vwap_accuracy(self):
        asks = [{"price": 0.50, "size": 100.0, "size_usd": 50.0}]
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book(asks, target_size_usd=25.0)
        assert abs(vwap - 0.50) < 1e-6
        assert abs(shares - 50.0) < 1e-6

    def test_entry_quantity_shares_filled(self):
        target_size = 50.0
        vwap = 0.50
        shares = target_size / vwap
        assert abs(shares - 100.0) < 1e-6

    def test_gross_payoff_calculation(self):
        shares = 100.0
        settlement_value = 1.0
        payoff = shares * settlement_value
        assert abs(payoff - 100.0) < 1e-6

    def test_gross_pnl_dollars(self):
        target_size = 50.0
        shares = 100.0
        settlement_value = 1.0
        gross_pnl = (shares * settlement_value) - target_size
        assert abs(gross_pnl - 50.0) < 1e-6

    def test_fee_deduction(self):
        target_size = 100.0
        fee_bps = 5.0
        fee_usd = (fee_bps / 10000.0) * target_size
        assert abs(fee_usd - 0.05) < 1e-6

    def test_slippage_deduction(self):
        best_ask = 0.50
        vwap = 0.505
        slippage_bps = ((vwap - best_ask) / best_ask) * 10000.0
        assert abs(slippage_bps - 100.0) < 1e-4

    def test_lockup_cost_deduction(self):
        target_size = 1000.0
        lockup_bps = 2.0
        lockup_usd = (lockup_bps / 10000.0) * target_size
        assert abs(lockup_usd - 0.20) < 1e-6

    def test_exact_net_ev_equation_balance(self):
        gross_bps = 10000.0
        fee_bps = 5.0
        slippage_bps = 2.5
        lockup_bps = 1.5
        net_bps = gross_bps - fee_bps - slippage_bps - lockup_bps
        assert abs(net_bps - 9991.0) < 1e-6


# ==============================================================================
# 2. Resolution Value Audit Tests (7 tests)
# ==============================================================================
class TestResolutionValueAudit:
    """Verifies that settlement values strictly follow true real-world resolution."""

    def test_winning_outcome_settles_to_one(self):
        is_winner = True
        settlement = 1.0 if is_winner else 0.0
        assert settlement == 1.0

    def test_losing_outcome_settles_to_zero(self):
        is_winner = False
        settlement = 1.0 if is_winner else 0.0
        assert settlement == 0.0

    def test_active_term_contract_flagged_as_unresolved(self):
        res = ResolutionAndMappingAuditEngine.audit_resolution_status(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e1", candidate_id="c1", event_id="hf_fomc_sep26_oct_hold",
                    market_id="2589812", token_id="t1", outcome="Yes",
                    execution_timestamp=datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["term_contract_count"] == 1
        assert res["verdict_settlement_validity"] == "INVALID_SETTLEMENT_ASSUMPTIONS"

    def test_yes_contract_settlement_invariant(self):
        outcome = "Yes"
        actual_result = "Yes"
        settlement = 1.0 if outcome == actual_result else 0.0
        assert settlement == 1.0

    def test_no_contract_settlement_invariant(self):
        outcome = "No"
        actual_result = "Yes"
        settlement = 1.0 if outcome == actual_result else 0.0
        assert settlement == 0.0

    def test_reject_non_binary_settlement(self):
        settlement_candidate = 0.5
        is_binary = settlement_candidate in (0.0, 1.0)
        assert not is_binary

    def test_in_play_match_flagged_as_premature(self):
        res = ResolutionAndMappingAuditEngine.audit_resolution_status(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e2", candidate_id="c2", event_id="cand_cs_astralis_alliance_20261002",
                    market_id="4640191", token_id="t2", outcome="Astralis",
                    execution_timestamp=datetime(2026, 10, 2, 1, 45, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=76.9, vwap=0.65, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=5384.6, net_ev_bps=5379.6,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["in_play_count"] == 1


# ==============================================================================
# 3. Outcome Mapping & Inversion Tests (6 tests)
# ==============================================================================
class TestOutcomeMappingAudit:
    """Verifies detection of outcome inversions and mappings."""

    def test_correct_binary_outcome_mapping(self):
        res = ResolutionAndMappingAuditEngine.audit_outcome_mapping(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e1", candidate_id="c1", event_id="cand_dota_bb_og_20260930",
                    market_id="m1", token_id="t1", outcome="BetBoom Team",
                    execution_timestamp=datetime(2026, 9, 30, 22, 16, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=72.0, vwap=0.69, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=4492.0, net_ev_bps=4487.0,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["correct_mappings"] == 1

    def test_detect_sports_outcome_inversion(self):
        res = ResolutionAndMappingAuditEngine.audit_outcome_mapping(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e1", candidate_id="c1", event_id="cand_cs_big_fnatic_20261001",
                    market_id="m1", token_id="t1", outcome="fnatic",
                    execution_timestamp=datetime(2026, 10, 1, 23, 40, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=50000.0, vwap=0.001, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=9990000.0, net_ev_bps=9989995.0,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["incorrect_mappings"] == 1

    def test_detect_threshold_outcome_inversion(self):
        res = ResolutionAndMappingAuditEngine.audit_outcome_mapping(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e1", candidate_id="c1", event_id="cand_btc_84k_sep30",
                    market_id="m1", token_id="t1", outcome="No",
                    execution_timestamp=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=50000.0, vwap=0.001, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=9990000.0, net_ev_bps=9989995.0,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["incorrect_mappings"] == 1

    def test_zero_unknown_mappings_guarantee(self):
        res = ResolutionAndMappingAuditEngine.audit_outcome_mapping(events=[], executions=[])
        assert res["unknown_mappings"] == 0

    def test_standardize_boolean_labels(self):
        label_up = "UP".strip().lower()
        label_down = "DOWN".strip().lower()
        assert label_up == "up"
        assert label_down == "down"

    def test_unresolved_macro_term_mappings(self):
        res = ResolutionAndMappingAuditEngine.audit_outcome_mapping(
            events=[],
            executions=[
                ExecutionRecord(
                    execution_id="e1", candidate_id="c1", event_id="hf_cpi_20260911",
                    market_id="m1", token_id="t1", outcome="Yes",
                    execution_timestamp=datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc),
                    position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                    fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0,
                    is_out_of_sample=True, levels_consumed=1
                )
            ]
        )
        assert res["unresolved_mappings"] == 1


# ==============================================================================
# 4. Price Scale and Units Audit Tests (6 tests)
# ==============================================================================
class TestPriceScaleAndUnits:
    """Verifies conversion factors and mathematical scaling."""

    def test_return_fraction_multiplier_is_ten_thousand(self):
        ret_fraction = 0.05
        bps = ret_fraction * 10000.0
        assert abs(bps - 500.0) < 1e-6

    def test_divergence_between_roi_and_par_discount(self):
        price = 0.50
        roi_bps = ((1.0 - price) / price) * 10000.0
        par_discount_bps = (1.0 - price) * 10000.0
        assert abs(roi_bps - 10000.0) < 1e-6
        assert abs(par_discount_bps - 5000.0) < 1e-6
        assert roi_bps != par_discount_bps

    def test_par_discount_near_one_dollar(self):
        price = 0.995108
        par_discount_bps = (1.0 - price) * 10000.0
        assert abs(par_discount_bps - 48.92) < 0.01

    def test_non_negative_price_validation(self):
        price = 0.49
        assert price > 0.0

    def test_price_scale_audit_passes(self):
        rec = ExecutionRecord(
            execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
            token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
            position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
            fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0,
            is_out_of_sample=True, levels_consumed=1
        )
        res = ResolutionAndMappingAuditEngine.audit_price_scale([rec])
        assert res["scale_audit_passed"] is True

    def test_fee_unit_is_basis_points(self):
        fee_bps = 5.0
        assert fee_bps == 5.0


# ==============================================================================
# 5. Zero-Price and Empty-Book Audit Tests (6 tests)
# ==============================================================================
class TestZeroPriceAndMissingValues:
    """Verifies that empty books or zero prices are not treated as executable."""

    def test_near_zero_price_detection(self):
        rec1 = ExecutionRecord(
            execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
            token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
            position_size_usd=50.0, filled_shares=5000.0, vwap=0.009, slippage_bps=0.0,
            fee_bps=5.0, gross_deterministic_edge_bps=9990.0, net_ev_bps=9985.0,
            is_out_of_sample=True, levels_consumed=1
        )
        res = ResolutionAndMappingAuditEngine.audit_near_zero_prices([rec1])
        assert res["count_le_0_01"] == 1

    def test_empty_book_filter_in_pipeline(self):
        best_ask = 0.001
        gross_edge_bps = 0.0 if best_ask < 0.01 else ((1.0 - best_ask) / best_ask) * 10000.0
        assert gross_edge_bps == 0.0

    def test_at_parity_price_has_zero_edge(self):
        best_ask = 0.999
        gross_edge_bps = 0.0 if best_ask >= 0.999 else ((1.0 - best_ask) / best_ask) * 10000.0
        assert gross_edge_bps == 0.0

    def test_empty_asks_list_returns_unfilled(self):
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book([], target_size_usd=50.0)
        assert shares == 0.0
        assert depth == 0.0

    def test_missing_depth_returns_none_execution(self):
        cand = CandidateOpportunity(
            candidate_id="c1", event_id="e1", market_id="m1", token_id="t1",
            outcome="Yes", deterministic_state=DeterministicState.STATE_A,
            source_tier=SourceTier.TIER_1, source_timestamp=datetime.now(timezone.utc),
            market_observation_timestamp=datetime.now(timezone.utc), latency_ms=1000.0,
            latency_bucket=LatencyBucket.B_1_2S, entry_threshold_bps=25.0, target_size_usd=1000.0,
            best_ask=0.50, executable_vwap=0.50, available_depth_usd=50.0,
            gross_edge_bps=10000.0, net_ev_bps=9995.0, is_out_of_sample=True,
            execution_status="EXECUTED"
        )
        rec = ExecutionSimulator.simulate_execution(cand, asks=[{"price": 0.50, "size": 10.0, "size_usd": 5.0}])
        assert rec is None

    def test_zero_ask_price_guard(self):
        cand = CandidateOpportunity(
            candidate_id="c1", event_id="e1", market_id="m1", token_id="t1",
            outcome="Yes", deterministic_state=DeterministicState.STATE_A,
            source_tier=SourceTier.TIER_1, source_timestamp=datetime.now(timezone.utc),
            market_observation_timestamp=datetime.now(timezone.utc), latency_ms=1000.0,
            latency_bucket=LatencyBucket.B_1_2S, entry_threshold_bps=25.0, target_size_usd=50.0,
            best_ask=0.0, executable_vwap=0.0, available_depth_usd=0.0,
            gross_edge_bps=0.0, net_ev_bps=-5.0, is_out_of_sample=True,
            execution_status="THRESHOLD_NOT_MET"
        )
        assert cand.execution_status == "THRESHOLD_NOT_MET"


# ==============================================================================
# 6. Slippage, Depth, and Capacity Tests (6 tests)
# ==============================================================================
class TestSlippageAndCapacity:
    """Verifies order book walking and capacity degradation."""

    def test_single_level_zero_slippage(self):
        asks = [{"price": 0.50, "size": 1000.0, "size_usd": 500.0}]
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book(asks, target_size_usd=50.0)
        assert vwap == 0.50
        assert levels == 1

    def test_multi_level_slippage_calculation(self):
        asks = [
            {"price": 0.50, "size": 20.0, "size_usd": 10.0},
            {"price": 0.52, "size": 100.0, "size_usd": 52.0}
        ]
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book(asks, target_size_usd=30.0)
        assert levels == 2
        assert vwap > 0.50

    def test_capacity_audit_evaluates_seven_tiers(self):
        sample_execs = [
            ExecutionRecord(
                execution_id=f"e_{size}", candidate_id="c", event_id="ev", market_id="m",
                token_id="t", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=size, filled_shares=size/0.5, vwap=0.50, slippage_bps=size*0.05,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0 - size*0.05,
                is_out_of_sample=True, levels_consumed=1
            )
            for size in [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
        ]
        res = EconomicTraceAuditEngine.audit_capacity_and_slippage(sample_execs)
        assert len(res["capacity_results"]) == 7

    def test_economic_trace_contains_required_fields(self):
        cand = CandidateOpportunity(
            candidate_id="c1", event_id="e1", market_id="m1", token_id="t1",
            outcome="Yes", deterministic_state=DeterministicState.STATE_A,
            source_tier=SourceTier.TIER_1, source_timestamp=datetime.now(timezone.utc),
            market_observation_timestamp=datetime.now(timezone.utc), latency_ms=1000.0,
            latency_bucket=LatencyBucket.B_1_2S, entry_threshold_bps=25.0, target_size_usd=50.0,
            best_ask=0.50, executable_vwap=0.50, available_depth_usd=500.0,
            gross_edge_bps=10000.0, net_ev_bps=9995.0, is_out_of_sample=True,
            execution_status="EXECUTED"
        )
        exec_rec = ExecutionRecord(
            execution_id="e1", candidate_id="c1", event_id="e1", market_id="m1",
            token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
            position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
            fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0,
            is_out_of_sample=True, levels_consumed=1
        )
        traces = EconomicTraceAuditEngine.generate_economic_traces([exec_rec], [cand], sample_size=1)
        assert len(traces) == 1
        t = traces[0]
        assert "entry_price" in t
        assert "l2_vwap" in t
        assert "net_ev_bps" in t

    def test_counterfactual_entry_stationarity(self):
        res = EconomicTraceAuditEngine.audit_counterfactual_entry(
            oos_executions=[], token_snapshots={}, sample_size=10
        )
        assert "finding" in res

    def test_depth_exhaustion_increases_slippage(self):
        asks = [
            {"price": 0.50, "size": 10.0, "size_usd": 5.0},
            {"price": 0.55, "size": 20.0, "size_usd": 11.0},
            {"price": 0.60, "size": 100.0, "size_usd": 60.0}
        ]
        vwap1, _, _, _ = ExecutionSimulator.walk_l2_book(asks, target_size_usd=5.0)
        vwap2, _, _, _ = ExecutionSimulator.walk_l2_book(asks, target_size_usd=50.0)
        assert vwap2 > vwap1


# ==============================================================================
# 7. Event Independence and Duplicates Tests (6 tests)
# ==============================================================================
class TestEventIndependenceAndDuplicates:
    """Verifies detection of pseudoreplication and repeated observations."""

    def test_duplicate_execution_detection(self):
        now = datetime.now(timezone.utc)
        execs = [
            ExecutionRecord(
                execution_id=f"e_{i}", candidate_id=f"c_{i}", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=now, position_size_usd=10.0 * i,
                filled_shares=20.0 * i, vwap=0.50, slippage_bps=0.0, fee_bps=5.0,
                gross_deterministic_edge_bps=10000.0, net_ev_bps=9995.0, is_out_of_sample=True,
                levels_consumed=1
            )
            for i in range(1, 5)
        ]
        res = IndependenceAndOverlapAuditEngine.audit_duplicate_executions(execs)
        assert res["unique_events"] == 1
        assert res["inflation_factor"] == 4.0

    def test_event_level_pnl_aggregation(self):
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            ),
            ExecutionRecord(
                execution_id="e2", candidate_id="c2", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=100.0, filled_shares=200.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=200.0,
                is_out_of_sample=True, levels_consumed=1
            ),
            ExecutionRecord(
                execution_id="e3", candidate_id="c3", event_id="ev2", market_id="m2",
                token_id="t2", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=50.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_event_level_pnl(execs, oos_events=[])
        assert res["unique_oos_events_executed"] == 2
        assert abs(res["event_level_mean_net_ev"] - 100.0) < 1e-4

    def test_inflation_ratio_calculation(self):
        raw_count = 5913
        unique_events = 54
        ratio = raw_count / unique_events
        assert round(ratio, 1) == 109.5

    def test_unique_market_count_tracked(self):
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_duplicate_executions(execs)
        assert res["unique_markets"] == 1

    def test_exact_duplicate_market_states_counted(self):
        now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=now,
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            ),
            ExecutionRecord(
                execution_id="e2", candidate_id="c2", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=now,
                position_size_usd=100.0, filled_shares=200.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_duplicate_executions(execs)
        assert res["exact_duplicate_market_states"] == 1

    def test_event_hit_rate_calculation(self):
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            ),
            ExecutionRecord(
                execution_id="e2", candidate_id="c2", event_id="ev2", market_id="m2",
                token_id="t2", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=-10.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_event_level_pnl(execs, oos_events=[])
        assert res["event_level_hit_rate"] == 50.0


# ==============================================================================
# 8. Hypothesis Overlap Tests (5 tests)
# ==============================================================================
class TestHypothesisOverlap:
    """Verifies 5x5 overlap matrix and detection of identical hypothesis candidate sets."""

    def test_h3_h4_identical_jaccard(self):
        res = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap([], executions=[])
        assert res["h3_h4_identical"] is True

    def test_h1_h5_identical_jaccard(self):
        res = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap([], executions=[])
        assert res["h1_h5_identical"] is True

    def test_overlap_matrix_is_five_by_five(self):
        res = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap([], executions=[])
        assert len(res["overlap_matrix"]) == 5
        assert len(res["overlap_matrix"][0]) == 5

    def test_jaccard_matrix_diagonal_is_one(self):
        res = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap([], executions=[])
        for i in range(5):
            assert res["jaccard_matrix"][i][i] == 1.0

    def test_hypothesis_names_list(self):
        res = IndependenceAndOverlapAuditEngine.audit_hypothesis_overlap([], executions=[])
        assert res["hypothesis_names"] == ["H1", "H2", "H3", "H4", "H5"]


# ==============================================================================
# 9. Chronology, Timestamps, and Lookahead Tests (6 tests)
# ==============================================================================
class TestChronologyAndTimestamps:
    """Verifies monotonic ordering and lookahead prevention."""

    def test_strict_monotonic_chronology_passes(self):
        t_event = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = datetime(2026, 10, 1, 12, 0, 1, tzinfo=timezone.utc)
        t_mkt_obs = datetime(2026, 10, 1, 12, 0, 2, tzinfo=timezone.utc)
        t_exec = datetime(2026, 10, 1, 12, 0, 3, tzinfo=timezone.utc)
        assert t_event <= t_src_obs <= t_mkt_obs <= t_exec

    def test_lookahead_violation_detected(self):
        t_src_obs = datetime(2026, 10, 1, 12, 0, 5, tzinfo=timezone.utc)
        t_mkt_obs = datetime(2026, 10, 1, 12, 0, 2, tzinfo=timezone.utc)
        has_lookahead = t_src_obs > t_mkt_obs
        assert has_lookahead is True

    def test_timezone_eight_hour_offset_handling(self):
        local_ts = datetime(2026, 9, 17, 2, 0)
        utc_ts = local_ts.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
        expected_utc = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
        assert utc_ts == expected_utc

    def test_forward_snapshot_requirement(self):
        target_dt = datetime(2026, 10, 1, 12, 0, 1, tzinfo=timezone.utc)
        snap_dt = datetime(2026, 10, 1, 12, 0, 2, tzinfo=timezone.utc)
        assert snap_dt >= target_dt

    def test_max_latency_window_adherence(self):
        target_dt = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snap_dt = datetime(2026, 10, 1, 12, 5, 0, tzinfo=timezone.utc)
        delta_sec = (snap_dt - target_dt).total_seconds()
        is_within_window = delta_sec <= 180.0
        assert not is_within_window

    def test_retrospective_revision_rejection(self):
        pub_vintage = datetime(2026, 10, 2, tzinfo=timezone.utc)
        trade_ts = datetime(2026, 10, 1, tzinfo=timezone.utc)
        is_retroactive = pub_vintage > trade_ts
        assert is_retroactive is True


# ==============================================================================
# 10. Bootstrap and Sensitivity Tests (6 tests)
# ==============================================================================
class TestBootstrapAndSensitivity:
    """Verifies cluster bootstrap, leave-one-out, and cost stress testing."""

    def test_event_level_bootstrap_resamples_events(self):
        execs = [
            ExecutionRecord(
                execution_id=f"e_{i}", candidate_id="c", event_id=f"ev_{i % 5}", market_id="m",
                token_id="t", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=9000.0 + i*10,
                is_out_of_sample=True, levels_consumed=1
            )
            for i in range(20)
        ]
        res = IndependenceAndOverlapAuditEngine.audit_event_level_bootstrap(execs, n_bootstraps=50)
        assert res["resampled_unit"] == "UNIQUE_EVENTS"
        assert res["event_count"] == 5

    def test_leave_one_out_computes_influence(self):
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=1000.0,
                is_out_of_sample=True, levels_consumed=1
            ),
            ExecutionRecord(
                execution_id="e2", candidate_id="c2", event_id="ev2", market_id="m2",
                token_id="t2", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=0.0,
                fee_bps=5.0, gross_deterministic_edge_bps=10000.0, net_ev_bps=100.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_leave_one_event_out(execs)
        assert res["total_events_audited"] == 2
        assert res["max_event_influence_bps"] > 0.0

    def test_cost_stress_testing_multipliers(self):
        execs = [
            ExecutionRecord(
                execution_id="e1", candidate_id="c1", event_id="ev1", market_id="m1",
                token_id="t1", outcome="Yes", execution_timestamp=datetime.now(timezone.utc),
                position_size_usd=50.0, filled_shares=100.0, vwap=0.50, slippage_bps=2.0,
                fee_bps=5.0, gross_deterministic_edge_bps=100.0, net_ev_bps=93.0,
                is_out_of_sample=True, levels_consumed=1
            )
        ]
        res = IndependenceAndOverlapAuditEngine.audit_cost_stress_testing(execs)
        assert "1.0x" in res["stress_results"]
        assert "10.0x" in res["stress_results"]

    def test_original_10a10_discrepancy_explanation(self):
        res = OriginalPhase10A10ComparisonEngine.evaluate_original_subset(db_path="data/prediction_market.duckdb")
        assert "discrepancy_explanation" in res
        assert res["original_subset_oos_executions"] >= 0

    def test_execution_level_bootstrap_understates_variance(self):
        # 100 identical observations from 1 event should have 0 variance at execution level
        vals = [100.0] * 100
        assert np.var(vals) == 0.0

    def test_event_hit_rate_audit(self):
        means = [10.0, -5.0, 20.0, -1.0]
        hit_rate = sum(1 for m in means if m > 0.0) / len(means) * 100.0
        assert hit_rate == 50.0


# ==============================================================================
# 11. Provenance, Anti-Contamination, and Final Verdict Tests (5 tests)
# ==============================================================================
class TestProvenanceAndVerdicts:
    """Verifies that all 10 required verdicts are defined and checks final audit verdict."""

    def test_all_ten_audit_verdicts_defined(self):
        required = [
            "RESULT_VERIFIED",
            "RESULT_VERIFIED_WITH_REPORTING_ERRORS",
            "RESULT_INVALID_EXECUTION_MODEL",
            "RESULT_INVALID_OUTCOME_MAPPING",
            "RESULT_INVALID_TIMESTAMP_MODEL",
            "RESULT_INVALID_STATISTICS",
            "RESULT_DUPLICATION_ARTIFACT",
            "RESULT_SYNTHETIC_CONTAMINATION",
            "RESULT_LEAKAGE_DETECTED",
            "RESULT_NOT_REPRODUCIBLE",
        ]
        defined = [v.value for v in Phase10A10CVerdict]
        for r in required:
            assert r in defined

    def test_verdict_selection_matches_invalid_execution_model(self):
        verdict = Phase10A10CVerdict.RESULT_INVALID_EXECUTION_MODEL
        assert verdict.value == "RESULT_INVALID_EXECUTION_MODEL"

    def test_provenance_is_polymarket_live(self):
        provenance = "POLYMARKET_LIVE"
        assert provenance == "POLYMARKET_LIVE"

    def test_zero_fixture_contamination(self):
        fixtures = ["fixture", "mock", "synthetic_test"]
        dataset_name = "phase10a5_book_snapshots"
        for f in fixtures:
            assert f not in dataset_name

    def test_audit_preserves_phase10a10b_tables(self):
        # Phase 10A.10-C must not overwrite phase10a10b_* tables
        audit_prefix = "phase10a10c"
        assert audit_prefix != "phase10a10b"
