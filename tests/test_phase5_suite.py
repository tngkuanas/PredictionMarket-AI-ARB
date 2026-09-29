"""Unit tests for Phase 5: Live Prospective Shadow-Trading Engine."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import pandas as pd

from src.normalization.schema import (
    Market,
    Platform,
    MarketStatus,
    OrderSide,
    OpportunityClass,
    ShadowCandidate,
    ShadowOrder,
    ShadowFill,
)
from src.execution.order_book import ReconstructedOrderBook
from src.execution.shadow_trader import LiveShadowTrader, FrozenShadowTraderConfig
from src.db.duckdb_store import DuckDBStore


def test_frozen_shadow_config_immutability():
    config = FrozenShadowTraderConfig(
        frozen_min_edge_threshold=0.015,
        frozen_min_sample_epochs=15,
        frozen_latency_ms=250.0,
        paper_trading_only=True
    )
    assert config.frozen_min_edge_threshold == 0.015
    assert config.frozen_min_sample_epochs == 15
    assert config.paper_trading_only is True

    # Check immutability (frozen dataclass)
    with pytest.raises(Exception):
        config.frozen_min_edge_threshold = 0.05


def test_reconstructed_order_book_from_clob():
    clob_json = {
        "bids": [
            {"price": "0.48", "size": "1000"},
            {"price": "0.47", "size": "2000"}
        ],
        "asks": [
            {"price": "0.52", "size": "1500"},
            {"price": "0.53", "size": "2500"}
        ]
    }
    book = ReconstructedOrderBook.from_clob_order_book("test_mkt", clob_json)
    assert book.best_bid == 0.48
    assert book.best_ask == 0.52
    assert round(book.spread, 4) == 0.04
    assert len(book.bids) == 2
    assert len(book.asks) == 2


def test_shadow_trader_evaluation_and_rejection_logic():
    # Mock client and DB
    mock_client = MagicMock()
    mock_db = MagicMock()

    config = FrozenShadowTraderConfig(
        frozen_min_edge_threshold=0.015,
        frozen_min_sample_epochs=15,
        paper_trading_only=True
    )
    trader = LiveShadowTrader(config=config, client=mock_client, db=mock_db)

    # 1. Test structural ladder inversion detection
    t0 = datetime(2026, 9, 29, 12, 0)
    mkt_a = Market(
        platform=Platform.POLYMARKET,
        market_id="mkt_btc_90k",
        event_id="ev_btc",
        title="Will Bitcoin reach $90k?",
        description="",
        resolution_rules="",
        outcome_labels=["Yes", "No"],
        category="crypto",
        clob_token_ids=["tok_90k"]
    )
    mkt_b = Market(
        platform=Platform.POLYMARKET,
        market_id="mkt_btc_80k",
        event_id="ev_btc",
        title="Will Bitcoin reach $80k?",
        description="",
        resolution_rules="",
        outcome_labels=["Yes", "No"],
        category="crypto",
        clob_token_ids=["tok_80k"]
    )

    # Case A: Monotonic order preserved (P(90k) = 0.30, P(80k) = 0.60) -> No inversion
    mock_client.fetch_order_book.side_effect = [
        {"bids": [{"price": "0.29", "size": "100"}], "asks": [{"price": "0.31", "size": "100"}]},
        {"bids": [{"price": "0.59", "size": "100"}], "asks": [{"price": "0.61", "size": "100"}]}
    ]
    candidates = trader._evaluate_structural_ladders([mkt_a, mkt_b], t0)
    assert len(candidates) == 1
    assert candidates[0].status == "FILTERED_OUT"
    assert candidates[0].rejection_reason == "NO_MONOTONIC_INVERSION_OBSERVED"

    # Case B: Inversion observed (P(90k) = 0.70 > P(80k) = 0.50 + 0.015)
    mock_client.fetch_order_book.side_effect = [
        {"bids": [{"price": "0.69", "size": "100"}], "asks": [{"price": "0.71", "size": "100"}]},
        {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "100"}]}
    ]
    candidates_inv = trader._evaluate_structural_ladders([mkt_a, mkt_b], t0)
    assert len(candidates_inv) == 1
    assert candidates_inv[0].status == "CANDIDATE_ACTIVE"
    assert candidates_inv[0].raw_edge > 0.015


def test_shadow_order_execution_simulation():
    mock_client = MagicMock()
    mock_db = MagicMock()
    config = FrozenShadowTraderConfig(paper_trading_only=True)
    trader = LiveShadowTrader(config=config, client=mock_client, db=mock_db)

    cand = ShadowCandidate(
        candidate_id="cand_test",
        t0_timestamp=datetime.utcnow(),
        market_id="mkt_1",
        token_id="tok_1",
        title="Test Opportunity",
        opportunity_class=OpportunityClass.STRUCTURAL,
        predicted_fair_value=0.60,
        market_mid_price=0.50,
        raw_edge=0.10,
        frozen_min_edge_threshold=0.015,
        status="CANDIDATE_ACTIVE"
    )

    mock_client.fetch_order_book.return_value = {
        "bids": [{"price": "0.49", "size": "1000"}],
        "asks": [{"price": "0.51", "size": "1000"}]
    }

    order, fill = trader._execute_shadow_order(cand, datetime.utcnow())
    assert order is not None
    assert order.status == "FILLED"
    assert order.side == OrderSide.BUY
    assert fill is not None
    assert fill.size_usd == 500.0
    assert fill.fee_usd > 0.0
    assert fill.fill_price >= 0.51 # Walked ask side


def test_evaluate_prospective_binned_and_three_layer():
    mock_client = MagicMock()
    mock_db = MagicMock()
    config = FrozenShadowTraderConfig(paper_trading_only=True)
    trader = LiveShadowTrader(config=config, client=mock_client, db=mock_db)

    # Return candidates across different bins
    df_cands = pd.DataFrame([
        {"candidate_id": "c1", "token_id": "tok1", "market_mid_price": 0.50, "predicted_fair_value": 0.51, "target_timestamp": datetime.utcnow()}, # +2.0%
        {"candidate_id": "c2", "token_id": "tok2", "market_mid_price": 0.50, "predicted_fair_value": 0.52, "target_timestamp": datetime.utcnow()}, # +4.0%
        {"candidate_id": "c3", "token_id": "tok3", "market_mid_price": 0.50, "predicted_fair_value": 0.54, "target_timestamp": datetime.utcnow()}, # +8.0%
        {"candidate_id": "c4", "token_id": "tok4", "market_mid_price": 0.50, "predicted_fair_value": 0.60, "target_timestamp": datetime.utcnow()}, # +20.0%
    ])
    mock_db.get_shadow_candidates.return_value = df_cands

    # Return current prices flat at 0.50
    mock_client.fetch_order_book.return_value = {
        "bids": [{"price": "0.49", "size": "1000"}],
        "asks": [{"price": "0.51", "size": "1000"}]
    }

    res = trader.evaluate_prospective_outcomes()
    assert res["evaluated_candidates"] == 4
    assert res["raw_prediction_realization_gap_pp"] < 0 # Negative gap
    assert "three_layer_decomposition" in res
    assert "binned_analysis" in res
    assert len(res["binned_analysis"]) == 5 # <1.5%, 1.5-3%, 3-5%, 5-10%, >10%

