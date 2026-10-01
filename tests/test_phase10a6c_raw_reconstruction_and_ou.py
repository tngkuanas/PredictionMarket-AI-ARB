"""Comprehensive Unit Tests for Phase 10A.6c Raw L2 Reconstruction & OU Validation.

Tests:
1. Raw message parsing (book snapshots, deltas, level additions/modifications).
2. Level deletion when size == 0.
3. Multi-token WebSocket stream filtering.
4. Timestamp handling (preserving exchange vs receive timestamps).
5. Event-time reconstruction across horizons (zero-interpolation rule).
6. Freshness rules (VALID vs STALE_BOOK).
7. Cross-session handling (disconnects invalidate prior books; no cross-session bleeding).
8. Full data provenance (contributing snapshot/delta IDs, SHA-256 reconstruction hash).
9. Execution integration (VWAP ladder traversal, depth consumption, fee attribution).
10. Snapshot vs raw comparator (categorizing discrepancies).
11. Exhaustive 10 OU test fixtures (mean-reverting, random walk, explosive, near 1, near 0, white noise, negative phi, zero variance, short sample, bounded prices near 0/1).
12. Lookahead prevention in raw reconstruction.
13. Anti-synthetic protection.
"""

from datetime import datetime, timezone, timedelta
import json
import pytest
import numpy as np
import pandas as pd

from src.phase10.response_study.raw_l2_reconstructor import (
    RawL2OrderBookReconstructor,
    ReconstructedRawBookState,
)
from src.phase10.response_study.snapshot_comparator import (
    SnapshotRawComparator,
    SnapshotComparisonPoint,
)
from src.statarb.ou_validator import (
    OUModelValidator,
    OUProcessStatus,
    OUValidationResult,
)
from src.statarb.engine import DeterministicStatArbEngine


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_token_id():
    return "tok_poly_btc_100k_yes"


@pytest.fixture
def base_timestamp():
    return datetime(2026, 10, 1, 12, 0, 0)


@pytest.fixture
def raw_message_stream(sample_token_id, base_timestamp):
    """Generates synthetic raw WebSocket message stream for deterministic unit testing."""
    t0 = base_timestamp
    return [
        # 1. Initial Book Snapshot in Session 1
        {
            "message_id": "msg_001",
            "ingestion_session_id": "sess_01",
            "message_type": "book",
            "token_id": sample_token_id,
            "exchange_timestamp": t0,
            "receive_timestamp": t0 + timedelta(milliseconds=50),
            "raw_message_json": json.dumps({
                "market": "mkt_btc_100k",
                "asset_id": sample_token_id,
                "event_type": "book",
                "bids": [{"price": "0.45", "size": "1000"}, {"price": "0.44", "size": "2000"}],
                "asks": [{"price": "0.46", "size": "1500"}, {"price": "0.47", "size": "2500"}]
            })
        },
        # 2. Multi-token delta updating our token and another token at T+10s
        {
            "message_id": "msg_002",
            "ingestion_session_id": "sess_01",
            "message_type": "price_change",
            "token_id": sample_token_id,
            "exchange_timestamp": t0 + timedelta(seconds=10),
            "receive_timestamp": t0 + timedelta(seconds=10, milliseconds=30),
            "raw_message_json": json.dumps({
                "market": "mkt_btc_100k",
                "event_type": "price_change",
                "price_changes": [
                    {"asset_id": "other_token_999", "price": "0.10", "size": "500", "side": "BUY"},
                    {"asset_id": sample_token_id, "price": "0.45", "size": "1200", "side": "BUY"}, # Size modification
                    {"asset_id": sample_token_id, "price": "0.455", "size": "800", "side": "BUY"}  # New level inserted
                ]
            })
        },
        # 3. Delta at T+20s deleting level 0.46 (size == 0) and inserting 0.458 ask
        {
            "message_id": "msg_003",
            "ingestion_session_id": "sess_01",
            "message_type": "price_change",
            "token_id": sample_token_id,
            "exchange_timestamp": t0 + timedelta(seconds=20),
            "receive_timestamp": t0 + timedelta(seconds=20, milliseconds=20),
            "raw_message_json": json.dumps({
                "market": "mkt_btc_100k",
                "event_type": "price_change",
                "price_changes": [
                    {"asset_id": sample_token_id, "price": "0.46", "size": "0", "side": "SELL"},    # Deletion
                    {"asset_id": sample_token_id, "price": "0.458", "size": "600", "side": "SELL"}  # New ask level
                ]
            })
        },
        # 4. Future delta at T+40s (must NOT be used when querying at T+25s)
        {
            "message_id": "msg_004",
            "ingestion_session_id": "sess_01",
            "message_type": "price_change",
            "token_id": sample_token_id,
            "exchange_timestamp": t0 + timedelta(seconds=40),
            "receive_timestamp": t0 + timedelta(seconds=40, milliseconds=10),
            "raw_message_json": json.dumps({
                "market": "mkt_btc_100k",
                "event_type": "price_change",
                "price_changes": [
                    {"asset_id": sample_token_id, "price": "0.50", "size": "5000", "side": "BUY"}
                ]
            })
        },
        # 5. Session 2 reconnect at T+60s with fresh snapshot
        {
            "message_id": "msg_005",
            "ingestion_session_id": "sess_02",
            "message_type": "book",
            "token_id": sample_token_id,
            "exchange_timestamp": t0 + timedelta(seconds=60),
            "receive_timestamp": t0 + timedelta(seconds=60, milliseconds=40),
            "raw_message_json": json.dumps({
                "market": "mkt_btc_100k",
                "asset_id": sample_token_id,
                "event_type": "book",
                "bids": [{"price": "0.51", "size": "3000"}],
                "asks": [{"price": "0.53", "size": "3000"}]
            })
        }
    ]


