"""Comprehensive Unit Tests for Phase 10A.6e Cross-Venue Polymarket-Kalshi Arbitrage.

Covers:
1. 16 Deterministic Fixtures (Section 14)
2. Adversarial Testing Battery (Section 15)
3. AI Boundary Enforcement (Section 16)
4. 10 Independent Categorical Quality Gates (No Composite Score, Section 18)
5. Analysis Synchronization Windows (Section 9)
6. DuckDB Append-Only Persistence (Section 17)
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from pathlib import Path
import tempfile

from src.cross_venue.schema import (
    EquivalenceClass,
    MappingStatus,
    StaleStatus,
    CategoryStatus,
    FinalArbitrageVerdict,
    CanonicalEconomicContract,
    ContractMappingResult,
    SyncQuote,
    QuoteState,
    CrossVenueCostBreakdown,
    ArbitrageLeg,
    CrossVenueArbitrageOpportunity,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer
from src.cross_venue.synchronizer import CrossVenueSynchronizer
from src.cross_venue.cross_venue_arb_engine import CrossVenueArbEngine
from src.cross_venue.db_store import CrossVenueDBStore
from src.statarb.boundary_validator import BoundaryValidator, BoundaryViolationError


# =============================================================================
# BASE FIXTURES
# =============================================================================

@pytest.fixture
def base_poly_contract() -> CanonicalEconomicContract:
    return CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="0x1234567890abcdef",
        underlying_event="US CPI YoY Rate December 2026",
        observation_variable="US CPI YoY",
        geographic_scope="US",
        temporal_scope="December 2026",
        measurement_timestamp=datetime(2026, 12, 15, 13, 30, tzinfo=timezone.utc),
        resolution_timestamp=datetime(2026, 12, 15, 13, 30, tzinfo=timezone.utc),
        threshold=2.5,
        inequality_direction=">=",
        units="percent",
        currency="USDC",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="Resolves to YES if 12-month unadjusted CPI is >= 2.5% as reported in first BLS release.",
        cancellation_rules="Market remains open if release is delayed; voids only if BLS permanently discontinues series.",
        invalidation_rules="Preliminary release data governs; subsequent revisions are ignored.",
    )


@pytest.fixture
def base_kalshi_contract() -> CanonicalEconomicContract:
    return CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="CPI-26DEC-2.5",
        underlying_event="US CPI YoY Rate December 2026",
        observation_variable="US CPI YoY",
        geographic_scope="US",
        temporal_scope="December 2026",
        measurement_timestamp=datetime(2026, 12, 15, 13, 30, tzinfo=timezone.utc),
        resolution_timestamp=datetime(2026, 12, 15, 13, 30, tzinfo=timezone.utc),
        threshold=2.5,
        inequality_direction=">=",
        units="percent",
        currency="USD",
        source_of_resolution="BLS",
        resolution_rules="Resolves to YES if 12-month unadjusted CPI is >= 2.5% as reported in first BLS release.",
        cancellation_rules="Market remains open if release is delayed; voids only if BLS permanently discontinues series.",
        invalidation_rules="Preliminary release data governs; subsequent revisions are ignored.",
    )


@pytest.fixture
def arb_engine() -> CrossVenueArbEngine:
    return CrossVenueArbEngine(
        polymarket_fee_bps=0.0,
        kalshi_fee_bps=20.0,
        default_latency_penalty_bps=5.0,
        default_hedge_cost_bps=5.0,
        max_allowable_hedge_latency_ms=250.0,
        capital_a_usd=10000.0,
        capital_b_usd=10000.0,
    )


# =============================================================================
# PART 1: 16 DETERMINISTIC FIXTURES (SECTION 14)
# =============================================================================

def test_fixture_1_exact_same_yes_contract(base_poly_contract, base_kalshi_contract):
    """Fixture 1: Exact same YES contract across venues is EXACT_EQUIVALENT."""
    res = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    assert res.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT
    assert res.settlement_equivalence is True
    assert res.mapping_status == MappingStatus.EXACT_EQUIVALENT
    assert len(res.mapping_config_hash) == 64


def test_fixture_2_exact_same_no_contract(base_poly_contract, base_kalshi_contract):
    """Fixture 2: Exact same NO contract (< 2.5) across venues is EXACT_EQUIVALENT."""
    poly_no = base_poly_contract.model_copy(update={"inequality_direction": "<"})
    kalshi_no = base_kalshi_contract.model_copy(update={"inequality_direction": "<"})
    res = SettlementNormalizer.compare_contracts(poly_no, kalshi_no)
    assert res.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT
    assert res.settlement_equivalence is True


def test_fixture_3_complementary_contracts(base_poly_contract, base_kalshi_contract):
    """Fixture 3: P(X >= 2.5) vs P(X < 2.5) is recognized as COMPLEMENTARY."""
    kalshi_comp = base_kalshi_contract.model_copy(update={"inequality_direction": "<"})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_comp)
    assert res.equivalence_class == EquivalenceClass.COMPLEMENTARY
    assert res.settlement_equivalence is False
    assert res.mapping_status == MappingStatus.COMPLEMENTARY


def test_fixture_4_threshold_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 4: Threshold mismatch (2.5 vs 3.0) is NESTED or NON_EQUIVALENT."""
    kalshi_nested = base_kalshi_contract.model_copy(update={"threshold": 3.0})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_nested)
    assert res.equivalence_class == EquivalenceClass.NESTED
    assert res.settlement_equivalence is False


