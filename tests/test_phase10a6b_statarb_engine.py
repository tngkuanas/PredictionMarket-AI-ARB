"""Comprehensive Unit Tests for Phase 10A.6b Stat-Arb Framework.

Covers:
1. Hypothesis schema validation & 7 hypothesis families.
2. Lineage tracking, versioning & family multiple-testing penalty.
3. Parameter freezing & SHA-256 configuration hash immutability.
4. Lookahead prevention & train/OOS separation.
5. Spread construction & in-sample hedge ratio estimation (OLS, Huber, Theil-Sen).
6. Standard and robust MAD rolling z-scores.
7. Mean-reversion half-life (Ornstein-Uhlenbeck AR(1) dynamics).
8. Stationarity (ADF) and Engle-Granger cointegration testing.
9. Lead-lag cross-correlation profile.
10. Multi-tier executability gating (quote, spread, depth, VWAP, fee, slippage, latency, capacity, net EV).
11. Insufficient depth & zero depth extrapolation.
12. 10-tier adversarial testing battery & diagnostic failure classification.
13. Machine-readable scorecard with categorical axes (no composite score).
14. Anti-synthetic data guard.
15. Strict AI vs Deterministic engine boundary enforcement.
"""

import hashlib
import json
import pytest
import numpy as np
import pandas as pd

from src.statarb.schema import (
    HypothesisFamily,
    HypothesisStatus,
    ScorecardStatus,
    ScorecardVerdict,
    AdversarialVerdict,
    StructuredHypothesis,
    HypothesisScorecard,
    SpreadModelConfig,
    ExecutionGateResult,
    StatArbMetrics,
)
from src.statarb.lineage import (
    HypothesisLineageTracker,
    LineageViolationError,
)
from src.statarb.engine import DeterministicStatArbEngine
from src.statarb.executability import ExecutabilityGate
from src.statarb.adversarial import AdversarialTestingBattery
from src.statarb.scorecard import ScorecardEvaluator
from src.statarb.boundary_validator import (
    BoundaryValidator,
    BoundaryViolationError,
)
from src.statarb.phase10a5_feed import Phase10A5DataFeed


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def valid_hypothesis_dict():
    return {
        "hypothesis_id": "hyp_btc_eth_leadlag_001",
        "hypothesis_family": "cross_market_lead_lag",
        "source_markets": ["poly_btc_100k"],
        "target_markets": ["poly_eth_4k"],
        "causal_mechanism": "Spot Bitcoin institutional flows lead secondary Ethereum repricing due to cross-asset capital rotation.",
        "required_observations": ["order_book_l2", "trades"],
        "observable_variables": ["mid_price", "signed_imbalance"],
        "expected_relationship": "ΔP(ETH)_{t+15m} = beta * ΔP(BTC)_t",
        "direction": "lead_lag",
        "expected_time_horizon": "15m",
        "falsification_condition": "H0: Out-of-sample forward correlation <= 0 or net return after friction <= 0.",
        "minimum_sample_requirement": 30,
        "proposed_statistical_test": "permutation_test",
        "proposed_placebo_control": "time_shift_24h",
        "execution_dependency": "taker_l2_walk",
        "expected_friction_sensitivity": "medium",
        "capacity_dependency": 1000.0,
        "known_confounders": ["macro_announcements", "usd_dxy_volatility"],
        "lookahead_risk": "Strict zero-lookahead: leading market trigger strictly precedes evaluation window.",
        "confidence": 0.85,
        "input_signal": "5-minute return in BTC contract",
        "transformation": "standardized return > 2.0 sigma",
        "prediction": "ETH executable price moves in same direction by >= 25 bps",
        "horizon": "15 minutes",
        "cost_model": "Observed L2 ladder + 20 bps taker fee",
        "falsification_test": "Time-shifted placebo + reverse-direction test",
        "lineage_family_id": "fam_btc_eth_leadlag",
        "parameters": {"threshold": 2.0, "beta": 0.85},
    }


