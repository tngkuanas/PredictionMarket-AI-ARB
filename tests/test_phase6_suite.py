"""Phase 6 Test Suite: Verifying Strict Hypotheses, Stat-Arb Residuals, Trade Engine, and Decay Analyzer."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from src.normalization.schema import OpportunityClass, RelationshipType, OrderSide
from src.phase6.config import Phase6Config
from src.phase6.strict_hypotheses import StrictHypothesis, StrictHypothesisGenerator
from src.phase6.relative_value_stat_arb import RelativeValueStatArbModel, ResidualAnalysisResult
from src.phase6.trade_engine import Phase6TradeEngine, TradeDecision
from src.phase6.multi_horizon_decay import MultiHorizonDecayAnalyzer, HORIZON_LABELS


@pytest.fixture
def config():
    return Phase6Config()


@pytest.fixture
def sample_hypothesis():
    return StrictHypothesis(
        hypothesis_id="test_h6_001",
        market_a_id="mkt_a",
        market_b_id="mkt_b",
        market_a_title="Fed Rate Hike Q4",
        market_b_title="Bitcoin Dip Below 80k",
        opportunity_class=OpportunityClass.AI_SEMANTIC,
        relationship_type=RelationshipType.POSITIVE_ECONOMIC,
        causal_mechanism="Monetary contraction tightening liquidity, reducing crypto risk tolerance.",
        exact_leading_variable="Delta P(A)_1h >= +0.04",
        expected_response_function="Delta P(B) = 0.5 * Delta P(A)",
        expected_lag_distribution={"mode_hours": 0.25, "half_life_hours": 1.5, "max_lag_hours": 6.0},
        regime_conditions={"min_volatility_a": 0.015, "min_target_liquidity_usd": 15000.0, "max_spread_b": 0.03},
        invalidation_conditions=["Residual ADF non-stationary", "OU kappa <= 0"],
        min_economic_move=0.02,
        persistence_rationale="Attention latency between primary FOMC rate decision and derivative crypto books.",
        disappearance_catalysts="Direct algorithmic cross-hedging between macro and crypto books.",
        confidence_score=0.88
    )


@pytest.fixture
def synthetic_cointegrated_series():
    """Generates synthetic mean-reverting relative-value pair."""
    np.random.seed(42)
    n = 200
    times = pd.date_range("2026-01-01", periods=n, freq="1h")
    # A is a random walk
    walk_a = np.cumsum(np.random.normal(0, 0.02, n))
    pa = pd.Series(np.clip(0.50 + walk_a, 0.10, 0.90), index=times)
    # B is driven by A + stationary mean-reverting OU noise
    ou_noise = np.zeros(n)
    kappa = 0.35
    for t in range(1, n):
        ou_noise[t] = ou_noise[t-1] - kappa * ou_noise[t-1] + np.random.normal(0, 0.01)
    pb = pd.Series(np.clip(0.40 + 0.6 * walk_a + ou_noise, 0.05, 0.95), index=times)
    return pa, pb


def test_phase6_config_immutability(config):
    """Test that Phase 6 config is frozen and has deterministic SHA-256 hash."""
    assert config.config_version == "v2.0.0-phase6"
    assert len(config.config_hash) == 16
    with pytest.raises(Exception):
        config.min_net_edge_hurdle = 0.05


def test_strict_hypothesis_schema(sample_hypothesis):
    """Test that strict hypothesis validates all 9 causal dimensions."""
    assert sample_hypothesis.hypothesis_id == "test_h6_001"
    assert "liquidity" in sample_hypothesis.causal_mechanism.lower()
    assert sample_hypothesis.min_economic_move >= 0.02
    assert sample_hypothesis.expected_lag_distribution["half_life_hours"] == 1.5
    assert len(sample_hypothesis.invalidation_conditions) == 2


def test_relative_value_stat_arb_model(config, synthetic_cointegrated_series):
    """Test state-conditional model fitting, residual extraction, and OU mean reversion."""
    pa, pb = synthetic_cointegrated_series
    model = RelativeValueStatArbModel(config=config)
    df = model.build_feature_matrix(series_a=pa, series_b=pb)

    assert not df.empty
    assert "delta_a" in df.columns
    assert "volatility_a" in df.columns

    b_hat, beta, r_sq = model.fit_relative_value_model(df)
    assert len(beta) == 7
    assert r_sq > 0.30

    res_result = model.analyze_residuals_and_mean_reversion(df, z_threshold=1.0)
    assert res_result.is_stationary
    assert res_result.ou_kappa > 0.0
    assert res_result.reversion_half_life_hours < 48.0


def test_trade_construction_separation(config, sample_hypothesis, synthetic_cointegrated_series):
    """Test strict separation of Discovery, Forecast, Fair Value, Mispricing, and Hurdle Filter."""
    pa, pb = synthetic_cointegrated_series
    model = RelativeValueStatArbModel(config=config)
    df = model.build_feature_matrix(series_a=pa, series_b=pb)
    b_hat, beta, r_sq = model.fit_relative_value_model(df)
    res_result = model.analyze_residuals_and_mean_reversion(df)

    trade_engine = Phase6TradeEngine(config=config)
    features = {
        "price_a": float(pa.iloc[-1]),
        "delta_a": 0.03,
        "volatility_a": 0.02,
        "spread_b": 0.015,
        "time_to_expiry": 20.0,
        "regime_high_vol": 1.0
    }

    # Case 1: Market quote equals fair value -> No gross edge
    mid = float(b_hat.iloc[-1])
    decision = trade_engine.evaluate_opportunity(
        hypothesis=sample_hypothesis,
        model=model,
        residual_result=res_result,
        current_state_features=features,
        market_bid_b=mid - 0.01,
        market_ask_b=mid + 0.01,
        order_size_usd=500.0
    )
    assert not decision.is_executed
    assert decision.rejection_stage == "NO_GROSS_EDGE"

    # Case 2: Large dislocation exceeding hurdle -> Trade executed
    decision_big_edge = trade_engine.evaluate_opportunity(
        hypothesis=sample_hypothesis,
        model=model,
        residual_result=res_result,
        current_state_features=features,
        market_bid_b=mid - 0.15,
        market_ask_b=mid - 0.10, # Market severely underpriced relative to forecast
        order_size_usd=500.0
    )
    assert decision_big_edge.is_executed
    assert decision_big_edge.side == OrderSide.BUY
    assert decision_big_edge.net_edge >= config.min_net_edge_hurdle


def test_multi_horizon_decay_analyzer(config):
    """Test that signal trajectory records all 7 discrete horizons."""
    times = pd.date_range("2026-01-01", periods=100, freq="5min")
    # Simulate a price that spikes up at 15m and reverts by 24h
    prices = [0.50] * 100
    # At index 3 (15 min), price jumps to 0.55, then drifts back to 0.50
    prices[3] = 0.55
    prices[4] = 0.54
    prices[12] = 0.51 # 1 hour
    price_series = pd.Series(prices, index=times)

    analyzer = MultiHorizonDecayAnalyzer(config=config)
    obs_list = analyzer.evaluate_signal_trajectory(
        signal_id="sig_test_01",
        t0=times[0],
        side=OrderSide.BUY,
        price_series=price_series,
        total_friction=0.015
    )

    assert len(obs_list) == len(config.evaluation_horizons_hours)
    labels = [o.horizon_label for o in obs_list]
    assert "1m" in labels
    assert "15m" in labels
    assert "1h" in labels
    assert "24h" in labels

    decay_curve = analyzer.compute_decay_curve(obs_list)
    assert "15m" in decay_curve
    assert decay_curve["15m"].mean_gross_movement_pp == pytest.approx(0.05, abs=0.01)
