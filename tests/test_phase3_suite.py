"""Comprehensive unit tests for normalization, resolution analysis, EV engine, and falsification."""
import pytest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.normalization.schema import (
    Market,
    CanonicalMarket,
    Platform,
    MarketStatus,
    OpportunityClass,
    RelationshipType,
    ConstraintType,
    CandidateRelationship,
    OutputARelationshipDiscovery,
    OutputBEconomicConstraint,
    HypothesisVerdict,
)
from src.normalization.normalizer import MarketNormalizer
from src.llm.resolution_analyzer import ResolutionRuleAnalyzer
from src.strategies.ev_engine import MispricingEVEngine
from src.statistics.falsification_engine import HypothesisFalsificationEngine

def test_market_normalizer():
    normalizer = MarketNormalizer()
    market = Market(
        platform=Platform.POLYMARKET,
        market_id="test_1",
        event_id="evt_1",
        title="Will the Fed increase interest rates by December 31, 2026?",
        description="Market settles based on official FOMC rate announcement.",
        resolution_rules="Resolves based on Federal Reserve official announcement.",
        outcome_labels=["Yes", "No"],
        category="Macro",
        close_time=datetime(2026, 12, 31, 23, 59, 59)
    )
    canon = normalizer.normalize(market)
    assert "Federal Reserve / Fed" in canon.entities
    assert canon.event_type == "rate_decision"
    assert canon.geographic_scope == "United States"

def test_resolution_analyzer_structural_vs_novel():
    analyzer = ResolutionRuleAnalyzer()
    m_a = Market(
        platform=Platform.POLYMARKET,
        market_id="btc_88k",
        event_id="e1",
        title="Will the price of Bitcoin be above $88,000 on September 29?",
        description="Resolves via Binance 1-minute candle print.",
        resolution_rules="Binance print.",
        outcome_labels=["Yes", "No"],
        category="Crypto",
        close_time=datetime(2026, 9, 29, 23, 59)
    )
    m_b = Market(
        platform=Platform.POLYMARKET,
        market_id="btc_82k",
        event_id="e2",
        title="Will the price of Bitcoin be above $82,000 on September 29?",
        description="Resolves via Binance 1-minute candle print.",
        resolution_rules="Binance print.",
        outcome_labels=["Yes", "No"],
        category="Crypto",
        close_time=datetime(2026, 9, 29, 23, 59)
    )
    
    # Structural tautology on same date
    res_struct = analyzer.analyze_pair(m_a, m_b, opportunity_class=OpportunityClass.STRUCTURAL)
    assert res_struct.is_mathematically_guaranteed is True
    assert res_struct.prob_divergence == 0.0

    # Cross-domain relationship with oracle divergence
    m_c = Market(
        platform=Platform.POLYMARKET,
        market_id="oil_1",
        event_id="e3",
        title="Will Crude Oil hit $90 before October?",
        description="Settles via UMA optimistic oracle.",
        resolution_rules="UMA optimistic oracle consensus.",
        outcome_labels=["Yes", "No"],
        category="Commodities",
        close_time=datetime(2026, 10, 15, 23, 59)
    )
    res_novel = analyzer.analyze_pair(m_a, m_c, opportunity_class=OpportunityClass.SECOND_ORDER)
    assert res_novel.is_mathematically_guaranteed is False
    assert res_novel.prob_divergence >= 0.35
    assert res_novel.deadline_divergence is True

def test_ev_engine_friction_and_basis_risk():
    ev_engine = MispricingEVEngine(
        min_required_net_edge=0.015,
        taker_fee_rate=0.001,
        slippage_rate=0.002,
        default_spread=0.012
    )
    
    analyzer = ResolutionRuleAnalyzer()
    m_a = Market(platform=Platform.POLYMARKET, market_id="1", event_id="1", title="A", description="", resolution_rules="", outcome_labels=["Y","N"], category="")
    m_b = Market(platform=Platform.POLYMARKET, market_id="2", event_id="2", title="B", description="", resolution_rules="", outcome_labels=["Y","N"], category="")

    # Guaranteed structural arbitrage: 5% raw edge
    res_struct = analyzer.analyze_pair(m_a, m_b, opportunity_class=OpportunityClass.STRUCTURAL)
    res_struct.is_mathematically_guaranteed = True
    res_struct.prob_divergence = 0.0
    calc_struct = ev_engine.calculate_net_ev(raw_edge=0.05, resolution_analysis=res_struct, opportunity_class=OpportunityClass.STRUCTURAL)
    assert calc_struct["is_executable"] is True
    assert calc_struct["net_expected_value"] > 0.03 # 5% - ~1.8% friction = ~3.2%

    # Novel relationship with 35% divergence risk and 2% raw edge
    res_novel = analyzer.analyze_pair(m_a, m_b, opportunity_class=OpportunityClass.AI_SEMANTIC)
    calc_novel = ev_engine.calculate_net_ev(raw_edge=0.02, resolution_analysis=res_novel, opportunity_class=OpportunityClass.AI_SEMANTIC)
    assert calc_novel["is_executable"] is False
    assert calc_novel["net_expected_value"] < 0.0 # Wiped out by basis risk and friction

