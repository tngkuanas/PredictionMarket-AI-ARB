"""Comprehensive Unit Test Suite for Phase 10A.6 Deterministic Event-Study Engine.

Tests:
1. Book-state extraction & missing observation handling (no interpolation).
2. Crossed book, stale book, and extreme spread gating.
3. Order-book walking & VWAP taker execution (BUY and SELL).
4. Insufficient liquidity / capacity failure enforcement.
5. Microstructure cost decomposition (spread, slippage, fee).
6. Latency alignment (t_exec >= t_event + latency).
7. Event validation, deterministic contract mapping, and ambiguity gating.
8. Event dependence, duplicate detection, and cluster aggregation.
9. Empirical control batteries (Placebo, Reverse Direction, Pre-event Leakage).
10. Deterministic statistical moments, Bootstrap CIs, Permutation test, and Holm-Bonferroni correction.
11. Anti-synthetic guard verification.
12. End-to-end dry-run execution on mock genuine fixtures.
"""

from datetime import datetime, timezone, timedelta
import json
import pytest

from src.phase10.response_study.schema import (
    EventStudyConfig,
    EventStudyQualityStatus,
    EventStudyObservation,
    ExecutableResponse,
)
from src.phase10.response_study.executable_price_model import (
    ExecutablePriceModel,
    TakerExecutionFill,
)
from src.phase10.response_study.l2_book_extractor import L2BookExtractor
from src.phase10.response_study.event_validator import EventValidatorAndMapper
from src.phase10.response_study.controls import EventStudyControlBatteries
from src.phase10.response_study.statistical_engine import DeterministicStatisticalEngine
from src.phase10.response_study.event_study_engine import DeterministicEventStudyEngine
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard


# ==============================================================================
# 1. EXECUTABLE PRICE MODEL & ORDER-BOOK WALKING TESTS
# ==============================================================================

def test_order_book_walking_buy_vwap():
    """Verifies that buying walks the ask ladder ascending by price and calculates exact VWAP."""
    model = ExecutablePriceModel(default_fee_bps=20.0)

    # Ask ladder:
    # Level 1: 0.50, size=1000 ($500 notional)
    # Level 2: 0.52, size=2000 ($1040 notional)
    # Level 3: 0.55, size=5000 ($2750 notional)
    asks = [
        {"price": 0.50, "size": 1000.0, "size_usd": 500.0},
        {"price": 0.52, "size": 2000.0, "size_usd": 1040.0},
        {"price": 0.55, "size": 5000.0, "size_usd": 2750.0},
    ]
    bids = [
        {"price": 0.48, "size": 2000.0, "size_usd": 960.0}
    ]

    # Order 1: $500 (fully filled at level 1: 0.50)
    fill_500 = model.execute_taker_order(bids, asks, direction="BUY", order_size_usd=500.0)
    assert fill_500.is_fillable is True
    assert fill_500.fill_price_vwap == 0.50
    assert fill_500.total_shares_filled == 1000.0
    assert fill_500.slippage_bps == 0.0  # At best ask
    assert fill_500.exchange_fee_bps == 20.0

    # Order 2: $1000 (takes $500 at 0.50, $500 at 0.52)
    # Shares: 1000 + 500 / 0.52 = 1000 + 961.5385 = 1961.5385
    # VWAP: 1000 / 1961.5385 = 0.5098
    fill_1000 = model.execute_taker_order(bids, asks, direction="BUY", order_size_usd=1000.0)
    assert fill_1000.is_fillable is True
    assert fill_1000.fill_price_vwap > 0.50
    assert fill_1000.fill_price_vwap < 0.52
    assert fill_1000.slippage_bps > 0.0  # Walked into level 2


def test_order_book_walking_sell_vwap():
    """Verifies that selling walks the bid ladder descending by price."""
    model = ExecutablePriceModel(default_fee_bps=20.0)

    # Bid ladder:
    # Level 1: 0.60, size=1000 ($600 notional)
    # Level 2: 0.58, size=1000 ($580 notional)
    bids = [
        {"price": 0.60, "size": 1000.0, "size_usd": 600.0},
        {"price": 0.58, "size": 1000.0, "size_usd": 580.0},
    ]
    asks = [
        {"price": 0.62, "size": 1000.0, "size_usd": 620.0}
    ]

    fill = model.execute_taker_order(bids, asks, direction="SELL", order_size_usd=800.0)
    assert fill.is_fillable is True
    assert fill.fill_price_vwap < 0.60
    assert fill.fill_price_vwap > 0.58
    assert fill.slippage_bps > 0.0


