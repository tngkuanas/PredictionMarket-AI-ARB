"""Comprehensive Test Suite for Phase 10A.11 Executable Alpha Discovery.

Minimum requirement: >= 40 dedicated tests.
Tests cover:
- Dataset provenance and read-only protection
- Feature chronology and strict anti-lookahead
- Novelty checks and duplicate-family detection
- AI hypothesis schema and candidate registry (max 10)
- Hard profitability standard (no 'PROFITABLE' status)
- L2 order-book ladder execution, VWAP, slippage, and taker fees
- Multi-tier capacity evaluation ($10 to $1,000)
- Baseline and adversarial controls (placebo, permutation, reverse, cost stress)
- Economic clustering and cluster-robust standard errors
- Multiple-testing Holm-Bonferroni correction
- Chronological Discovery / Validation / OOS partitioning
- Production safety (no production writes, recorder remains stopped)
"""

import datetime
import json
import math
import os
import subprocess
import pytest
import numpy as np
import duckdb

from src.phase10a11 import (
    NoveltyVerdict,
    CandidateStatus,
    ClosedFamily,
    SplitPhase,
    FillStatus,
    ExecutionStyle,
)
from src.phase10a11.dataset_inventory import DatasetInventory, DatasetInventoryEngine
from src.phase10a11.novelty_validator import NoveltyValidator, NoveltyAssessment, CLOSED_FAMILY_REGISTRY
from src.phase10a11.features import (
    MicrostructureFeatures,
    FeatureLookaheadValidator,
    FeatureExtractor,
    LookaheadViolationError,
)
from src.phase10a11.candidate_mechanisms import (
    CandidateMechanism,
    CandidateRegistry,
    AIDiscoveryLayer,
    RegistryCapacityExceededError,
    InvalidStatusTransitionError,
)
from src.phase10a11.execution_model import (
    OrderBookLevel,
    ExecutionResult,
    L2ExecutionModel,
    CAPACITY_TIERS_USD,
)
from src.phase10a11.discovery_pipeline import (
    ChronologicalSplit,
    DiscoveryPipeline,
    BaselineControlResult,
    ClusteredInferenceResult,
)


# =====================================================================
# 1. Dataset Provenance and Read-Only Protection
# =====================================================================

class TestDatasetProvenance:

    def test_database_exists_and_readable(self):
        db_path = "data/prediction_market.duckdb"
        assert os.path.exists(db_path), f"Database file {db_path} must exist"
        con = duckdb.connect(db_path, read_only=True)
        try:
            cnt = con.execute("SELECT COUNT(*) FROM phase10a5_book_snapshots").fetchone()[0]
            assert cnt > 5000000, f"Expected > 5M snapshots, found {cnt}"
        finally:
            con.close()

    def test_read_only_protection_prevents_writes(self):
        db_path = "data/prediction_market.duckdb"
        con = duckdb.connect(db_path, read_only=True)
        try:
            with pytest.raises(Exception):
                con.execute("CREATE TABLE test_unauthorized_write (id INT)")
        finally:
            con.close()

    def test_dataset_inventory_engine_runs(self):
        engine = DatasetInventoryEngine(db_path="data/prediction_market.duckdb")
        inv = engine.run_inventory()
        assert inv.is_read_only is True
        assert inv.number_of_snapshots > 5000000
        assert inv.number_of_trades > 25000
        assert inv.number_of_markets >= 150
        assert inv.number_of_tokens >= 300
        assert inv.total_duration_hours > 30.0

    def test_dataset_inventory_timestamps_chronological(self):
        engine = DatasetInventoryEngine(db_path="data/prediction_market.duckdb")
        inv = engine.run_inventory()
        assert inv.earliest_timestamp is not None
        assert inv.latest_timestamp is not None
        assert inv.earliest_timestamp < inv.latest_timestamp

    def test_market_families_categorization(self):
        engine = DatasetInventoryEngine(db_path="data/prediction_market.duckdb")
        inv = engine.run_inventory()
        assert inv.number_of_market_families >= 3
        assert "Macroeconomics & Monetary Policy" in inv.market_families
        assert "Geopolitics & Foreign Affairs" in inv.market_families
        assert "Esports (LoL, CS, Dota)" in inv.market_families

    def test_median_observation_frequency_positive(self):
        engine = DatasetInventoryEngine(db_path="data/prediction_market.duckdb")
        inv = engine.run_inventory()
        assert inv.median_observation_frequency_sec > 0.0
        assert inv.median_observation_frequency_sec < 1.0  # sub-second frequency

    def test_no_synthetic_fixtures_in_inventory(self):
        engine = DatasetInventoryEngine(db_path="data/prediction_market.duckdb")
        inv = engine.run_inventory()
        # Genuine data has substantial trade volume and asymmetric buy/sell distribution
        assert inv.buy_trades_count > inv.sell_trades_count
        assert inv.mean_depth_bid_usd > 1000.0


