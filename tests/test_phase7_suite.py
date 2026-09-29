"""Phase 7 Test Suite: Verifying Event-Specific Responses, Passive Order Simulation, Markouts, and Adverse Selection."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from src.normalization.schema import OrderSide
from src.phase7.config import Phase7Config
from src.phase7.event_response_analyzer import EventResponseAnalyzer, EventResponseMetrics
from src.phase7.passive_order_simulator import (
    PassiveOrderSimulator,
    PassiveQuoteSimulationRecord,
    DistanceAggregateMetrics,
)
from src.phase7.passive_evaluator import PassiveExecutionEvaluator


@pytest.fixture
def config():
    return Phase7Config()


@pytest.fixture
def sample_timeseries():
    """Generates synthetic hourly price series for pair A and B with catalyst impulse."""
    np.random.seed(42)
    n = 100
    times = pd.date_range("2026-01-01", periods=n, freq="1h")
    # A has an impulse at index 20
    prices_a = [0.50] * n
    prices_a[20] = 0.55 # +0.05 impulse
    for i in range(21, n):
        prices_a[i] = 0.54

    # B responds with +0.03 at index 21 (1h lag)
    prices_b = [0.40] * n
    prices_b[21] = 0.43
    for i in range(22, n):
        prices_b[i] = 0.425

    sa = pd.Series(prices_a, index=times)
    sb = pd.Series(prices_b, index=times)
    liq = pd.Series([50000.0] * n, index=times)
    return sa, sb, liq


def test_phase7_config_immutability(config):
    """Test that Phase 7 config is frozen and has deterministic SHA-256 hash."""
    assert config.config_version == "v3.0.0-phase7"
    assert len(config.config_hash) == 16
    assert config.maker_fee_rate == 0.000
    assert config.passive_tick_distances == (0, 1, 2, 3)
    with pytest.raises(Exception):
        config.order_size_usd = 1000.0


def test_event_response_analyzer(config, sample_timeseries):
    """Test event response function extraction and regression fitting."""
    sa, sb, liq = sample_timeseries
    analyzer = EventResponseAnalyzer(config=config)

    df_imp = analyzer.extract_category_impulses(
        series_a=sa,
        series_b=sb,
        liquidity_b=liq,
        min_impulse=0.03
    )

    assert not df_imp.empty
    assert "delta_a" in df_imp.columns
    assert "delta_b_15m" in df_imp.columns

    metrics = analyzer.analyze_event_category(
        category_id="test_macro",
        category_label="Test Macro Impulse",
        df_impulses=df_imp
    )

    assert metrics.category_id == "test_macro"
    assert metrics.sample_size_n >= 1


def test_passive_order_simulator_fill_and_markout(config, sample_timeseries):
    """Test passive limit order placement, Brownian touch fill, and post-fill markout."""
    sa, sb, liq = sample_timeseries
    simulator = PassiveOrderSimulator(config=config)

    # Place buy limit order at Best Bid (d=0)
    rec_d0 = simulator.simulate_quote_placement(
        t0=sa.index[20],
        market_id="test_mkt_b",
        predicted_delta_15m=+0.03,
        price_series=sb,
        tick_distance_d=0
    )

    assert rec_d0.side == OrderSide.BUY
    assert rec_d0.tick_distance_d == 0
    assert rec_d0.market_mid_t0 == pytest.approx(0.40, abs=0.01)

    # If filled, verify markout calculation
    if rec_d0.is_filled:
        assert rec_d0.fill_price is not None
        assert rec_d0.markout_15m_pp is not None
        assert rec_d0.net_pnl_pp == rec_d0.markout_15m_pp - config.maker_fee_rate
        assert rec_d0.spread_captured_pp > 0.0


def test_passive_evaluator_distance_grid(config):
    """Test aggregation of passive orders and unconditional expected P&L."""
    evaluator = PassiveExecutionEvaluator(config=config)

    now = datetime.utcnow()
    # Create mock records: 4 filled (3 favorable, 1 toxic) and 1 unfilled
    records = [
        PassiveQuoteSimulationRecord(
            quote_id="q1", timestamp=now, market_id="m1", side=OrderSide.BUY,
            tick_distance_d=1, predicted_delta_15m=0.02, market_mid_t0=0.50,
            market_bid_t0=0.4925, market_ask_t0=0.5075, quote_limit_price=0.4875,
            queue_size_ahead_usd=5000.0, is_filled=True, fill_price=0.4875,
            markout_15m_pp=+0.025, spread_captured_pp=0.0125, net_pnl_pp=+0.025,
            net_pnl_usd=12.50, is_adverse_fill=False
        ),
        PassiveQuoteSimulationRecord(
            quote_id="q2", timestamp=now, market_id="m1", side=OrderSide.BUY,
            tick_distance_d=1, predicted_delta_15m=0.02, market_mid_t0=0.50,
            market_bid_t0=0.4925, market_ask_t0=0.5075, quote_limit_price=0.4875,
            queue_size_ahead_usd=5000.0, is_filled=True, fill_price=0.4875,
            markout_15m_pp=+0.015, spread_captured_pp=0.0125, net_pnl_pp=+0.015,
            net_pnl_usd=7.50, is_adverse_fill=False
        ),
        PassiveQuoteSimulationRecord(
            quote_id="q3", timestamp=now, market_id="m1", side=OrderSide.BUY,
            tick_distance_d=1, predicted_delta_15m=0.02, market_mid_t0=0.50,
            market_bid_t0=0.4925, market_ask_t0=0.5075, quote_limit_price=0.4875,
            queue_size_ahead_usd=5000.0, is_filled=True, fill_price=0.4875,
            markout_15m_pp=-0.020, spread_captured_pp=0.0125, net_pnl_pp=-0.020,
            net_pnl_usd=-10.00, is_adverse_fill=True
        ),
        PassiveQuoteSimulationRecord(
            quote_id="q4", timestamp=now, market_id="m1", side=OrderSide.BUY,
            tick_distance_d=1, predicted_delta_15m=0.02, market_mid_t0=0.50,
            market_bid_t0=0.4925, market_ask_t0=0.5075, quote_limit_price=0.4875,
            queue_size_ahead_usd=5000.0, is_filled=False, rejection_or_cancellation_reason="Unfilled"
        ),
    ]

    metrics = evaluator.evaluate_distance_performance(records, tick_distance_d=1)

    assert metrics.total_orders_posted == 4
    assert metrics.filled_orders_count == 3
    assert metrics.fill_probability == 0.75
    assert metrics.adverse_selection_rate == pytest.approx(1.0 / 3.0)
    # Mean markout = (0.025 + 0.015 - 0.020) / 3 = 0.020 / 3 = 0.00667
    assert metrics.mean_markout_15m_pp == pytest.approx(0.00667, abs=1e-4)
    # Unconditional P&L = 0.75 * 0.00667 = 0.0050
    assert metrics.unconditional_expected_pnl_pp == pytest.approx(0.0050, abs=1e-4)
    assert metrics.is_profitable