def test_falsifier_spurious_drift_filter():
    falsifier = HypothesisFalsificationEngine(min_net_edge_pp=0.015)
    
    # Generate two synthetic series with high raw level correlation but ZERO return correlation (spurious drift)
    dates = pd.date_range("2026-09-01", periods=100, freq="1h")
    trend = np.linspace(0.10, 0.90, 100)
    noise_a = np.random.normal(0, 0.02, 100)
    noise_b = np.random.normal(0, 0.02, 100)
    
    s_a = pd.Series(trend + noise_a, index=dates)
    s_b = pd.Series(trend + noise_b, index=dates)

    rel = CandidateRelationship(
        discovery=OutputARelationshipDiscovery(
            discovery_id="d1", market_a_id="a", market_b_id="b",
            opportunity_class=OpportunityClass.AI_SEMANTIC,
            relationship_type=RelationshipType.POSITIVE_ECONOMIC,
            economic_mechanism="Test mechanism", domain_cluster="Test",
            why_embedding_misses="", confidence=0.8
        ),
        constraint=OutputBEconomicConstraint(
            constraint_id="c1", discovery_id="d1", market_a_id="a", market_b_id="b",
            constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
            trigger_threshold_delta_a=0.03, expected_delta_b=0.02,
            lead_time_hours=4.0, testable_null_hypothesis="H0",
            mathematical_expression="ΔB >= 0.02"
        )
    )

    report = falsifier.test_hypothesis_walk_forward(rel, s_a, s_b)
    # Must NOT be tradeable! Must be killed as spurious or underpowered
    assert report.verdict != HypothesisVerdict.TRADEABLE

def test_epoch_clustering_and_dynamic_costs():
    from src.execution.fee_model import DynamicExecutionCostModel
    cost_model = DynamicExecutionCostModel()
    
    # 1. Test dynamic friction scaling with depth and price
    cost_liquid = cost_model.calculate_cost(price=0.50, order_size_usd=1000, liquidity_usd=150_000)
    cost_illiquid = cost_model.calculate_cost(price=0.50, order_size_usd=1000, liquidity_usd=3_000)
    assert cost_liquid["total_friction"] < cost_illiquid["total_friction"]
    assert cost_liquid["spread"] == 0.008
    assert cost_illiquid["spread"] == 0.050

    # 2. Test independent event epoch clustering: impulses within 72h should cluster to 1 epoch
    falsifier = HypothesisFalsificationEngine(epoch_window_hours=72.0)
    t0 = pd.Timestamp("2026-01-01 00:00:00")
    # Three impulses within 36 hours (all in same epoch)
    # Two impulses on day 10 (second epoch)
    timestamps = [
        t0,
        t0 + pd.Timedelta(hours=12),
        t0 + pd.Timedelta(hours=36),
        t0 + pd.Timedelta(days=10),
        t0 + pd.Timedelta(days=10, hours=6)
    ]
    delta_s = pd.Series([0.05, 0.08, 0.04, 0.06, 0.07], index=timestamps)
    epochs = falsifier._cluster_independent_epochs(pd.DatetimeIndex(timestamps), delta_s, epoch_window_hours=72.0)
    assert len(epochs) == 2 # Clustered into exactly 2 independent event epochs
    assert epochs[0] == t0 + pd.Timedelta(hours=12) # Peak impulse in first epoch (0.08)
    assert epochs[1] == t0 + pd.Timedelta(days=10, hours=6) # Peak impulse in second epoch (0.07)

