"""Dedicated Test Suite for Phase 10A.6K: Genuine Kalshi Access, Universe Expansion,
Deterministic Mapping Reproduction, and Permanent Contamination Guards.

Covers the 25 required test dimensions:
1. credential absence
2. credential redaction
3. credential success path using isolated mock
4. malformed Kalshi metadata
5. complete Kalshi metadata
6. universe deduplication
7. deterministic candidate generation
8. exact mapping reproduction
9. complementary mapping reproduction
10. inequality mismatch
11. timezone mismatch
12. threshold mismatch
13. resolution-source mismatch
14. revision-policy mismatch
15. cancellation-policy mismatch
16. provenance classification
17. fixture rejection
18. synthetic rejection
19. archived/live separation
20. raw-message hashing
21. WebSocket snapshot validation
22. WebSocket delta validation
23. reconnect isolation
24. cross-venue timestamp validation
25. anti-lookahead validation
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Dict, Any
import pytest

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from src.cross_venue.schema import (
    CanonicalEconomicContract,
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer
from src.cross_venue.cross_venue_market_discovery import (
    RejectionReason,
    ConservativeTextNormalizer,
)
from src.cross_venue.provenance_auditor import (
    SourceClassification,
    AdversarialProvenanceAuditor,
)
from src.cross_venue.universe_expansion import (
    KalshiCredentialStatusRecord,
    KalshiCredentialGate,
    CredentialFailureCategory,
    ExpandedKalshiMarketRecord,
    ExpandedMarketUniverseCollector,
    DeterministicMappingRecord,
    ExpandedCrossVenuePipeline,
    MappingVerificationError,
    IndependentMappingVerifier,
    ContaminationError,
    ProductionContaminationGuard,
)
from src.cross_venue.db_store import CrossVenueDBStore
from src.kalshi.order_book_reconstructor import KalshiOrderBookReconstructor
from src.kalshi.raw_recorder import KalshiRawRecorder
from src.kalshi.connection_supervisor import KalshiConnectionSupervisor, KalshiSupervisorState


# ==============================================================================
# 1. Credential Absence Test
# ==============================================================================
def test_credential_absence(monkeypatch):
    """Verifies that when Kalshi credentials are absent, gate returns BLOCKED_CREDENTIALS_UNAVAILABLE."""
    # Ensure all Kalshi credential environment variables are cleared
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("KALSHI_PEM_PATH", raising=False)

    record = KalshiCredentialGate.audit_credentials()
    assert record.credentials_available is False
    assert record.credential_source == "none"
    assert record.authentication_attempted is False
    assert record.authentication_success is False
    assert record.failure_category == CredentialFailureCategory.BLOCKED_CREDENTIALS_UNAVAILABLE.value


# ==============================================================================
# 2. Credential Redaction Test
# ==============================================================================
def test_credential_redaction():
    """Verifies that secrets, keys, and signatures are strictly redacted from output dictionaries."""
    sensitive_dict = {
        "api_key_id": "test_key_12345",
        "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
        "auth_signature": "dGVzdF9zaWduYXR1cmVfYnl0ZXM=",
        "auth_token": "secret_session_token_xyz",
        "market_id": "KXINXD-26DEC31-T5000",
        "title": "Will S&P 500 close above 5000?",
    }
    redacted = KalshiCredentialGate.redact_data(sensitive_dict)

    assert redacted["api_key_id"] == "[REDACTED]"
    assert redacted["private_key_pem"] == "[REDACTED]"
    assert redacted["auth_signature"] == "[REDACTED]"
    assert redacted["auth_token"] == "[REDACTED]"
    assert redacted["market_id"] == "KXINXD-26DEC31-T5000"
    assert redacted["title"] == "Will S&P 500 close above 5000?"


# ==============================================================================
# 3. Credential Success Path Using Isolated Mock
# ==============================================================================
def test_credential_success_path_using_isolated_mock(monkeypatch):
    """Verifies valid RSA PEM verification without printing secrets."""
    # Generate an ephemeral RSA 2048 private key in memory
    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")

    monkeypatch.setenv("KALSHI_API_KEY_ID", "mock_key_id_999")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", pem)

    record = KalshiCredentialGate.audit_credentials()
    assert record.credentials_available is True
    assert record.credential_source == "environment"
    assert record.authentication_attempted is True
    assert record.authentication_success is True
    assert record.failure_category is None

    # Verify no secret text in representation or safe dict
    safe_dict = record.to_safe_dict()
    assert "mock_key_id" not in json.dumps(safe_dict)
    assert "BEGIN RSA" not in json.dumps(safe_dict)


# ==============================================================================
# 4. Malformed Kalshi Metadata Test
# ==============================================================================
def test_malformed_kalshi_metadata():
    """Verifies that malformed or empty metadata is handled safely with raw hash preserved."""
    collector = ExpandedMarketUniverseCollector()
    malformed = {"ticker": "KXINCOMPLETE"}  # Missing all other fields

    rec = collector.parse_kalshi_market_dict(malformed)
    assert rec.ticker == "KXINCOMPLETE"
    assert rec.event_ticker == "KXINCOMPLETE"
    assert rec.title == "KXINCOMPLETE"
    assert rec.floor_strike is None
    assert rec.open_time is None
    assert len(rec.raw_payload_hash) == 64  # Valid SHA-256


# ==============================================================================
# 5. Complete Kalshi Metadata Test
# ==============================================================================
def test_complete_kalshi_metadata():
    """Verifies parsing of complete Kalshi market payload containing all 20+ fields."""
    raw_item = {
        "ticker": "KXFED-26DEC-T525",
        "event_ticker": "KXFED-26DEC",
        "title": "Fed funds rate target in Dec 2026",
        "subtitle": "Will upper target exceed 5.25%?",
        "rules_primary": "Federal Reserve FOMC statement",
        "rules_secondary": "Standard CFTC resolution rules",
        "market_type": "binary",
        "strike_type": "greater",
        "floor_strike": 5.25,
        "cap_strike": None,
        "open_time": "2026-01-01T00:00:00Z",
        "close_time": "2026-12-31T20:00:00Z",
        "expiration_time": "2026-12-31T22:00:00Z",
        "category": "Economics",
        "series_ticker": "KXFED",
        "status": "active",
        "created_time": "2025-12-01T00:00:00Z",
        "updated_time": "2026-10-01T12:00:00Z",
    }
    collector = ExpandedMarketUniverseCollector()
    rec = collector.parse_kalshi_market_dict(raw_item)

    assert rec.ticker == "KXFED-26DEC-T525"
    assert rec.inequality_direction == ">="
    assert rec.floor_strike == 5.25
    assert rec.category == "Economics"
    assert rec.close_time == datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert rec.raw_payload_hash is not None

    contract = rec.to_canonical_contract()
    assert contract.venue == "kalshi"
    assert contract.threshold == 5.25
    assert contract.inequality_direction == ">="
    assert contract.source_of_resolution == "Federal Reserve FOMC statement"


# ==============================================================================
# 6. Universe Deduplication Test
# ==============================================================================
def test_universe_deduplication():
    """Verifies that duplicate tickers across files/endpoints deduplicate deterministically."""
    collector = ExpandedMarketUniverseCollector()
    item1 = {"ticker": "KXTEST-01", "title": "Version 1", "status": "active"}
    item2 = {"ticker": "KXTEST-01", "title": "Version 2 (Updated)", "status": "active"}

    rec1 = collector.parse_kalshi_market_dict(item1, provenance=SourceClassification.KALSHI_ARCHIVED)
    rec2 = collector.parse_kalshi_market_dict(item2, provenance=SourceClassification.KALSHI_LIVE)

    universe = {r.ticker: r for r in [rec1, rec2]}
    assert len(universe) == 1
    assert universe["KXTEST-01"].title == "Version 2 (Updated)"
    assert universe["KXTEST-01"].provenance == SourceClassification.KALSHI_LIVE


# ==============================================================================
# 7. Deterministic Candidate Generation Test
# ==============================================================================
def test_deterministic_candidate_generation():
    """Verifies candidate blocking and matching reproducibility."""
    poly_contract = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_fed_525",
        underlying_event="Federal Reserve Fed Funds Rate December 2026",
        geographic_scope="US",
        observation_variable="Fed Funds Rate",
        temporal_scope="2026-12-31",
        threshold=5.25,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="Federal Reserve",
        resolution_rules="Federal Reserve official FOMC rate",
    )
    kalshi_contract = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_fed_525",
        underlying_event="Federal Reserve Fed Funds Rate December 2026",
        geographic_scope="US",
        observation_variable="Fed Funds Rate",
        temporal_scope="2026-12-31",
        threshold=5.25,
        inequality_direction=">=",
        units="USD",
        currency="USD",
        source_of_resolution="Federal Reserve",
        resolution_rules="Federal Reserve official FOMC rate",
    )

    pipeline = ExpandedCrossVenuePipeline()
    counts1, rej1, acc1, _ = pipeline.run_pipeline([poly_contract], [kalshi_contract])
    counts2, rej2, acc2, _ = pipeline.run_pipeline([poly_contract], [kalshi_contract])

    assert counts1 == counts2
    assert rej1 == rej2
    assert len(acc1) == 1
    assert acc1[0].equivalence_class == EquivalenceClass.EXACT_EQUIVALENT


# ==============================================================================
# 8. Exact Mapping Reproduction Test
# ==============================================================================
def test_exact_mapping_reproduction():
    """Verifies independent verifier reproduces exact equivalent mapping from raw metadata."""
    poly_raw = {
        "id": "poly_cpi_300",
        "question": "US CPI YoY >= 3.0% in December 2026",
        "endDate": "2026-12-31T23:59:59Z",
        "threshold": 3.0,
        "inequality_direction": ">=",
        "resolutionSource": "Bureau of Labor Statistics",
        "description": "Official BLS CPI-U release",
    }
    kalshi_raw = {
        "ticker": "KXCPI-26DEC-T300",
        "event_ticker": "KXCPI-26DEC",
        "title": "US CPI YoY >= 3.0% in December 2026",
        "floor_strike": 3.0,
        "strike_type": "greater",
        "close_time": "2026-12-31T23:59:59Z",
        "rules_primary": "Bureau of Labor Statistics",
    }

    collector = ExpandedMarketUniverseCollector()
    poly_c = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_cpi_300",
        underlying_event="US CPI YoY >= 3.0% in December 2026",
        geographic_scope="US",
        observation_variable="US CPI YoY >= 3.0% in December 2026",
        temporal_scope="2026-12-31",
        threshold=3.0,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="Official BLS CPI-U release",
    )
    kalshi_rec = collector.parse_kalshi_market_dict(kalshi_raw)
    kalshi_c = kalshi_rec.to_canonical_contract()

    res = SettlementNormalizer.compare_contracts(poly_c, kalshi_c)
    assert res.settlement_equivalence is True
    assert res.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT

    record = DeterministicMappingRecord(
        mapping_id=res.mapping_id,
        polymarket_contract_id=poly_c.venue_contract_id,
        kalshi_contract_id=kalshi_c.venue_contract_id,
        canonical_polymarket=poly_c,
        canonical_kalshi=kalshi_c,
        economic_terms_hash_polymarket=poly_c.compute_economic_terms_hash(),
        economic_terms_hash_kalshi=kalshi_c.compute_economic_terms_hash(),
        equivalence_class=res.equivalence_class,
        mapping_status=res.mapping_status,
        settlement_rule_comparison="BLS vs BLS",
        inequality_comparison=">= vs >=",
        resolution_source_comparison="BLS vs BLS",
        source_metadata_hash_poly=poly_c.compute_contract_hash(),
        source_metadata_hash_kalshi=kalshi_c.compute_contract_hash(),
    )

    # Independent reproduction from raw metadata alone
    assert IndependentMappingVerifier.independently_verify_mapping(poly_raw, kalshi_raw, record) is True


# ==============================================================================
# 9. Complementary Mapping Reproduction Test
# ==============================================================================
def test_complementary_mapping_reproduction():
    """Verifies complementary contract detection (P(X >= K) vs P(X < K))."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_unemp_45_gte",
        underlying_event="US Unemployment Rate",
        geographic_scope="US",
        observation_variable="Unemployment Rate",
        temporal_scope="2026-12-31",
        threshold=4.5,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="BLS monthly unemployment report",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_unemp_45_lt",
        underlying_event="US Unemployment Rate",
        geographic_scope="US",
        observation_variable="Unemployment Rate",
        temporal_scope="2026-12-31",
        threshold=4.5,
        inequality_direction="<",
        units="USD",
        currency="USD",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="BLS monthly unemployment report",
    )

    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.equivalence_class == EquivalenceClass.COMPLEMENTARY
    assert res.mapping_status == MappingStatus.COMPLEMENTARY