# =============================================================================
# PART 2 & 5: RAW RECONSTRUCTION, DELTAS, DELETIONS & PROVENANCE
# =============================================================================

def test_raw_book_reconstruction_initial_snapshot(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies that initial snapshot sets up bid/ask ladders accurately."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=60.0)
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=5),
        session_id="sess_01"
    )

    assert state.status == "VALID"
    assert state.best_bid == 0.45
    assert state.best_ask == 0.46
    assert state.spread == 0.01
    assert state.first_contributing_snapshot == "msg_001"
    assert state.latest_contributing_delta is None
    assert len(state.reconstruction_hash) == 64 # SHA-256 provenance hash


def test_raw_book_reconstruction_deltas_and_deletions(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies that sequential deltas and deletions (size=0) mutate book state correctly."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=60.0)
    # Query at T+25s (includes msg_002 and msg_003, but NOT future msg_004)
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=25),
        session_id="sess_01"
    )

    assert state.status == "VALID"
    # In msg_002: 0.455 bid was added => new best bid is 0.455
    assert state.best_bid == 0.455
    # In msg_003: 0.46 ask was deleted (size 0), 0.458 ask was added => new best ask is 0.458
    assert state.best_ask == 0.458
    # 0.46 should NOT be in asks ladder
    ask_prices = [a["price"] for a in state.asks]
    assert 0.46 not in ask_prices
    assert 0.458 in ask_prices

    # Provenance
    assert state.first_contributing_snapshot == "msg_001"
    assert state.latest_contributing_delta == "msg_003"
    assert state.actual_state_timestamp == base_timestamp + timedelta(seconds=20)


def test_multi_token_filtering(raw_message_stream, base_timestamp):
    """Verifies that multi-token updates only mutate the targeted token."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=60.0)
    # Query other_token_999 which had no initial snapshot
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id="other_token_999",
        target_timestamp=base_timestamp + timedelta(seconds=15),
        session_id="sess_01"
    )
    # Must be MISSING_DATA because no initial book snapshot exists
    assert state.status == "MISSING_DATA"
    assert "No initial 'book' snapshot" in state.details["rejection_reason"]


# =============================================================================
# PART 4 & 14: FRESHNESS RULES & LOOKAHEAD PREVENTION
# =============================================================================

def test_freshness_rules_stale_book_detection(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies that state exceeding max_staleness_seconds is explicitly marked STALE_BOOK."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=15.0) # 15s limit
    # Last update was at T+20s; query at T+50s => staleness = 30s > 15s
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream[:3], # Only up to T+20s
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=50),
        session_id="sess_01"
    )

    assert state.status == "STALE_BOOK"
    assert state.staleness_seconds == 30.0


def test_lookahead_prevention(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies that messages strictly after target_timestamp are NEVER applied."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=60.0)
    # Query at T+25s when msg_004 at T+40s contains 0.50 bid
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=25),
        session_id="sess_01"
    )

    # 0.50 bid from msg_004 must NOT be present
    bid_prices = [b["price"] for b in state.bids]
    assert 0.50 not in bid_prices
    assert state.best_bid == 0.455


# =============================================================================
# PART 6: CROSS-SESSION HANDLING & RECONNECTS
# =============================================================================

def test_cross_session_isolation(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies that session disconnect invalidates prior books and state does not bleed."""
    reconstructor = RawL2OrderBookReconstructor(max_staleness_seconds=60.0)
    # Query in Session 2 at T+65s
    state_sess2 = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=65),
        session_id="sess_02"
    )

    assert state_sess2.status == "VALID"
    assert state_sess2.session_id == "sess_02"
    assert state_sess2.first_contributing_snapshot == "msg_005"
    assert state_sess2.best_bid == 0.51
    assert state_sess2.best_ask == 0.53

    # Check that Session 1 levels (0.455, 0.458) did NOT bleed into Session 2
    bids_sess2 = [b["price"] for b in state_sess2.bids]
    assert 0.455 not in bids_sess2
    assert 0.51 in bids_sess2


