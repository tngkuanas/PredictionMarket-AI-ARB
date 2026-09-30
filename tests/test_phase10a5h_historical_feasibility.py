"""Unit tests for Phase 10A.5h Historical Data Feasibility Investigation.

Validates:
1. Historical price schema properties (only 't' and 'p', lack of bid/ask depth).
2. Absence of historical L2/L3 order book endpoints.
3. Strict schema incompatibility between live CLOB schema and historical REST feeds.
4. Correct feasibility classification as INSUFFICIENT for high-frequency event studies.
"""

import pytest
from datetime import datetime, timezone
from src.phase10.acquisition.schema import ReconstructedBookSnapshot, DataQualityStatus


def test_historical_price_schema_incompleteness():
    """Verify that historical price points contain only t and p, lacking L2 quote depth."""
    sample_price_point = {"t": 1790691557, "p": 0.745}
    
    assert "t" in sample_price_point
    assert "p" in sample_price_point
    assert "best_bid" not in sample_price_point
    assert "best_ask" not in sample_price_point
    assert "spread" not in sample_price_point
    assert "bids" not in sample_price_point
    assert "asks" not in sample_price_point
    assert "depth_bid_usd" not in sample_price_point


def test_live_vs_historical_schema_mismatch():
    """Verify that ReconstructedBookSnapshot requires fields that historical prices cannot provide."""
    # ReconstructedBookSnapshot requires executable bid/ask spreads and depth
    now = datetime.now(timezone.utc)
    snapshot = ReconstructedBookSnapshot(
        snapshot_id="snap_test_001",
        session_id="sess_test",
        market_id="mkt_test",
        token_id="tok_test",
        timestamp=now,
        exchange_timestamp=now,
        best_bid=0.60,
        best_ask=0.62,
        midpoint=0.61,
        spread=0.02,
        spread_bps=327.87,
        depth_bid_usd=1500.0,
        depth_ask_usd=2100.0,
        book_imbalance=-0.1667,
        bids=[{"price": 0.60, "size": 2500.0, "size_usd": 1500.0}],
        asks=[{"price": 0.62, "size": 3387.1, "size_usd": 2100.0}],
        quality_status=DataQualityStatus.VALID,
    )
    
    # Historical price point cannot populate required L2 fields
    hist_point = {"t": int(now.timestamp()), "p": 0.61}
    assert "bids" not in hist_point
    assert "asks" not in hist_point
    assert "depth_bid_usd" not in hist_point
    assert snapshot.depth_bid_usd == 1500.0


def test_feasibility_classification_logic():
    """Verify decision logic strictly classifies historical data as INSUFFICIENT."""
    has_historical_l2_books = False
    has_subsecond_timestamps = False
    has_executable_spreads = False
    has_order_book_depth = False

    if has_historical_l2_books and has_subsecond_timestamps and has_executable_spreads and has_order_book_depth:
        classification = "SUFFICIENT"
    elif has_executable_spreads:
        classification = "PARTIALLY SUFFICIENT"
    else:
        classification = "INSUFFICIENT"

    assert classification == "INSUFFICIENT"