@pytest.fixture
def mean_reverting_series():
    """Generates synthetic mean-reverting OU series with known half-life."""
    rng = np.random.RandomState(42)
    n = 300
    theta = -0.15 # phi = 0.85, lambda ~= 0.1625, half_life ~= 4.26 steps
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = spread[t-1] + theta * spread[t-1] + rng.normal(0, 0.02)
    x = pd.Series(rng.normal(0.5, 0.05, n))
    y = pd.Series(spread + 1.2 * x.values)
    return x, y, pd.Series(spread)


# =============================================================================
# 1. SCHEMA VALIDATION & HYPOTHESIS FAMILIES
# =============================================================================

def test_structured_hypothesis_validation_success(valid_hypothesis_dict):
    """Verifies that a well-formed hypothesis conforms to schema."""
    hyp = StructuredHypothesis(**valid_hypothesis_dict)
    assert hyp.hypothesis_id == "hyp_btc_eth_leadlag_001"
    assert hyp.hypothesis_family == HypothesisFamily.CROSS_MARKET_LEAD_LAG
    assert hyp.version == 1
    assert hyp.status == HypothesisStatus.DISCOVERY
    assert hyp.confidence == 0.85 # Discovery prior only!


def test_structured_hypothesis_rejects_missing_falsification(valid_hypothesis_dict):
    """Verifies rejection of hypothesis without concrete falsification condition."""
    bad_dict = dict(valid_hypothesis_dict)
    bad_dict["falsification_condition"] = ""
    with pytest.raises(ValueError, match="concrete quantitative falsification condition"):
        StructuredHypothesis(**bad_dict)


def test_structured_hypothesis_rejects_missing_causal_mechanism(valid_hypothesis_dict):
    """Verifies rejection of hypothesis without causal mechanism."""
    bad_dict = dict(valid_hypothesis_dict)
    bad_dict["causal_mechanism"] = "too short"
    with pytest.raises(ValueError, match="explicit causal economic mechanism"):
        StructuredHypothesis(**bad_dict)


def test_seven_hypothesis_families_enumeration():
    """Ensures all 7 designated hypothesis families are present."""
    expected = {
        "exact_contract_arb",
        "resolution_arb",
        "conditional_stat_arb",
        "cross_market_lead_lag",
        "order_flow_microstructure",
        "event_conditional_stat_arb",
        "cross_venue_platform"
    }
    actual = {f.value for f in HypothesisFamily}
    assert actual == expected


# =============================================================================
# 2. LINEAGE TRACKING & MULTIPLE TESTING PENALTIES
# =============================================================================

def test_hypothesis_lineage_and_mutation_penalty(valid_hypothesis_dict):
    """Tests registration, mutation, and family testing penalty accumulation."""
    tracker = HypothesisLineageTracker()
    hyp1 = StructuredHypothesis(**valid_hypothesis_dict)
    tracker.register_hypothesis(hyp1)

    assert tracker.get_family_multiple_testing_penalty(hyp1.lineage_family_id) == 1

    # Mutate hypothesis
    hyp2 = tracker.mutate_hypothesis(
        parent_id=hyp1.hypothesis_id,
        new_hypothesis_id="hyp_btc_eth_leadlag_002",
        mutation_rationale="Adjusted threshold from 2.0 to 2.5 sigma based on prior exploratory run.",
        parameter_updates={"threshold": 2.5}
    )

    assert hyp2.version == 2
    assert hyp2.parent_hypothesis_id == hyp1.hypothesis_id
    assert tracker.get_family_multiple_testing_penalty(hyp1.lineage_family_id) == 2

    # Family p-value penalty: p = 0.03 * 2 = 0.06
    adj_p = tracker.compute_adjusted_family_p_value(0.03, hyp1.lineage_family_id)
    assert round(adj_p, 4) == 0.06