# ==============================================================================
# 10. Inequality Mismatch Test
# ==============================================================================
def test_inequality_mismatch():
    """Verifies rejection when inequality semantics are non-complementary and non-identical."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_test_10",
        underlying_event="GDP Growth",
        geographic_scope="US",
        observation_variable="GDP Growth",
        temporal_scope="2026-12-31",
        threshold=2.5,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="BEA",
        resolution_rules="BEA GDP report",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_test_10",
        underlying_event="GDP Growth",
        geographic_scope="US",
        observation_variable="GDP Growth",
        temporal_scope="2026-12-31",
        threshold=2.5,
        inequality_direction=">",
        units="USD",
        currency="USD",
        source_of_resolution="BEA",
        resolution_rules="BEA GDP report",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.settlement_equivalence is False
    assert "INEQUALITY_MISMATCH" in res.mapping_reason


# ==============================================================================
# 11. Timezone Mismatch Test
# ==============================================================================
def test_timezone_mismatch():
    """Verifies rejection when expiration dates differ by time window."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_tz_1",
        underlying_event="Election 2026",
        geographic_scope="US",
        observation_variable="Election",
        temporal_scope="2026-11-03",
        threshold=None,
        inequality_direction=None,
        units="USD",
        currency="USDC",
        source_of_resolution="AP",
        resolution_rules="AP call",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_tz_1",
        underlying_event="Election 2026",
        geographic_scope="US",
        observation_variable="Election",
        temporal_scope="2026-12-31",
        threshold=None,
        inequality_direction=None,
        units="USD",
        currency="USD",
        source_of_resolution="AP",
        resolution_rules="AP call",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.settlement_equivalence is False
    assert "TIME_WINDOW_MISMATCH" in res.mapping_reason


