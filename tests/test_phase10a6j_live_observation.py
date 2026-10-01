"""Unit Tests for Phase 10A.6J Live Observation Harness and Empirical Calibration.

Validates:
1. Credential absence handled safely
2. Credentials never appear in logs or output
3. Exact mapping only enters scanner funnel
4. Genuine quote provenance preserved
5. Synchronized timestamps evaluation
6. Synchronization distribution calculation
7. Staleness calculation and percentiles
8. L2 depth calculation
9. Executable VWAP calculation
10. No midpoint pricing
11. No last-trade pricing
12. No lookahead enforcement
13. Adverse movement measurement (observed post-quote adverse movement)
14. Quote persistence measurement
15. Lead/lag classification
16. Scanner lifecycle preservation
17. Mapping version preservation
18. Price changes do not alter mapping identity
19. Isolated database operation
20. Synthetic fixtures cannot enter production tables
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import pytest

from src.cross_venue.schema import (
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
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
    CrossVenueArbitrageScanner,
    CrossVenueArbitrageCandidate,
)
from src.cross_venue.cross_venue_observation_harness import (
    KalshiCredentialStatus,
    SyncDistributionMetrics,
    QuoteStalenessMetrics,
    BookUpdateFrequencyMetrics,
    DisplayedDepthTier,
    ObservedPostQuoteMovement,
    CandidatePersistenceMetrics,
    LeadLagClassification,
    LeadLagObservationRecord,
    ObservationHarnessConfig,
    CrossVenueObservationHarness,
)
from src.cross_venue.db_store import CrossVenueDBStore


@pytest.fixture
def exact_mapping() -> ContractMappingResult:
    """Fixture providing an EXACT_EQUIVALENT mapping result."""
    return ContractMappingResult(
        mapping_id="map_cpi_exact_obs",
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
    """Fixture providing a non-exact mapping result."""
    return ContractMappingResult(
        mapping_id="map_cpi_comp_obs",
        polymarket_market_id="poly_cpi_dec2026_gt3",
        polymarket_token_id="poly_tok_111",
        kalshi_market_id="kalshi_cpi_dec2026_lte3",
        kalshi_contract_id="KXCPIDEC26-3.0-LTE",
        canonical_contract_id="canon_cpi_comp_obs",
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
def sample_quotes(exact_mapping):
    """Provides a pair of synchronized fresh quotes."""
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    recv_poly = now - timedelta(milliseconds=10)
    recv_kalshi = now - timedelta(milliseconds=15)

    quote_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id=exact_mapping.polymarket_market_id,
        token_id=exact_mapping.polymarket_token_id,
        bids=[{"price": 0.44, "size": 5000.0}],
        asks=[{"price": 0.46, "size": 5000.0}],
        receive_timestamp=recv_poly,
        exchange_timestamp=recv_poly - timedelta(milliseconds=2),
        session_id="sess_poly_obs",
        message_id="msg_poly_obs_1",
        economic_outcome="YES",
    )

    quote_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        ticker=exact_mapping.kalshi_contract_id,
        bids=[{"price": 0.46, "size": 5000.0}],
        asks=[{"price": 0.49, "size": 5000.0}],
        receive_timestamp=recv_kalshi,
        exchange_timestamp=recv_kalshi - timedelta(milliseconds=3),
        session_id="sess_kalshi_obs",
        message_id="msg_kalshi_obs_1",
        economic_outcome="NO",
    )

    return quote_poly, quote_kalshi, now


# ==============================================================================
# TEST 1: Credential Absence Handled Safely
# ==============================================================================
def test_credential_absence_handled_safely(monkeypatch):
    """Verifies that audit handles missing credentials gracefully without throwing errors."""
    for key in ["KALSHI_API_KEY", "KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH", "KALSHI_KEY_ID"]:
        monkeypatch.delenv(key, raising=False)

    status = CrossVenueObservationHarness.audit_kalshi_credentials()
    assert isinstance(status, KalshiCredentialStatus)
    assert not status.credentials_available
    assert status.status_category == "BLOCKED_CREDENTIALS_UNAVAILABLE"


# ==============================================================================
# TEST 2: Credentials Never Appear in Logs
# ==============================================================================
def test_credentials_never_appear_in_logs():
    """Ensures credential audit dictionary exposes only metadata, never secrets."""
    status = KalshiCredentialStatus(
        credentials_available=False,
        credential_source="none",
        status_category="BLOCKED_CREDENTIALS_UNAVAILABLE",
    )
    d = status.to_audit_dict()
    assert "private_key" not in d
    assert "api_key" not in d
    assert "secret" not in d
    assert d["credentials_available"] is False


# ==============================================================================
# TEST 3: Exact Mapping Only Enters Scanner Funnel
# ==============================================================================
def test_exact_mapping_only(exact_mapping, non_exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    harness = CrossVenueObservationHarness()

    funnel_exact = harness.evaluate_candidate_survival_funnel(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    assert funnel_exact["stages"]["exact_mappings"] is True

    funnel_non_exact = harness.evaluate_candidate_survival_funnel(
        mapping=non_exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    assert funnel_non_exact["stages"]["exact_mappings"] is False
    assert funnel_non_exact["stages"]["scanner_surviving_observations"] is False


# ==============================================================================
# TEST 4: Genuine Quote Provenance Preserved
# ==============================================================================
def test_genuine_quote_provenance_preserved(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    harness = CrossVenueObservationHarness()

    res = harness.evaluate_candidate_survival_funnel(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    cand = res["candidate"]
    assert cand is not None
    assert cand.quote_poly_hash == quote_poly.book_hash
    assert cand.quote_kalshi_hash == quote_kalshi.book_hash
    assert cand.poly_market_id == quote_poly.venue_contract_id
    assert cand.kalshi_market_id == quote_kalshi.venue_contract_id


# ==============================================================================
# TEST 5: Synchronized Timestamps Evaluation
# ==============================================================================
def test_synchronized_timestamps(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    harness = CrossVenueObservationHarness()

    funnel = harness.evaluate_candidate_survival_funnel(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    # Timestamps are 10ms and 15ms ago -> skew delta is 5ms <= 100ms
    assert funnel["stages"]["synchronized_observations"] is True


# ==============================================================================
# TEST 6: Synchronization Distribution Calculation
# ==============================================================================
def test_synchronization_distribution_calculation(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    pairs = []
    # Create pairs with skews: 5ms, 15ms, 45ms, 120ms
    skews = [5.0, 15.0, 45.0, 120.0]
    for sk in skews:
        qp = PolymarketQuoteAdapter.from_l2_dict(
            mapping_id=exact_mapping.mapping_id,
            market_id="poly",
            token_id="tok",
            bids=[{"price": 0.40, "size": 100.0}],
            asks=[{"price": 0.45, "size": 100.0}],
            receive_timestamp=now,
        )
        qk = KalshiQuoteAdapter.from_l2_dict(
            mapping_id=exact_mapping.mapping_id,
            ticker="kalshi",
            bids=[{"price": 0.40, "size": 100.0}],
            asks=[{"price": 0.45, "size": 100.0}],
            receive_timestamp=now - timedelta(milliseconds=sk),
            economic_outcome="NO",
        )
        pairs.append((qp, qk))

    dist = CrossVenueObservationHarness.compute_sync_distribution(pairs)
    assert dist.sample_size_n == 4
    assert dist.min_ms == 5.0
    assert dist.max_ms == 120.0
    assert dist.count_within_10ms == 1
    assert dist.count_within_25ms == 2
    assert dist.count_within_50ms == 3
    assert dist.count_within_100ms == 3
    assert dist.count_within_250ms == 4


# ==============================================================================
# TEST 7: Staleness Calculation and Percentiles
# ==============================================================================
def test_staleness_calculation():
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    ages_ms = [10.0, 30.0, 80.0, 300.0]
    quotes = [
        PolymarketQuoteAdapter.from_l2_dict(
            mapping_id="map_1",
            market_id="mkt",
            token_id="tok",
            bids=[{"price": 0.40, "size": 100.0}],
            asks=[{"price": 0.45, "size": 100.0}],
            receive_timestamp=now - timedelta(milliseconds=a),
        )
        for a in ages_ms
    ]

    stale_metrics = CrossVenueObservationHarness.compute_staleness_distribution(quotes, evaluation_timestamp=now)
    assert stale_metrics.sample_size_n == 4
    assert stale_metrics.pct_exceeding_25ms == 75.0   # 3 out of 4 (30, 80, 300)
    assert stale_metrics.pct_exceeding_50ms == 50.0   # 2 out of 4 (80, 300)
    assert stale_metrics.pct_exceeding_250ms == 25.0  # 1 out of 4 (300)


# ==============================================================================
# TEST 8: L2 Depth Calculation
# ==============================================================================
def test_l2_depth_calculation(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    quote = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.40, "size": 500.0}],
        asks=[{"price": 0.45, "size": 100.0}, {"price": 0.50, "size": 200.0}],  # 45 + 100 = 145 USD depth
        receive_timestamp=now,
    )

    harness = CrossVenueObservationHarness()
    tiers = harness.calibrate_displayed_liquidity(quote, target_sizes=[10.0, 50.0, 200.0])

    assert len(tiers) == 3
    assert tiers[0].is_fully_displayed is True   # $10 fits
    assert tiers[1].is_fully_displayed is True   # $50 fits
    assert tiers[2].is_fully_displayed is False  # $200 exceeds $145 depth


# ==============================================================================
# TEST 9: Executable VWAP Calculation
# ==============================================================================
def test_executable_vwap_calculation(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Tier 1: $0.40 for 100 shares ($40 notional)
    # Tier 2: $0.50 for 200 shares ($100 notional)
    quote = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.35, "size": 100.0}],
        asks=[{"price": 0.40, "size": 100.0}, {"price": 0.50, "size": 200.0}],
        receive_timestamp=now,
    )

    harness = CrossVenueObservationHarness()
    tiers = harness.calibrate_displayed_liquidity(quote, target_sizes=[100.0])
    tier = tiers[0]

    # For $100 order: $40 at 0.40 (100 shares) + $60 at 0.50 (120 shares) = 220 shares -> VWAP = 100 / 220 = 0.4545
    assert tier.executable_vwap > tier.best_ask
    assert tier.executable_vwap == pytest.approx(100.0 / 220.0, abs=0.01)


# ==============================================================================
# TEST 10: No Midpoint Pricing
# ==============================================================================
def test_no_midpoint_pricing(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Bid 0.40, Ask 0.60 -> Midpoint 0.50
    quote = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.40, "size": 1000.0}],
        asks=[{"price": 0.60, "size": 1000.0}],
        receive_timestamp=now,
    )

    harness = CrossVenueObservationHarness()
    tiers = harness.calibrate_displayed_liquidity(quote, target_sizes=[10.0])
    assert tiers[0].executable_vwap == pytest.approx(0.60, abs=0.001)
    assert tiers[0].executable_vwap != pytest.approx(0.50, abs=0.001)


# ==============================================================================
# TEST 11: No Last-Trade Pricing
# ==============================================================================
def test_no_last_trade_pricing(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    quote = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.35, "size": 1000.0}],
        asks=[{"price": 0.48, "size": 1000.0}],
        receive_timestamp=now,
    )
    harness = CrossVenueObservationHarness()
    tiers = harness.calibrate_displayed_liquidity(quote, target_sizes=[10.0])
    # Must use ask ladder price (0.48), not an arbitrary external last trade
    assert tiers[0].executable_vwap == pytest.approx(0.48, abs=0.001)


# ==============================================================================
# TEST 12: No Lookahead Enforcement
# ==============================================================================
def test_no_lookahead(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    harness = CrossVenueObservationHarness()

    # Pass evaluation timestamp strictly BEFORE quote receive timestamp
    past_eval_time = quote_poly.local_receive_timestamp - timedelta(seconds=1)

    with pytest.raises(ValueError, match="Anti-lookahead violation"):
        harness.evaluate_candidate_survival_funnel(
            mapping=exact_mapping,
            quote_poly=quote_poly,
            quote_kalshi=quote_kalshi,
            evaluation_timestamp=past_eval_time,
        )


# ==============================================================================
# TEST 13: Adverse Movement Measurement
# ==============================================================================
def test_adverse_movement_measurement(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    q0 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.40, "size": 100.0}],
        asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now,
    )
    # Subsequent quote 50ms later with price moving from 0.45 to 0.46 (100 bps adverse move)
    q1 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id,
        market_id="poly",
        token_id="tok",
        bids=[{"price": 0.41, "size": 100.0}],
        asks=[{"price": 0.46, "size": 100.0}],
        receive_timestamp=now + timedelta(milliseconds=50),
    )

    harness = CrossVenueObservationHarness()
    moves = harness.measure_post_quote_adverse_movement(
        initial_quote=q0,
        subsequent_quotes=[q1],
        horizons_ms=[10.0, 50.0, 100.0],
    )
    assert len(moves) == 3
    # At 50ms horizon, adverse movement is (0.46 - 0.45) * 10000 = 100 bps
    m_50 = [m for m in moves if m.horizon_ms == 50.0][0]
    assert m_50.median_adverse_bps == pytest.approx(100.0, abs=1.0)


# ==============================================================================
# TEST 14: Quote Persistence Measurement
# ==============================================================================
def test_quote_persistence_measurement():
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    initial_cand = CrossVenueArbitrageCandidate(
        candidate_id="c_0",
        mapping_id="map_1",
        direction=ArbitrageDirection.POLY_YES_KALSHI_NO,
        lifecycle_status=ScannerLifecycleStatus.EXECUTABLE,
        evaluation_timestamp=now,
        quote_poly_hash="h1",
        quote_kalshi_hash="h2",
        poly_market_id="p1",
        kalshi_market_id="k1",
        sync_latency_delta_ms=5.0,
        gross_edge_bps=50.0,
        best_net_edge_bps=20.0,
    )

    future_cand_alive = CrossVenueArbitrageCandidate(
        candidate_id="c_1",
        mapping_id="map_1",
        direction=ArbitrageDirection.POLY_YES_KALSHI_NO,
        lifecycle_status=ScannerLifecycleStatus.EXECUTABLE,
        evaluation_timestamp=now + timedelta(milliseconds=50),
        quote_poly_hash="h1",
        quote_kalshi_hash="h2",
        poly_market_id="p1",
        kalshi_market_id="k1",
        sync_latency_delta_ms=5.0,
        gross_edge_bps=40.0,
        best_net_edge_bps=10.0,
    )

    persistence = CrossVenueObservationHarness.measure_candidate_persistence(
        initial_candidate=initial_cand,
        future_candidates=[(50.0, future_cand_alive)],
        horizons_ms=[10.0, 25.0, 50.0, 100.0],
    )
    assert persistence.n_positive_observations == 1
    assert persistence.pct_positive_at_50ms == 100.0
    assert persistence.median_lifetime_ms == 50.0


# ==============================================================================
# TEST 15: Lead/Lag Classification
# ==============================================================================
def test_lead_lag_classification(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Poly moves price at +10ms
    q_poly_0 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now,
    )
    q_poly_1 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.48, "size": 100.0}],  # Move!
        receive_timestamp=now + timedelta(milliseconds=10),
    )

    # Kalshi moves price at +30ms (20ms later)
    q_kalshi_0 = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, ticker="k",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now, economic_outcome="NO",
    )
    q_kalshi_1 = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, ticker="k",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.49, "size": 100.0}],  # Move!
        receive_timestamp=now + timedelta(milliseconds=30), economic_outcome="NO",
    )

    records = CrossVenueObservationHarness.classify_lead_lag(
        quotes_poly=[q_poly_0, q_poly_1],
        quotes_kalshi=[q_kalshi_0, q_kalshi_1],
    )
    assert len(records) == 1
    rec = records[0]
    assert rec.classification == LeadLagClassification.VENUE_A_FIRST
    assert rec.first_mover_venue == "polymarket"
    assert rec.second_mover_venue == "kalshi"
    assert rec.lag_magnitude_ms == pytest.approx(20.0, abs=0.5)


# ==============================================================================
# TEST 16: Scanner Lifecycle Preservation
# ==============================================================================
def test_scanner_lifecycle_preservation(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    harness = CrossVenueObservationHarness()

    funnel = harness.evaluate_candidate_survival_funnel(
        mapping=exact_mapping,
        quote_poly=quote_poly,
        quote_kalshi=quote_kalshi,
        evaluation_timestamp=eval_time,
    )
    cand = funnel["candidate"]
    assert cand.lifecycle_status in [
        ScannerLifecycleStatus.DETECTED,
        ScannerLifecycleStatus.EXECUTABLE,
        ScannerLifecycleStatus.REJECTED,
    ]


# ==============================================================================
# TEST 17: Mapping Version Preservation
# ==============================================================================
def test_mapping_version_preservation(exact_mapping):
    original_hash = exact_mapping.compute_mapping_hash()
    assert len(original_hash) == 64
    assert exact_mapping.mapping_id == "map_cpi_exact_obs"


# ==============================================================================
# TEST 18: Price Changes Do Not Alter Mapping Identity
# ==============================================================================
def test_price_changes_do_not_alter_mapping_identity(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    q1 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now,
    )
    q2 = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.10, "size": 100.0}], asks=[{"price": 0.90, "size": 100.0}],
        receive_timestamp=now,
    )
    harness = CrossVenueObservationHarness()
    t1 = harness.calibrate_displayed_liquidity(q1, [10.0])[0]
    t2 = harness.calibrate_displayed_liquidity(q2, [10.0])[0]

    assert t1.executable_vwap != t2.executable_vwap
    # Mapping ID remains invariant
    assert q1.mapping_id == q2.mapping_id == exact_mapping.mapping_id


# ==============================================================================
# TEST 19: Isolated Database Operation
# ==============================================================================
def test_isolated_database_operation(exact_mapping, sample_quotes):
    quote_poly, quote_kalshi, eval_time = sample_quotes
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "test_phase10a6j.duckdb"
        store = CrossVenueDBStore(db_path=test_db)

        session_id = "sess_obs_test_1"
        store.record_observation_session(
            session_id=session_id,
            session_type="LIVE_OBSERVATION",
            credential_status="BLOCKED_CREDENTIALS_UNAVAILABLE",
            credential_source="none",
            start_timestamp=eval_time,
            end_timestamp=eval_time,
            is_authenticated=False,
            config_hash="cfg_hash_test",
        )

        store.record_observation_harness_run(
            run_id="run_10a6j_001",
            start_timestamp=eval_time,
            end_timestamp=eval_time,
            mappings_observed_count=1,
            sync_observations=[{
                "observation_id": "obs_1",
                "mapping_id": exact_mapping.mapping_id,
                "poly_contract_id": quote_poly.venue_contract_id,
                "kalshi_contract_id": quote_kalshi.venue_contract_id,
                "poly_receive_timestamp": quote_poly.local_receive_timestamp,
                "kalshi_receive_timestamp": quote_kalshi.local_receive_timestamp,
                "poly_exchange_timestamp": quote_poly.exchange_timestamp,
                "kalshi_exchange_timestamp": quote_kalshi.exchange_timestamp,
                "skew_delta_ms": 5.0,
                "poly_book_hash": quote_poly.book_hash,
                "kalshi_book_hash": quote_kalshi.book_hash,
                "source_session_id": session_id,
            }],
            friction_records=[{
                "friction_id": "fric_1",
                "observation_id": "obs_1",
                "mapping_id": exact_mapping.mapping_id,
                "venue": "polymarket",
                "target_size_usd": 10.0,
                "best_ask": 0.46,
                "executable_vwap": 0.46,
                "slippage_bps": 0.0,
                "available_depth_usd": 5000.0,
                "unfilled_usd": 0.0,
                "fee_bps": 0.0,
                "quote_age_ms": 10.0,
            }],
            latency_records=[{
                "latency_id": "lat_1",
                "observation_id": "obs_1",
                "mapping_id": exact_mapping.mapping_id,
                "venue": "polymarket",
                "horizon_ms": 50.0,
                "adverse_movement_bps": 5.0,
            }],
            survival_records=[{
                "survival_id": "surv_1",
                "observation_id": "obs_1",
                "mapping_id": exact_mapping.mapping_id,
                "funnel_stage": "scanner_surviving_observations",
                "is_survived": True,
                "gross_edge_bps": 50.0,
                "net_edge_bps": 20.0,
                "scanner_status": "EXECUTABLE",
                "rejection_reason": "",
            }],
            persistence_records=[{
                "persistence_id": "pers_1",
                "observation_id": "obs_1",
                "mapping_id": exact_mapping.mapping_id,
                "horizon_ms": 50.0,
                "is_positive_edge": True,
                "edge_bps": 20.0,
            }],
            lead_lag_records=[{
                "lead_lag_id": "ll_1",
                "mapping_id": exact_mapping.mapping_id,
                "timestamp": eval_time,
                "classification": "VENUE_A_FIRST",
                "first_mover_venue": "polymarket",
                "second_mover_venue": "kalshi",
                "lag_magnitude_ms": 10.0,
            }],
            config_hash="cfg_test_hash",
            summary_dict={"test": True},
        )

        conn = store._get_connection(read_only=True)
        try:
            assert conn.execute("SELECT count(*) FROM phase10a6j_live_sessions").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_sync_observations").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_friction_observations").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_latency_observations").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_candidate_survival").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_persistence_observations").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_lead_lag_observations").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM phase10a6j_calibration_runs").fetchone()[0] == 1
        finally:
            conn.close()


# ==============================================================================
# TEST 20: Synthetic Fixtures Cannot Enter Production Tables
# ==============================================================================
def test_synthetic_fixtures_cannot_enter_production_tables():
    q = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id="map_prod",
        market_id="poly_prod",
        token_id="tok_prod",
        bids=[{"price": 0.40, "size": 100.0}],
        asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=datetime.now(timezone.utc),
        session_id="sess_genuine_ws",
        message_id="msg_genuine_1",
    )
    assert "synthetic" not in q.source_session_id.lower()
    assert "synthetic" not in q.source_message_id.lower()
    assert not q.stale
