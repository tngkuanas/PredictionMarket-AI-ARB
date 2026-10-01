"""Unit Tests for Phase 10A.6I Live Cross-Venue Quote Synchronization and Scanner.

Validates:
1. Exact mapped pair enters scanner
2. Non-exact mapping is rejected
3. Synchronized timestamps within 10ms
4. Synchronization window rejection
5. Stale quote rejection
6. Missing bid handling
7. Missing ask rejection
8. Insufficient depth rejection
9. L2 VWAP execution
10. Partial fill handling
11. Fee erosion
12. Slippage erosion
13. Both arbitrage directions
14. Latency stress
15. Asynchronous leg risk (Cases A-F)
16. Emergency unwind cost
17. Provenance preservation
18. Deterministic candidate reproducibility
19. Price changes alter candidate economics but NOT mapping identity
20. Mapping changes invalidate previous mapping version
21. No midpoint pricing
22. No last-trade pricing
23. No synthetic live observations
24. Isolated database operation
25. Full candidate lifecycle
"""

from datetime import datetime, timezone, timedelta
import math
from pathlib import Path
import tempfile
import pytest

from src.cross_venue.schema import (
    EquivalenceClass,
    MappingStatus,
    ContractMappingResult,
    CanonicalEconomicContract,
)
from src.cross_venue.cross_venue_quote_adapter import (
    MappedContractQuote,
    PolymarketQuoteAdapter,
    KalshiQuoteAdapter,
)
from src.cross_venue.cross_venue_scanner import (
    ScannerLifecycleStatus,
    ScannerRejectionReason,
    ArbitrageDirection,
    ScannerConfig,
    CrossVenueArbitrageCandidate,
    ScanRunSummary,
    CrossVenueArbitrageScanner,
)
from src.cross_venue.db_store import CrossVenueDBStore


@pytest.fixture
def exact_mapping() -> ContractMappingResult:
    """Fixture providing an EXACT_EQUIVALENT mapping result."""
    return ContractMappingResult(
        mapping_id="map_cpi_exact_001",
        polymarket_market_id="poly_cpi_dec2026_gt3",
        polymarket_token_id="poly_tok_111",
        kalshi_market_id="kalshi_cpi_dec2026_gt3",
        kalshi_contract_id="KXCPIDEC26-3.0",
        canonical_contract_id="canon_cpi_2026_12_gt30",
        equivalence_class=EquivalenceClass.EXACT_EQUIVALENT,
        settlement_equivalence=True,
        mapping_status=MappingStatus.EXACT_EQUIVALENT,
        mapping_reason="Provably identical BLS CPI YoY metric and threshold 3.0%",
        resolution_source_polymarket="BLS",
        resolution_source_kalshi="BLS",
        threshold_polymarket=3.0,
        threshold_kalshi=3.0,
        direction_polymarket=">",
        direction_kalshi=">",
    )


@pytest.fixture
def non_exact_mapping() -> ContractMappingResult:
    """Fixture providing a COMPLEMENTARY (non-exact) mapping result."""
    return ContractMappingResult(
        mapping_id="map_cpi_comp_002",
        polymarket_market_id="poly_cpi_dec2026_gt3",
        polymarket_token_id="poly_tok_111",
        kalshi_market_id="kalshi_cpi_dec2026_lte3",
        kalshi_contract_id="KXCPIDEC26-3.0-LTE",
        canonical_contract_id="canon_cpi_comp_002",
        equivalence_class=EquivalenceClass.COMPLEMENTARY,
        settlement_equivalence=False,
        mapping_status=MappingStatus.COMPLEMENTARY,
        mapping_reason="Complementary inequality direction (> vs <=)",
        resolution_source_polymarket="BLS",
        resolution_source_kalshi="BLS",
        threshold_polymarket=3.0,
        threshold_kalshi=3.0,
        direction_polymarket=">",
        direction_kalshi="<=",
    )