def test_mutation_without_rationale_rejected(valid_hypothesis_dict):
    """Ensures hypothesis mutation without detailed rationale is rejected."""
    tracker = HypothesisLineageTracker()
    hyp1 = StructuredHypothesis(**valid_hypothesis_dict)
    tracker.register_hypothesis(hyp1)

    with pytest.raises(LineageViolationError, match="detailed economic/empirical mutation_rationale"):
        tracker.mutate_hypothesis(
            parent_id=hyp1.hypothesis_id,
            new_hypothesis_id="hyp_btc_eth_leadlag_002",
            mutation_rationale="",
        )


# =============================================================================
# 3. PARAMETER FREEZING & SHA-256 IMMUTABILITY
# =============================================================================

def test_parameter_freezing_and_tampering_detection(valid_hypothesis_dict):
    """Verifies SHA-256 config hash generation and tampering detection."""
    tracker = HypothesisLineageTracker()
    hyp = StructuredHypothesis(**valid_hypothesis_dict)
    tracker.register_hypothesis(hyp)

    # Freeze
    frozen_hyp = tracker.freeze_hypothesis(hyp.hypothesis_id)
    assert frozen_hyp.status == HypothesisStatus.FROZEN
    assert frozen_hyp.config_hash is not None
    assert len(frozen_hyp.config_hash) == 64 # SHA-256 hex string
    assert tracker.verify_frozen_integrity(hyp.hypothesis_id) is True

    # Attempt to tamper with parameters after freezing
    frozen_hyp.parameters["threshold"] = 99.0
    assert tracker.verify_frozen_integrity(hyp.hypothesis_id) is False

    # Advancing stage with tampered config raises LineageViolationError and marks REJECTED
    with pytest.raises(LineageViolationError, match="Config hash mismatch"):
        tracker.advance_lifecycle_stage(hyp.hypothesis_id, HypothesisStatus.OUT_OF_SAMPLE_TESTED)
    assert frozen_hyp.status == HypothesisStatus.REJECTED


# =============================================================================
# 4. DETERMINISTIC STAT-ARB ENGINE (SPREAD, HEDGE RATIO, Z-SCORE)
# =============================================================================

def test_stat_arb_spread_and_in_sample_hedge_ratio(mean_reverting_series):
    """Verifies that beta is estimated in-sample and spread is correctly computed."""
    x, y, true_spread = mean_reverting_series
    engine = DeterministicStatArbEngine(SpreadModelConfig(min_observations=30))

    # Split train/test (60% / 40%)
    split = int(len(x) * 0.6)
    train_x, train_y = x.iloc[:split], y.iloc[:split]
    test_x, test_y = x.iloc[split:], y.iloc[split:]

    # In-sample OLS beta
    beta_ols, alpha_ols = engine.estimate_hedge_ratio(train_x, train_y, method="ols")
    assert 1.0 < beta_ols < 1.4 # True synthetic beta is 1.2

    # Robust Huber beta
    beta_huber, alpha_huber = engine.estimate_hedge_ratio(train_x, train_y, method="huber")
    assert 1.0 < beta_huber < 1.4

    # Robust Theil-Sen beta
    beta_ts, alpha_ts = engine.estimate_hedge_ratio(train_x, train_y, method="theil_sen")
    assert 1.0 < beta_ts < 1.4

    # Compute spread on test set using in-sample beta
    spread_test = engine.compute_spread(test_x, test_y, beta_ols, alpha_ols)
    assert len(spread_test) == len(test_x)
    assert spread_test.std() < test_y.std() # Spread variance should be less than raw Y variance


def test_standard_and_robust_mad_z_score():
    """Verifies rolling standard z-score and outlier-resistant robust MAD z-score."""
    engine = DeterministicStatArbEngine(SpreadModelConfig(rolling_window=30, min_observations=15))
    rng = np.random.RandomState(42)
    clean_data = pd.Series(rng.normal(0, 1.0, 100))
    
    # Introduce massive flash jump at t=50
    dirty_data = clean_data.copy()
    dirty_data.iloc[50] = 50.0

    z_std = engine.compute_z_score(dirty_data)
    z_mad = engine.compute_robust_mad_z_score(dirty_data)

    # For the outlier point itself at t=50:
    # Standard std explodes to ~9, so z_std[50] is ~5
    # Robust MAD is unaffected (~0.9), so z_mad[50] is ~37 (detecting the outlier much more sharply!)
    assert abs(z_mad.iloc[50]) > abs(z_std.iloc[50])


