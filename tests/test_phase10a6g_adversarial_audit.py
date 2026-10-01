"""Comprehensive Unit Test Suite for Phase 10A.6G Adversarial Execution Audit.

Covers all 20 required deterministic test areas:
1. baseline reproduction
2. latency stress
3. depth stress
4. fee stress
5. slippage stress
6. quote-age stress
7. full/partial fill combinations
8. failed second leg
9. adverse price movement
10. capital stress
11. combined stress
12. midpoint false positive
13. depth false positive
14. fee false positive
15. latency false positive
16. stale quote false positive
17. resolution mismatch
18. lookahead protection
19. configuration hashing
20. deterministic reproducibility
"""
from datetime import datetime, timezone, timedelta
import json
import pytest
import duckdb

from src.cross_venue.schema import (
    EquivalenceClass,
    MappingStatus,
    CategoryStatus,
    FinalArbitrageVerdict,
    CanonicalEconomicContract,
    ContractMappingResult,
    SyncQuote,
    QuoteState,
    CrossVenueArbitrageOpportunity,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer
from src.cross_venue.cross_venue_arb_engine import CrossVenueArbEngine
from src.cross_venue.cross_venue_adversarial import (
    AdversarialConfig,
    CrossVenueAdversarialEngine,
    AdversarialAuditSummary,
)
from src.cross_venue.db_store import CrossVenueDBStore


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def eval_timestamp():
    return datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def canonical_pair(eval_timestamp):
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_fed_dec26",
        underlying_event="Fed Funds Target Rate December 2026",
        observation_variable="Fed Funds Rate >= 4.50%",
        geographic_scope="US",
        temporal_scope="December 2026",
        resolution_timestamp=eval_timestamp + timedelta(days=60),
        threshold=4.50,
        inequality_direction=">=",
        source_of_resolution="Federal Reserve Board",
        currency="USD",
        tick_size=0.01,
        contract_multiplier=1.0,
        resolution_rules="Official FOMC statement release.",
        invalidation_rules="",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_fed_dec26",
        underlying_event="Fed Funds Target Rate December 2026",
        observation_variable="Fed Funds Rate >= 4.50%",
        geographic_scope="US",
        temporal_scope="December 2026",
        resolution_timestamp=eval_timestamp + timedelta(days=60),
        threshold=4.50,
        inequality_direction=">=",
        source_of_resolution="Federal Reserve Board",
        currency="USD",
        tick_size=0.01,
        contract_multiplier=1.0,
        resolution_rules="Official FOMC statement release.",
        invalidation_rules="",
    )
    return poly, kalshi


@pytest.fixture
def exact_mapping(canonical_pair):
    poly, kalshi = canonical_pair
    return SettlementNormalizer.compare_contracts(poly, kalshi)


@pytest.fixture
def synchronized_quotes(eval_timestamp):
    """Creates a viable baseline candidate:
    Polymarket YES ask = 0.44 (size 5000)
    Kalshi NO ask = 0.51 (size 5000)
    Combined acquisition cost = 0.95 (Gross edge = 500 bps).
    """
    ts = eval_timestamp - timedelta(milliseconds=20)
    poly_quote = SyncQuote(
        venue="polymarket",
        market_id="poly_fed_dec26",
        contract_id="poly_fed_dec26",
        side="ask",
        outcome="YES",
        price=0.44,
        size=5000.0,
        bids=[{"price": 0.43, "size": 5000.0}],
        asks=[{"price": 0.44, "size": 5000.0}, {"price": 0.45, "size": 10000.0}],
        venue_timestamp=ts,
        exchange_timestamp=ts,
        local_receive_timestamp=ts,
        sequence_frame_id="seq_poly_100",
    )
    kalshi_quote = SyncQuote(
        venue="kalshi",
        market_id="kalshi_fed_dec26",
        contract_id="kalshi_fed_dec26",
        side="ask",
        outcome="NO",
        price=0.51,
        size=5000.0,
        bids=[{"price": 0.50, "size": 5000.0}],
        asks=[{"price": 0.51, "size": 5000.0}, {"price": 0.52, "size": 10000.0}],
        venue_timestamp=ts,
        exchange_timestamp=ts,
        local_receive_timestamp=ts,
        sequence_frame_id="seq_kalshi_100",
    )
    return poly_quote, kalshi_quote