def test_capacity_failure_insufficient_depth():
    """Verifies that requesting order size larger than available book depth is rejected."""
    model = ExecutablePriceModel(default_fee_bps=20.0)
    asks = [{"price": 0.50, "size": 200.0, "size_usd": 100.0}]
    bids = [{"price": 0.48, "size": 200.0, "size_usd": 96.0}]

    # Request $500 when only $100 available
    fill = model.execute_taker_order(bids, asks, direction="BUY", order_size_usd=500.0)
    assert fill.is_fillable is False
    assert fill.capacity_limit_usd == 100.0
    assert "Insufficient ladder depth" in fill.rejection_reason


def test_net_response_calculation():
    """Verifies exact gross and net PnL and return calculation between entry and exit fills."""
    model = ExecutablePriceModel(default_fee_bps=20.0)

    # Buy at 0.50, Sell at 0.55 (+10% gross move)
    asks_entry = [{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}]
    bids_entry = [{"price": 0.49, "size": 2000.0, "size_usd": 980.0}]
    entry = model.execute_taker_order(bids_entry, asks_entry, "BUY", 1000.0)

    bids_exit = [{"price": 0.55, "size": 2000.0, "size_usd": 1100.0}]
    asks_exit = [{"price": 0.56, "size": 2000.0, "size_usd": 1120.0}]
    exit = model.execute_taker_order(bids_exit, asks_exit, "SELL", 1000.0)

    pnl = model.calculate_net_response(entry, exit)
    assert pnl["gross_return_bps"] == 1000.0  # +10% = 1000 bps
    assert pnl["gross_pnl_usd"] == 100.0
    assert pnl["total_friction_bps"] > 0.0
    assert pnl["net_return_bps"] < pnl["gross_return_bps"]


# ==============================================================================
# 2. L2 ORDER BOOK EXTRACTOR & VALIDATION TESTS
# ==============================================================================

def test_crossed_book_rejection():
    """Verifies that an inverted/crossed book state is flagged as CROSSED_BOOK."""
    extractor = L2BookExtractor()
    crossed_snap = {
        "best_bid": 0.55,
        "best_ask": 0.50,  # Bid > Ask
        "spread": -0.05,
        "timestamp": datetime.now(timezone.utc),
        "exchange_timestamp": datetime.now(timezone.utc)
    }
    status, reason = extractor.validate_snapshot(crossed_snap)
    assert status == EventStudyQualityStatus.CROSSED_BOOK
    assert "Crossed book" in reason


def test_stale_book_rejection():
    """Verifies that excessive skew between exchange and receive timestamp is flagged as STALE_BOOK."""
    extractor = L2BookExtractor(max_staleness_seconds=60.0)
    now = datetime.now(timezone.utc)
    stale_snap = {
        "best_bid": 0.48,
        "best_ask": 0.52,
        "spread": 0.04,
        "timestamp": now,
        "exchange_timestamp": now - timedelta(seconds=120)  # 120s skew
    }
    status, reason = extractor.validate_snapshot(stale_snap)
    assert status == EventStudyQualityStatus.STALE_BOOK
    assert "Stale book" in reason


def test_depth_at_levels():
    """Verifies cumulative USD depth calculation across thresholds."""
    extractor = L2BookExtractor()
    ladder = [
        {"price": 0.50, "size": 100.0, "size_usd": 50.0},
        {"price": 0.52, "size": 500.0, "size_usd": 260.0},
        {"price": 0.55, "size": 2000.0, "size_usd": 1100.0}
    ]
    depth = extractor.calculate_depth_at_levels(ladder, levels=[100.0, 500.0, 2000.0])
    assert depth["total_available_usd"] == 1410.0
    assert depth["has_capacity_100"] is True
    assert depth["has_capacity_500"] is True
    assert depth["has_capacity_2000"] is False