def test_mean_reversion_half_life_estimation(mean_reverting_series):
    """Verifies Ornstein-Uhlenbeck AR(1) half-life estimation."""
    _, _, true_spread = mean_reverting_series
    engine = DeterministicStatArbEngine()

    half_life, theta, p_val = engine.estimate_half_life(true_spread)
    assert theta < 0.0 # Mean reverting
    assert p_val < 0.01 # Statistically significant reversion
    assert 2.0 <= half_life <= 10.0 # True theoretical half life is ~4.3 steps

    # Random walk (non-mean-reverting) fails ADF stationarity test and has long half-life
    rng = np.random.RandomState(42)
    rw = pd.Series(np.cumsum(rng.normal(0, 1.0, 200)))
    hl_rw, theta_rw, _ = engine.estimate_half_life(rw)
    is_stat_rw, _, adf_p_rw = engine.test_stationarity_adf(rw)
    assert is_stat_rw is False
    assert adf_p_rw > 0.05
    assert not np.isfinite(hl_rw) or hl_rw > 15.0


def test_stationarity_and_cointegration(mean_reverting_series):
    """Verifies ADF stationarity and Engle-Granger cointegration."""
    x, y, true_spread = mean_reverting_series
    engine = DeterministicStatArbEngine()

    # True spread should be stationary
    is_stat, adf_stat, p_val = engine.test_stationarity_adf(true_spread)
    assert is_stat is True
    assert p_val < 0.05

    # Pair should be cointegrated
    is_coint, _, coint_p = engine.test_cointegration_engle_granger(x, y)
    assert is_coint is True
    assert coint_p < 0.05


def test_lead_lag_cross_correlation():
    """Verifies that lead-lag cross correlation identifies temporal ordering."""
    engine = DeterministicStatArbEngine()
    rng = np.random.RandomState(42)
    n = 200
    ret_x = pd.Series(rng.normal(0, 0.02, n))
    # Y lags X by exactly 2 periods: Y_t = 0.8 * X_{t-2} + noise
    ret_y = pd.Series(np.zeros(n))
    ret_y.iloc[2:] = 0.8 * ret_x.iloc[:-2].values + rng.normal(0, 0.005, n-2)

    profile = engine.compute_lead_lag_profile(ret_x, ret_y, max_lag=5)
    assert profile["optimal_lag"] == 2
    assert profile["max_correlation"] > 0.60
    assert profile["x_leads_y"] is True


# =============================================================================
# 5. MULTI-TIER EXECUTABILITY GATE
# =============================================================================

def test_executability_gate_quote_and_spread_checks():
    """Verifies rejection of empty books, crossed books, and wide spreads."""
    gate = ExecutabilityGate(max_allowable_spread_bps=300.0)

    # Empty book
    res_empty = gate.evaluate_execution(
        bids_raw=[], asks_raw=[], direction="BUY", order_size_usd=100.0, gross_expected_return_bps=50.0
    )
    assert res_empty.is_executable is False
    assert res_empty.rejection_stage == "QUOTE_UNAVAILABLE"

    # Crossed book (bid 0.55 >= ask 0.50)
    res_crossed = gate.evaluate_execution(
        bids_raw=[[0.55, 100]], asks_raw=[[0.50, 100]], direction="BUY", order_size_usd=50.0, gross_expected_return_bps=50.0
    )
    assert res_crossed.is_executable is False
    assert res_crossed.rejection_stage == "CROSSED_BOOK"

    # Wide spread (bid 0.40, ask 0.60 => spread 0.20 on 0.50 mid = 4000 bps > 300 bps limit)
    res_wide = gate.evaluate_execution(
        bids_raw=[[0.40, 500]], asks_raw=[[0.60, 500]], direction="BUY", order_size_usd=50.0, gross_expected_return_bps=50.0
    )
    assert res_wide.is_executable is False
    assert res_wide.rejection_stage == "WIDE_SPREAD"