@pytest.fixture
def baseline_candidate(exact_mapping, synchronized_quotes, eval_timestamp):
    poly_q, kalshi_q = synchronized_quotes
    engine = CrossVenueArbEngine(
        polymarket_fee_bps=0.0,
        kalshi_fee_bps=30.0,
        default_latency_penalty_bps=8.0,
        default_hedge_cost_bps=5.0,
        capital_a_usd=10000.0,
        capital_b_usd=10000.0,
    )
    candidate = engine.evaluate_arbitrage(
        mapping=exact_mapping,
        quote_poly=poly_q,
        quote_kalshi=kalshi_q,
        target_order_size_usd=1000.0,
        sync_window_ms=100,
        evaluation_timestamp=eval_timestamp,
    )
    return candidate


@pytest.fixture
def adv_engine():
    return CrossVenueAdversarialEngine()


# ==============================================================================
# TESTS
# ==============================================================================

# 1. Baseline Reproduction
def test_baseline_reproduction(adv_engine, baseline_candidate):
    baseline = adv_engine.evaluate_baseline(baseline_candidate)
    assert baseline.candidate_id == baseline_candidate.opportunity_id
    assert baseline.mapping_id == baseline_candidate.mapping_id
    assert baseline.gross_settlement_value == 1.0
    assert baseline.gross_edge_bps == baseline_candidate.gross_edge_bps
    assert baseline.net_edge_bps == baseline_candidate.net_deterministic_edge_bps
    assert baseline.final_verdict == "ELIGIBLE"
    assert baseline.residual_exposure_usd == 0.0


# 2. Latency Stress
def test_latency_stress(adv_engine, baseline_candidate):
    lat_results = adv_engine.evaluate_latency_stress(baseline_candidate)
    assert len(lat_results) == 10
    assert lat_results[0].latency_ms == 0.0
    assert lat_results[-1].latency_ms == 5000.0

    # Net edge must monotonically decrease as latency increases
    edges = [r.net_executable_edge_bps for r in lat_results]
    for i in range(len(edges) - 1):
        assert edges[i] > edges[i + 1]


# 3. Depth Stress
def test_depth_stress(adv_engine, baseline_candidate, synchronized_quotes):
    poly_q, kalshi_q = synchronized_quotes
    depth_results = adv_engine.evaluate_depth_stress(baseline_candidate, poly_q, kalshi_q)
    assert len(depth_results) == 5

    # 10% depth factor: available depth drops below 1000 USD target size
    dep_10 = depth_results[-1]
    assert dep_10.depth_factor == 0.10
    assert dep_10.executable_quantity_usd < 1000.0
    assert dep_10.residual_unhedged_qty_usd > 0.0
    assert dep_10.is_fully_hedged is False
    assert dep_10.is_edge_positive is False


# 4. Fee Stress
def test_fee_stress(adv_engine, baseline_candidate):
    fee_results = adv_engine.evaluate_fee_stress(baseline_candidate)
    assert len(fee_results) == 6
    assert fee_results[0].fee_multiplier == 1.0
    assert fee_results[-1].fee_multiplier == 2.50

    # Higher fees compress net edge
    assert fee_results[0].net_edge_bps > fee_results[-1].net_edge_bps


# 5. Slippage Stress
def test_slippage_stress(adv_engine, baseline_candidate):
    slip_results = adv_engine.evaluate_slippage_stress(baseline_candidate)
    assert len(slip_results) == 6
    assert slip_results[0].slippage_stress_bps == 0.0
    assert slip_results[-1].slippage_stress_bps == 50.0

    # Recalculated VWAP should increase
    assert slip_results[-1].recalculated_combined_vwap > slip_results[0].recalculated_combined_vwap
    assert slip_results[-1].net_edge_bps < slip_results[0].net_edge_bps


# 6. Quote-Age Stress
def test_quote_age_stress(adv_engine, baseline_candidate):
    staleness_results = adv_engine.evaluate_quote_staleness(baseline_candidate)
    assert len(staleness_results) == 8

    fresh = staleness_results[0]
    assert fresh.quote_age_ms == 0.0
    assert fresh.classification == "EXECUTABLE_DISCREPANCY"
    assert fresh.is_stale is False

    stale_case = staleness_results[-1]
    assert stale_case.quote_age_ms == 5000.0
    assert stale_case.classification == "STALE_QUOTE_ARTIFACT"
    assert stale_case.is_stale is True