# =====================================================================
# 2. Feature Chronology and Anti-Lookahead Validation
# =====================================================================

class TestFeatureChronologyAndLookahead:

    def setup_method(self):
        self.validator = FeatureLookaheadValidator()

    def test_causal_timeline_valid(self):
        t0 = datetime.datetime(2026, 10, 1, 12, 0, 0)
        t1 = datetime.datetime(2026, 10, 1, 12, 0, 1)
        t2 = datetime.datetime(2026, 10, 1, 12, 0, 2)
        assert self.validator.validate_causal_timeline(t0, t1, t2) is True

    def test_causal_timeline_identical_timestamps_valid(self):
        t = datetime.datetime(2026, 10, 1, 12, 0, 0)
        assert self.validator.validate_causal_timeline(t, t, t) is True

    def test_causal_timeline_feature_future_violation(self):
        t_feat = datetime.datetime(2026, 10, 1, 12, 0, 2)
        t_sig = datetime.datetime(2026, 10, 1, 12, 0, 1)
        t_exec = datetime.datetime(2026, 10, 1, 12, 0, 3)
        with pytest.raises(LookaheadViolationError, match="Feature timestamp .* > Signal timestamp"):
            self.validator.validate_causal_timeline(t_feat, t_sig, t_exec)

    def test_causal_timeline_signal_future_violation(self):
        t_feat = datetime.datetime(2026, 10, 1, 12, 0, 0)
        t_sig = datetime.datetime(2026, 10, 1, 12, 0, 5)
        t_exec = datetime.datetime(2026, 10, 1, 12, 0, 3)
        with pytest.raises(LookaheadViolationError, match="Signal timestamp .* > Execution timestamp"):
            self.validator.validate_causal_timeline(t_feat, t_sig, t_exec)

    def test_forbidden_keys_detected(self):
        now = datetime.datetime(2026, 10, 1, 12, 0, 0)
        bad_dict = {"midpoint": 0.50, "future_price": 0.55}
        with pytest.raises(LookaheadViolationError, match="Forbidden leakage key"):
            self.validator.validate_feature_dictionary(bad_dict, now)

    def test_forbidden_settlement_value_detected(self):
        now = datetime.datetime(2026, 10, 1, 12, 0, 0)
        bad_dict = {"midpoint": 0.50, "settlement_value": 1.0}
        with pytest.raises(LookaheadViolationError, match="Forbidden leakage key"):
            self.validator.validate_feature_dictionary(bad_dict, now)

    def test_clean_feature_dict_passes(self):
        now = datetime.datetime(2026, 10, 1, 12, 0, 0)
        good_dict = {"best_bid": 0.49, "best_ask": 0.51, "spread_bps": 400.0}
        assert self.validator.validate_feature_dictionary(good_dict, now) is True

    def test_chronological_dataset_validation_passes(self):
        obs = [
            {"timestamp": "2026-10-01T12:00:00", "price": 0.50},
            {"timestamp": "2026-10-01T12:00:05", "price": 0.51},
            {"timestamp": "2026-10-01T12:00:10", "price": 0.52},
        ]
        assert self.validator.validate_dataset_chronology(obs) is True

    def test_chronological_dataset_validation_detects_out_of_order(self):
        obs = [
            {"timestamp": "2026-10-01T12:00:10", "price": 0.50},
            {"timestamp": "2026-10-01T12:00:05", "price": 0.51},
        ]
        with pytest.raises(LookaheadViolationError, match="Dataset chronology broken"):
            self.validator.validate_dataset_chronology(obs)

    def test_feature_extractor_point_in_time(self):
        extractor = FeatureExtractor(validator=self.validator)
        now = datetime.datetime(2026, 10, 1, 12, 0, 30)
        snap = {
            "timestamp": now,
            "market_id": "mkt_1",
            "token_id": "tok_1",
            "best_bid": 0.48,
            "best_ask": 0.52,
            "midpoint": 0.50,
            "spread": 0.04,
            "spread_bps": 800.0,
            "depth_bid_usd": 1000.0,
            "depth_ask_usd": 1500.0,
            "bids": [{"price": 0.48, "size": 1000}],
            "asks": [{"price": 0.52, "size": 1000}],
        }
        past_snaps = [{"timestamp": now - datetime.timedelta(seconds=15), "midpoint": 0.49}]
        past_trades = [{"receive_timestamp": now - datetime.timedelta(seconds=10), "size_usd": 100.0}]
        
        feats = extractor.extract_features(snap, past_snaps, past_trades)
        assert feats.best_bid == 0.48
        assert feats.best_ask == 0.52
        assert feats.trade_intensity_60s == 1
        assert feats.trade_volume_usd_60s == 100.0

    def test_feature_extractor_future_snapshot_violation(self):
        extractor = FeatureExtractor(validator=self.validator)
        now = datetime.datetime(2026, 10, 1, 12, 0, 30)
        snap = {"timestamp": now, "best_bid": 0.48, "best_ask": 0.52}
        future_snaps = [{"timestamp": now + datetime.timedelta(seconds=5), "midpoint": 0.55}]
        with pytest.raises(LookaheadViolationError, match="Past snapshot timestamp .* > current timestamp"):
            extractor.extract_features(snap, future_snaps, [])

    def test_feature_extractor_future_trade_violation(self):
        extractor = FeatureExtractor(validator=self.validator)
        now = datetime.datetime(2026, 10, 1, 12, 0, 30)
        snap = {"timestamp": now, "best_bid": 0.48, "best_ask": 0.52}
        future_trades = [{"receive_timestamp": now + datetime.timedelta(seconds=2), "size_usd": 50.0}]
        with pytest.raises(LookaheadViolationError, match="Past trade timestamp .* > current timestamp"):
            extractor.extract_features(snap, [], future_trades)