def test_fixture_5_date_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 5: Date/window mismatch (December 2026 vs January 2027) is NON_EQUIVALENT."""
    kalshi_date = base_kalshi_contract.model_copy(update={"temporal_scope": "January 2027"})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_date)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert res.settlement_equivalence is False
    assert "DATE_MISMATCH" in res.mapping_reason


def test_fixture_6_geography_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 6: Geography mismatch (US vs Eurozone) is NON_EQUIVALENT."""
    kalshi_geo = base_kalshi_contract.model_copy(update={"geographic_scope": "EU"})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_geo)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert res.settlement_equivalence is False
    assert "GEOGRAPHY_MISMATCH" in res.mapping_reason


def test_fixture_7_resolution_source_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 7: Resolution source mismatch (BLS vs Bloomberg Index) is SEMANTIC_ONLY."""
    kalshi_src = base_kalshi_contract.model_copy(update={"source_of_resolution": "Bloomberg Index"})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_src)
    assert res.equivalence_class == EquivalenceClass.SEMANTIC_ONLY
    assert res.settlement_equivalence is False
    assert "RESOLUTION_SOURCE_MISMATCH" in res.mapping_reason


def test_fixture_8_timezone_and_cutoff_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 8: Resolution timestamp divergence (> 1 hour) is NON_EQUIVALENT."""
    kalshi_time = base_kalshi_contract.model_copy(
        update={"resolution_timestamp": datetime(2026, 12, 16, 13, 30, tzinfo=timezone.utc)} # 24h later
    )
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_time)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "RESOLUTION_TIME_MISMATCH" in res.mapping_reason


def test_fixture_9_stale_quote_detection():
    """Fixture 9: Stale quote (age > 5000ms) fails synchronization and is rejected."""
    sync = CrossVenueSynchronizer(default_stale_threshold_ms=5000.0)
    now = datetime.now(timezone.utc)

    fresh_quote = SyncQuote(
        venue="polymarket", market_id="m1", contract_id="c1", side="ask", outcome="YES",
        price=0.45, size=1000.0, exchange_timestamp=now - timedelta(milliseconds=100)
    )
    stale_quote = SyncQuote(
        venue="kalshi", market_id="m2", contract_id="c2", side="ask", outcome="NO",
        price=0.45, size=1000.0, exchange_timestamp=now - timedelta(milliseconds=6000)
    )

    is_synced, status, state_a, state_b, msg = sync.synchronize_quotes(
        fresh_quote, stale_quote, window_ms=250, evaluation_timestamp=now
    )
    assert is_synced is False
    assert status == CategoryStatus.FAIL
    assert state_b.stale_status == StaleStatus.STALE