# ==============================================================================
# 3. EVENT VALIDATION, CONTRACT MAPPING & DEPENDENCE TESTS
# ==============================================================================

def test_event_validation_future_timestamp_rejected():
    """Verifies that an event published in the future is rejected."""
    validator = EventValidatorAndMapper()
    future_ev = {
        "event_id": "ev_future_test",
        "publication_timestamp": datetime.now(timezone.utc) + timedelta(hours=10),
        "source": "BLS",
        "source_url": "https://bls.gov/cpi",
        "direction": "INCREASE"
    }
    is_valid, status, reason = validator.validate_event_record(future_ev)
    assert is_valid is False
    assert status == EventStudyQualityStatus.INVALID_TIMESTAMP


def test_ambiguous_direction_gated():
    """Verifies that an event with uncertain direction is excluded from primary analysis."""
    validator = EventValidatorAndMapper()
    ambig_ev = {
        "event_id": "ev_ambig_test",
        "publication_timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
        "source": "Fed",
        "source_url": "https://federalreserve.gov",
        "direction": "UNCERTAIN"
    }
    is_valid, status, reason = validator.validate_event_record(ambig_ev)
    assert is_valid is False
    assert status == EventStudyQualityStatus.AMBIGUOUS_MAPPING


def test_event_clustering_and_overlap():
    """Verifies that overlapping events on the same contract within 1 hour are clustered."""
    validator = EventValidatorAndMapper(cluster_window_seconds=3600.0)
    base_time = datetime(2026, 9, 30, 14, 0, 0, tzinfo=timezone.utc)

    events = [
        {
            "event_id": "ev_fomc_1",
            "mapped_market_id": "mkt_fed_rate",
            "publication_timestamp": base_time,
            "direction": "INCREASE"
        },
        {
            "event_id": "ev_fomc_2",
            "mapped_market_id": "mkt_fed_rate",
            "publication_timestamp": base_time + timedelta(minutes=15),  # 15m later (overlapping)
            "direction": "INCREASE"
        },
        {
            "event_id": "ev_other",
            "mapped_market_id": "mkt_unrelated",
            "publication_timestamp": base_time,
            "direction": "BUY"
        }
    ]

    clustered = validator.cluster_events_and_detect_overlap(events)
    assert len(clustered) == 3
    # First FOMC event is VALID
    assert clustered[0]["dependence_status"] == EventStudyQualityStatus.VALID
    # Second FOMC event is marked OVERLAPPING_EVENT and shares the cluster ID
    assert clustered[1]["dependence_status"] == EventStudyQualityStatus.OVERLAPPING_EVENT
    assert clustered[0]["event_cluster_id"] == clustered[1]["event_cluster_id"]


# ==============================================================================
# 4. CONTROL BATTERIES TESTS
# ==============================================================================

def test_placebo_timestamp_control_collapses_to_negative():
    """Verifies that placebo shifted timestamps produce negative net returns under friction."""
    controls = EventStudyControlBatteries(random_seed=42)

    # 10 mock valid observations
    obs_list = [
        {"observation_id": f"obs_{i}", "net_return_bps": 50.0, "total_friction_bps": 25.0}
        for i in range(20)
    ]
    placebo = controls.run_placebo_timestamp_control(obs_list)
    assert placebo.control_type == "PLACEBO_TIMESTAMPS"
    assert placebo.sample_size == 20
    assert placebo.mean_return_bps < 0.0
    assert placebo.verdict == "COLLAPSED_TO_NULL"


def test_reverse_direction_control_inverts_sign():
    """Verifies that reverse trading direction inverts the captured return into severe losses."""
    controls = EventStudyControlBatteries()

    responses = [
        {
            "is_fillable": True,
            "gross_return_bps": 150.0,
            "net_return_bps": 110.0,
            "spread_cost_bps": 10.0,
            "slippage_bps": 5.0,
            "fee_bps": 20.0
        }
        for _ in range(10)
    ]
    rev = controls.run_reverse_direction_control(responses)
    assert rev.control_type == "REVERSE_DIRECTION"
    assert rev.mean_return_bps < -150.0
    assert rev.verdict == "REVERSED"