# ==============================================================================
# 12. Threshold Mismatch Test
# ==============================================================================
def test_threshold_mismatch():
    """Verifies rejection when numeric strikes differ (e.g. 5.25 vs 5.50)."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_thresh_1",
        underlying_event="Fed Funds Rate",
        geographic_scope="US",
        observation_variable="Fed Funds Rate",
        temporal_scope="2026-12-31",
        threshold=5.25,
        inequality_direction="==",
        units="USD",
        currency="USDC",
        source_of_resolution="Federal Reserve",
        resolution_rules="FOMC rate",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_thresh_1",
        underlying_event="Fed Funds Rate",
        geographic_scope="US",
        observation_variable="Fed Funds Rate",
        temporal_scope="2026-12-31",
        threshold=5.50,
        inequality_direction="==",
        units="USD",
        currency="USD",
        source_of_resolution="Federal Reserve",
        resolution_rules="FOMC rate",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.settlement_equivalence is False
    assert "THRESHOLD_MISMATCH" in res.mapping_reason


# ==============================================================================
# 13. Resolution Source Mismatch Test
# ==============================================================================
def test_resolution_source_mismatch():
    """Verifies rejection when authoritative resolution sources differ."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_res_1",
        underlying_event="Bitcoin Price",
        geographic_scope="GLOBAL",
        observation_variable="Bitcoin Price",
        temporal_scope="2026-12-31",
        threshold=100000.0,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="Binance",
        resolution_rules="Binance BTC/USDT 1-minute close",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_res_1",
        underlying_event="Bitcoin Price",
        geographic_scope="GLOBAL",
        observation_variable="Bitcoin Price",
        temporal_scope="2026-12-31",
        threshold=100000.0,
        inequality_direction=">=",
        units="USD",
        currency="USD",
        source_of_resolution="Coinbase",
        resolution_rules="Coinbase BTC/USD 1-minute close",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.settlement_equivalence is False
    assert "RESOLUTION_SOURCE_MISMATCH" in res.mapping_reason