# =====================================================================
# 3. Novelty Checks and Duplicate-Family Detection
# =====================================================================

class TestNoveltyAndDuplicateDetection:

    def setup_method(self):
        self.validator = NoveltyValidator()

    def test_directional_microstructure_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_C6",
            drivers=["momentum", "order_flow_imbalance"],
            signals=["ofi_threshold"],
            causal_description="Taking directional trades following momentum and volume surge",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASE10A7_DIRECTIONAL_MICROSTRUCTURE
        assert assessment.novelty_score == 0.0

    def test_passive_maker_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_C7",
            drivers=["passive_maker", "spread_capture"],
            signals=["symmetric_quoting"],
            causal_description="Posting resting limit quotes at the inside spread",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASE10A8_PASSIVE_MAKER

    def test_hedged_passive_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_C8",
            drivers=["hedged_passive", "complementary_taker_hedge"],
            signals=["parity_arbitrage"],
            causal_description="Making on YES and taking on NO to capture parity",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASE10A9_HEDGED_PASSIVE

    def test_deterministic_resolution_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_C9",
            drivers=["deterministic_resolution", "resolution_lag"],
            signals=["verified_outcome_buy"],
            causal_description="Sniping contracts after news confirms the outcome",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASE10A10_DETERMINISTIC_RESOLUTION

    def test_semantic_stat_arb_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_STATARB",
            drivers=["cointegration", "stat_arb_spread"],
            signals=["embedding_distance_spread"],
            causal_description="Pair trading cointegrated contracts based on semantic embeddings",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASES3_9_SEMANTIC_STATARB

    def test_cross_venue_duplicate_detected(self):
        assessment = self.validator.assess_candidate(
            candidate_id="TEST_XVENUE",
            drivers=["cross_venue", "kalshi_polymarket"],
            signals=["kalshi_bid_higher_than_polymarket_ask"],
            causal_description="Cross venue arbitrage between Kalshi and Polymarket",
        )
        assert assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert assessment.matched_closed_family == ClosedFamily.PHASE10A6_CROSS_VENUE_ARBITRAGE

    def test_novel_post_sweep_resiliency_passes(self):
        assessment = self.validator.assess_candidate(
            candidate_id="M1_POST_SWEEP_RESILIENCY",
            drivers=["transient_depth_exhaustion", "liquidity_replenishment", "book_resiliency"],
            signals=["depth_depletion_recovery", "post_sweep_rebound"],
            causal_description="Mean reversion following mechanical liquidity depletion",
        )
        assert assessment.verdict == NoveltyVerdict.NOVEL
        assert assessment.matched_closed_family is None
        assert assessment.novelty_score == 1.0

    def test_novel_structural_fee_wedge_passes(self):
        assessment = self.validator.assess_candidate(
            candidate_id="M2_STRUCTURAL_FEE_SUBPENNY_WEDGE",
            drivers=["tick_discreteness", "subpenny_wedge", "boundary_pricing"],
            signals=["boundary_tick_mispricing"],
            causal_description="Exploiting discrete tick brackets near probability boundaries",
        )
        assert assessment.verdict == NoveltyVerdict.NOVEL
        assert assessment.novelty_score == 1.0