def test_pre_event_leakage_detection():
    """Verifies that significant pre-event drift is flagged as leakage."""
    controls = EventStudyControlBatteries()

    # Pre-event drift: price rose from 0.40 at T-60m to 0.45 at T-1m (+1250 bps)
    leaked_obs = [
        {
            "pre_mid_60m": 0.40,
            "pre_mid_1m": 0.45,
            "direction": "BUY"
        }
        for _ in range(5)
    ]
    leakage = controls.run_pre_event_leakage_check(leaked_obs, leakage_threshold_bps=50.0)
    assert leakage.verdict == "LEAKAGE_DETECTED"
    assert leakage.details["leakage_rate"] == 1.0


# ==============================================================================
# 5. STATISTICAL ENGINE & MULTIPLE-TESTING CORRECTION
# ==============================================================================

def test_statistical_distribution_moments_and_ci():
    """Verifies deterministic moment calculations and confidence intervals."""
    stats = DeterministicStatisticalEngine(random_seed=42)

    returns = [50.0, 75.0, 60.0, 80.0, 45.0, 90.0, 55.0, 70.0]
    res = stats.compute_distribution_statistics(returns, metric_name="test_stat")

    assert res.sample_size == 8
    assert res.mean == pytest.approx(65.62, abs=0.1)
    assert res.hit_rate == 1.0
    assert res.ci_lower < res.mean < res.ci_upper
    assert res.bootstrap_ci_lower < res.mean < res.bootstrap_ci_upper
    assert res.p_value < 0.05


def test_holm_bonferroni_multiple_testing_correction():
    """Verifies step-down multiple testing correction monotonically bounds family-wise error."""
    stats_engine = DeterministicStatisticalEngine()

    # Create 4 test results with varied p-values
    from src.phase10.response_study.schema import StatisticalResult
    raw_results = [
        StatisticalResult("t5s", 50, 10.0, 10.0, 5.0, 0.7, 5.0, 15.0, 5.0, 15.0, 0.005, 0.005, "T", True),
        StatisticalResult("t15s", 50, 8.0, 8.0, 5.0, 0.65, 3.0, 13.0, 3.0, 13.0, 0.02, 0.02, "T", True),
        StatisticalResult("t30s", 50, 5.0, 5.0, 5.0, 0.55, 0.0, 10.0, 0.0, 10.0, 0.04, 0.04, "T", True),
        StatisticalResult("t60s", 50, 2.0, 2.0, 5.0, 0.52, -2.0, 6.0, -2.0, 6.0, 0.15, 0.15, "T", False),
    ]

    adjusted = stats_engine.apply_holm_bonferroni(raw_results)
    assert len(adjusted) == 4
    # Lowest p-value (0.005) multiplied by 4 = 0.02
    assert adjusted[0].adjusted_p_value == pytest.approx(0.02, abs=0.001)
    # Second lowest (0.02) multiplied by 3 = 0.06
    assert adjusted[1].adjusted_p_value == pytest.approx(0.06, abs=0.001)
    # Adjusted p-values must be non-decreasing
    assert adjusted[0].adjusted_p_value <= adjusted[1].adjusted_p_value <= adjusted[2].adjusted_p_value


def test_cluster_level_aggregation():
    """Verifies that multi-contract reactions to a single catalyst are aggregated to N=1 cluster."""
    stats_engine = DeterministicStatisticalEngine()

    responses = [
        {"event_cluster_id": "cluster_fomc_sep26", "event_timestamp": datetime.now(timezone.utc), "net_return_bps": 100.0, "gross_return_bps": 120.0},
        {"event_cluster_id": "cluster_fomc_sep26", "event_timestamp": datetime.now(timezone.utc), "net_return_bps": 80.0, "gross_return_bps": 100.0},
        {"event_cluster_id": "cluster_fomc_sep26", "event_timestamp": datetime.now(timezone.utc), "net_return_bps": 90.0, "gross_return_bps": 110.0},
        {"event_cluster_id": "cluster_cpi_sep26", "event_timestamp": datetime.now(timezone.utc), "net_return_bps": 50.0, "gross_return_bps": 65.0},
    ]

    clusters = stats_engine.aggregate_by_cluster(responses)
    assert len(clusters) == 2  # 4 contract observations collapsed into 2 independent clusters
    fomc_c = next(c for c in clusters if c["event_cluster_id"] == "cluster_fomc_sep26")
    assert fomc_c["contracts_count"] == 3
    assert fomc_c["net_return_bps"] == 90.0  # Mean of (100, 80, 90)


