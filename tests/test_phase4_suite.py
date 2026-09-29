"""Unit tests for Phase 4: Multiple Testing FDR, Order Book Simulator, and Backtest Engine."""
import pytest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.normalization.schema import OrderSide, Platform
from src.statistics.multiple_testing import benjamini_hochberg_correction, PipelineFunnelAuditor
from src.execution.order_book import ReconstructedOrderBook, OrderBookSimulator
from src.backtest.engine import ArbitragePosition, WalkForwardBacktestEngine

def test_benjamini_hochberg_correction():
    # 5 hypotheses with various p-values
    # p = [0.001, 0.008, 0.03, 0.08, 0.40]
    # For q = 0.05:
    # rank 1: p=0.001 <= (1/5)*0.05 = 0.01 (True)
    # rank 2: p=0.008 <= (2/5)*0.05 = 0.02 (True)
    # rank 3: p=0.03  <= (3/5)*0.05 = 0.03 (True)
    # rank 4: p=0.08  <= (4/5)*0.05 = 0.04 (False)
    # rank 5: p=0.40  <= (5/5)*0.05 = 0.05 (False)
    p_vals = [0.001, 0.008, 0.03, 0.08, 0.40]
    res = benjamini_hochberg_correction(p_vals, fdr_q=0.05)
    assert res["significant_count"] == 3
    assert res["rejected"] == [True, True, True, False, False]
    assert res["q_values"][0] <= 0.05
    assert res["q_values"][3] > 0.05

def test_order_book_simulator_walk_and_capacity():
    # Create order book with $10,000 depth across levels
    book = ReconstructedOrderBook.from_market_snapshot(
        market_id="test_market",
        mid_price=0.50,
        spread=0.01,
        liquidity_usd=10_000.0
    )
    assert book.best_bid < 0.50
    assert book.best_ask > 0.50
    assert book.spread >= 0.005

    sim = OrderBookSimulator(default_latency_ms=250.0, taker_fee_rate=0.001)

    # 1. Test small fill within L1 depth
    fill_small = sim.walk_the_book(book, OrderSide.BUY, order_size_usd=500.0)
    assert fill_small["status"] == "FILLED"
    assert fill_small["fill_ratio"] == 1.0
    assert fill_small["levels_swept"] == 1
    assert fill_small["fee_usd"] == 500.0 * 0.001

    # 2. Test large fill sweeping multiple depth levels
    fill_large = sim.walk_the_book(book, OrderSide.BUY, order_size_usd=3_000.0)
    assert fill_large["status"] == "FILLED"
    assert fill_large["levels_swept"] > 1
    # Slippage should be strictly higher than small order
    assert fill_large["effective_slippage_pp"] > fill_small["effective_slippage_pp"]

    # 3. Test capacity calculator
    cap = sim.calculate_market_capacity(book, OrderSide.BUY, raw_edge_pp=0.05, min_required_net_edge_pp=0.015)
    assert cap["is_viable"] is True
    assert cap["max_deployable_capacity_usd"] >= 500.0

def test_arbitrage_position_and_capital_metrics():
    t_entry = datetime(2026, 1, 1, 12, 0)
    pos = ArbitragePosition(
        position_id="pos_1",
        constraint_id="c_1",
        market_a="m_a",
        market_b="m_b",
        entry_time=t_entry,
        side_a=OrderSide.SELL,
        side_b=OrderSide.BUY,
        fill_price_a=0.60,
        fill_price_b=0.40,
        size_usd_a=1000.0,
        size_usd_b=1000.0,
        entry_fees_usd=2.0,
        entry_slippage_usd=4.0
    )
    assert pos.deployed_capital == 2000.0

    # Close after 5 days when prices converge to 0.50 / 0.50
    # Leg A: sold at 0.60, bought back at 0.50 -> gross profit = (0.60 - 0.50) * (1000 / 0.60) = $166.67
    # Leg B: bought at 0.40, sold at 0.50 -> gross profit = (0.50 - 0.40) * (1000 / 0.40) = $250.00
    # Total gross = $416.67. Fees = $2.0 entry + $2.0 exit = $4.0. Net PnL = $412.67.
    t_exit = t_entry + timedelta(days=5)
    pos.close(exit_time=t_exit, price_a=0.50, price_b=0.50, exit_fees_usd=2.0)

    assert pos.is_open is False
    assert pos.holding_days == 5.0
    assert pos.realized_pnl > 400.0
    assert pos.roc > 0.20 # ~20.6% ROC on $2000 deployed
    assert pos.annualized_roc > pos.roc # Annualized ROC compounding


def test_pipeline_funnel_monotonicity():
    auditor = PipelineFunnelAuditor()

    # Valid monotonic progression
    s0 = ["c1", "c2", "c3", "c4", "c5"]
    s1 = ["c1", "c2", "c3", "c4"]
    s2 = ["c1", "c2", "c3"]
    s3 = ["c1", "c2"]
    s4 = ["c1"]
    s5 = ["c1"]
    s6 = ["c1"]
    s7 = ["c1"]
    s8 = []

    auditor.record_stage_candidates(0, s0)
    auditor.record_stage_candidates(1, s1)
    auditor.record_stage_candidates(2, s2)
    auditor.record_stage_candidates(3, s3)
    auditor.record_stage_candidates(4, s4)
    auditor.record_stage_candidates(5, s5)
    auditor.record_stage_candidates(6, s6)
    auditor.record_stage_candidates(7, s7)
    auditor.record_stage_candidates(8, s8)

    df = auditor.generate_report_table()
    counts = df["Surviving Count"].tolist()
    assert counts == [5, 4, 3, 2, 1, 1, 1, 1, 0]
    # Verify strict non-increasing
    for i in range(1, len(counts)):
        assert counts[i] <= counts[i - 1]

    # Test that subset violation raises AssertionError
    auditor_bad_subset = PipelineFunnelAuditor()
    auditor_bad_subset.record_stage_candidates(0, ["c1", "c2"])
    with pytest.raises(AssertionError, match="Funnel subset violation"):
        auditor_bad_subset.record_stage_candidates(1, ["c1", "c999"])  # c999 not in stage 0

    # Test that count monotonicity violation raises AssertionError
    auditor_bad_count = PipelineFunnelAuditor()
    auditor_bad_count.set_stage_count(0, 10)
    with pytest.raises(AssertionError, match="Funnel monotonicity violation"):
        auditor_bad_count.set_stage_count(1, 15)  # 15 > 10

