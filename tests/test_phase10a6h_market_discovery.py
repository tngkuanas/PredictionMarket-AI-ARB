"""Tests for Phase 10A.6H Deterministic Market Discovery and Equivalence Validation.

Validates:
1. Exact equivalent markets
2. Complementary markets
3. Nested markets
4. Threshold mismatch
5. Inequality mismatch
6. Date mismatch
7. Timezone mismatch
8. Geography mismatch
9. Resolution source mismatch
10. Revision-policy mismatch
11. Cancellation mismatch
12. Missing metadata
13. Ambiguous mapping
14. Duplicate contract
15. One-to-many mapping
16. Metadata-version change
17. Price-independence
18. Deterministic reproducibility
19. Synonym-dictionary hashing
20. Provenance completeness
"""

from datetime import datetime, timezone, timedelta
import os
import shutil
import tempfile
from typing import Dict, Any, List
import pytest

from src.cross_venue.schema import (
    CanonicalEconomicContract,
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer
from src.cross_venue.cross_venue_market_discovery import (
    RejectionReason,
    CandidateFilterStatus,
    ContractCardinality,
    ContractStatus,
    DiscoveryConfig,
    ConservativeTextNormalizer,
    PolymarketCanonicalAdapter,
    KalshiCanonicalAdapter,
    MarketCandidatePair,
    MappingProvenance,
    MappingVersionRecord,
    CrossVenueMappingGraph,
    DiscoveryRunSummary,
    CrossVenueMarketDiscovery,
)
from src.cross_venue.db_store import CrossVenueDBStore


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def eval_timestamp() -> datetime:
    return datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def canonical_cpi_pair(eval_timestamp) -> tuple[CanonicalEconomicContract, CanonicalEconomicContract]:
    res_dt = datetime(2026, 12, 15, 13, 30, 0, tzinfo=timezone.utc)
    poly = CanonicalEconomicContract(
        venue="polymarket",
        venue_contract_id="poly_cpi_202612_yes",
        underlying_event="US CPI YoY >= 2.5% for December 2026",
        observation_variable="US CPI YoY",
        geographic_scope="US",
        temporal_scope="December 2026",
        resolution_timestamp=res_dt,
        threshold=2.5,
        inequality_direction=">=",
        units="PERCENT",
        currency="USDC",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="Official BLS CPI-U All Items YoY rate for December 2026 as released.",
        cancellation_rules="Market resolves to Other if BLS cancels or fails to publish.",
        invalidation_rules="Official determination from BLS is binding.",
    )
    kalshi = CanonicalEconomicContract(
        venue="kalshi",
        venue_contract_id="KXCPIDEC26-2.5",
        underlying_event="US CPI YoY >= 2.5% for December 2026",
        observation_variable="US CPI YoY",
        geographic_scope="US",
        temporal_scope="December 2026",
        resolution_timestamp=res_dt,
        threshold=2.5,
        inequality_direction=">=",
        units="PERCENT",
        currency="USD",
        source_of_resolution="Bureau of Labor Statistics",
        resolution_rules="Official BLS CPI-U All Items YoY rate for December 2026 as released.",
        cancellation_rules="Market resolves to Other if BLS cancels or fails to publish.",
        invalidation_rules="Official determination from BLS is binding.",
    )
    return poly, kalshi


@pytest.fixture
def temp_db_store():
    temp_dir = tempfile.mkdtemp(prefix="test_phase10a6h_")
    db_file = os.path.join(temp_dir, "test_discovery.duckdb")
    store = CrossVenueDBStore(db_path=db_file)
    yield store
    shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# TESTS
# =====================================================================

# 1. Exact Equivalent Markets
def test_exact_equivalent_markets(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    res = SettlementNormalizer.compare_contracts(poly, kalshi)
    assert res.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT
    assert res.settlement_equivalence is True
    assert res.mapping_status == MappingStatus.EXACT_EQUIVALENT
    assert "EXACT_EQUIVALENT" in res.mapping_reason


# 2. Complementary Markets
def test_complementary_markets(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_comp = kalshi.model_copy(update={"inequality_direction": "<"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_comp)
    assert res.equivalence_class == EquivalenceClass.COMPLEMENTARY
    assert res.settlement_equivalence is False
    assert res.mapping_status == MappingStatus.COMPLEMENTARY


# 3. Nested Markets
def test_nested_markets(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_nested = kalshi.model_copy(update={"threshold": 3.0})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_nested)
    assert res.equivalence_class == EquivalenceClass.NESTED
    assert res.settlement_equivalence is False
    assert res.mapping_status == MappingStatus.NESTED


# 4. Threshold Mismatch
def test_threshold_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_diff = kalshi.model_copy(update={"threshold": 4.5, "inequality_direction": "<="})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_diff)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "THRESHOLD_MISMATCH" in res.mapping_reason


# 5. Inequality Mismatch
def test_inequality_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_strict = kalshi.model_copy(update={"inequality_direction": ">"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_strict)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert res.mapping_status == MappingStatus.AMBIGUOUS
    assert "INEQUALITY_MISMATCH" in res.mapping_reason or "INEQUALITY_STRICTNESS_MISMATCH" in res.mapping_reason


# 6. Date Mismatch
def test_date_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_date = kalshi.model_copy(update={"temporal_scope": "January 2027"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_date)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "TIME_WINDOW_MISMATCH" in res.mapping_reason or "DATE_MISMATCH" in res.mapping_reason


# 7. Timezone Mismatch
def test_timezone_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    # 5 hour difference due to UTC vs EST offset
    kalshi_tz = kalshi.model_copy(
        update={"resolution_timestamp": datetime(2026, 12, 15, 13, 30, 0, tzinfo=timezone(timedelta(hours=-5)))}
    )
    res = SettlementNormalizer.compare_contracts(poly, kalshi_tz)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "TIMEZONE_MISMATCH" in res.mapping_reason or "RESOLUTION_TIME_MISMATCH" in res.mapping_reason


# 8. Geography Mismatch
def test_geography_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_eu = kalshi.model_copy(update={"geographic_scope": "EUR"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_eu)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "GEOGRAPHY_MISMATCH" in res.mapping_reason


# 9. Resolution Source Mismatch
def test_resolution_source_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_src = kalshi.model_copy(update={"source_of_resolution": "Bloomberg Proprietary Analytics"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_src)
    assert res.equivalence_class == EquivalenceClass.SEMANTIC_ONLY
    assert res.settlement_equivalence is False
    assert "RESOLUTION_SOURCE_MISMATCH" in res.mapping_reason


# 10. Revision-Policy Mismatch
def test_revision_policy_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    poly_prelim = poly.model_copy(update={
        "resolution_rules": "Resolves based on preliminary initial first release.",
        "invalidation_rules": "Preliminary first release is authoritative."
    })
    kalshi_final = kalshi.model_copy(update={
        "resolution_rules": "Resolves based strictly on final revised figures.",
        "invalidation_rules": "Final revised figures are authoritative."
    })
    res = SettlementNormalizer.compare_contracts(poly_prelim, kalshi_final)
    assert res.equivalence_class == EquivalenceClass.SEMANTIC_ONLY
    assert "REVISION_POLICY_MISMATCH" in res.mapping_reason


# 11. Cancellation Mismatch
def test_cancellation_mismatch(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    poly_void = poly.model_copy(update={"cancellation_rules": "Void market if postponed or delayed past 24 hours."})
    kalshi_delay = kalshi.model_copy(update={"cancellation_rules": "Market will delay expiration indefinitely until release."})
    res = SettlementNormalizer.compare_contracts(poly_void, kalshi_delay)
    assert res.equivalence_class == EquivalenceClass.NON_EQUIVALENT
    assert "CANCELLATION_POLICY_MISMATCH" in res.mapping_reason or "CANCELLATION_RULE_MISMATCH" in res.mapping_reason


# 12. Missing Metadata
def test_missing_metadata(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    poly_missing = poly.model_copy(update={"underlying_event": ""})
    res = SettlementNormalizer.compare_contracts(poly_missing, kalshi)
    assert res.mapping_status == MappingStatus.INSUFFICIENT_DATA
    assert "MISSING_REQUIRED_METADATA" in res.mapping_reason or "INSUFFICIENT_DATA" in res.mapping_reason


# 13. Ambiguous Mapping
def test_ambiguous_mapping(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_amb = kalshi.model_copy(update={"inequality_direction": ">"})
    res = SettlementNormalizer.compare_contracts(poly, kalshi_amb)
    assert res.mapping_status == MappingStatus.AMBIGUOUS
    assert "AMBIGUOUS" in res.mapping_status.value


# 14. Duplicate Contract Detection
def test_duplicate_contract(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    graph = CrossVenueMappingGraph()
    # Add poly contract
    graph.nodes[poly.venue_contract_id] = {
        "venue": "polymarket", "id": poly.venue_contract_id, "canonical_hash": poly.compute_economic_terms_hash()
    }
    # Add duplicate with different ID but same terms
    poly_dup = poly.model_copy(update={"venue_contract_id": "poly_cpi_dup"})
    graph.nodes[poly_dup.venue_contract_id] = {
        "venue": "polymarket", "id": poly_dup.venue_contract_id, "canonical_hash": poly_dup.compute_economic_terms_hash()
    }

    dups = graph.detect_duplicates("polymarket")
    assert len(dups) == 1
    assert dups[0][0] == poly.venue_contract_id
    assert dups[0][1] == poly_dup.venue_contract_id


# 15. One-to-Many Mapping
def test_one_to_many_mapping(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    kalshi_2 = kalshi.model_copy(update={"venue_contract_id": "KXCPIDEC26-3.0", "threshold": 3.0})

    discovery = CrossVenueMarketDiscovery()
    summary = discovery.run_discovery([poly], [kalshi, kalshi_2], persist=False)
    
    cardinality = discovery.graph.get_cardinality()
    assert len(cardinality) == 2
    for m_id, card in cardinality.items():
        assert card == ContractCardinality.ONE_TO_MANY


# 16. Metadata-Version Change
def test_metadata_version_change(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    discovery = CrossVenueMarketDiscovery()
    summary = discovery.run_discovery([poly], [kalshi], persist=False)
    
    mapping_id = list(discovery.version_tracker.keys())[0]
    rec_v1 = discovery.version_tracker[mapping_id]
    assert rec_v1.contract_status == ContractStatus.ACTIVE
    assert rec_v1.version_index == 1

    # Invalidate due to terms change
    new_rec = discovery.invalidate_mapping_due_to_metadata_change(mapping_id, reason="SETTLEMENT_RULES_AMENDED")
    assert new_rec is not None
    assert new_rec.version_index == 2
    assert new_rec.contract_status == ContractStatus.ACTIVE
    assert rec_v1.contract_status == ContractStatus.INVALIDATED
    assert rec_v1.mapping_end is not None


# 17. Price Independence Test
def test_price_independence(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    discovery = CrossVenueMarketDiscovery()

    # Run 1: with baseline contracts
    summary1 = discovery.run_discovery([poly], [kalshi], persist=False)

    # Simulate raw market payloads with varying price fields
    poly_raw_low = {
        "id": "poly_test", "question": poly.underlying_event, "description": poly.resolution_rules,
        "resolutionSource": poly.source_of_resolution, "endDate": poly.resolution_timestamp.isoformat(),
        "price": 0.10, "yes_bid": 0.09, "yes_ask": 0.11, "volume": 500.0, "liquidity": 1000.0,
        "clobTokenIds": ["tok_yes_1"]
    }
    kalshi_raw_low = {
        "ticker": "kalshi_test", "title": kalshi.underlying_event, "rules_primary": kalshi.resolution_rules,
        "settlement_source": kalshi.source_of_resolution, "close_time": kalshi.resolution_timestamp.isoformat(),
        "yes_bid_dollars": "0.15", "yes_ask_dollars": "0.18", "volume_fp": "100.0", "liquidity_dollars": "500.0"
    }

    poly_raw_high = dict(poly_raw_low, price=0.92, yes_bid=0.90, yes_ask=0.94, volume=9999999.0, liquidity=5000000.0)
    kalshi_raw_high = dict(kalshi_raw_low, yes_bid_dollars="0.85", yes_ask_dollars="0.88", volume_fp="8888888.0", liquidity_dollars=4000000.0)

    # Adapters convert without price contamination
    poly_ad_low = discovery.poly_adapter.adapt_market(poly_raw_low)
    kalshi_ad_low = discovery.kalshi_adapter.adapt_market(kalshi_raw_low)
    poly_ad_high = discovery.poly_adapter.adapt_market(poly_raw_high)
    kalshi_ad_high = discovery.kalshi_adapter.adapt_market(kalshi_raw_high)

    res_low = SettlementNormalizer.compare_contracts(poly_ad_low, kalshi_ad_low)
    res_high = SettlementNormalizer.compare_contracts(poly_ad_high, kalshi_ad_high)

    # Verify identical classification and hashing regardless of prices
    assert res_low.equivalence_class == res_high.equivalence_class
    assert res_low.settlement_equivalence == res_high.settlement_equivalence
    assert res_low.compute_mapping_hash() == res_high.compute_mapping_hash()


# 18. Deterministic Reproducibility
def test_deterministic_reproducibility(canonical_cpi_pair, temp_db_store):
    poly, kalshi = canonical_cpi_pair
    discovery = CrossVenueMarketDiscovery(db_store=temp_db_store)

    summary1 = discovery.run_discovery([poly], [kalshi], persist=True)
    summary2 = discovery.run_discovery([poly], [kalshi], persist=False)

    assert summary1.config_hash == summary2.config_hash
    assert summary1.exact_equivalent_count == summary2.exact_equivalent_count
    assert summary1.candidate_pairs_generated == summary2.candidate_pairs_generated
    assert summary1.validation_count == summary2.validation_count

    # Check persistence in DuckDB
    conn = temp_db_store._get_connection(read_only=True)
    try:
        cand_count = conn.execute("SELECT COUNT(*) FROM phase10a6h_market_candidates").fetchone()[0]
        assert cand_count >= 1
        res_count = conn.execute("SELECT COUNT(*) FROM phase10a6h_mapping_results").fetchone()[0]
        assert res_count >= 1
    finally:
        conn.close()


# 19. Synonym Dictionary Hashing
def test_synonym_dictionary_hashing():
    cfg1 = DiscoveryConfig()
    hash1 = cfg1.compute_synonym_dict_hash()
    assert len(hash1) == 64

    # Alter synonym dictionary
    synonyms_modified = dict(cfg1.synonyms)
    synonyms_modified["new_term"] = "canonical_new_term"
    cfg2 = DiscoveryConfig(synonyms=synonyms_modified)
    hash2 = cfg2.compute_synonym_dict_hash()

    assert hash1 != hash2
    assert len(hash2) == 64


# 20. Provenance Completeness
def test_provenance_completeness(canonical_cpi_pair):
    poly, kalshi = canonical_cpi_pair
    discovery = CrossVenueMarketDiscovery()
    candidates = discovery.generate_candidates([poly], [kalshi])
    validated = discovery.validate_candidates(candidates)

    assert len(validated) == 1
    mapping, prov = validated[0]

    assert prov.mapping_id and len(prov.mapping_id) > 0
    assert prov.polymarket_market_id == poly.venue_contract_id
    assert prov.kalshi_market_id == kalshi.venue_contract_id
    assert prov.canonical_contract_id and len(prov.canonical_contract_id) > 0
    assert prov.normalization_version == "1.0.0"
    assert len(prov.synonym_dict_hash) == 64
    assert len(prov.poly_metadata_hash) == 64
    assert len(prov.kalshi_metadata_hash) == 64
    assert prov.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT
    assert len(prov.validation_reason) > 0
    assert len(prov.config_hash) == 64