# 7. Full / Partial Fill Combinations
def test_full_partial_fill_combinations(adv_engine, baseline_candidate):
    async_results = adv_engine.evaluate_asynchronous_legs(baseline_candidate)
    cases = {r.case_name: r for r in async_results}

    # Case C: Leg A 100%, Leg B 50%
    c = cases["CASE_C_LEG_A_FULL_B_PARTIAL"]
    assert c.leg_a_fill_pct == 1.0
    assert c.leg_b_fill_pct == 0.50
    assert c.unhedged_quantity_usd == 500.0
    assert c.residual_directional_exposure_usd == 500.0
    assert c.worst_case_loss_usd > 0.0

    # Case F: Both legs partial (60% and 40%)
    f = cases["CASE_F_BOTH_LEGS_PARTIAL"]
    assert f.unhedged_quantity_usd == 200.0


# 8. Failed Second Leg
def test_failed_second_leg(adv_engine, baseline_candidate):
    async_results = adv_engine.evaluate_asynchronous_legs(baseline_candidate)
    cases = {r.case_name: r for r in async_results}
    e = cases["CASE_E_LEG_A_FULL_B_FAILED"]

    assert e.leg_a_fill_pct == 1.0
    assert e.leg_b_fill_pct == 0.0
    assert e.unhedged_quantity_usd == 1000.0
    assert e.residual_directional_exposure_usd == 1000.0
    assert e.net_pnl_usd < 0.0


# 9. Adverse Price Movement
def test_adverse_price_movement(adv_engine, baseline_candidate):
    move_results = adv_engine.evaluate_price_movement(baseline_candidate)
    adverse_moves = [r for r in move_results if r.movement_type == "adverse"]
    fav_moves = [r for r in move_results if r.movement_type == "favorable"]

    assert len(adverse_moves) == 7
    assert len(fav_moves) == 4

    # 10 tick adverse move (= 1000 bps) must destroy the edge
    large_adverse = [r for r in adverse_moves if r.movement_amount == 10.0 and r.movement_unit == "tick"][0]
    assert large_adverse.edge_destroyed is True
    assert large_adverse.net_edge_bps < 0.0


# 10. Capital Stress
def test_capital_stress(adv_engine, baseline_candidate):
    cap_results = adv_engine.evaluate_capital_stress(baseline_candidate)
    assert len(cap_results) == 5

    # 10% capital factor: 10000 * 0.10 = 1000 USD
    c10 = cap_results[-1]
    assert c10.capital_factor == 0.10
    assert c10.available_capital_a == 1000.0
    assert c10.max_common_executable_qty_usd == 1000.0
    assert c10.simultaneous_opportunities_count == 1


# 11. Combined Stress
def test_combined_stress(adv_engine, baseline_candidate, synchronized_quotes):
    poly_q, kalshi_q = synchronized_quotes
    corr_results = adv_engine.evaluate_correlated_stress(baseline_candidate, poly_q, kalshi_q)
    assert len(corr_results) == 5

    scenarios = {r.scenario_name: r for r in corr_results}
    assert "STRESS_1" in scenarios
    assert "STRESS_2" in scenarios
    assert "STRESS_3" in scenarios
    assert "STRESS_4" in scenarios
    assert "STRESS_5" in scenarios

    # Severe scenarios must fail viability
    assert scenarios["STRESS_4"].is_viable is False
    assert scenarios["STRESS_5"].is_viable is False


