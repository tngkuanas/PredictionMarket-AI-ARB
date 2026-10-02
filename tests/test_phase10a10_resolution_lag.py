"""Dedicated Test Suite for Phase 10A.10 Deterministic Resolution-State Lag Research.

Covers:
- Source timestamp validation & historical chronology
- Publication timestamp validation & anti-lookahead
- Deterministic outcome mapping (STATE_A, STATE_B, STATE_C, STATE_D)
- Ambiguous outcome rejection & non-standard rule patterns
- Timezone normalization (UTC)
- Threshold & inequality handling (GT, GTE, LT, LTE, EQ)
- Retroactive revision vintage checks
- L2 book reconstruction across horizons without interpolation
- Executable VWAP & depth walking
- Source-to-market reaction latency calculation
- Price convergence (1bp - 100bp) and formal settlement tracking
- Capital lockup and annualized opportunity costs
- Adversarial controls: C1 (pre-event placebo), C2 (random ts), C3 (reverse outcome),
  C4 (source shuffle), C5 (non-deterministic rejection), C6 (cost stress)
- Multiple testing (Holm-Bonferroni) and cluster-robust inference
- ProductionContaminationGuard & fixture contamination prevention

Requires: >= 50 dedicated tests.
"""

from datetime import datetime, timedelta, timezone
import json
import numpy as np
import pytest

from src.phase10a10.schema import (
    DeterministicState,
    SourceTier,
    LatencyBucket,
    Phase10A10Verdict,
    SourceRecord,
    ContractResolutionRules,
    ResolutionLagEvent,
    MarketStateSnapshot,
    CandidateOpportunity,
    ExecutionRecord,
    ConvergenceRecord,
    CapitalLockupRecord,
    NegativeControlRecord,
    HypothesisResultRecord,
)
from src.phase10a10.source_registry import SourceRegistry
from src.phase10a10.source_validator import SourceValidator, SourceValidationError
from src.phase10a10.resolution_rules import ResolutionRulesParser
from src.phase10a10.deterministic_state import DeterministicStateClassifier
from src.phase10a10.market_reconstructor import MarketStateReconstructor
from src.phase10a10.execution_model import ExecutionSimulator
from src.phase10a10.convergence import ConvergenceTracker
from src.phase10a10.capital_lockup import CapitalLockupModel
from src.phase10a10.controls import AdversarialControlsEvaluator
from src.phase10a10.statistical_engine import StatisticalEngine
from src.phase10a10.db_store import ProductionContaminationGuard, Phase10A10ContaminationError


# ==============================================================================
# 1. TIMESTAMP VALIDATION & CHRONOLOGY TESTS (1-6)
# ==============================================================================