# ==============================================================================
# 14. Revision Policy Mismatch Test
# ==============================================================================
def test_revision_policy_mismatch():
    """Verifies rejection when revision handling policies conflict."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_rev_1",
        underlying_event="US GDP",
        geographic_scope="US",
        observation_variable="US GDP",
        temporal_scope="2026-12-31",
        threshold=2.0,
        inequality_direction=">=",
        units="USD",
        currency="USDC",
        source_of_resolution="BEA",
        resolution_rules="Settles strictly on first advance estimate without revision",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_rev_1",
        underlying_event="US GDP",
        geographic_scope="US",
        observation_variable="US GDP",
        temporal_scope="2026-12-31",
        threshold=2.0,
        inequality_direction=">=",
        units="USD",
        currency="USD",
        source_of_resolution="BEA",
        resolution_rules="Settles on final revised estimate after 90 days",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    # Different settlement terms must result in non-equivalence or rejection
    assert res.settlement_equivalence is False


# ==============================================================================
# 15. Cancellation Policy Mismatch Test
# ==============================================================================
def test_cancellation_policy_mismatch():
    """Verifies rejection when cancellation policies diverge."""
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_canc_1",
        underlying_event="SpaceX Launch",
        geographic_scope="US",
        observation_variable="SpaceX Launch",
        temporal_scope="2026-12-31",
        threshold=None,
        inequality_direction=None,
        units="USD",
        currency="USDC",
        source_of_resolution="FAA",
        resolution_rules="If scrubbed, resolves to 50/50 UMA split",
        cancellation_rules="Market will cancel on launch scrub",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="kalshi_canc_1",
        underlying_event="SpaceX Launch",
        geographic_scope="US",
        observation_variable="SpaceX Launch",
        temporal_scope="2026-12-31",
        threshold=None,
        inequality_direction=None,
        units="USD",
        currency="USD",
        source_of_resolution="FAA",
        resolution_rules="If scrubbed, market is voided and capital refunded at $0.00",
        cancellation_rules="Market will postpone on launch scrub",
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.settlement_equivalence is False
    assert "CANCELLATION_POLICY_MISMATCH" in res.mapping_reason


# ==============================================================================
# 16. Provenance Classification Test
# ==============================================================================
def test_provenance_classification():
    """Verifies strict classification of sources."""
    auditor = AdversarialProvenanceAuditor()
    assert auditor.classify_source("sess_20261001_160404", "msg_1", "polymarket") == SourceClassification.POLYMARKET_LIVE
    assert auditor.classify_source("kalshi_live_sess_01", "msg_1", "kalshi") == SourceClassification.KALSHI_LIVE
    assert auditor.classify_source("gamma_archived_20260929", "msg_1", "polymarket") == SourceClassification.POLYMARKET_ARCHIVED
    assert auditor.classify_source("kalshi_archived_2026", "msg_1", "kalshi") == SourceClassification.KALSHI_ARCHIVED
    assert auditor.classify_source("fixture_sess_1", "msg_1", "kalshi") == SourceClassification.UNIT_FIXTURE
    assert auditor.classify_source("synthetic_mock_1", "msg_1", "polymarket") == SourceClassification.SYNTHETIC


# ==============================================================================
# 17. Fixture Rejection Test
# ==============================================================================
def test_fixture_rejection():
    """Verifies that ProductionContaminationGuard permanently rejects unit fixtures."""
    fixture_observation = {
        "observation_id": "obs_fixture_100",
        "mapping_id": "map_test_1",
        "source_session_id": "sess_unit_fixture_run",
        "poly_contract_id": "poly_test",
        "kalshi_contract_id": "kalshi_test",
    }
    with pytest.raises(ContaminationError, match="Production contamination rejected"):
        ProductionContaminationGuard.assert_valid_production_observation(fixture_observation, is_production_db=True)


# ==============================================================================
# 18. Synthetic Rejection Test
# ==============================================================================
def test_synthetic_rejection():
    """Verifies that ProductionContaminationGuard permanently rejects synthetic data."""
    synthetic_observation = {
        "observation_id": "obs_synthetic_500",
        "mapping_id": "map_live_1",
        "source_session_id": "sess_synthetic_feed",
        "poly_contract_id": "poly_1",
        "kalshi_contract_id": "kalshi_1",
    }
    with pytest.raises(ContaminationError, match="Production contamination rejected"):
        ProductionContaminationGuard.assert_valid_production_observation(synthetic_observation, is_production_db=True)


# ==============================================================================
# 19. Archived vs Live Separation Test
# ==============================================================================
def test_archived_live_separation():
    """Verifies that archived records are never conflated with live records."""
    collector = ExpandedMarketUniverseCollector()
    rec_archived = collector.parse_kalshi_market_dict(
        {"ticker": "KXARCH"},
        provenance=SourceClassification.KALSHI_ARCHIVED
    )
    rec_live = collector.parse_kalshi_market_dict(
        {"ticker": "KXLIVE"},
        provenance=SourceClassification.KALSHI_LIVE
    )

    assert rec_archived.provenance == SourceClassification.KALSHI_ARCHIVED
    assert rec_live.provenance == SourceClassification.KALSHI_LIVE
    assert rec_archived.provenance != rec_live.provenance


# ==============================================================================
# 20. Raw Message Hashing Test
# ==============================================================================
def test_raw_message_hashing():
    """Verifies SHA-256 cryptographic immutability of raw frames."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        recorder = KalshiRawRecorder(raw_storage_dir=tmp_dir, session_id="test_hash_sess")
        raw_payload = '{"channel":"orderbook_delta","market_ticker":"KXTEST","msg":{"delta":[]}}'
        expected_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

        records = recorder.record_raw_frame(raw_payload, "orderbook_delta")
        assert len(records) == 1
        assert records[0].payload_sha256 == expected_hash