# 12. Midpoint False Positive
def test_midpoint_false_positive(exact_mapping, eval_timestamp):
    """Midpoint gives appearance of 400 bps spread, but executable asks eliminate it."""
    ts = eval_timestamp
    poly_quote = SyncQuote(
        venue="polymarket", market_id="mkt", contract_id="poly", side="ask", outcome="YES",
        price=0.52, size=1000.0,
        bids=[{"price": 0.40, "size": 1000.0}],
        asks=[{"price": 0.52, "size": 1000.0}],  # Midpoint is 0.46
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    kalshi_quote = SyncQuote(
        venue="kalshi", market_id="mkt", contract_id="kalshi", side="ask", outcome="NO",
        price=0.52, size=1000.0,
        bids=[{"price": 0.44, "size": 1000.0}],
        asks=[{"price": 0.52, "size": 1000.0}],  # Midpoint is 0.48 (Sum of mids = 0.94 -> 600 bps theoretical)
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    engine = CrossVenueArbEngine()
    cand = engine.evaluate_arbitrage(exact_mapping, poly_quote, kalshi_quote, target_order_size_usd=500.0)

    # Executable sum = 0.52 + 0.52 = 1.04 > 1.00! Negative net edge.
    assert cand.gross_edge_bps < 0.0
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 13. Depth False Positive
def test_depth_false_positive(exact_mapping, eval_timestamp):
    """Top of book edge exists for 10 USD, but target order is 50,000 USD."""
    ts = eval_timestamp
    poly_quote = SyncQuote(
        venue="polymarket", market_id="mkt", contract_id="poly", side="ask", outcome="YES",
        price=0.45, size=10.0,
        bids=[], asks=[{"price": 0.45, "size": 10.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    kalshi_quote = SyncQuote(
        venue="kalshi", market_id="mkt", contract_id="kalshi", side="ask", outcome="NO",
        price=0.50, size=10.0,
        bids=[], asks=[{"price": 0.50, "size": 10.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    engine = CrossVenueArbEngine()
    cand = engine.evaluate_arbitrage(exact_mapping, poly_quote, kalshi_quote, target_order_size_usd=50000.0)
    assert cand.executable_status == CategoryStatus.FAIL
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 14. Fee False Positive
def test_fee_false_positive(exact_mapping, eval_timestamp):
    """Gross edge is +20 bps, but fees consume it completely."""
    ts = eval_timestamp
    poly_quote = SyncQuote(
        venue="polymarket", market_id="mkt", contract_id="poly", side="ask", outcome="YES",
        price=0.499, size=1000.0,
        bids=[], asks=[{"price": 0.499, "size": 1000.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    kalshi_quote = SyncQuote(
        venue="kalshi", market_id="mkt", contract_id="kalshi", side="ask", outcome="NO",
        price=0.499, size=1000.0,
        bids=[], asks=[{"price": 0.499, "size": 1000.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    # Sum of asks = 0.998 -> Gross edge is 20 bps. Kalshi fee alone is 30 bps.
    engine = CrossVenueArbEngine(kalshi_fee_bps=30.0)
    cand = engine.evaluate_arbitrage(exact_mapping, poly_quote, kalshi_quote, target_order_size_usd=500.0)
    assert cand.gross_edge_bps > 0.0
    assert cand.net_deterministic_edge_bps < 0.0
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 15. Latency False Positive
def test_latency_false_positive(exact_mapping, eval_timestamp):
    """Discrepancy disappears under excessive hedge latency."""
    ts = eval_timestamp
    poly_quote = SyncQuote(
        venue="polymarket", market_id="mkt", contract_id="poly", side="ask", outcome="YES",
        price=0.47, size=1000.0, bids=[], asks=[{"price": 0.47, "size": 1000.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    kalshi_quote = SyncQuote(
        venue="kalshi", market_id="mkt", contract_id="kalshi", side="ask", outcome="NO",
        price=0.51, size=1000.0, bids=[], asks=[{"price": 0.51, "size": 1000.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    engine = CrossVenueArbEngine(max_allowable_hedge_latency_ms=250.0)
    # Hedge latency 600ms exceeds 250ms limit
    cand = engine.evaluate_arbitrage(
        exact_mapping, poly_quote, kalshi_quote, target_order_size_usd=500.0,
        override_hedge_latency_ms=600.0
    )
    assert cand.latency_status == CategoryStatus.FAIL
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 16. Stale Quote False Positive
def test_stale_quote_false_positive(exact_mapping, eval_timestamp):
    """One quote has stale flag set."""
    ts = eval_timestamp - timedelta(seconds=40)
    poly_quote = SyncQuote(
        venue="polymarket", market_id="mkt", contract_id="poly", side="ask", outcome="YES",
        price=0.45, size=1000.0, bids=[], asks=[{"price": 0.45, "size": 1000.0}],
        venue_timestamp=ts, exchange_timestamp=ts, local_receive_timestamp=ts,
    )
    kalshi_quote = SyncQuote(
        venue="kalshi", market_id="mkt", contract_id="kalshi", side="ask", outcome="NO",
        price=0.50, size=1000.0, bids=[], asks=[{"price": 0.50, "size": 1000.0}],
        venue_timestamp=eval_timestamp, exchange_timestamp=eval_timestamp,
        local_receive_timestamp=eval_timestamp,
    )
    engine = CrossVenueArbEngine()
    cand = engine.evaluate_arbitrage(exact_mapping, poly_quote, kalshi_quote, target_order_size_usd=500.0, evaluation_timestamp=eval_timestamp)
    assert cand.synchronization_status == CategoryStatus.FAIL
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 17. Resolution Mismatch
def test_resolution_mismatch(canonical_pair, eval_timestamp, synchronized_quotes):
    poly, kalshi = canonical_pair
    # Alter resolution source to cause divergence
    kalshi_diff = kalshi.model_copy(update={"source_of_resolution": "Different Private Index Provider"})
    mapping = SettlementNormalizer.compare_contracts(poly, kalshi_diff)
    assert mapping.equivalence_class == EquivalenceClass.SEMANTIC_ONLY
    assert mapping.settlement_equivalence is False

    poly_q, kalshi_q = synchronized_quotes
    engine = CrossVenueArbEngine()
    cand = engine.evaluate_arbitrage(mapping, poly_q, kalshi_q, target_order_size_usd=1000.0, evaluation_timestamp=eval_timestamp)
    assert cand.mapping_status == CategoryStatus.FAIL
    assert cand.settlement_status == CategoryStatus.FAIL
    assert cand.final_verdict == FinalArbitrageVerdict.REJECTED


# 18. Lookahead Protection
def test_lookahead_protection(adv_engine, baseline_candidate, synchronized_quotes, eval_timestamp):
    poly_q, kalshi_q = synchronized_quotes
    # Set quote receive timestamp in the future relative to eval_timestamp
    future_q = poly_q.model_copy(update={"local_receive_timestamp": eval_timestamp + timedelta(seconds=10)})

    with pytest.raises(ValueError, match="LOOKAHEAD VIOLATION"):
        adv_engine._verify_no_lookahead(future_q, kalshi_q, eval_timestamp)


# 19. Configuration Hashing
def test_configuration_hashing():
    cfg1 = AdversarialConfig()
    cfg2 = AdversarialConfig()
    hash1 = cfg1.compute_config_hash()
    hash2 = cfg2.compute_config_hash()
    assert hash1 == hash2
    assert len(hash1) == 64

    # Altering configuration changes hash
    cfg_altered = AdversarialConfig(volatility_rate_bps_per_sqrt_sec=99.9)
    assert cfg_altered.compute_config_hash() != hash1


# 20. Deterministic Reproducibility
def test_deterministic_reproducibility(adv_engine, baseline_candidate, synchronized_quotes, exact_mapping, eval_timestamp):
    poly_q, kalshi_q = synchronized_quotes

    # Run audit twice on same inputs
    audit_1 = adv_engine.run_full_adversarial_audit(baseline_candidate, poly_q, kalshi_q, exact_mapping, eval_timestamp)
    audit_2 = adv_engine.run_full_adversarial_audit(baseline_candidate, poly_q, kalshi_q, exact_mapping, eval_timestamp)

    assert audit_1.config_hash == audit_2.config_hash
    assert audit_1.baseline.net_edge_bps == audit_2.baseline.net_edge_bps
    assert audit_1.edge_survival.max_latency_tolerated_ms == audit_2.edge_survival.max_latency_tolerated_ms
    assert len(audit_1.latency_stress) == len(audit_2.latency_stress)

    # Persist to in-memory DuckDB
    mem_conn = duckdb.connect(":memory:")
    db_store = CrossVenueDBStore(db_path=None)
    # Test DB tables insertion
    db_store.record_adversarial_config(adv_engine.config)
    db_store.record_adversarial_audit(audit_1)

    # Verify tables populated in db_path
    conn = db_store._get_connection(read_only=True)
    try:
        scen_count = conn.execute("SELECT COUNT(*) FROM phase10a6g_adversarial_scenarios").fetchone()[0]
        assert scen_count > 0
        surv_count = conn.execute("SELECT COUNT(*) FROM phase10a6g_edge_survival").fetchone()[0]
        assert surv_count > 0
    finally:
        conn.close()