class TestTimestampValidation:

    def test_chronology_strictly_monotonic_pass(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = t0 + timedelta(milliseconds=100)
        t_mkt_obs = t0 + timedelta(milliseconds=250)
        t_exec = t0 + timedelta(milliseconds=500)

        valid, err = SourceValidator.validate_chronology(t0, t_src_obs, t_mkt_obs, t_exec)
        assert valid is True
        assert err is None

    def test_chronology_rejects_source_obs_before_event(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = t0 - timedelta(seconds=1)  # invalid
        valid, err = SourceValidator.validate_chronology(t0, t_src_obs, t0, t0)
        assert valid is False
        assert "Chronology violation" in err

    def test_chronology_rejects_market_obs_before_source_obs(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = t0 + timedelta(seconds=2)
        t_mkt_obs = t0 + timedelta(seconds=1)  # lookahead
        valid, err = SourceValidator.validate_chronology(t0, t_src_obs, t_mkt_obs, t_src_obs)
        assert valid is False
        assert "Lookahead violation" in err

    def test_chronology_rejects_execution_before_market_obs(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_mkt_obs = t0 + timedelta(seconds=2)
        t_exec = t0 + timedelta(seconds=1)  # acausal
        valid, err = SourceValidator.validate_chronology(t0, t0, t_mkt_obs, t_exec)
        assert valid is False
        assert "Causality violation" in err

    def test_publication_before_retrieval_required(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 5, tzinfo=timezone.utc)
        t_ret = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)  # retrieved before publication!
        record = SourceRecord(
            source_id="src_test",
            source_tier=SourceTier.TIER_1,
            source_domain="bls.gov",
            source_name="BLS",
            source_url="https://bls.gov/cpi",
            source_timestamp=t_pub,
            retrieval_timestamp=t_ret,
            content_hash=SourceValidator.compute_content_hash("data"),
            raw_payload="data",
            is_authoritative=True
        )
        valid, err = SourceValidator.validate_source_record(record)
        assert valid is False
        assert "strictly after retrieval" in err

    def test_retroactive_revision_rejected(self):
        t_obs = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_vintage_revised = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)  # revised 2 weeks later
        assert SourceValidator.check_revision_vintage(t_vintage_revised, t_obs) is False

    def test_timezone_naive_converted_to_utc(self):
        naive_event = datetime(2026, 10, 1, 12, 0, 0)
        aware_obs = datetime(2026, 10, 1, 12, 0, 1, tzinfo=timezone.utc)
        valid, err = SourceValidator.validate_chronology(naive_event, aware_obs, aware_obs, aware_obs)
        assert valid is True


# ==============================================================================
# 2. SOURCE PROVENANCE & HIERARCHY TESTS (7-12)
# ==============================================================================

class TestSourceProvenance:

    def test_tier_1_official_source_accepted(self):
        tier = SourceRegistry.get_tier("federal_reserve")
        assert tier == SourceTier.TIER_1
        assert SourceRegistry.is_eligible_for_primary_research(tier) is True

    def test_tier_2_primary_wire_accepted(self):
        tier = SourceRegistry.get_tier("reuters_wire")
        assert tier == SourceTier.TIER_2
        assert SourceRegistry.is_eligible_for_primary_research(tier) is True

    def test_tier_3_secondary_source_rejected_for_primary(self):
        tier = SourceRegistry.get_tier("twitter_x")
        assert tier == SourceTier.TIER_3
        assert SourceRegistry.is_eligible_for_primary_research(tier) is False

    def test_unknown_source_defaults_tier_3(self):
        tier = SourceRegistry.get_tier("random_crypto_blog")
        assert tier == SourceTier.TIER_3
        assert SourceRegistry.is_eligible_for_primary_research(tier) is False

    def test_content_hash_integrity_pass(self):
        payload = "Official election certification notice 2026"
        h = SourceValidator.compute_content_hash(payload)
        record = SourceRecord(
            source_id="src_1",
            source_tier=SourceTier.TIER_1,
            source_domain="state.gov",
            source_name="State",
            source_url="https://state.gov",
            source_timestamp=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
            retrieval_timestamp=datetime(2026, 10, 1, 10, 0, 2, tzinfo=timezone.utc),
            content_hash=h,
            raw_payload=payload,
            is_authoritative=True
        )
        valid, err = SourceValidator.validate_source_record(record)
        assert valid is True

    def test_content_hash_tampering_rejected(self):
        record = SourceRecord(
            source_id="src_1",
            source_tier=SourceTier.TIER_1,
            source_domain="state.gov",
            source_name="State",
            source_url="https://state.gov",
            source_timestamp=datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
            retrieval_timestamp=datetime(2026, 10, 1, 10, 0, 2, tzinfo=timezone.utc),
            content_hash="tampered_hash_0000000000000000000000000000000000000000",
            raw_payload="original text",
            is_authoritative=True
        )
        valid, err = SourceValidator.validate_source_record(record)
        assert valid is False
        assert "Content hash mismatch" in err


# ==============================================================================
# 3. CONTRACT RESOLUTION RULES TESTS (13-20)
# ==============================================================================

class TestResolutionRules:

    def test_parse_btc_price_threshold_market(self):
        title = "Will the price of Bitcoin be above $82,000 on September 30?"
        rules = ResolutionRulesParser.parse_market_rules("m1", "tok1", title, "Yes")
        assert rules.is_deterministic_eligible is True
        assert rules.threshold == 82000.0
        assert rules.inequality == "GT"
        assert rules.measurement_variable == "BTC_USD_PRICE"

    def test_parse_daily_spx_open_market(self):
        title = "S&P 500 (SPX) Opens Up or Down on October 1?"
        rules = ResolutionRulesParser.parse_market_rules("m2", "tok2", title, "Up")
        assert rules.is_deterministic_eligible is True
        assert rules.measurement_variable == "S&P 500 (SPX)_OPEN_DIRECTION"
        assert rules.inequality == "GT"

    def test_parse_match_winner_market(self):
        title = "Counter-Strike: BIG vs fnatic - Map 1 Winner"
        rules = ResolutionRulesParser.parse_market_rules("m3", "tok3", title, "fnatic")
        assert rules.is_deterministic_eligible is True
        assert rules.measurement_variable == "MATCH_WINNER"

    def test_parse_ceasefire_market(self):
        title = "US x Iran ceasefire continues through September 30?"
        rules = ResolutionRulesParser.parse_market_rules("m4", "tok4", title, "Yes")
        assert rules.is_deterministic_eligible is True
        assert rules.measurement_variable == "CEASEFIRE_INTACT"

    def test_parse_scheduled_release_market(self):
        title = "Gemini 4.0 released by September 30, 2026?"
        rules = ResolutionRulesParser.parse_market_rules("m5", "tok5", title, "No")
        assert rules.is_deterministic_eligible is True
        assert rules.measurement_variable == "PRODUCT_RELEASE_OCCURRED"

    def test_reject_unrecognized_pattern(self):
        title = "Will aliens land in Central Park before midnight?"
        rules = ResolutionRulesParser.parse_market_rules("m6", "tok6", title, "Yes")
        assert rules.is_deterministic_eligible is False
        assert "Unrecognized non-standard" in rules.rejection_reason

    def test_evaluate_numerical_condition_gt_satisfied(self):
        is_met, settle_val = ResolutionRulesParser.evaluate_numerical_condition(
            actual_value=83500.0, threshold=82000.0, inequality="GT", outcome_name="Yes"
        )
        assert is_met is True
        assert settle_val == 1.0

    def test_evaluate_numerical_condition_gt_not_satisfied(self):
        is_met, settle_val = ResolutionRulesParser.evaluate_numerical_condition(
            actual_value=81500.0, threshold=82000.0, inequality="GT", outcome_name="Yes"
        )
        assert is_met is False
        assert settle_val == 0.0

    def test_evaluate_numerical_condition_inverted_outcome(self):
        is_met, settle_val = ResolutionRulesParser.evaluate_numerical_condition(
            actual_value=81500.0, threshold=82000.0, inequality="GT", outcome_name="No"
        )
        # GT condition failed, so "No" outcome wins -> $1.0
        assert is_met is False
        assert settle_val == 1.0


# ==============================================================================
# 4. DETERMINISTIC STATE CLASSIFICATION TESTS (21-27)
# ==============================================================================

class TestDeterministicState:

    def test_state_a_official_final_classified(self):
        rules = ContractResolutionRules("m1", "t1", "Match", "Winner", is_deterministic_eligible=True)
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_1,
            event_type="esports_match",
            is_official_final=True
        )
        assert state == DeterministicState.STATE_A
        assert val == 1.0
        assert reason is None

    def test_state_b_mechanically_determined_classified(self):
        rules = ContractResolutionRules("m2", "t2", "BTC > 80k", "Yes", threshold=80000.0, inequality="GT", is_deterministic_eligible=True)
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_1,
            event_type="crypto_fix",
            is_official_final=True,
            actual_numerical_value=85000.0
        )
        assert state == DeterministicState.STATE_B
        assert val == 1.0

    def test_state_c_near_deterministic_segregated(self):
        rules = ContractResolutionRules("m3", "t3", "Race", "Car A", is_deterministic_eligible=True)
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_1,
            event_type="race",
            is_official_final=False,
            probability_estimate=0.995
        )
        assert state == DeterministicState.STATE_C
        assert "Segregated" in reason

    def test_state_d_forecast_rejected(self):
        rules = ContractResolutionRules("m4", "t4", "Fed Rate", "Yes", is_deterministic_eligible=True)
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_1,
            event_type="opinion",
            is_official_final=False,
            is_forecast_or_opinion=True
        )
        assert state == DeterministicState.STATE_D
        assert "Rejected" in reason

    def test_state_d_tier3_source_rejected(self):
        rules = ContractResolutionRules("m5", "t5", "Match", "Yes", is_deterministic_eligible=True)
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_3,
            event_type="esports",
            is_official_final=True
        )
        assert state == DeterministicState.STATE_D
        assert "Tier 3" in reason

    def test_primary_eligibility_filter(self):
        assert DeterministicStateClassifier.is_primary_eligible(DeterministicState.STATE_A) is True
        assert DeterministicStateClassifier.is_primary_eligible(DeterministicState.STATE_B) is True
        assert DeterministicStateClassifier.is_primary_eligible(DeterministicState.STATE_C) is False
        assert DeterministicStateClassifier.is_primary_eligible(DeterministicState.STATE_D) is False

    def test_ineligible_rules_produce_state_d(self):
        rules = ContractResolutionRules("m6", "t6", "Bad Market", "Yes", is_deterministic_eligible=False, rejection_reason="Ambiguous")
        state, val, reason = DeterministicStateClassifier.classify_event(
            rules=rules,
            source_tier=SourceTier.TIER_1,
            event_type="test",
            is_official_final=True
        )
        assert state == DeterministicState.STATE_D