# =====================================================================
# 4. Candidate Registry, AI Schema, and Hard Profitability Standard
# =====================================================================

class TestCandidateRegistryAndAISchema:

    def test_registry_max_capacity_enforced(self):
        registry = CandidateRegistry()
        for i in range(CandidateRegistry.MAX_CANDIDATES):
            c = CandidateMechanism(
                candidate_id=f"TEST_{i}",
                name=f"Mechanism {i}",
                mechanism="Test",
                why_it_could_exist="Test",
                required_observable_variables=["var1"],
                economic_participant_causing_it="Participant",
                expected_direction="Direction",
                expected_holding_period="10s",
                execution_style=ExecutionStyle.TAKER_CROSS,
                main_friction="Friction",
                capacity_constraint="$100",
                why_previous_phases_did_not_test_it="New",
                primary_falsification_test="Falsification",
                signal_definition="Signal",
                causal_story="Causal",
                required_data="Data",
                expected_return_bps=10.0,
                expected_horizon_sec=10.0,
                execution_method="Method",
                failure_mode="Failure",
            )
            registry.register_candidate(c, drivers=[f"unique_driver_{i}"], signals=[f"unique_sig_{i}"])

        # 11th registration must fail
        c11 = CandidateMechanism(
            candidate_id="TEST_11_OVERFLOW",
            name="Overflow",
            mechanism="Test",
            why_it_could_exist="Test",
            required_observable_variables=["var1"],
            economic_participant_causing_it="Participant",
            expected_direction="Direction",
            expected_holding_period="10s",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Friction",
            capacity_constraint="$100",
            why_previous_phases_did_not_test_it="New",
            primary_falsification_test="Falsification",
            signal_definition="Signal",
            causal_story="Causal",
            required_data="Data",
            expected_return_bps=10.0,
            expected_horizon_sec=10.0,
            execution_method="Method",
            failure_mode="Failure",
        )
        with pytest.raises(RegistryCapacityExceededError):
            registry.register_candidate(c11, drivers=["overflow"], signals=["overflow"])

    def test_duplicate_candidate_auto_rejected_in_registry(self):
        registry = CandidateRegistry()
        c = CandidateMechanism(
            candidate_id="C6_DUP",
            name="OFI Momentum",
            mechanism="Momentum",
            why_it_could_exist="Test",
            required_observable_variables=["trade_volume_surge"],
            economic_participant_causing_it="Takers",
            expected_direction="Directional",
            expected_holding_period="10s",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Friction",
            capacity_constraint="$100",
            why_previous_phases_did_not_test_it="None",
            primary_falsification_test="Falsification",
            signal_definition="Signal",
            causal_story="Momentum following order flow imbalance",
            required_data="Trades",
            expected_return_bps=10.0,
            expected_horizon_sec=10.0,
            execution_method="Taker buy",
            failure_mode="Adverse selection",
        )
        registry.register_candidate(c, drivers=["momentum", "order_flow_imbalance"], signals=["ofi_threshold"])
        assert c.novelty_verdict == NoveltyVerdict.DUPLICATE_FAMILY
        assert c.status == CandidateStatus.REJECTED
        assert "duplicates closed family" in c.rejection_reason

    def test_hard_profitability_standard_disallows_profitable(self):
        c = CandidateMechanism(
            candidate_id="TEST_STATUS",
            name="Test",
            mechanism="Test",
            why_it_could_exist="Test",
            required_observable_variables=["var1"],
            economic_participant_causing_it="Participant",
            expected_direction="Direction",
            expected_holding_period="10s",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Friction",
            capacity_constraint="$100",
            why_previous_phases_did_not_test_it="New",
            primary_falsification_test="Falsification",
            signal_definition="Signal",
            causal_story="Causal",
            required_data="Data",
            expected_return_bps=10.0,
            expected_horizon_sec=10.0,
            execution_method="Method",
            failure_mode="Failure",
        )
        # Attempting to assign string 'PROFITABLE' must fail
        with pytest.raises(InvalidStatusTransitionError):
            c.set_status("PROFITABLE")  # type: ignore

    def test_allowed_candidate_statuses(self):
        c = CandidateMechanism(
            candidate_id="TEST_STATUS",
            name="Test",
            mechanism="Test",
            why_it_could_exist="Test",
            required_observable_variables=["var1"],
            economic_participant_causing_it="Participant",
            expected_direction="Direction",
            expected_holding_period="10s",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Friction",
            capacity_constraint="$100",
            why_previous_phases_did_not_test_it="New",
            primary_falsification_test="Falsification",
            signal_definition="Signal",
            causal_story="Causal",
            required_data="Data",
            expected_return_bps=10.0,
            expected_horizon_sec=10.0,
            execution_method="Method",
            failure_mode="Failure",
        )
        c.set_status(CandidateStatus.REJECTED)
        assert c.status == CandidateStatus.REJECTED
        c.set_status(CandidateStatus.PROMISING_BUT_UNVALIDATED)
        assert c.status == CandidateStatus.PROMISING_BUT_UNVALIDATED
        c.set_status(CandidateStatus.OOS_CANDIDATE)
        assert c.status == CandidateStatus.OOS_CANDIDATE

    def test_ai_discovery_pre_registered_slate_count(self):
        registry = CandidateRegistry()
        ai_layer = AIDiscoveryLayer(registry=registry)
        ai_layer.build_registered_slate()
        assert len(registry.list_candidates()) == 10
        assert registry.is_frozen is True


