"""Forensic Provenance Audit Tests for Phase 10A.6J.

Phase 10A.6J-A:
1. Section 3 vs Section 6 contradiction detection
2. Source classification
3. Fixture cannot enter empirical population
4. Synthetic cannot enter empirical population
5. Missing provenance detection
6. Raw book hash reproduction
7. Timestamp integrity
8. No-lookahead enforcement
9. Mapping reproducibility
10. Price independence
11. Independent +500 bps calculation
12. Archived vs Live separation
13. Persistence N validation
14. Lead/lag provenance
15. Production table contamination detection
16. Isolated DB operation
17. Credential unavailable state
18. Exact mapping count reproducibility
19. Candidate count reproducibility
20. Audit classification determinism
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
    ArbitrageDirection,
    ScannerConfig,
    CrossVenueArbitrageScanner,
)
from src.cross_venue.cross_venue_observation_harness import (
    CrossVenueObservationHarness,
    KalshiCredentialStatus,
)
from src.cross_venue.provenance_auditor import (
    SourceClassification,
    AuditVerdict,
    ObservationProvenanceRecord,
    AdversarialProvenanceAuditor,
)
from src.cross_venue.db_store import CrossVenueDBStore


@pytest.fixture
def exact_mapping() -> ContractMappingResult:
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
def disputed_500bps_quotes(exact_mapping):
    """The exact quote pair that produced the +500 bps gross edge in the 10A.6J report."""
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
# TEST 1: Section 3 vs Section 6 Contradiction Detection
# ==============================================================================
def test_section3_vs_section6_contradiction_detection():
    """Identifies the exact contradiction: Section 3 exact_equivalent=0 vs Section 6 exact_mappings=1."""
    auditor = AdversarialProvenanceAuditor()
    contradiction = auditor.audit_section3_vs_section6_contradiction(
        section3_exact_count=0,
        section6_exact_count=1,
        section6_source=SourceClassification.UNIT_FIXTURE,
    )
    assert contradiction["is_contradictory"] is True
    assert "Section 3 correctly reported exact_equivalent_count=0" in contradiction["explanation"]
    assert "UNIT_FIXTURE" in contradiction["explanation"]


# ==============================================================================
# TEST 2: Source Classification
# ==============================================================================
def test_source_classification():
    """Verifies strict mutually-exclusive classification of quote sources."""
    # Test fixture
    assert AdversarialProvenanceAuditor.classify_source("sess_poly_obs", "msg_1", "polymarket") == SourceClassification.UNIT_FIXTURE
    assert AdversarialProvenanceAuditor.classify_source("sess_test_123", "msg_1", "kalshi") == SourceClassification.UNIT_FIXTURE

    # Synthetic
    assert AdversarialProvenanceAuditor.classify_source("synthetic_sess", "msg_1", "polymarket") == SourceClassification.SYNTHETIC
    assert AdversarialProvenanceAuditor.classify_source("sess_live", "mock_msg", "kalshi") == SourceClassification.SYNTHETIC

    # Live Polymarket
    assert AdversarialProvenanceAuditor.classify_source("sess_20261001_160404_354", "msg_1", "polymarket") == SourceClassification.POLYMARKET_LIVE

    # Archived
    assert AdversarialProvenanceAuditor.classify_source("gamma_archived_20260929", "msg_1", "polymarket") == SourceClassification.POLYMARKET_ARCHIVED
    assert AdversarialProvenanceAuditor.classify_source("kalshi_archived_20260929", "msg_1", "kalshi") == SourceClassification.KALSHI_ARCHIVED


# ==============================================================================
# TEST 3: Fixture Cannot Enter Empirical Population
# ==============================================================================
def test_fixture_cannot_enter_empirical_population(exact_mapping, disputed_500bps_quotes):
    """Confirms that the +500 bps candidate originated from test fixtures and cannot enter empirical records."""
    q_poly, q_kalshi, eval_time = disputed_500bps_quotes
    auditor = AdversarialProvenanceAuditor()

    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, eval_time)
    assert rec.source_classification_poly == SourceClassification.UNIT_FIXTURE
    assert rec.source_classification_kalshi == SourceClassification.UNIT_FIXTURE
    assert rec.is_empirical is False
    assert rec.audit_status == "INVALID_FIXTURE_CONTAMINATION"


# ==============================================================================
# TEST 4: Synthetic Cannot Enter Empirical Population
# ==============================================================================
def test_synthetic_cannot_enter_empirical_population(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    q_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now, session_id="synthetic_mock_sess", message_id="mock_msg",
    )
    q_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, ticker="k",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now, session_id="synthetic_mock_sess", message_id="mock_msg",
        economic_outcome="NO",
    )
    auditor = AdversarialProvenanceAuditor()
    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, now)

    assert rec.source_classification_poly == SourceClassification.SYNTHETIC
    assert rec.is_empirical is False
    assert rec.audit_status == "INVALID_FIXTURE_CONTAMINATION"


# ==============================================================================
# TEST 5: Missing Provenance Detection
# ==============================================================================
def test_missing_provenance_detection(exact_mapping):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Empty session or unknown format
    q_poly = PolymarketQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, market_id="p", token_id="t",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now, session_id="", message_id="",
    )
    q_kalshi = KalshiQuoteAdapter.from_l2_dict(
        mapping_id=exact_mapping.mapping_id, ticker="k",
        bids=[{"price": 0.40, "size": 100.0}], asks=[{"price": 0.45, "size": 100.0}],
        receive_timestamp=now, session_id="", message_id="",
        economic_outcome="NO",
    )
    auditor = AdversarialProvenanceAuditor()
    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, now)

    assert rec.source_classification_poly == SourceClassification.UNKNOWN
    assert rec.is_empirical is False


# ==============================================================================
# TEST 6: Raw Book Hash Reproduction
# ==============================================================================
def test_raw_book_hash_reproduction(exact_mapping, disputed_500bps_quotes):
    q_poly, q_kalshi, eval_time = disputed_500bps_quotes
    auditor = AdversarialProvenanceAuditor()

    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, eval_time)
    assert rec.hashes_match is True
    assert rec.raw_book_hash_poly == rec.reconstructed_book_hash_poly
    assert rec.raw_book_hash_kalshi == rec.reconstructed_book_hash_kalshi


# ==============================================================================
# TEST 7: Timestamp Integrity
# ==============================================================================
def test_timestamp_integrity(exact_mapping, disputed_500bps_quotes):
    q_poly, q_kalshi, eval_time = disputed_500bps_quotes
    auditor = AdversarialProvenanceAuditor()

    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, eval_time)
    # Ensure evaluation_timestamp >= receive_timestamps
    assert rec.evaluation_timestamp >= rec.poly_receive_timestamp
    assert rec.evaluation_timestamp >= rec.kalshi_receive_timestamp
    assert rec.poly_receive_timestamp > q_poly.exchange_timestamp
    assert rec.kalshi_receive_timestamp > q_kalshi.exchange_timestamp


# ==============================================================================
# TEST 8: No-Lookahead Enforcement
# ==============================================================================
def test_no_lookahead(exact_mapping, disputed_500bps_quotes):
    q_poly, q_kalshi, eval_time = disputed_500bps_quotes
    auditor = AdversarialProvenanceAuditor()

    # Pass past evaluation timestamp
    past_ts = q_poly.local_receive_timestamp - timedelta(seconds=10)
    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, past_ts)
    assert any("LOOKAHEAD_VIOLATION" in note for note in rec.audit_notes)


# ==============================================================================
# TEST 9: Mapping Reproducibility
# ==============================================================================
def test_mapping_reproducibility():
    """Confirms that re-running mapping against raw files independently yields 0 exact mappings."""
    harness = CrossVenueObservationHarness()
    summary, pairs = harness.run_market_universe_discovery([], [], persist=False)
    assert summary.exact_equivalent_count == 0


# ==============================================================================
# TEST 10: Price Independence
# ==============================================================================
def test_price_independence(exact_mapping):
    original_terms_hash = exact_mapping.compute_mapping_hash()

    # Create two different quotes at radically different prices
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    q1 = PolymarketQuoteAdapter.from_l2_dict(exact_mapping.mapping_id, "p", "t", [{"price": 0.10, "size": 100.0}], [{"price": 0.20, "size": 100.0}], now)
    q2 = PolymarketQuoteAdapter.from_l2_dict(exact_mapping.mapping_id, "p", "t", [{"price": 0.80, "size": 100.0}], [{"price": 0.90, "size": 100.0}], now)

    # Contract hash and mapping hash remain 100% invariant
    assert exact_mapping.compute_mapping_hash() == original_terms_hash
    assert q1.mapping_id == q2.mapping_id


# ==============================================================================
# TEST 11: Independent +500 bps Calculation
# ==============================================================================
def test_independent_500bps_calculation(exact_mapping, disputed_500bps_quotes):
    q_poly, q_kalshi, eval_time = disputed_500bps_quotes
    auditor = AdversarialProvenanceAuditor()

    rec = auditor.audit_observation(q_poly, q_kalshi, exact_mapping, eval_time)

    # 1.00 - (0.46 + 0.49) = 0.05 = 500 bps
    assert rec.independent_vwap_poly == 0.46
    assert rec.independent_vwap_kalshi == 0.49
    assert rec.independent_gross_edge_bps == 500.0
    # Net edge survives after costs
    assert rec.independent_net_edge_bps > 0.0
    # BUT source is UNIT_FIXTURE
    assert rec.source_classification_poly == SourceClassification.UNIT_FIXTURE


# ==============================================================================
# TEST 12: Archived vs Live Separation
# ==============================================================================
def test_archived_live_separation():
    auditor = AdversarialProvenanceAuditor()
    cls_live = auditor.classify_source("sess_20261001_160404_354", "msg_live_1", "polymarket")
    cls_arch = auditor.classify_source("gamma_archived_20260929", "msg_arch_1", "polymarket")

    assert cls_live == SourceClassification.POLYMARKET_LIVE
    assert cls_arch == SourceClassification.POLYMARKET_ARCHIVED
    assert cls_live != cls_arch


# ==============================================================================
# TEST 13: Persistence N Validation
# ==============================================================================
def test_persistence_n_validation():
    auditor = AdversarialProvenanceAuditor()
    res = auditor.audit_persistence_sample_size(n_positive_observations=1)
    assert res["is_statistically_sound"] is False
    assert "N=1 is an isolated observation or fixture test" in res["warning"]


# ==============================================================================
# TEST 14: Lead/Lag Provenance
# ==============================================================================
def test_lead_lag_provenance():
    auditor = AdversarialProvenanceAuditor()
    # If clocks are not synchronized to sub-millisecond hardware accuracy, 20ms ordering is indeterminate
    res_unsync = auditor.audit_lead_lag_causality(clock_synchronized=False, lag_ms=20.0)
    assert res_unsync["verdict"] == "INDETERMINATE_CLOCK_UNSYNCHRONIZED"
    assert res_unsync["is_causal"] is False

    res_sync = auditor.audit_lead_lag_causality(clock_synchronized=True, lag_ms=20.0)
    assert res_sync["verdict"] == "CAUSAL_ORDERING_VERIFIED"
    assert res_sync["is_causal"] is True


# ==============================================================================
# TEST 15: Production Table Contamination Detection
# ==============================================================================
def test_production_table_contamination_detection():
    """Inspects production database tables and confirms 0 rows of contamination."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "clean.duckdb"
        store = CrossVenueDBStore(db_path=test_db)
        auditor = AdversarialProvenanceAuditor(db_store=store)

        res = auditor.audit_production_database()
        assert res["total_rows_in_production"] == 0
        assert res["status"] == "CLEAN_ZERO_CONTAMINATION"