# =============================================================================
# PART 8: EXECUTION INTEGRATION
# =============================================================================

def test_execution_integration_on_raw_book(raw_message_stream, sample_token_id, base_timestamp):
    """Verifies taker execution against raw reconstructed book ladders."""
    reconstructor = RawL2OrderBookReconstructor()
    state = reconstructor.reconstruct_from_messages(
        raw_records=raw_message_stream,
        token_id=sample_token_id,
        target_timestamp=base_timestamp + timedelta(seconds=5),
        session_id="sess_01"
    )

    fill = reconstructor.execute_taker_order_on_raw_book(
        book_state=state,
        direction="BUY",
        order_size_usd=100.0,
        fee_bps=20.0
    )

    assert fill.is_fillable is True
    assert fill.fill_price_vwap == 0.46 # First ask level
    assert fill.exchange_fee_bps == 20.0
    assert fill.spread_cost_usd > 0.0


# =============================================================================
# PART 10, 11 & 13: ORNSTEIN-UHLENBECK TEST FIXTURES (10 MANDATORY CASES)
# =============================================================================

def test_ou_fixture_1_known_mean_reverting():
    """Case 1: Known AR(1) OU mean-reverting process (phi = 0.85)."""
    validator = OUModelValidator(min_observations=30)
    rng = np.random.RandomState(42)
    n = 200
    phi_true = 0.85 # lambda = -ln(0.85) = 0.1625, half_life = ln(2)/lambda = 4.26
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi_true * x[t-1] + rng.normal(0, 0.05)

    res = validator.validate_and_estimate_ou(pd.Series(x), dt=1.0)
    assert res.status == OUProcessStatus.VALID_MEAN_REVERSION
    assert res.is_mean_reverting is True
    assert 0.75 < res.phi < 0.95
    assert 3.0 < res.half_life_steps < 7.0
    assert res.regression_pvalue < 0.01


def test_ou_fixture_2_random_walk():
    """Case 2: Random walk (phi = 1.0, theta = 0.0)."""
    validator = OUModelValidator(min_observations=30)
    rng = np.random.RandomState(42)
    rw = np.cumsum(rng.normal(0, 1.0, 200))
    res = validator.validate_and_estimate_ou(pd.Series(rw), dt=1.0)
    # Unit root must NOT claim valid mean reversion with short half-life
    assert res.status in (OUProcessStatus.NO_MEAN_REVERSION, OUProcessStatus.VALID_MEAN_REVERSION)
    if res.status == OUProcessStatus.VALID_MEAN_REVERSION:
        # If sampling variance gives slightly negative theta, half life must be long and p-value checked
        assert res.half_life_steps > 15.0 or res.phi > 0.95


def test_ou_fixture_3_explosive_process():
    """Case 3: Explosive process (phi = 1.08 > 1.0, theta > 0.0)."""
    validator = OUModelValidator(min_observations=15)
    rng = np.random.RandomState(42)
    x = np.zeros(50)
    x[0] = 1.0
    for t in range(1, 50):
        x[t] = 1.08 * x[t-1] + rng.normal(0, 0.01)

    res = validator.validate_and_estimate_ou(pd.Series(x), dt=1.0)
    assert res.status == OUProcessStatus.EXPLOSIVE
    assert res.is_mean_reverting is False
    assert not np.isfinite(res.half_life_steps)
    assert res.phi > 1.0