# =====================================================================
# 5. L2 Execution Model, VWAP, Slippage, and Fees
# =====================================================================

class TestL2ExecutionModel:

    def setup_method(self):
        self.exec_model = L2ExecutionModel()

    def test_ladder_parsing_dict(self):
        raw = '[{"price": 0.52, "size": 100}, {"price": 0.53, "size": 200}]'
        levels = self.exec_model.parse_ladder(raw)
        assert len(levels) == 2
        assert levels[0].price == 0.52
        assert levels[0].size == 100
        assert levels[0].size_usd == 52.0

    def test_ladder_parsing_tuple(self):
        raw = '[[0.48, 50], [0.47, 100]]'
        levels = self.exec_model.parse_ladder(raw)
        assert len(levels) == 2
        assert levels[0].price == 0.48
        assert levels[0].size == 50

    def test_empty_ladder_unfilled(self):
        snap = {"best_ask": 0.55, "asks": "[]"}
        res = self.exec_model.execute_order(side="BUY", order_size_usd=50.0, book_snapshot=snap)
        assert res.fill_status == FillStatus.UNFILLED
        assert res.filled_size_usd == 0.0
        assert res.unfilled_size_usd == 50.0

    def test_single_level_full_fill_zero_slippage(self):
        # 1 level with $500 available at 0.50
        snap = {"asks": '[{"price": 0.50, "size": 1000}]'}
        res = self.exec_model.execute_order(side="BUY", order_size_usd=100.0, book_snapshot=snap, fee_rate_bps=5.0)
        assert res.fill_status == FillStatus.FULL_FILL
        assert res.filled_size_usd == 100.0
        assert res.vwap == 0.50
        assert res.slippage_bps == 0.0
        assert res.fee_usd == 0.05  # 5 bps on $100
        assert res.effective_price > 0.50  # includes fee

    def test_multi_level_walk_vwap_and_slippage(self):
        # Asks: $50 at 0.50, $52 at 0.52
        snap = {"asks": '[{"price": 0.50, "size": 100}, {"price": 0.52, "size": 100}]'}
        res = self.exec_model.execute_order(side="BUY", order_size_usd=100.0, book_snapshot=snap, fee_rate_bps=0.0)
        assert res.fill_status == FillStatus.FULL_FILL
        # 100 shares at 0.50 = $50; 96.1538 shares at 0.52 = $50
        # total shares = 196.1538, total USD = 100.0 -> vwap = 100 / 196.1538 = 0.5098
        assert 0.509 < res.vwap < 0.511
        assert res.slippage_bps > 0.0  # VWAP higher than top of book 0.50

    def test_partial_fill_when_depth_exhausted(self):
        # Only $25 available in total
        snap = {"bids": '[{"price": 0.50, "size": 50}]'}
        res = self.exec_model.execute_order(side="SELL", order_size_usd=100.0, book_snapshot=snap)
        assert res.fill_status == FillStatus.PARTIAL_FILL
        assert res.filled_size_usd == 25.0
        assert res.unfilled_size_usd == 75.0

    def test_invalid_side_raises_error(self):
        snap = {"asks": '[{"price": 0.50, "size": 100}]'}
        with pytest.raises(ValueError, match="Side must be 'BUY' or 'SELL'"):
            self.exec_model.execute_order(side="HOLD", order_size_usd=50.0, book_snapshot=snap)

    def test_capacity_sweep_evaluates_all_tiers(self):
        snap = {"asks": '[{"price": 0.50, "size": 5000}]'}
        sweep = self.exec_model.evaluate_capacity_sweep(side="BUY", book_snapshot=snap)
        assert len(sweep) == len(CAPACITY_TIERS_USD)
        for tier in [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]:
            assert tier in sweep
            assert sweep[tier].fill_status == FillStatus.FULL_FILL