def test_executability_gate_depth_and_zero_extrapolation():
    """Verifies that insufficient depth rejects order and capacity is never extrapolated."""
    gate = ExecutabilityGate()
    # Book only has 100 shares @ 0.50 = 50 USD total depth
    bids = [[0.49, 100]]
    asks = [[0.51, 100]]

    # Request order size 500 USD
    res = gate.evaluate_execution(
        bids_raw=bids, asks_raw=asks, direction="BUY", order_size_usd=500.0, gross_expected_return_bps=100.0
    )
    assert res.is_executable is False
    assert res.rejection_stage == "INSUFFICIENT_DEPTH"
    assert res.total_depth_available_usd <= 51.0
    assert res.capacity_limit_usd <= 51.0


def test_executability_gate_net_ev_rejection():
    """Verifies rejection of candidate with positive gross return but negative net EV."""
    gate = ExecutabilityGate(default_fee_bps=20.0, default_latency_penalty_bps=10.0)
    # Book with 0.50 bid and 0.52 ask (spread 2 cents = ~392 bps)
    # Half spread ~ 196 bps + 20 bps fee + 10 bps latency = 226 bps friction
    # Gross expected return = 100 bps
    # Net EV = 100 - 226 = -126 bps => MUST BE REJECTED
    bids = [[0.50, 2000]]
    asks = [[0.52, 2000]]

    res = gate.evaluate_execution(
        bids_raw=bids, asks_raw=asks, direction="BUY", order_size_usd=100.0, gross_expected_return_bps=100.0
    )
    assert res.is_executable is False
    assert res.rejection_stage == "NEGATIVE_NET_EV"
    assert res.net_return_bps < 0.0


def test_executability_gate_successful_fill():
    """Verifies that large enough gross return passes all execution tiers."""
    gate = ExecutabilityGate(default_fee_bps=20.0, default_latency_penalty_bps=5.0)
    # Tight book: 0.500 bid, 0.502 ask (spread = 0.002 = ~40 bps, half-spread = 20 bps)
    # Friction = 20 bps half-spread + 20 bps fee + 5 bps latency = 45 bps
    # Gross return = 150 bps => Net EV = ~105 bps => PASS
    bids = [[0.500, 5000]]
    asks = [[0.502, 5000]]

    res = gate.evaluate_execution(
        bids_raw=bids, asks_raw=asks, direction="BUY", order_size_usd=100.0, gross_expected_return_bps=150.0
    )
    assert res.is_executable is True
    assert res.rejection_stage is None
    assert res.net_return_bps > 50.0


# =============================================================================
# 6. ADVERSARIAL TESTING BATTERY & DIAGNOSTIC CLASSIFICATION
# =============================================================================

def test_adversarial_testing_battery(mean_reverting_series):
    """Verifies the 10-tier adversarial controls on genuine mean-reverting data."""
    x, y, _ = mean_reverting_series
    battery = AdversarialTestingBattery(random_seed=42)

    split = int(len(x) * 0.6)
    train_x, train_y = x.iloc[:split], y.iloc[:split]
    oos_x, oos_y = x.iloc[split:], y.iloc[split:]

    results = battery.run_full_adversarial_battery(
        train_x=train_x,
        train_y=train_y,
        oos_x=oos_x,
        oos_y=oos_y,
        base_gross_bps=80.0,
        base_friction_bps=25.0
    )

    assert "time_shift_placebo" in results
    assert "reverse_direction" in results
    assert "randomized_pair" in results
    assert "out_of_sample" in results
    assert "different_horizon" in results
    assert "liquidity_regime_stress" in results
    assert "higher_cost_stress" in results
    assert "latency_stress" in results
    assert "reduced_capacity" in results
    assert "feature_removal_ablation" in results
    assert "final_adversarial_verdict" in results

    # Time shift placebo must collapse
    assert results["time_shift_placebo"]["passed"] is True
    # Reverse direction must yield negative return
    assert results["reverse_direction"]["passed"] is True
    # Final verdict is typed AdversarialVerdict
    assert isinstance(results["final_adversarial_verdict"], AdversarialVerdict)