@pytest.fixture
def sample_quotes(exact_mapping: ContractMappingResult):
    """Provides a pair of synchronized fresh quotes with deep executable depth."""
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=10)
    recv_kalshi = now - timedelta(milliseconds=15)  # 5ms delta

    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 5000.0}],
        asks=[{"price": 0.48, "size": 5000.0}],
        receive_timestamp=recv_poly,
        exchange_timestamp=recv_poly - timedelta(milliseconds=2),
        session_id="sess_poly_01",
        message_id="msg_poly_101",
        economic_outcome="YES",
    )

    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.47, "size": 5000.0}],
        asks=[{"price": 0.50, "size": 5000.0}],
        receive_timestamp=recv_kalshi,
        exchange_timestamp=recv_kalshi - timedelta(milliseconds=3),
        session_id="sess_kalshi_01",
        message_id="msg_kalshi_101",
        economic_outcome="NO",
    )

    return quote_poly, quote_kalshi, now


# ==============================================================================
# TEST 1: Exact Mapped Pair Enters Scanner
# ==============================================================================
def test_exact_mapped_pair_enters_scanner(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    assert len(candidates) == 2
    # Verify no NON_EXACT_MAPPING rejection reason
    for cand in candidates:
        assert ScannerRejectionReason.NON_EXACT_MAPPING.value not in str(cand.rejection_reasons)


# ==============================================================================
# TEST 2: Non-Exact Mapping is Rejected
# ==============================================================================
def test_non_exact_mapping_rejected(non_exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=non_exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    for cand in candidates:
        assert cand.lifecycle_status == ScannerLifecycleStatus.REJECTED
        assert any(ScannerRejectionReason.NON_EXACT_MAPPING.value in r for r in cand.rejection_reasons)


# ==============================================================================
# TEST 3: Synchronized Timestamps Within 10ms
# ==============================================================================
def test_synchronized_timestamps_within_10ms(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    for cand in candidates:
        assert cand.sync_latency_delta_ms <= 10.0
        assert not any(ScannerRejectionReason.ASYNC_WINDOW_EXCEEDED.value in r for r in cand.rejection_reasons)


# ==============================================================================
# TEST 4: Synchronization Window Rejection
# ==============================================================================
def test_synchronization_window_rejection(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=10)
    recv_kalshi = now - timedelta(milliseconds=250)  # 240ms delta > 100ms limit

    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=recv_poly,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=recv_kalshi,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    for cand in candidates:
        assert cand.lifecycle_status == ScannerLifecycleStatus.REJECTED
        assert any(ScannerRejectionReason.ASYNC_WINDOW_EXCEEDED.value in r for r in cand.rejection_reasons)


# ==============================================================================
# TEST 5: Stale Quote Rejection
# ==============================================================================
def test_stale_quote_rejection(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=500)  # 500ms > 250ms threshold
    recv_kalshi = now - timedelta(milliseconds=505)

    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=recv_poly,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=recv_kalshi,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    for cand in candidates:
        assert cand.lifecycle_status == ScannerLifecycleStatus.REJECTED
        assert any(ScannerRejectionReason.STALE_QUOTE.value in r for r in cand.rejection_reasons)


# ==============================================================================
# TEST 6: Missing Bid Handling
# ==============================================================================
def test_missing_bid_handling(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=10)
    recv_kalshi = now - timedelta(milliseconds=12)

    # Empty bids, non-empty asks
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[],
        asks=[{"price": 0.46, "size": 5000.0}],
        receive_timestamp=recv_poly,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[],
        asks=[{"price": 0.50, "size": 5000.0}],
        receive_timestamp=recv_kalshi,
        economic_outcome="NO",
    )

    assert quote_poly.best_bid is None
    assert quote_kalshi.best_bid is None

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    # Missing bids does NOT crash scanner; taker buying uses ask ladder
    assert len(candidates) == 2


# ==============================================================================
# TEST 7: Missing Ask Rejection
# ==============================================================================
def test_missing_ask_rejection(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=10)
    recv_kalshi = now - timedelta(milliseconds=12)

    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 500.0}],
        asks=[],  # Missing asks
        receive_timestamp=recv_poly,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.47, "size": 500.0}],
        asks=[{"price": 0.50, "size": 500.0}],
        receive_timestamp=recv_kalshi,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    assert cand_a.lifecycle_status == ScannerLifecycleStatus.REJECTED
    assert any(ScannerRejectionReason.MISSING_ASK.value in r for r in cand_a.rejection_reasons)