# =====================================================================
# 6. Baseline and Adversarial Controls
# =====================================================================

class TestBaselineAndAdversarialControls:

    def setup_method(self):
        self.pipeline = DiscoveryPipeline()

    def test_placebo_control_computation(self):
        returns = np.random.normal(loc=35.0, scale=40.0, size=100)
        res = self.pipeline.run_baseline_controls("TEST_M1", returns)
        assert res.placebo_mean_ev_bps < 0.0  # Placebo with fee drag is negative
        assert res.placebo_p_value < 0.05

    def test_sign_permutation_detects_genuine_edge(self):
        # Very strong positive signal
        returns = np.random.normal(loc=50.0, scale=10.0, size=200)
        res = self.pipeline.run_baseline_controls("TEST_M1", returns)
        assert res.permutation_survival is True
        assert res.sign_permutation_p_value < 0.01

    def test_reverse_signal_penalizes_direction(self):
        returns = np.random.normal(loc=40.0, scale=20.0, size=100)
        res = self.pipeline.run_baseline_controls("TEST_M1", returns)
        assert res.reverse_signal_mean_ev_bps < -40.0
        assert res.reverse_survival is True

    def test_transaction_cost_stress_survival(self):
        # Strong signal surviving 2x fee
        returns = np.random.normal(loc=30.0, scale=20.0, size=100)
        res = self.pipeline.run_baseline_controls("TEST_M1", returns, base_fee_bps=5.0)
        assert res.cost_survival is True
        assert res.cost_stressed_ev_bps > 0.0

    def test_transaction_cost_stress_fails_weak_signal(self):
        # Marginal signal wiped out by fee
        returns = np.random.normal(loc=2.0, scale=20.0, size=100)
        res = self.pipeline.run_baseline_controls("TEST_WEAK", returns, base_fee_bps=5.0)
        assert res.cost_survival is False


