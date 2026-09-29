"""Phase 8 Test Suite: Verifying Latency Sweeps, Dynamic Cancellation, Queue Stress, and Prospective Engine."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from src.phase8.config import Phase8Config, CancellationPolicy
from src.phase8.latency_queue_stress import LatencyQueueStressTester, LatencySweepMetric, QueuePositionMetric
from src.phase8.dynamic_cancellation import DynamicCancellationExperiment, CancellationPolicyResult
from src.phase8.prospective_engine import ProspectiveStressEngine, ProspectiveRunSummary


@pytest.fixture
def config():
    return Phase8Config()


@pytest.fixture
def sample_stress_data():
    """Generates synthetic hourly price series for pair A and B with catalyst impulse."""
    np.random.seed(42)
    n = 100
    times = pd.date_range("2026-01-01", periods=n, freq="1h")
    prices_a = [0.50] * n
    prices_a[20] = 0.55
    for i in range(21, n):
        prices_a[i] = 0.54

    prices_b = [0.40] * n
    prices_b[21] = 0.43
    for i in range(22, n):
        prices_b[i] = 0.425

    sa = pd.Series(prices_a, index=times)
    sb = pd.Series(prices_b, index=times)
    df_b = pd.DataFrame({"yes_mid": sb})
    token_snaps = {"tkn_b": df_b}
    mkt_to_tkn = {"mkt_b": "tkn_b"}

    events = [
        {
            "event_id": "evt_001",
            "timestamp": times[20],
            "market_a_id": "mkt_a",
            "market_b_id": "mkt_b",
            "delta_a": 0.05,
            "predicted_delta_15m": 0.025
        }
    ]
    return events, token_snaps, mkt_to_tkn


def test_phase8_config_immutability(config):
    """Test that Phase 8 config is immutable with deterministic hash."""
    assert config.config_version == "v4.0.0-phase8"
    assert len(config.config_hash) == 16
    assert config.candidate_quote_distance_d == 1
    assert 0.0 in config.latency_sweep_ms
    assert 5000.0 in config.latency_sweep_ms
    assert config.min_prospective_events >= 100
    with pytest.raises(Exception):
        config.order_size_usd = 1000.0


def test_latency_sweep_execution(config, sample_stress_data):
    """Test latency sweep across grid."""
    events, snaps, m_map = sample_stress_data
    tester = LatencyQueueStressTester(config=config)

    results = tester.run_latency_sweep(
        event_impulses=events,
        token_snapshots=snaps,
        market_to_token=m_map,
        fixed_queue_ratio=0.75,
        quote_distance_d=1
    )

    assert len(results) == len(config.latency_sweep_ms)
    assert results[0].latency_ms == 0.0
    assert results[-1].latency_ms == 5000.0


def test_queue_stress_execution(config, sample_stress_data):
    """Test queue-position stress testing."""
    events, snaps, m_map = sample_stress_data
    tester = LatencyQueueStressTester(config=config)

    results = tester.run_queue_stress(
        event_impulses=events,
        token_snapshots=snaps,
        market_to_token=m_map,
        fixed_latency_ms=150.0,
        quote_distance_d=1
    )

    assert len(results) == len(config.queue_ahead_ratios)
    assert results[0].queue_ahead_ratio == 0.0
    assert results[-1].queue_ahead_ratio == 0.99


def test_dynamic_cancellation_policies(config, sample_stress_data):
    """Test dynamic cancellation simulation."""
    events, snaps, m_map = sample_stress_data
    exp = DynamicCancellationExperiment(config=config)

    res_never = exp.evaluate_cancellation_policy(
        policy=CancellationPolicy.NEVER_CANCEL,
        event_impulses=events,
        token_snapshots=snaps,
        market_to_token=m_map
    )
    assert res_never.policy == CancellationPolicy.NEVER_CANCEL

    res_rev = exp.evaluate_cancellation_policy(
        policy=CancellationPolicy.CANCEL_A_REVERSES,
        event_impulses=events,
        token_snapshots=snaps,
        market_to_token=m_map
    )
    assert res_rev.policy == CancellationPolicy.CANCEL_A_REVERSES


def test_prospective_engine_metrics(config, sample_stress_data):
    """Test prospective engine summary and institutional metrics."""
    events, snaps, m_map = sample_stress_data
    engine = ProspectiveStressEngine(config=config)

    summary, df_trades = engine.run_prospective_evaluation(
        events=events,
        token_snapshots=snaps,
        market_to_token=m_map,
        fixed_latency_ms=150.0,
        fixed_queue_ratio=0.75,
        quote_distance_d=1
    )

    assert summary.orders_placed_count == len(events)
    assert summary.max_capital_deployed_usd <= config.portfolio_capital_usd
    assert not df_trades.empty