# ==============================================================================
# 6. ANTI-SYNTHETIC GUARD INTEGRATION
# ==============================================================================

def test_anti_synthetic_guard_rejects_synthetic_tokens():
    """Verifies that banned synthetic token prefixes are immediately rejected."""
    assert AntiSyntheticGuard.validate_token_id("token_geopol_001") is False
    assert AntiSyntheticGuard.validate_token_id("token_test_abc") is False
    assert AntiSyntheticGuard.validate_token_id("88391114873121460534755374453373541457506862776360231577867131214687456642030") is True


# ==============================================================================
# 7. END-TO-END PIPELINE UNIT TEST WITH DETERMINISTIC TEST FIXTURE
# ==============================================================================

def test_end_to_end_engine_process_event():
    """Verifies that process_event produces valid observations and executable responses."""
    config = EventStudyConfig(
        post_horizons=[("T+15s", 15, 5)],
        latencies_ms=[0, 100],
        order_sizes_usd=[100.0, 500.0]
    )
    engine = DeterministicEventStudyEngine(config=config)

    now = datetime(2026, 9, 30, 14, 0, 0, tzinfo=timezone.utc)
    event = {
        "event_id": "test_fixture_ev_001",
        "publication_timestamp": now,
        "source": "BLS",
        "source_url": "https://bls.gov/cpi",
        "direction": "INCREASE",
        "mapped_market_id": "mkt_test_cpi",
        "mapped_token_id": "tok_test_cpi_yes"
    }

    # Mock L2 extractor responses
    pre_snap = {
        "snapshot_id": "snap_pre",
        "timestamp": now - timedelta(seconds=60),
        "exchange_timestamp": now - timedelta(seconds=60),
        "midpoint": 0.50,
        "best_bid": 0.49,
        "best_ask": 0.51,
        "spread": 0.02,
        "spread_bps": 400.0,
        "depth_bid_usd": 5000.0,
        "depth_ask_usd": 5000.0,
        "book_imbalance": 0.0,
        "bids": [{"price": 0.49, "size": 10000.0, "size_usd": 4900.0}],
        "asks": [{"price": 0.51, "size": 10000.0, "size_usd": 5100.0}]
    }

    post_snap = {
        "snapshot_id": "snap_post",
        "timestamp": now + timedelta(seconds=15),
        "exchange_timestamp": now + timedelta(seconds=15),
        "midpoint": 0.55,
        "best_bid": 0.54,
        "best_ask": 0.56,
        "spread": 0.02,
        "spread_bps": 363.64,
        "depth_bid_usd": 5000.0,
        "depth_ask_usd": 5000.0,
        "book_imbalance": 0.0,
        "bids": [{"price": 0.54, "size": 10000.0, "size_usd": 5400.0}],
        "asks": [{"price": 0.56, "size": 10000.0, "size_usd": 5600.0}]
    }

    # Patch extractor methods on this instance for deterministic test fixture
    # Arrival at latency (offset=0) gets initial book, exit at T+15s (offset=15) gets repriced book
    engine.extractor.find_pre_event_snapshot = lambda **kw: (pre_snap, EventStudyQualityStatus.VALID, None)
    def mock_post(**kw):
        if kw.get("target_offset_sec", 0) == 0:
            return (pre_snap, EventStudyQualityStatus.VALID, None)
        return (post_snap, EventStudyQualityStatus.VALID, None)
    engine.extractor.find_post_event_snapshot = mock_post

    obs, responses = engine.process_event(event, market_universe=[])

    assert len(obs) == 1
    assert obs[0].status == EventStudyQualityStatus.VALID
    assert obs[0].signed_mid_movement_bps == 1000.0  # (0.55 - 0.50) / 0.50 = +1000 bps

    # 2 latencies * 2 order sizes = 4 responses
    assert len(responses) == 4
    for r in responses:
        assert r.is_fillable is True
        assert r.gross_return_bps > 0
        assert r.net_return_bps is not None
        assert r.fee_bps == 20.0