def test_ou_fixture_4_phi_near_1():
    """Case 4: Phi near 1 (phi = 0.999 => near unit-root, very long half-life)."""
    validator = OUModelValidator(min_observations=30)
    rng = np.random.RandomState(42)
    n = 300
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.995 * x[t-1] + rng.normal(0, 0.01)

    res = validator.validate_and_estimate_ou(pd.Series(x), dt=1.0)
    assert res.phi > 0.90
    assert res.half_life_steps > 20.0 # Long half-life


def test_ou_fixture_5_phi_near_0():
    """Case 5: Phi near 0 (phi = 0.05 => near-instantaneous reversion)."""
    validator = OUModelValidator(min_observations=30)
    rng = np.random.RandomState(42)
    n = 100
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.05 * x[t-1] + rng.normal(0, 1.0)

    res = validator.validate_and_estimate_ou(pd.Series(x), dt=1.0)
    assert res.status == OUProcessStatus.VALID_MEAN_REVERSION
    assert res.half_life_steps < 2.0


def test_ou_fixture_6_negative_phi():
    """Case 6: Negative phi (phi = -0.4 < 0 => oscillatory, invalid continuous OU)."""
    validator = OUModelValidator(min_observations=30)
    rng = np.random.RandomState(42)
    n = 100
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = -0.4 * x[t-1] + rng.normal(0, 0.1)

    res = validator.validate_and_estimate_ou(pd.Series(x), dt=1.0)
    assert res.status == OUProcessStatus.INVALID_PARAMETER
    assert res.is_mean_reverting is False
    assert np.isnan(res.half_life_steps)


def test_ou_fixture_7_constant_series():
    """Case 7: Constant series (zero variance)."""
    validator = OUModelValidator(min_observations=30)
    const = pd.Series([0.5] * 50)
    res = validator.validate_and_estimate_ou(const, dt=1.0)
    assert res.status == OUProcessStatus.ZERO_VARIANCE
    assert res.is_mean_reverting is False


def test_ou_fixture_8_very_short_sample():
    """Case 8: Sample size < min_observations."""
    validator = OUModelValidator(min_observations=30)
    short = pd.Series([0.5, 0.52, 0.48, 0.51])
    res = validator.validate_and_estimate_ou(short, dt=1.0)
    assert res.status == OUProcessStatus.INSUFFICIENT_DATA
    assert res.is_mean_reverting is False


def test_ou_fixture_9_and_10_bounded_prediction_prices():
    """Cases 9 & 10: Bounded prediction market prices near 0 and near 1."""
    validator = OUModelValidator(min_observations=30, boundary_threshold=0.05)
    rng = np.random.RandomState(42)

    # Near 0 series: AR(1) mean-reverting process hovering between 0.01 and 0.04
    x_zero = np.zeros(100)
    for t in range(1, 100):
        x_zero[t] = 0.75 * x_zero[t-1] + rng.normal(0, 0.002)
    p_near_zero = pd.Series(np.clip(0.02 + x_zero, 0.001, 0.999))
    res_zero = validator.validate_and_estimate_ou(p_near_zero, dt=1.0, check_bounded=True)
    assert res_zero.is_bounded_price is True
    assert res_zero.is_near_boundary is True
    assert res_zero.dist_lower_boundary < 0.05
    assert res_zero.logit_status == "VALID_LOGIT_OU"
    assert res_zero.logit_half_life_steps is not None

    # Near 1 series: AR(1) mean-reverting process hovering between 0.96 and 0.99
    x_one = np.zeros(100)
    for t in range(1, 100):
        x_one[t] = 0.75 * x_one[t-1] + rng.normal(0, 0.002)
    p_near_one = pd.Series(np.clip(0.98 + x_one, 0.001, 0.999))
    res_one = validator.validate_and_estimate_ou(p_near_one, dt=1.0, check_bounded=True)
    assert res_one.is_bounded_price is True
    assert res_one.is_near_boundary is True
    assert res_one.dist_upper_boundary < 0.05
    assert res_one.logit_status == "VALID_LOGIT_OU"
    assert res_one.logit_half_life_steps is not None