# =====================================================================
# 7. Clustered Inference and Multiple-Testing Bookkeeping
# =====================================================================

class TestClusteredInferenceAndMultipleTesting:

    def setup_method(self):
        self.pipeline = DiscoveryPipeline()

    def test_clustered_inference_calculation(self):
        np.random.seed(42)
        n = 150
        returns = np.random.normal(loc=30.0, scale=50.0, size=n)
        clusters = np.random.choice(range(1, 15), size=n)
        res = self.pipeline.run_clustered_inference("TEST_CLUST", returns, clusters, "market")
        assert res.n_observations == n
        assert res.n_clusters == 14
        assert res.cluster_std_err_bps > 0.0
        assert res.t_stat > 0.0

    def test_clustered_inference_empty_data(self):
        res = self.pipeline.run_clustered_inference("TEST_EMPTY", np.array([]), np.array([]), "market")
        assert res.n_observations == 0
        assert res.p_value == 1.0

    def test_multiple_testing_holm_bonferroni_adjustment(self):
        c1 = CandidateMechanism(
            candidate_id="C1", name="C1", mechanism="", why_it_could_exist="",
            required_observable_variables=[], economic_participant_causing_it="",
            expected_direction="", expected_holding_period="", execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="", capacity_constraint="", why_previous_phases_did_not_test_it="",
            primary_falsification_test="", signal_definition="", causal_story="", required_data="",
            expected_return_bps=0.0, expected_horizon_sec=0.0, execution_method="", failure_mode="",
            baseline_p_value=0.001,
        )
        c2 = CandidateMechanism(
            candidate_id="C2", name="C2", mechanism="", why_it_could_exist="",
            required_observable_variables=[], economic_participant_causing_it="",
            expected_direction="", expected_holding_period="", execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="", capacity_constraint="", why_previous_phases_did_not_test_it="",
            primary_falsification_test="", signal_definition="", causal_story="", required_data="",
            expected_return_bps=0.0, expected_horizon_sec=0.0, execution_method="", failure_mode="",
            baseline_p_value=0.04,
        )
        candidates = [c1, c2]
        self.pipeline.apply_multiple_testing_adjustments(candidates)
        # m = 2: rank 1 multiplier is 2, rank 2 multiplier is 1
        assert c1.adjusted_p_value == pytest.approx(0.002, abs=1e-3)
        assert c2.adjusted_p_value == pytest.approx(0.04, abs=1e-3)


# =====================================================================
# 8. Chronological Split and Production Safety
# =====================================================================

class TestChronologicalSplitAndProductionSafety:

    def test_chronological_split_partition_bounds(self):
        t0 = datetime.datetime(2026, 10, 1, 0, 0, 0)
        t3 = datetime.datetime(2026, 10, 3, 0, 0, 0)
        pipeline = DiscoveryPipeline()
        split = pipeline.build_chronological_split(t0, t3)
        assert split.total_hours == 48.0
        assert split.discovery_end == split.validation_start
        assert split.validation_end == split.oos_start
        assert split.oos_end == t3

    def test_chronological_split_phase_lookup(self):
        t0 = datetime.datetime(2026, 10, 1, 0, 0, 0)
        t3 = datetime.datetime(2026, 10, 3, 0, 0, 0)
        pipeline = DiscoveryPipeline()
        split = pipeline.build_chronological_split(t0, t3)

        assert split.get_phase(t0 + datetime.timedelta(hours=10)) == SplitPhase.DISCOVERY
        assert split.get_phase(t0 + datetime.timedelta(hours=30)) == SplitPhase.VALIDATION
        assert split.get_phase(t0 + datetime.timedelta(hours=40)) == SplitPhase.OOS

    def test_recorder_remains_stopped(self):
        # Hard constraint: Daemon must NOT be restarted
        res = subprocess.run(
            ["pgrep", "-f", "run_phase10a5e_daemon.py"],
            capture_output=True,
            text=True,
        )
        pids = res.stdout.strip().split()
        assert len(pids) == 0, f"Recorder daemon PID {pids} is running! Must remain stopped."