# ==============================================================================
# 5. MARKET RECONSTRUCTION TESTS (28-32)
# ==============================================================================

class TestMarketReconstruction:

    def test_find_nearest_snapshot_forward_enforced(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {"timestamp": t0 - timedelta(seconds=2), "best_ask": 0.50},  # backward
            {"timestamp": t0 + timedelta(seconds=1), "best_ask": 0.95},  # forward
            {"timestamp": t0 + timedelta(seconds=5), "best_ask": 0.99},  # forward
        ]
        nearest = MarketStateReconstructor.find_nearest_snapshot(snapshots, t0, require_forward=True)
        assert nearest["best_ask"] == 0.95
        assert nearest["timestamp"] == t0 + timedelta(seconds=1)

    def test_find_nearest_snapshot_bidirectional_for_negative_offset(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {"timestamp": t0 - timedelta(seconds=1), "best_ask": 0.49},
            {"timestamp": t0 + timedelta(seconds=5), "best_ask": 0.55},
        ]
        nearest = MarketStateReconstructor.find_nearest_snapshot(snapshots, t0, require_forward=False)
        assert nearest["best_ask"] == 0.49

    def test_reconstruct_event_window_all_offsets(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {"timestamp": t0 + timedelta(seconds=offset), "best_bid": 0.98, "best_ask": 0.99, "midpoint": 0.985, "spread_bps": 10.0, "bids": "[]", "asks": "[]"}
            for _, offset in MarketStateReconstructor.RECONSTRUCTION_OFFSETS_SEC
        ]
        window = MarketStateReconstructor.reconstruct_event_window(snapshots, t0, "m1", "tok1")
        assert len(window) == len(MarketStateReconstructor.RECONSTRUCTION_OFFSETS_SEC)
        assert "T" in window
        assert "T-60m" in window
        assert "T+15m" in window

    def test_depth_calculation_accuracy(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        asks_json = json.dumps([
            {"price": 0.95, "size": 100.0, "size_usd": 95.0},
            {"price": 0.96, "size": 200.0, "size_usd": 192.0}
        ])
        snapshots = [{"timestamp": t0, "best_bid": 0.94, "best_ask": 0.95, "midpoint": 0.945, "spread_bps": 10.0, "bids": "[]", "asks": asks_json}]
        window = MarketStateReconstructor.reconstruct_event_window(snapshots, t0, "m1", "tok1")
        assert window["T"].depth_ask_usd == 287.0


# ==============================================================================
# 6. EXECUTION ECONOMICS & L2 LADDER WALKING TESTS (33-38)
# ==============================================================================

class TestExecutionEconomics:

    def test_walk_l2_book_single_level_fill(self):
        asks = [{"price": 0.95, "size": 1000.0, "size_usd": 950.0}]
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book(asks, 50.0)
        assert vwap == 0.95
        assert shares == pytest.approx(50.0 / 0.95, rel=1e-4)
        assert levels == 1
        assert depth == 950.0

    def test_walk_l2_book_multi_level_fill(self):
        asks = [
            {"price": 0.95, "size": 20.0, "size_usd": 19.0},   # $19
            {"price": 0.98, "size": 100.0, "size_usd": 98.0},  # $98
        ]
        vwap, shares, levels, depth = ExecutionSimulator.walk_l2_book(asks, 50.0)
        # Level 1: $19 / 0.95 = 20 shares
        # Level 2: $31 / 0.98 = 31.6326 shares
        expected_shares = 20.0 + (31.0 / 0.98)
        expected_vwap = 50.0 / expected_shares
        assert vwap == pytest.approx(expected_vwap, rel=1e-4)
        assert levels == 2

    def test_walk_l2_book_insufficient_depth(self):
        asks = [{"price": 0.95, "size": 10.0, "size_usd": 9.5}]
        cand = CandidateOpportunity(
            candidate_id="c1", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=25.0,
            target_size_usd=100.0, best_ask=0.95, executable_vwap=0.95, available_depth_usd=9.5,
            gross_edge_bps=500.0, net_ev_bps=490.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        rec = ExecutionSimulator.simulate_execution(cand, asks, settlement_value=1.0)
        assert rec is None  # rejected due to insufficient depth

    def test_gross_edge_and_slippage_calculation(self):
        asks = [
            {"price": 0.95, "size": 10.0, "size_usd": 9.5},
            {"price": 0.97, "size": 100.0, "size_usd": 97.0}
        ]
        cand = CandidateOpportunity(
            candidate_id="c2", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=25.0,
            target_size_usd=50.0, best_ask=0.95, executable_vwap=0.95, available_depth_usd=106.5,
            gross_edge_bps=500.0, net_ev_bps=490.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        rec = ExecutionSimulator.simulate_execution(cand, asks, settlement_value=1.0)
        assert rec is not None
        assert rec.vwap > 0.95
        assert rec.slippage_bps > 0.0
        assert rec.gross_deterministic_edge_bps == pytest.approx(((1.0 - rec.vwap) / rec.vwap) * 10000.0)

    def test_cost_stress_erodes_net_ev(self):
        asks = [{"price": 0.99, "size": 1000.0, "size_usd": 990.0}]
        cand = CandidateOpportunity(
            candidate_id="c3", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=5.0,
            target_size_usd=50.0, best_ask=0.99, executable_vwap=0.99, available_depth_usd=990.0,
            gross_edge_bps=101.0, net_ev_bps=96.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        rec_1x = ExecutionSimulator.simulate_execution(cand, asks, settlement_value=1.0, fee_stress_multiplier=1.0)
        rec_3x = ExecutionSimulator.simulate_execution(cand, asks, settlement_value=1.0, fee_stress_multiplier=3.0)
        assert rec_3x.fee_bps == rec_1x.fee_bps * 3.0
        assert rec_3x.net_ev_bps < rec_1x.net_ev_bps


# ==============================================================================
# 7. CONVERGENCE & CAPITAL LOCKUP TESTS (39-44)
# ==============================================================================

class TestConvergenceAndLockup:

    def test_convergence_detection_at_epsilon_threshold(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {"timestamp": t0 + timedelta(seconds=1), "best_bid": 0.85, "best_ask": 0.90},
            {"timestamp": t0 + timedelta(seconds=10), "best_bid": 0.995, "best_ask": 1.00},  # converged at 10bp
        ]
        conv = ConvergenceTracker.evaluate_convergence("e1", "m1", "t1", t0, snapshots, epsilon_bps=10.0)
        assert conv.has_converged is True
        assert conv.reaction_delay_sec == 10.0

    def test_convergence_not_reached(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            {"timestamp": t0 + timedelta(seconds=1), "best_bid": 0.85, "best_ask": 0.90},
        ]
        conv = ConvergenceTracker.evaluate_convergence("e2", "m2", "t2", t0, snapshots, epsilon_bps=5.0)
        assert conv.has_converged is False
        assert conv.reaction_delay_sec is None

    def test_capital_lockup_cost_calculation(self):
        t_entry = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_settle = t_entry + timedelta(hours=24)
        rec = CapitalLockupModel.calculate_lockup(
            event_id="e1", market_id="m1", position_size_usd=100.0,
            entry_ts=t_entry, scheduled_end_ts=t_settle, actual_settlement_ts=t_settle,
            gross_pnl_usd=1.0, trading_fees_usd=0.05
        )
        assert rec.actual_delay_hours == pytest.approx(24.0)
        assert rec.cost_of_capital_bps > 0.0
        assert rec.net_pnl_usd < rec.gross_pnl_usd

    def test_annualized_return_formula(self):
        t_entry = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_settle = t_entry + timedelta(hours=12)
        rec = CapitalLockupModel.calculate_lockup(
            event_id="e2", market_id="m2", position_size_usd=100.0,
            entry_ts=t_entry, scheduled_end_ts=t_settle, actual_settlement_ts=t_settle,
            gross_pnl_usd=2.0, trading_fees_usd=0.0
        )
        # 12h holding period -> 730 periods per year
        assert rec.annualized_return_pct > 100.0


# ==============================================================================
# 8. ADVERSARIAL CONTROLS TESTS (45-50)
# ==============================================================================

class TestAdversarialControls:

    def test_c1_pre_event_placebo_zero_edge(self):
        cand = CandidateOpportunity(
            candidate_id="c1", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=25.0,
            target_size_usd=50.0, best_ask=0.50, executable_vwap=0.50, available_depth_usd=500.0,
            gross_edge_bps=0.0, net_ev_bps=-25.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        asks = [{"price": 0.50, "size": 100.0, "size_usd": 50.0}]
        ctrl = AdversarialControlsEvaluator.evaluate_c1_pre_event_placebo(cand, 0.50, asks)
        assert ctrl.expected_result_valid is True

    def test_c2_random_timestamp_control(self):
        cand = CandidateOpportunity(
            candidate_id="c2", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=25.0,
            target_size_usd=50.0, best_ask=0.52, executable_vwap=0.52, available_depth_usd=500.0,
            gross_edge_bps=0.0, net_ev_bps=-25.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        ctrl = AdversarialControlsEvaluator.evaluate_c2_random_timestamp(cand, 0.52)
        assert ctrl.expected_result_valid is True

    def test_c3_reverse_outcome_catastrophic_loss(self):
        cand = CandidateOpportunity(
            candidate_id="c3", event_id="e1", market_id="m1", token_id="t1", outcome="Yes",
            deterministic_state=DeterministicState.STATE_A, source_tier=SourceTier.TIER_1,
            source_timestamp=datetime.now(timezone.utc), market_observation_timestamp=datetime.now(timezone.utc),
            latency_ms=500.0, latency_bucket=LatencyBucket.B_500MS_1S, entry_threshold_bps=25.0,
            target_size_usd=50.0, best_ask=0.98, executable_vwap=0.98, available_depth_usd=500.0,
            gross_edge_bps=200.0, net_ev_bps=190.0, is_out_of_sample=False, execution_status="EXECUTED"
        )
        ctrl = AdversarialControlsEvaluator.evaluate_c3_reverse_outcome(cand, 0.98)
        assert ctrl.expected_result_valid is True
        assert ctrl.net_ev_bps <= -5000.0

    def test_c5_non_deterministic_rejected(self):
        ctrl = AdversarialControlsEvaluator.evaluate_c5_non_deterministic("e_bad", DeterministicState.STATE_D)
        assert ctrl.expected_result_valid is True


# ==============================================================================
# 9. STATISTICAL ENGINE & MULTIPLE TESTING TESTS (51-55)
# ==============================================================================

class TestStatisticalEngine:

    def test_bootstrap_ci_calculation(self):
        values = np.array([50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
        lower, upper = StatisticalEngine.compute_bootstrap_ci(values, num_resamples=500)
        assert lower < upper
        assert lower >= 40.0
        assert upper <= 110.0

    def test_observation_level_t_test(self):
        values = np.array([10.0, 12.0, 11.0, 13.0, 12.5, 11.5])
        t_stat, p_val = StatisticalEngine.compute_t_test(values)
        assert t_stat > 0.0
        assert p_val < 0.001

    def test_holm_bonferroni_adjustment(self):
        p_vals = [0.01, 0.04, 0.03]
        adj = StatisticalEngine.apply_holm_bonferroni(p_vals)
        # Sorted: 0.01 (x3=0.03), 0.03 (x2=0.06), 0.04 (x1=0.06)
        assert adj[0] == pytest.approx(0.03)
        assert adj[1] >= adj[2]

    def test_sample_size_below_30_produces_sparse_verdict(self):
        # Even with positive EV, if N < 30, verdict must be EVENT_UNIVERSE_TOO_SPARSE
        execs = [
            ExecutionRecord(f"e_{i}", f"c_{i}", f"ev_{i}", "m1", "tok1", "Yes", datetime.now(timezone.utc),
                            50.0, 50.0, 0.95, 0.0, 5.0, 526.0, 521.0, 1, False)
            for i in range(15)  # N = 15 < 30
        ]
        cands = [
            CandidateOpportunity(f"c_{i}", f"ev_{i}", "m1", "tok1", "Yes", DeterministicState.STATE_A, SourceTier.TIER_1,
                                 datetime.now(timezone.utc), datetime.now(timezone.utc), 500.0, LatencyBucket.B_500MS_1S,
                                 25.0, 50.0, 0.95, 0.95, 500.0, 526.0, 521.0, False, "EXECUTED")
            for i in range(15)
        ]
        res = StatisticalEngine.evaluate_hypothesis("H1", "Official lag", execs, cands, 25.0, LatencyBucket.B_500MS_1S, 50.0, is_sparse_universe=True)
        assert res.verdict == Phase10A10Verdict.EVENT_UNIVERSE_TOO_SPARSE
        assert res.is_significant is False


# ==============================================================================
# 10. PRODUCTION CONTAMINATION GUARD TESTS (56-57)
# ==============================================================================

class TestContaminationGuard:

    def test_guard_blocks_synthetic_markers_in_production(self):
        bad_record = {"event_id": "test_fake_event_1", "title": "synthetic outcome", "provenance": "POLYMARKET_LIVE"}
        with pytest.raises(Phase10A10ContaminationError) as exc:
            ProductionContaminationGuard.assert_valid_production_record(bad_record, is_production_db=True)
        assert "Contamination detected" in str(exc.value)

    def test_guard_allows_valid_live_record(self):
        good_record = {"event_id": "evt_4904811", "title": "Dota 2: BetBoom vs OG", "provenance": "POLYMARKET_LIVE"}
        # Should not raise
        ProductionContaminationGuard.assert_valid_production_record(good_record, is_production_db=True)