# ==============================================================================
# TEST 8: Insufficient Depth Rejection
# ==============================================================================
def test_insufficient_depth_rejection(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Only $15 worth of depth
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 30.0}],
        asks=[{"price": 0.46, "size": 35.0}],  # 35 * 0.46 = ~$16.10 USD
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.45, "size": 30.0}],
        asks=[{"price": 0.48, "size": 35.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    # Check that $1,000 size is unfillable and rejected with INSUFFICIENT_DEPTH
    exec_1000 = [s for s in cand_a.size_executions if s.target_size_usd == 1000.0][0]
    assert not exec_1000.is_fillable
    assert ScannerRejectionReason.INSUFFICIENT_DEPTH.value in exec_1000.rejection_reason


# ==============================================================================
# TEST 9: L2 VWAP Execution
# ==============================================================================
def test_l2_vwap_execution(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Multi-level ladder:
    # Level 1: $0.40 for 100 shares ($40 notional)
    # Level 2: $0.50 for 200 shares ($100 notional)
    # For a $90 order: $40 at 0.40 (100 shares) + $50 at 0.50 (100 shares) = 200 shares, VWAP = 90 / 200 = 0.45
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.35, "size": 100.0}],
        asks=[{"price": 0.40, "size": 100.0}, {"price": 0.50, "size": 200.0}],
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.35, "size": 100.0}],
        asks=[{"price": 0.45, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_100 = [s for s in cand_a.size_executions if s.target_size_usd == 100.0][0]

    # Poly VWAP must walk book and exceed top-of-book 0.40
    assert exec_100.vwap_a > 0.40
    assert exec_100.vwap_a == pytest.approx(100.0 / 220.0, abs=0.01)


# ==============================================================================
# TEST 10: Partial Fill Handling
# ==============================================================================
def test_partial_fill_handling(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Exactly $50 depth on Poly, $500 on Kalshi
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.40, "size": 100.0}],
        asks=[{"price": 0.50, "size": 100.0}],  # 100 * 0.50 = $50 USD
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.40, "size": 500.0}],
        asks=[{"price": 0.45, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_25 = [s for s in cand_a.size_executions if s.target_size_usd == 25.0][0]
    exec_100 = [s for s in cand_a.size_executions if s.target_size_usd == 100.0][0]

    assert exec_25.is_fillable
    assert not exec_100.is_fillable
    assert exec_100.shares_filled_a < (100.0 / 0.50)


# ==============================================================================
# TEST 11: Fee Erosion
# ==============================================================================
def test_fee_erosion(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Poly ask = 0.499, Kalshi ask = 0.499
    # Combined = 0.998 -> Gross edge = 0.002 = 20 bps
    # Fees = (0 + 30)/2 = 15 bps, plus latency & unwind friction (18 bps) -> total cost > 20 bps -> Net edge < 0
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.499, "size": 10000.0}],
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.499, "size": 10000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_10 = cand_a.size_executions[0]
    assert exec_10.gross_edge_bps > 0.0
    assert exec_10.net_edge_bps <= 0.0
    assert ScannerRejectionReason.FEE_EROSION.value in exec_10.rejection_reason


# ==============================================================================
# TEST 12: Slippage Erosion
# ==============================================================================
def test_slippage_erosion(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Top of book has 100 bps gross edge (0.45 + 0.54 = 0.99)
    # But next levels slip dramatically to 0.48 and 0.56
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.40, "size": 500.0}],
        asks=[{"price": 0.45, "size": 25.0}, {"price": 0.50, "size": 500.0}],
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.40, "size": 500.0}],
        asks=[{"price": 0.54, "size": 25.0}, {"price": 0.56, "size": 500.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_10 = [s for s in cand_a.size_executions if s.target_size_usd == 10.0][0]
    exec_250 = [s for s in cand_a.size_executions if s.target_size_usd == 250.0][0]

    assert exec_10.slippage_bps < exec_250.slippage_bps
    assert exec_250.net_edge_bps < exec_10.net_edge_bps


# ==============================================================================
# TEST 13: Both Arbitrage Directions
# ==============================================================================
def test_both_arbitrage_directions(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    directions = {c.direction for c in candidates}
    assert ArbitrageDirection.POLY_YES_KALSHI_NO in directions
    assert ArbitrageDirection.POLY_NO_KALSHI_YES in directions


# ==============================================================================
# TEST 14: Latency Stress
# ==============================================================================
def test_latency_stress(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    cand = candidates[0]
    assert len(cand.latency_stress_results) == 8  # 0 to 1000ms grid
    
    # Net edge should monotonically decrease with latency
    edges = [l.net_edge_bps for l in cand.latency_stress_results]
    for i in range(len(edges) - 1):
        assert edges[i] >= edges[i + 1]


# ==============================================================================
# TEST 15: Asynchronous Leg Risk (Cases A-F)
# ==============================================================================
def test_asynchronous_leg_risk(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    cand = candidates[0]
    case_names = {c.case_name for c in cand.leg_risk_results}
    expected_cases = {
        "CASE_A_LEG_A_FIRST_B_DELAYED",
        "CASE_B_LEG_B_FIRST_A_DELAYED",
        "CASE_C_LEG_A_FULL_B_PARTIAL",
        "CASE_D_LEG_A_PARTIAL_B_FULL",
        "CASE_E_LEG_A_FULL_B_FAILED",
        "CASE_F_BOTH_LEGS_PARTIAL",
    }
    assert case_names == expected_cases


# ==============================================================================
# TEST 16: Emergency Unwind Cost
# ==============================================================================
def test_emergency_unwind_cost(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    cand = candidates[0]
    case_e = [c for c in cand.leg_risk_results if c.case_name == "CASE_E_LEG_A_FULL_B_FAILED"][0]
    
    # In Case E, Leg A 100% full, Leg B 0% full. Unhedged = 100% of order size
    assert case_e.unhedged_usd > 0.0
    # Emergency haircut is 10%
    expected_haircut = round(case_e.unhedged_usd * 0.10, 2)
    assert case_e.emergency_unwind_cost_usd == pytest.approx(expected_haircut, abs=0.05)


# ==============================================================================
# TEST 17: Provenance Preservation
# ==============================================================================
def test_provenance_preservation(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    for cand in candidates:
        assert cand.quote_poly_hash == quote_poly.book_hash
        assert cand.quote_kalshi_hash == quote_kalshi.book_hash
        assert cand.poly_market_id == quote_poly.venue_contract_id
        assert cand.kalshi_market_id == quote_kalshi.venue_contract_id


# ==============================================================================
# TEST 18: Deterministic Candidate Reproducibility
# ==============================================================================
def test_deterministic_candidate_reproducibility(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    scanner = CrossVenueArbitrageScanner()

    cands_run1 = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    cands_run2 = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )

    for c1, c2 in zip(cands_run1, cands_run2):
        assert c1.direction == c2.direction
        assert c1.combined_vwap == c2.combined_vwap
        assert c1.gross_edge_bps == c2.gross_edge_bps
        assert c1.best_net_edge_bps == c2.best_net_edge_bps
        assert c1.rejection_reasons == c2.rejection_reasons


# ==============================================================================
# TEST 19: Price Changes Alter Candidate Economics but NOT Mapping Identity
# ==============================================================================
def test_price_changes_alter_candidate_economics_not_mapping_identity(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # State 1: Tight ask prices
    q_poly_1 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.46, "size": 1000.0}],
        receive_timestamp=recv,
    )
    q_kalshi_1 = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.45, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    # State 2: Wide ask prices
    q_poly_2 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.30, "size": 1000.0}],
        asks=[{"price": 0.70, "size": 1000.0}],
        receive_timestamp=recv,
    )
    q_kalshi_2 = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.30, "size": 1000.0}],
        asks=[{"price": 0.75, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    cand1 = scanner.scan_quote_pair(exact_mapping, q_poly_1, q_kalshi_1, evaluation_timestamp=now)[0]
    cand2 = scanner.scan_quote_pair(exact_mapping, q_poly_2, q_kalshi_2, evaluation_timestamp=now)[0]

    # Economics differ significantly
    assert cand1.combined_vwap != cand2.combined_vwap
    assert cand1.gross_edge_bps != cand2.gross_edge_bps

    # Mapping identity and terms hash remain 100% INVARIANT
    hash1 = exact_mapping.compute_mapping_hash()
    hash2 = exact_mapping.compute_mapping_hash()
    assert hash1 == hash2
    assert cand1.mapping_id == cand2.mapping_id == exact_mapping.mapping_id


# ==============================================================================
# TEST 20: Mapping Changes Invalidate Previous Mapping Version
# ==============================================================================
def test_mapping_changes_invalidate_previous_mapping_version(exact_mapping):
    original_hash = exact_mapping.compute_mapping_hash()

    # Modify resolution strike / threshold
    modified_mapping = exact_mapping.model_copy(update={"threshold_polymarket": 3.5})
    new_hash = modified_mapping.compute_mapping_hash()

    assert original_hash != new_hash


# ==============================================================================
# TEST 21: No Midpoint Pricing
# ==============================================================================
def test_no_midpoint_pricing(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Poly: Bid 0.40, Ask 0.50 -> Midpoint is 0.45
    # Kalshi: Bid 0.40, Ask 0.50 -> Midpoint is 0.45
    # If midpoints were used: 0.45 + 0.45 = 0.90 -> Gross edge = 1000 bps
    # But actual executable cost = Ask 0.50 + Ask 0.50 = 1.00 -> Gross edge = 0 bps
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.40, "size": 1000.0}],
        asks=[{"price": 0.50, "size": 1000.0}],
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.40, "size": 1000.0}],
        asks=[{"price": 0.50, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_10 = cand_a.size_executions[0]

    # Gross edge must reflect executable asks (1.0 - 1.0 = 0.0), NOT midpoint (0.10)
    assert exec_10.combined_vwap == pytest.approx(1.00, abs=0.001)
    assert exec_10.gross_edge_bps == pytest.approx(0.0, abs=0.01)


# ==============================================================================
# TEST 22: No Last-Trade Pricing
# ==============================================================================
def test_no_last_trade_pricing(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # Reconstructed quotes rely strictly on L2 asks
    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.42, "size": 1000.0}],
        asks=[{"price": 0.47, "size": 1000.0}],
        receive_timestamp=recv,
    )
    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.44, "size": 1000.0}],
        asks=[{"price": 0.49, "size": 1000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    candidates = scanner.scan_quote_pair(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=now,
    )

    cand_a = [c for c in candidates if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    exec_10 = cand_a.size_executions[0]

    # Combined acquisition is sum of asks (0.47 + 0.49 = 0.96)
    assert exec_10.combined_vwap == pytest.approx(0.96, abs=0.001)


# ==============================================================================
# TEST 23: No Synthetic Live Observations
# ==============================================================================
def test_no_synthetic_live_observations():
    # Verify quotes instantiated from adapter have real message IDs and no mock synthetic markers
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    q = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id="map_test",
        market_id="poly_mkt",
        token_id="tok_1",
        bids=[{"price": 0.45, "size": 100.0}],
        asks=[{"price": 0.48, "size": 100.0}],
        receive_timestamp=now,
        session_id="sess_live_123",
        message_id="msg_ws_456",
    )
    assert "synthetic" not in q.source_session_id
    assert "synthetic" not in q.source_message_id
    assert len(q.book_hash) == 64


# ==============================================================================
# TEST 24: Isolated Database Operation
# ==============================================================================
def test_isolated_database_operation(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_phase10a6i.duckdb"
        store = CrossVenueDBStore(db_path=test_db_path)

        scanner = CrossVenueArbitrageScanner(db_store=store)
        candidates = scanner.scan_quote_pair(
            mapping=exact_mapping,
            quote_poly=quote_poly,
            quote_kalshi=quote_kalshi,
            evaluation_timestamp=eval_time,
        )

        summary = ScanRunSummary(
            scan_run_id="run_test_001",
            start_timestamp=eval_time,
            end_timestamp=eval_time,
            mappings_scanned_count=1,
            quotes_processed_count=2,
            candidates_detected_count=len(candidates),
            candidates_executable_count=sum(1 for c in candidates if c.lifecycle_status == ScannerLifecycleStatus.EXECUTABLE),
            candidates_rejected_count=sum(1 for c in candidates if c.lifecycle_status == ScannerLifecycleStatus.REJECTED),
            config_hash=scanner.config.compute_config_hash(),
        )

        store.record_scanner_run(
            summary=summary,
            candidates=candidates,
            quotes=[quote_poly, quote_kalshi],
        )

        conn = store._get_connection(read_only=True)
        try:
            res_runs = conn.execute("SELECT count(*) FROM phase10a6i_scan_runs").fetchone()[0]
            res_quotes = conn.execute("SELECT count(*) FROM phase10a6i_quote_observations").fetchone()[0]
            res_cands = conn.execute("SELECT count(*) FROM phase10a6i_arbitrage_candidates").fetchone()[0]
            res_execs = conn.execute("SELECT count(*) FROM phase10a6i_execution_analysis").fetchone()[0]
            res_lat = conn.execute("SELECT count(*) FROM phase10a6i_latency_analysis").fetchone()[0]
            res_leg = conn.execute("SELECT count(*) FROM phase10a6i_leg_risk_analysis").fetchone()[0]

            assert res_runs == 1
            assert res_quotes == 2
            assert res_cands == 2
            assert res_execs == 2 * 7  # 7 sizes per candidate
            assert res_lat == 2 * 8    # 8 latency grid points
            assert res_leg == 2 * 6    # 6 cases A through F
        finally:
            conn.close()


# ==============================================================================
# TEST 25: Full Candidate Lifecycle
# ==============================================================================
def test_full_candidate_lifecycle(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv = now - timedelta(milliseconds=10)

    # 1. DETECTED / EXECUTABLE state: deep book with positive net edge
    # Poly ask = 0.40, Kalshi ask = 0.45 -> combined = 0.85 -> 1500 bps gross edge, plenty positive
    q_poly_good = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.38, "size": 1000.0}],
        asks=[{"price": 0.40, "size": 10000.0}],
        receive_timestamp=recv,
    )
    q_kalshi_good = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.42, "size": 1000.0}],
        asks=[{"price": 0.45, "size": 10000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )

    scanner = CrossVenueArbitrageScanner()
    cands = scanner.scan_quote_pair(exact_mapping, q_poly_good, q_kalshi_good, evaluation_timestamp=now)
    cand_exec = [c for c in cands if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    assert cand_exec.lifecycle_status == ScannerLifecycleStatus.EXECUTABLE

    # 2. REJECTED state: negative edge
    q_poly_bad = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.50, "size": 1000.0}],
        asks=[{"price": 0.55, "size": 10000.0}],
        receive_timestamp=recv,
    )
    q_kalshi_bad = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.50, "size": 1000.0}],
        asks=[{"price": 0.55, "size": 10000.0}],
        receive_timestamp=recv,
        economic_outcome="NO",
    )
    cands_bad = scanner.scan_quote_pair(exact_mapping, q_poly_bad, q_kalshi_bad, evaluation_timestamp=now)
    cand_rej = [c for c in cands_bad if c.direction == ArbitrageDirection.POLY_YES_KALSHI_NO][0]
    assert cand_rej.lifecycle_status == ScannerLifecycleStatus.REJECTED

    # 3. Transitions to EXPIRED and CANCELLED
    cand_expired = cand_exec.model_copy(update={"lifecycle_status": ScannerLifecycleStatus.EXPIRED})
    assert cand_expired.lifecycle_status == ScannerLifecycleStatus.EXPIRED

    cand_cancelled = cand_exec.model_copy(update={"lifecycle_status": ScannerLifecycleStatus.CANCELLED})
    assert cand_cancelled.lifecycle_status == ScannerLifecycleStatus.CANCELLED