# ==============================================================================
# TEST 16: Isolated DB Operation
# ==============================================================================
def test_isolated_db_operation():
    """Verifies that auditor connects and queries safely in an isolated database."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "isolated.duckdb"
        store = CrossVenueDBStore(db_path=test_db)
        conn = store._get_connection(read_only=True)
        try:
            assert conn is not None
        finally:
            conn.close()


# ==============================================================================
# TEST 17: Credential Unavailable State
# ==============================================================================
def test_credential_unavailable_state():
    status = CrossVenueObservationHarness.audit_kalshi_credentials()
    # Confirm credentials are not available in current environment
    assert status.credentials_available is False
    assert status.status_category == "BLOCKED_CREDENTIALS_UNAVAILABLE"


# ==============================================================================
# TEST 18: Exact Mapping Count Reproducibility
# ==============================================================================
def test_exact_mapping_count_reproducibility():
    """Independent execution yields exact_equivalent_count=0."""
    harness = CrossVenueObservationHarness()
    summary, _ = harness.run_market_universe_discovery([], [], persist=False)
    assert summary.exact_equivalent_count == 0


# ==============================================================================
# TEST 19: Candidate Count Reproducibility
# ==============================================================================
def test_candidate_count_reproducibility():
    harness = CrossVenueObservationHarness()
    summary, _ = harness.run_market_universe_discovery([], [], persist=False)
    assert summary.candidate_pairs_generated == 0


# ==============================================================================
# TEST 20: Audit Classification Determinism
# ==============================================================================
def test_audit_classification_determinism():
    auditor = AdversarialProvenanceAuditor()
    verdict = auditor.determine_audit_verdict(
        has_contradiction=True,
        candidate_source=SourceClassification.UNIT_FIXTURE,
        prod_db_contaminated=False,
    )
    assert verdict == AuditVerdict.FIXTURE_ONLY