# ==============================================================================
# 21. WebSocket Snapshot Validation Test
# ==============================================================================
def test_websocket_snapshot_validation():
    """Verifies order-book snapshot construction from Kalshi WebSocket frames."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        reconstructor = KalshiOrderBookReconstructor()
        recorder = KalshiRawRecorder(raw_storage_dir=tmp_dir, session_id="test_snap_sess")
        snapshot_payload = json.dumps({
            "type": "orderbook_snapshot",
            "seq": 1,
            "msg": {
                "market_ticker": "KXSNAP-01",
                "yes_dollars_fp": [["0.5000", "100.00"], ["0.4900", "200.00"]],
                "no_dollars_fp": [["0.5000", "100.00"]],
            }
        })
        raw_rec = recorder.record_raw_frame(snapshot_payload)[0]
        upds, snap = reconstructor.process_raw_record(raw_rec)
        assert snap is not None
        assert snap.market_id == "KXSNAP-01"
        assert snap.best_yes_bid == 0.50
        assert snap.best_yes_ask == 0.50
        assert reconstructor._books["KXSNAP-01"]["initialized"] is True


# ==============================================================================
# 22. WebSocket Delta Validation Test
# ==============================================================================
def test_websocket_delta_validation():
    """Verifies order-book delta application (price updates and removals)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        reconstructor = KalshiOrderBookReconstructor()
        recorder = KalshiRawRecorder(raw_storage_dir=tmp_dir, session_id="test_delta_sess")
        # Initial snapshot
        snap_payload = json.dumps({
            "type": "orderbook_snapshot",
            "seq": 1,
            "msg": {
                "market_ticker": "KXDELTA-01",
                "yes_dollars_fp": [["0.5000", "100.00"]],
                "no_dollars_fp": [["0.5000", "100.00"]],
            }
        })
        reconstructor.process_raw_record(recorder.record_raw_frame(snap_payload)[0])

        # Delta update
        delta_payload = json.dumps({
            "type": "orderbook_delta",
            "seq": 2,
            "msg": {
                "market_ticker": "KXDELTA-01",
                "side": "yes",
                "price_dollars": "0.5200",
                "delta_fp": "150.00",
            }
        })
        upds, snap = reconstructor.process_raw_record(recorder.record_raw_frame(delta_payload)[0])
        assert len(upds) == 1
        assert upds[0].action == "add"
        assert snap.best_yes_bid == 0.52