# =============================================================================
# 7. MACHINE-READABLE SCORECARD & INDEPENDENT CATEGORICAL AXES
# =============================================================================

def test_scorecard_evaluator_categorical_axes(valid_hypothesis_dict):
    """Verifies that scorecard produces independent categorical flags without numerical ranking."""
    hyp = StructuredHypothesis(**valid_hypothesis_dict)

    # Incomplete testing gives INCONCLUSIVE
    scorecard = ScorecardEvaluator.evaluate_scorecard(
        hypothesis=hyp,
        statistical_metrics=None,
        oos_results=None,
        adversarial_results=None,
        execution_results=None
    )
    assert scorecard.economic_mechanism == ScorecardStatus.PASS
    assert scorecard.statistical_evidence == ScorecardStatus.NOT_TESTED
    assert scorecard.verdict == ScorecardVerdict.INCONCLUSIVE

    # Failure in execution yields REJECTED
    scorecard_fail = ScorecardEvaluator.evaluate_scorecard(
        hypothesis=hyp,
        statistical_metrics={"sample_size": 100, "is_stationary": True},
        oos_results={"sample_size": 50, "passed": True},
        adversarial_results={"final_adversarial_verdict": AdversarialVerdict.PASS, "time_shift_placebo": {"passed": True}, "reverse_direction": {"passed": True}, "randomized_pair": {"passed": True}, "liquidity_regime_stress": {"passed": True}, "different_horizon": {"passed": True}, "feature_removal_ablation": {"passed": True}},
        execution_results={"is_executable": False, "rejection_stage": "NEGATIVE_NET_EV"},
        multiple_testing_fdr_passed=True,
        data_quality_clean=True,
    )
    assert scorecard_fail.execution_status == ScorecardStatus.FAIL
    assert scorecard_fail.verdict == ScorecardVerdict.REJECTED
    assert any("Execution gate rejected" in r for r in scorecard_fail.rejection_reasons)


# =============================================================================
# 8. ANTI-SYNTHETIC DATA GUARD
# =============================================================================

def test_anti_synthetic_guard_rejects_mock_tokens():
    """Ensures Phase10A5DataFeed rejects synthetic token IDs."""
    feed = Phase10A5DataFeed(db_path="data/prediction_market.duckdb")

    assert feed.is_token_genuine("0x1234567890abcdef1234567890abcdef12345678") is True
    assert feed.is_token_genuine("SYNTH_TOKEN_1") is False
    assert feed.is_token_genuine("SIM_TEST_MARKET") is False
    assert feed.is_token_genuine("MOCK_ASSET") is False

    status, df = feed.get_order_book_snapshots("SYNTH_POLY_01")
    assert status == ScorecardStatus.FAIL
    assert df.empty


# =============================================================================
# 9. STRICT AI VS DETERMINISTIC BOUNDARY ENFORCEMENT
# =============================================================================

def test_boundary_validator_rejects_order_placement(valid_hypothesis_dict):
    """Ensures AI proposal cannot submit orders or position sizes."""
    illegal_proposal = dict(valid_hypothesis_dict)
    illegal_proposal["place_order"] = True

    is_valid, reason = BoundaryValidator.validate_ai_proposal(illegal_proposal)
    assert is_valid is False
    assert "prohibited execution key" in reason

    with pytest.raises(BoundaryViolationError):
        BoundaryValidator.sanitize_and_construct(illegal_proposal)


def test_boundary_validator_rejects_profitability_claims(valid_hypothesis_dict):
    """Ensures AI proposal cannot claim guaranteed profit or proven alpha."""
    illegal_proposal = dict(valid_hypothesis_dict)
    illegal_proposal["causal_mechanism"] = "This is a proven alpha guaranteed profit mechanism."

    is_valid, reason = BoundaryValidator.validate_ai_proposal(illegal_proposal)
    assert is_valid is False
    assert "unauthorized profitability claim" in reason