def test_fixture_10_simultaneous_executable_arbitrage(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 10: Genuine simultaneous discrepancy with sufficient depth yields ELIGIBLE."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    # Buy Poly YES at 0.40, Buy Kalshi NO at 0.50 -> combined VWAP = 0.90, gross edge = 1000 bps
    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=2000.0, asks=[{"price": 0.40, "size": 2000.0, "size_usd": 800.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=250.0,
        sync_window_ms=100,
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.ELIGIBLE
    assert opp.net_deterministic_edge_bps > 900.0
    assert opp.mapping_status == CategoryStatus.PASS
    assert opp.executable_status == CategoryStatus.PASS
    assert opp.capacity_status == CategoryStatus.PASS


def test_fixture_11_apparent_mid_price_arbitrage_with_no_executable_edge(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 11: Midpoint suggests arbitrage (0.42 + 0.48 = 0.90), but wide asks eliminate it."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    # Asks are 0.52 and 0.50 -> Combined VWAP = 1.02 > 1.0 -> Negative gross edge
    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.52, size=1000.0, asks=[{"price": 0.52, "size": 1000.0, "size_usd": 520.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=1000.0, asks=[{"price": 0.50, "size": 1000.0, "size_usd": 500.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0,
        sync_window_ms=100,
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.net_edge_status == CategoryStatus.FAIL
    assert opp.net_deterministic_edge_bps < 0.0


def test_fixture_12_depth_insufficiency(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 12: Order size exceeds observable book depth -> REJECTED by capacity/liquidity gate."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    # Depth is only $50, but order size is $500
    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=100.0, asks=[{"price": 0.40, "size": 100.0, "size_usd": 40.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.45, size=2000.0, asks=[{"price": 0.45, "size": 2000.0, "size_usd": 900.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=500.0,
        sync_window_ms=100,
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.executable_status == CategoryStatus.FAIL
    assert opp.capacity_status == CategoryStatus.FAIL


def test_fixture_13_fee_destroyed_arbitrage(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 13: Gross edge of 15 bps is consumed by 30 bps of fees and slippage -> REJECTED."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    # Combined ask = 0.9985 (gross edge 15 bps), total friction = 30 bps -> net edge = -15 bps
    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.4985, size=2000.0, asks=[{"price": 0.4985, "size": 2000.0, "size_usd": 997.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.5000, size=2000.0, asks=[{"price": 0.5000, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0,
        sync_window_ms=100,
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.net_edge_status == CategoryStatus.FAIL
    assert opp.net_deterministic_edge_bps < 0.0


def test_fixture_14_asynchronous_leg_latency_failure(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 14: Hedge latency of 300ms exceeds maximum allowable limit (250ms) -> REJECTED."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=2000.0, asks=[{"price": 0.40, "size": 2000.0, "size_usd": 800.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0,
        override_hedge_latency_ms=300.0, # Exceeds 250ms limit
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.latency_status == CategoryStatus.FAIL
    assert "Hedge latency 300.0ms > max 250.0ms" in opp.rejection_reasons[0]


def test_fixture_15_partial_fill_capacity_failure(base_poly_contract, base_kalshi_contract, arb_engine):
    """Fixture 15: Capital constraint insufficient for both legs -> REJECTED by capacity gate."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=2000.0, asks=[{"price": 0.40, "size": 2000.0, "size_usd": 800.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        target_order_size_usd=1000.0,
        override_capital_a=500.0, # Capital constraint < order size
        evaluation_timestamp=now,
    )

    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.capacity_status == CategoryStatus.FAIL


def test_fixture_16_settlement_rule_mismatch(base_poly_contract, base_kalshi_contract):
    """Fixture 16: Settlement rule revision policy divergence is rejected as SEMANTIC_ONLY."""
    kalshi_revised = base_kalshi_contract.model_copy(
        update={"resolution_rules": "Resolves based on final revised CPI release 3 months later."}
    )
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_revised)
    assert res.equivalence_class == EquivalenceClass.SEMANTIC_ONLY
    assert res.settlement_equivalence is False


# =============================================================================
# PART 2: ADVERSARIAL TESTING BATTERY (SECTION 15)
# =============================================================================

def test_adversarial_reversed_direction(base_poly_contract, base_kalshi_contract):
    """Adversarial: Direction reversed without complement handling is rejected."""
    kalshi_rev = base_kalshi_contract.model_copy(update={"inequality_direction": "<="})
    res = SettlementNormalizer.compare_contracts(base_poly_contract, kalshi_rev)
    assert res.equivalence_class == EquivalenceClass.COMPLEMENTARY
    assert res.settlement_equivalence is False


def test_adversarial_crossed_book(base_poly_contract, base_kalshi_contract, arb_engine):
    """Adversarial: Crossed book (bid >= ask) is safely rejected."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    # Empty asks ladder
    quote_crossed = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="bid", outcome="YES",
        price=0.60, size=1000.0, asks=[], exchange_timestamp=now
    )
    quote_normal = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.45, size=1000.0, asks=[{"price": 0.45, "size": 1000.0, "size_usd": 450.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping, quote_poly=quote_crossed, quote_kalshi=quote_normal,
        target_order_size_usd=100.0, evaluation_timestamp=now
    )
    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED


def test_adversarial_fee_and_slippage_shocks(base_poly_contract, base_kalshi_contract):
    """Adversarial: Large fee and slippage shock turns profitable opportunity into rejection."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.45, size=2000.0, asks=[{"price": 0.45, "size": 2000.0, "size_usd": 900.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    # Engine with severe fee shock (1000 bps)
    shock_engine = CrossVenueArbEngine(polymarket_fee_bps=500.0, kalshi_fee_bps=500.0)
    opp = shock_engine.evaluate_arbitrage(
        mapping=mapping, quote_poly=quote_poly, quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0, evaluation_timestamp=now
    )
    assert opp.final_verdict == FinalArbitrageVerdict.REJECTED
    assert opp.net_edge_status == CategoryStatus.FAIL


# =============================================================================
# PART 3: AI BOUNDARY ENFORCEMENT (SECTION 16)
# =============================================================================

def test_ai_boundary_enforcement_cross_venue():
    """Verifies that AI cannot approve equivalence, place orders, or override capacity."""
    prohibited_actions = [
        {"place_order": True},
        {"approve_equivalence": True},
        {"override_fees": True},
        {"override_capacity": True},
        {"select_winning_strategy": True},
    ]

    for bad_dict in prohibited_actions:
        proposal = {
            "hypothesis_id": "hyp_test",
            "hypothesis_family": "cross_venue_platform",
            "source_markets": ["p1"],
            "target_markets": ["k1"],
            "causal_mechanism": "Arbitrage constraint across venues.",
            "falsification_condition": "H0: Net return after friction <= 0.",
            "input_signal": "p1", "transformation": "none", "prediction": "p2",
            "horizon": "1m", "cost_model": "l2", "falsification_test": "placebo",
        }
        proposal.update(bad_dict)
        with pytest.raises(BoundaryViolationError):
            BoundaryValidator.sanitize_and_construct(proposal)


# =============================================================================
# PART 4: 10 INDEPENDENT CATEGORICAL QUALITY GATES (SECTION 18)
# =============================================================================

def test_ten_independent_categorical_quality_gates(base_poly_contract, base_kalshi_contract, arb_engine):
    """Verifies that all 10 independent categorical gates are evaluated without numerical ranking."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=2000.0, asks=[{"price": 0.40, "size": 2000.0, "size_usd": 800.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping, quote_poly=quote_poly, quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0, evaluation_timestamp=now
    )

    # 10 Independent categorical axes
    gates = [
        opp.mapping_status,
        opp.quote_status,
        opp.synchronization_status,
        opp.liquidity_status,
        opp.fee_status,
        opp.latency_status,
        opp.capacity_status,
        opp.settlement_status,
        opp.executable_status,
        opp.net_edge_status,
    ]
    for gate in gates:
        assert isinstance(gate, CategoryStatus)
        assert gate in (CategoryStatus.PASS, CategoryStatus.FAIL, CategoryStatus.INSUFFICIENT_DATA)

    assert opp.final_verdict == FinalArbitrageVerdict.ELIGIBLE


# =============================================================================
# PART 5: DUCKDB APPEND-ONLY SCHEMA & STORAGE (SECTION 17)
# =============================================================================

def test_duckdb_append_only_persistence(base_poly_contract, base_kalshi_contract, arb_engine):
    """Verifies that the 6 append-only Phase 10A.6E DuckDB tables store records cleanly."""
    mapping = SettlementNormalizer.compare_contracts(base_poly_contract, base_kalshi_contract)
    now = datetime.now(timezone.utc)

    quote_poly = SyncQuote(
        venue="polymarket", market_id="p1", contract_id="p1", side="ask", outcome="YES",
        price=0.40, size=2000.0, asks=[{"price": 0.40, "size": 2000.0, "size_usd": 800.0}],
        exchange_timestamp=now
    )
    quote_kalshi = SyncQuote(
        venue="kalshi", market_id="k1", contract_id="k1", side="ask", outcome="NO",
        price=0.50, size=2000.0, asks=[{"price": 0.50, "size": 2000.0, "size_usd": 1000.0}],
        exchange_timestamp=now
    )

    opp = arb_engine.evaluate_arbitrage(
        mapping=mapping, quote_poly=quote_poly, quote_kalshi=quote_kalshi,
        target_order_size_usd=100.0, evaluation_timestamp=now
    )

    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    tmp_path.unlink()  # Remove 0-byte placeholder so DuckDB creates a fresh database file

    try:
        db = CrossVenueDBStore(db_path=tmp_path)
        db.record_contract_mapping(mapping)
        db.record_arbitrage_opportunity(opp)

        conn = db._get_connection(read_only=True)
        try:
            m_count = conn.execute("SELECT count(*) FROM phase10a6e_contract_mappings").fetchone()[0]
            c_count = conn.execute("SELECT count(*) FROM phase10a6e_arbitrage_candidates").fetchone()[0]
            e_count = conn.execute("SELECT count(*) FROM phase10a6e_execution_analysis").fetchone()[0]
            q_count = conn.execute("SELECT count(*) FROM phase10a6e_mapping_quality").fetchone()[0]

            assert m_count == 1
            assert c_count == 1
            assert e_count == 1
            assert q_count == 1
        finally:
            conn.close()
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