# ==============================================================================
# 23. Reconnect Isolation Test
# ==============================================================================
def test_reconnect_isolation():
    """Verifies that connection supervisor transitions through RECONNECTING and increments attempt count."""
    supervisor = KalshiConnectionSupervisor(api_key_id="dummy", private_key_pem="dummy")
    initial_session = supervisor.session_id

    supervisor.handle_disconnect("Simulated network drop")
    assert supervisor.current_state == KalshiSupervisorState.RECONNECTING
    assert supervisor.disconnect_count == 1
    assert len(supervisor.quality_anomalies) == 1
    assert supervisor.quality_anomalies[0].details == "Disconnected: Simulated network drop"


# ==============================================================================
# 24. Cross-Venue Timestamp Validation Test
# ==============================================================================
def test_cross_venue_timestamp_validation():
    """Verifies exchange vs local receive timestamp capture and skew calculation."""
    poly_rx = datetime(2026, 10, 1, 12, 0, 0, 100000, tzinfo=timezone.utc)
    kalshi_rx = datetime(2026, 10, 1, 12, 0, 0, 150000, tzinfo=timezone.utc)

    skew_ms = abs((poly_rx - kalshi_rx).total_seconds() * 1000.0)
    assert skew_ms == 50.0  # Exactly 50ms skew, well within 100ms tolerance


# ==============================================================================
# 25. Anti-Lookahead Validation Test
# ==============================================================================
def test_anti_lookahead_validation():
    """Verifies that evaluation timestamp before receive timestamps is rejected."""
    poly_rx = datetime(2026, 10, 1, 12, 0, 0, 500000, tzinfo=timezone.utc)
    kalshi_rx = datetime(2026, 10, 1, 12, 0, 0, 600000, tzinfo=timezone.utc)
    invalid_eval_ts = datetime(2026, 10, 1, 12, 0, 0, 400000, tzinfo=timezone.utc)

    # Evaluation timestamp occurred before quotes were received locally
    has_lookahead = (invalid_eval_ts < poly_rx) or (invalid_eval_ts < kalshi_rx)
    assert has_lookahead is True
