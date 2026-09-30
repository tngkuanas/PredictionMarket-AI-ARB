"""Test suite for Phase 9 Pre-Live Adversarial Validation."""
import pytest
import numpy as np
import pandas as pd

from src.phase9.config import Phase9Config, FillModel
from src.phase9.sharpe_and_splits import SharpeAndSplitsEngine
from src.phase9.bootstrap_and_placebo import BootstrapAndPlaceboEngine
from src.phase9.microstructure_adversary import MicrostructureAdversaryEngine
from src.phase9.ai_perturbation_and_controls import AiPerturbationAndControlsEngine


@pytest.fixture
def config():
    return Phase9Config()


@pytest.fixture
def sample_phase9_data():
    np.random.seed(42)
    n = 100
    times = pd.date_range("2026-01-01", periods=n, freq="1h")
    prices_b = [0.40] * n
    prices_b[21] = 0.43
    for i in range(22, n):
        prices_b[i] = 0.425

    sb = pd.Series(prices_b, index=times)
    df_b = pd.DataFrame({"yes_mid": sb})
    token_snaps = {"tkn_b": df_b}
    mkt_to_tkn = {"mkt_b": "tkn_b"}

    events = [
        {
            "event_id": f"evt_{i:03d}",
            "timestamp": times[i % 80],
            "market_a_id": "mkt_a",
            "market_b_id": "mkt_b",
            "delta_a": 0.05,
            "predicted_delta_15m": 0.025
        }
        for i in range(40)
    ]
    return events, token_snaps, mkt_to_tkn


def test_phase9_config_integrity(config):
    assert config.config_version == "v5.0.0-phase9"
    assert len(config.config_hash) == 16
    assert config.bootstrap_iterations == 2000
    assert config.permutation_iterations == 2000
    assert config.candidate_quote_distance_d == 1


def test_three_way_splits(config, sample_phase9_data):
    events, snaps, m_map = sample_phase9_data
    engine = SharpeAndSplitsEngine(config=config)
    train, val, test = engine.partition_events_chronological(events)
    assert len(train) + len(val) + len(test) == len(events)
    assert len(train) == int(len(events) * config.train_dev_ratio)


def test_fill_models_comparison(config, sample_phase9_data):
    events, snaps, m_map = sample_phase9_data
    engine = MicrostructureAdversaryEngine(config=config)
    results = engine.evaluate_fill_models(events, snaps, m_map)
    assert len(results) == 3
    model_names = [r.model_name for r in results]
    assert FillModel.CONSERVATIVE_TRADE_THROUGH.value in model_names
    assert FillModel.MODERATE_BROWNIAN_BRIDGE.value in model_names
    assert FillModel.ADVERSARIAL_VOLUME_DEPTH.value in model_names


def test_placebo_generation(config, sample_phase9_data):
    events, _, _ = sample_phase9_data
    engine = BootstrapAndPlaceboEngine(config=config)
    p_events = engine.generate_placebo_events(events, "random_pairs", ["tkn_x", "tkn_y"])
    assert len(p_events) == len(events)
    assert p_events[0]["market_b_id"] in ["tkn_x", "tkn_y"]


def test_clock_integrity_audit(config, sample_phase9_data):
    events, snaps, m_map = sample_phase9_data
    engine = AiPerturbationAndControlsEngine(config=config)
    audit = engine.audit_clock_integrity(events, snaps, m_map)
    assert audit.clock_integrity_passed is True
    assert audit.lookahead_violations == 0
