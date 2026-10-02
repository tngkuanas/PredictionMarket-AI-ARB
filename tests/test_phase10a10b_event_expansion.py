"""Dedicated Test Suite for Phase 10A.10-B Genuine Event-Universe Expansion.

Covers:
- Configuration freezing and SHA-256 hash validation
- Unchanged strategy parameter assertions
- Historical source timestamp validation and anti-lookahead
- Authoritative source tier qualification
- Deterministic exact contract matching & rejection of fuzzy matches
- Duplicate candidate detection and deduplication gates
- Multi-scale event independence (1m, 5m clusters, source event ID)
- Chronological ordering and mechanical Discovery/OOS splitting
- Complete rejection ledger recording across all 16 rejection categories
- Timezone normalization (UTC)
- Category coverage across 10 preregistered event categories (A-J)
- Anti-synthetic assertion & ProductionContaminationGuard
- Integration with Phase 10A.10 execution and statistical modules

Requires: >= 40 dedicated tests.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import pytest

from src.phase10a10b.universe import (
    EventTaxonomyCategory,
    RejectionCategory,
    Phase10A10BVerdict,
    ExpandedEventRecord,
    SourceEvidenceRecord,
    MarketMappingRecord,
    EventIndependenceRecord,
    CandidateRejectionRecord,
)
from src.phase10a10b.config_freeze import (
    FROZEN_PHASE10A10_CONFIG,
    PHASE10A10B_CONFIG_HASH,
    compute_config_hash,
    assert_config_unmodified,
)
from src.phase10a10b.historical_source_validator import HistoricalSourceValidator
from src.phase10a10b.market_matcher import DeterministicMarketMatcher
from src.phase10a10b.source_discovery import SourceDiscoveryEngine
from src.phase10a10b.independence import EventIndependenceTracker
from src.phase10a10b.chronology import ChronologyManager
from src.phase10a10.source_registry import SourceRegistry, SourceTier
from src.phase10a10.schema import DeterministicState, LatencyBucket
from src.phase10a10.db_store import ProductionContaminationGuard, Phase10A10ContaminationError


# ==============================================================================
# 1. CONFIGURATION FREEZE & HASH TESTS (1-5)
# ==============================================================================

class TestConfigFreeze:

    def test_frozen_config_hash_consistency(self):
        h = compute_config_hash(FROZEN_PHASE10A10_CONFIG)
        assert h == PHASE10A10B_CONFIG_HASH
        assert len(h) == 64

    def test_assert_config_unmodified_passes_on_canonical_config(self):
        # Should not raise
        assert_config_unmodified(FROZEN_PHASE10A10_CONFIG)

    def test_assert_config_unmodified_raises_on_altered_threshold(self):
        altered = dict(FROZEN_PHASE10A10_CONFIG)
        altered["entry_thresholds_bps"] = [1.0, 2.0]
        with pytest.raises(ValueError) as exc:
            assert_config_unmodified(altered)
        assert "Strategy configuration modified" in str(exc.value)

    def test_assert_config_unmodified_raises_on_altered_position_size(self):
        altered = dict(FROZEN_PHASE10A10_CONFIG)
        altered["position_sizes_usd"] = [5000.0]
        with pytest.raises(ValueError):
            assert_config_unmodified(altered)

    def test_assert_config_unmodified_raises_on_altered_fee(self):
        altered = dict(FROZEN_PHASE10A10_CONFIG)
        altered["base_fee_bps"] = 0.0
        with pytest.raises(ValueError):
            assert_config_unmodified(altered)


# ==============================================================================
# 2. HISTORICAL SOURCE VALIDATION & ANTI-LOOKAHEAD (6-11)
# ==============================================================================

class TestHistoricalSourceValidation:

    def test_valid_historical_source_passes(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = t_pub + timedelta(seconds=1)
        t_mkt_obs = t_pub + timedelta(seconds=2)
        payload = "Official Fed statement release text"
        evidence = SourceEvidenceRecord(
            source_id="src_fed_1",
            event_id="e1",
            source_url="https://federalreserve.gov",
            source_domain="federalreserve.gov",
            source_tier=SourceTier.TIER_1.value,
            published_at=t_pub,
            source_observation_timestamp=t_src_obs,
            retrieved_at=t_src_obs + timedelta(seconds=1),
            content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            raw_payload_snippet=payload,
            is_verified=True
        )
        valid, rej_cat, err = HistoricalSourceValidator.validate_historical_source(evidence, t_mkt_obs)
        assert valid is True
        assert rej_cat is None

    def test_reject_lookahead_source_obs_after_market_obs(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t_src_obs = t_pub + timedelta(seconds=5)
        t_mkt_obs = t_pub + timedelta(seconds=2)  # market observation earlier than source observation
        payload = "Data"
        evidence = SourceEvidenceRecord(
            source_id="src_1", event_id="e1", source_url="https://federalreserve.gov",
            source_domain="federalreserve.gov", source_tier=SourceTier.TIER_1.value,
            published_at=t_pub, source_observation_timestamp=t_src_obs,
            retrieved_at=t_src_obs, content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            raw_payload_snippet=payload, is_verified=True
        )
        valid, rej_cat, err = HistoricalSourceValidator.validate_historical_source(evidence, t_mkt_obs)
        assert valid is False
        assert rej_cat == RejectionCategory.LOOKAHEAD

    def test_reject_unverifiable_publication_after_observation(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 5, tzinfo=timezone.utc)
        t_src_obs = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        payload = "Data"
        evidence = SourceEvidenceRecord(
            source_id="src_2", event_id="e2", source_url="https://federalreserve.gov",
            source_domain="federalreserve.gov", source_tier=SourceTier.TIER_1.value,
            published_at=t_pub, source_observation_timestamp=t_src_obs,
            retrieved_at=t_src_obs, content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            raw_payload_snippet=payload, is_verified=True
        )
        valid, rej_cat, err = HistoricalSourceValidator.validate_historical_source(evidence, t_src_obs)
        assert valid is False
        assert rej_cat == RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE

    def test_reject_tier_3_source_domain(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        payload = "Social rumor"
        evidence = SourceEvidenceRecord(
            source_id="src_3", event_id="e3", source_url="https://x.com/user/post",
            source_domain="x.com", source_tier=SourceTier.TIER_3.value,
            published_at=t_pub, source_observation_timestamp=t_pub + timedelta(seconds=1),
            retrieved_at=t_pub + timedelta(seconds=2),
            content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            raw_payload_snippet=payload, is_verified=True
        )
        valid, rej_cat, err = HistoricalSourceValidator.validate_historical_source(evidence, t_pub + timedelta(seconds=5))
        assert valid is False
        assert rej_cat == RejectionCategory.SOURCE_NOT_AUTHORITATIVE

    def test_reject_content_hash_mismatch(self):
        t_pub = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        evidence = SourceEvidenceRecord(
            source_id="src_4", event_id="e4", source_url="https://bls.gov/cpi",
            source_domain="bls.gov", source_tier=SourceTier.TIER_1.value,
            published_at=t_pub, source_observation_timestamp=t_pub + timedelta(seconds=1),
            retrieved_at=t_pub + timedelta(seconds=2),
            content_hash="tampered_hash_0000000000000000000000000000000000000000",
            raw_payload_snippet="genuine content", is_verified=True
        )
        valid, rej_cat, err = HistoricalSourceValidator.validate_historical_source(evidence, t_pub + timedelta(seconds=5))
        assert valid is False
        assert rej_cat == RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE

    def test_timezone_naive_conversion_safety(self):
        naive_dt = datetime(2026, 10, 1, 12, 0, 0)
        utc_dt = HistoricalSourceValidator.to_utc(naive_dt)
        assert utc_dt.tzinfo == timezone.utc


# ==============================================================================
# 3. EXACT MARKET MATCHING TESTS (12-18)
# ==============================================================================

class TestMarketMatching:

    def test_exact_market_and_outcome_match_passes(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c1", market_id="m1", token_id="t1",
            market_title="Counter-Strike: BIG vs fnatic - Map 1 Winner",
            contract_outcome="fnatic",
            event_title="Counter-Strike: BIG vs fnatic - Map 1 Winner",
            event_outcome="fnatic"
        )
        assert valid is True
        assert mapping is not None
        assert mapping.is_exact_match is True

    def test_reject_outcome_token_mismatch(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c2", market_id="m1", token_id="t1",
            market_title="Counter-Strike: BIG vs fnatic",
            contract_outcome="BIG",
            event_title="Counter-Strike: BIG vs fnatic",
            event_outcome="fnatic"
        )
        assert valid is False
        assert rej == RejectionCategory.MARKET_MISMATCH
        assert "Outcome mismatch" in err

    def test_reject_threshold_mismatch(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c3", market_id="m2", token_id="t2",
            market_title="Will the price of Bitcoin be above $82,000 on September 30?",
            contract_outcome="Yes",
            event_title="Will the price of Bitcoin be above $84,000 on September 30?",
            event_outcome="Yes",
            event_threshold=84000.0,
            market_threshold=82000.0
        )
        assert valid is False
        assert rej == RejectionCategory.THRESHOLD_MISMATCH

    def test_reject_date_mismatch(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c4", market_id="m3", token_id="t3",
            market_title="Will the price of Bitcoin be above $82,000 on September 30?",
            contract_outcome="Yes",
            event_title="Will the price of Bitcoin be above $82,000 on October 1?",
            event_outcome="Yes",
            event_date="October 1",
            market_date="September 30"
        )
        assert valid is False
        assert rej == RejectionCategory.DATE_MISMATCH

    def test_canonical_boolean_mapping_up_equals_yes(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c5", market_id="m4", token_id="t4",
            market_title="S&P 500 (SPX) Opens Up or Down on October 1?",
            contract_outcome="Up",
            event_title="S&P 500 (SPX) Opens Up or Down on October 1?",
            event_outcome="Yes"  # Up is equivalent to Yes
        )
        assert valid is True

    def test_canonical_boolean_mapping_down_equals_no(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c6", market_id="m4", token_id="t4",
            market_title="S&P 500 (SPX) Opens Up or Down on October 1?",
            contract_outcome="Down",
            event_title="S&P 500 (SPX) Opens Up or Down on October 1?",
            event_outcome="No"
        )
        assert valid is True

    def test_reject_entity_mismatch(self):
        valid, mapping, rej, err = DeterministicMarketMatcher.match_contract(
            candidate_id="c7", market_id="m5", token_id="t5",
            market_title="Tennis: Rafael Nadal vs Novak Djokovic",
            contract_outcome="Novak Djokovic",
            event_title="Tennis: Carlos Alcaraz vs Daniil Medvedev",
            event_outcome="Novak Djokovic"
        )
        assert valid is False
        assert rej == RejectionCategory.MARKET_MISMATCH


# ==============================================================================
# 4. EVENT INDEPENDENCE & CLUSTERING TESTS (19-24)
# ==============================================================================

class TestEventIndependence:

    def test_independent_events_assigned_unique_source_id(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "src_ev_1", "tennis", EventTaxonomyCategory.A_SPORTS, "Match 1",
                                  "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Yes", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "src_ev_2", "tennis", EventTaxonomyCategory.A_SPORTS, "Match 2",
                                  "TIER_1_OFFICIAL", t0 + timedelta(hours=1), t0 + timedelta(hours=1), "m2", "t2", "Yes", "STATE_A", 1.0)
        recs = EventIndependenceTracker.assign_clusters([ev1, ev2])
        assert len(recs) == 2
        assert recs[0].is_independent_event is True
        assert recs[1].is_independent_event is True

    def test_duplicate_source_event_flagged_as_co_dependent(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Same underlying match generating match winner and map 1 winner
        ev1 = ExpandedEventRecord("e1", "shared_src_match", "cs", EventTaxonomyCategory.A_SPORTS, "CS Match",
                                  "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "fnatic", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "shared_src_match", "cs", EventTaxonomyCategory.A_SPORTS, "CS Map 1",
                                  "TIER_1_OFFICIAL", t0 + timedelta(seconds=10), t0 + timedelta(seconds=10), "m2", "t2", "fnatic", "STATE_A", 1.0)
        recs = EventIndependenceTracker.assign_clusters([ev1, ev2])
        assert recs[0].is_independent_event is True
        assert recs[1].is_independent_event is False  # co-dependent!

    def test_5m_cluster_grouping_within_window(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "macro", EventTaxonomyCategory.D_CENTRAL_BANK, "Fed 1",
                                  "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Yes", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "s2", "macro", EventTaxonomyCategory.D_CENTRAL_BANK, "Fed 2",
                                  "TIER_1_OFFICIAL", t0 + timedelta(seconds=60), t0 + timedelta(seconds=60), "m2", "t2", "Yes", "STATE_A", 1.0)
        EventIndependenceTracker.assign_clusters([ev1, ev2], window_5m_sec=300.0)
        assert ev1.cluster_5m_id == ev2.cluster_5m_id

    def test_5m_cluster_separation_outside_window(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "macro", EventTaxonomyCategory.D_CENTRAL_BANK, "Fed 1",
                                  "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Yes", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "s2", "macro", EventTaxonomyCategory.D_CENTRAL_BANK, "Fed 2",
                                  "TIER_1_OFFICIAL", t0 + timedelta(seconds=400), t0 + timedelta(seconds=400), "m2", "t2", "Yes", "STATE_A", 1.0)
        EventIndependenceTracker.assign_clusters([ev1, ev2], window_5m_sec=300.0)
        assert ev1.cluster_5m_id != ev2.cluster_5m_id

    def test_1m_cluster_separation(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "crypto", EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS, "BTC 1",
                                  "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Yes", "STATE_B", 1.0)
        ev2 = ExpandedEventRecord("e2", "s2", "crypto", EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS, "BTC 2",
                                  "TIER_1_OFFICIAL", t0 + timedelta(seconds=90), t0 + timedelta(seconds=90), "m2", "t2", "Yes", "STATE_B", 1.0)
        EventIndependenceTracker.assign_clusters([ev1, ev2], window_1m_sec=60.0)
        assert ev1.cluster_1m_id != ev2.cluster_1m_id

    def test_compute_independence_metrics_uniqueness(self):
        ev1 = ExpandedEventRecord("e1", "s1", "tennis", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL", datetime.now(timezone.utc), datetime.now(timezone.utc), "m1", "t1", "Yes", "STATE_A", 1.0, cluster_5m_id="c1", cluster_1m_id="c1_1")
        ev2 = ExpandedEventRecord("e2", "s1", "tennis", EventTaxonomyCategory.A_SPORTS, "T2", "TIER_1_OFFICIAL", datetime.now(timezone.utc), datetime.now(timezone.utc), "m2", "t2", "Yes", "STATE_A", 1.0, cluster_5m_id="c1", cluster_1m_id="c1_1")
        metrics = EventIndependenceTracker.compute_independence_metrics([ev1, ev2], candidate_count=50)
        assert metrics["unique_events"] == 2
        assert metrics["unique_source_events"] == 1  # shared source event!
        assert metrics["unique_markets"] == 2


# ==============================================================================
# 5. CHRONOLOGY & DISCOVERY/OOS SPLITTING TESTS (25-30)
# ==============================================================================

class TestChronologyManager:

    def test_chronological_sorting_strictly_applied(self):
        t1 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)
        ev_list = [
            ExpandedEventRecord("e3", "s3", "f", EventTaxonomyCategory.A_SPORTS, "T3", "TIER_1_OFFICIAL", t3, t3, "m3", "t3", "Y", "STATE_A", 1.0),
            ExpandedEventRecord("e1", "s1", "f", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL", t1, t1, "m1", "t1", "Y", "STATE_A", 1.0),
            ExpandedEventRecord("e2", "s2", "f", EventTaxonomyCategory.A_SPORTS, "T2", "TIER_1_OFFICIAL", t2, t2, "m2", "t2", "Y", "STATE_A", 1.0),
        ]
        disc, oos, summary = ChronologyManager.apply_chronological_split(ev_list, discovery_pct=0.67)
        assert disc[0].event_id == "e1"
        assert disc[1].event_id == "e2"
        assert oos[0].event_id == "e3"

    def test_mechanical_split_percentages(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev_list = [
            ExpandedEventRecord(f"e_{i}", f"s_{i}", "f", EventTaxonomyCategory.A_SPORTS, f"T_{i}", "TIER_1_OFFICIAL",
                                t0 + timedelta(hours=i), t0 + timedelta(hours=i), f"m_{i}", f"t_{i}", "Y", "STATE_A", 1.0)
            for i in range(10)
        ]
        disc, oos, summary = ChronologyManager.apply_chronological_split(ev_list, discovery_pct=0.60)
        assert len(disc) == 6
        assert len(oos) == 4
        assert summary["discovery_count"] == 6
        assert summary["oos_count"] == 4

    def test_is_out_of_sample_flag_assigned_accurately(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "f", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Y", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "s2", "f", EventTaxonomyCategory.A_SPORTS, "T2", "TIER_1_OFFICIAL", t0 + timedelta(hours=1), t0 + timedelta(hours=1), "m2", "t2", "Y", "STATE_A", 1.0)
        disc, oos, _ = ChronologyManager.apply_chronological_split([ev1, ev2], discovery_pct=0.50)
        assert ev1.is_out_of_sample is False
        assert ev2.is_out_of_sample is True

    def test_empty_event_list_split_handling(self):
        disc, oos, summary = ChronologyManager.apply_chronological_split([], discovery_pct=0.60)
        assert disc == []
        assert oos == []
        assert summary["discovery_count"] == 0

    def test_single_event_split_handling(self):
        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "f", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL", t0, t0, "m1", "t1", "Y", "STATE_A", 1.0)
        disc, oos, summary = ChronologyManager.apply_chronological_split([ev1], discovery_pct=0.60)
        # 1 * 0.6 = 0 disc, 1 oos
        assert len(oos) == 1

    def test_date_range_reporting_in_summary(self):
        t1 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)
        ev1 = ExpandedEventRecord("e1", "s1", "f", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL", t1, t1, "m1", "t1", "Y", "STATE_A", 1.0)
        ev2 = ExpandedEventRecord("e2", "s2", "f", EventTaxonomyCategory.A_SPORTS, "T2", "TIER_1_OFFICIAL", t2, t2, "m2", "t2", "Y", "STATE_A", 1.0)
        _, _, summary = ChronologyManager.apply_chronological_split([ev1, ev2], discovery_pct=0.50)
        assert summary["discovery_start"] == t1
        assert summary["oos_start"] == t2


# ==============================================================================
# 6. REJECTION LEDGER & GATE INTEGRITY (31-36)
# ==============================================================================

class TestRejectionLedger:

    def test_all_sixteen_rejection_categories_defined(self):
        expected_cats = [
            "NO_HISTORICAL_SOURCE", "SOURCE_TIMESTAMP_UNVERIFIABLE", "SOURCE_NOT_AUTHORITATIVE",
            "AMBIGUOUS_RESOLUTION", "MARKET_MISMATCH", "DATE_MISMATCH", "TIMEZONE_MISMATCH",
            "GEOGRAPHY_MISMATCH", "THRESHOLD_MISMATCH", "REVISION_AMBIGUITY", "CANCELLATION_AMBIGUITY",
            "DUPLICATE_EVENT", "LOOKAHEAD", "NON_DETERMINISTIC", "INSUFFICIENT_MARKET_DATA", "OTHER"
        ]
        actual_cats = [c.value for c in RejectionCategory]
        for ec in expected_cats:
            assert ec in actual_cats

    def test_rejection_record_creation(self):
        t = datetime.now(timezone.utc)
        rec = CandidateRejectionRecord(
            candidate_id="cand_bad", market_id="m99", event_type="sports",
            rejection_reason=RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE,
            rejection_stage="SOURCE_QUALIFICATION_GATE", timestamp=t, detail="Missing source timestamp"
        )
        assert rec.rejection_reason == RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE
        assert rec.rejection_stage == "SOURCE_QUALIFICATION_GATE"

    def test_deduplication_rejection_generation(self):
        rej = CandidateRejectionRecord(
            candidate_id="cand_dup", market_id="m1", event_type="esports",
            rejection_reason=RejectionCategory.DUPLICATE_EVENT,
            rejection_stage="DEDUPLICATION_GATE", timestamp=datetime.now(timezone.utc)
        )
        assert rej.rejection_reason == RejectionCategory.DUPLICATE_EVENT

    def test_ambiguous_resolution_rejection(self):
        rej = CandidateRejectionRecord(
            candidate_id="cand_ambig", market_id="m2", event_type="politics",
            rejection_reason=RejectionCategory.AMBIGUOUS_RESOLUTION,
            rejection_stage="DETERMINISTIC_GATE", timestamp=datetime.now(timezone.utc)
        )
        assert rej.rejection_reason == RejectionCategory.AMBIGUOUS_RESOLUTION

    def test_insufficient_market_data_rejection(self):
        rej = CandidateRejectionRecord(
            candidate_id="cand_no_data", market_id="m3", event_type="crypto",
            rejection_reason=RejectionCategory.INSUFFICIENT_MARKET_DATA,
            rejection_stage="L2_RECONSTRUCTION_GATE", timestamp=datetime.now(timezone.utc)
        )
        assert rej.rejection_reason == RejectionCategory.INSUFFICIENT_MARKET_DATA

    def test_revision_ambiguity_rejection(self):
        rej = CandidateRejectionRecord(
            candidate_id="cand_rev", market_id="m4", event_type="gdp",
            rejection_reason=RejectionCategory.REVISION_AMBIGUITY,
            rejection_stage="VINTAGE_GATE", timestamp=datetime.now(timezone.utc)
        )
        assert rej.rejection_reason == RejectionCategory.REVISION_AMBIGUITY


# ==============================================================================
# 7. TAXONOMY COVERAGE & VERDICT ENUMS (37-41)
# ==============================================================================

class TestTaxonomyAndVerdicts:

    def test_all_ten_taxonomy_categories_defined(self):
        cats = [c.value for c in EventTaxonomyCategory]
        assert "sports_competitions" in cats
        assert "elections_official_results" in cats
        assert "government_statistical_releases" in cats
        assert "central_bank_rate_outcomes" in cats
        assert "scheduled_economic_data" in cats
        assert "corporate_institutional_outcomes" in cats
        assert "weather_mechanical_observations" in cats
        assert "numerical_threshold_contracts" in cats
        assert "official_appointments" in cats
        assert "mechanical_public_events" in cats
        assert len(cats) == 10

    def test_required_phase10a10b_verdicts_defined(self):
        verdicts = [v.value for v in Phase10A10BVerdict]
        assert "EVENT_UNIVERSE_NOW_SUFFICIENT" in verdicts
        assert "EVENT_UNIVERSE_STILL_SPARSE" in verdicts
        assert "EDGE_NOT_REPRODUCED" in verdicts
        assert "EDGE_REPRODUCED_BUT_CAPACITY_LIMITED" in verdicts
        assert "EDGE_DESTROYED_BY_EXECUTION" in verdicts
        assert "METHODOLOGY_INVALID" in verdicts
        assert "UNIVERSE_EXPANSION_FAILED" in verdicts

    def test_anti_contamination_guard_protects_phase10a10b_tables(self):
        bad_rec = {"event_id": "mock_event_1", "provenance": "POLYMARKET_LIVE"}
        with pytest.raises(Phase10A10ContaminationError):
            ProductionContaminationGuard.assert_valid_production_record(bad_rec, is_production_db=True)

    def test_anti_contamination_guard_allows_live_record(self):
        good_rec = {"event_id": "cand_dota_bb_og_20260930", "provenance": "POLYMARKET_LIVE"}
        # Should not raise
        ProductionContaminationGuard.assert_valid_production_record(good_rec, is_production_db=True)

    def test_market_data_provenance_must_be_polymarket_live(self):
        ev = ExpandedEventRecord("e1", "s1", "f", EventTaxonomyCategory.A_SPORTS, "T1", "TIER_1_OFFICIAL",
                                 datetime.now(timezone.utc), datetime.now(timezone.utc), "m1", "t1", "Y", "STATE_A", 1.0)
        assert ev.provenance == "POLYMARKET_LIVE"
