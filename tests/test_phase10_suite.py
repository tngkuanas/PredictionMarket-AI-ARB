"""Test suite for Phase 10A: Information Latency Event Schema & Deterministic Contract Mapping."""
from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from src.normalization.schema import CanonicalMarket, Platform
from src.phase10.events.schema import (
    SourceType,
    EventDirection,
    ImpactDistribution,
    InformationEvent,
)
from src.phase10.events.contract_mapper import (
    MappingDecision,
    AmbiguityFlag,
    ContractMapping,
    DeterministicContractMapper,
)


@pytest.fixture
def valid_impact():
    return ImpactDistribution(
        impact_point=0.08,
        impact_lower=0.05,
        impact_upper=0.12,
        impact_confidence=0.85,
        impact_horizon_seconds=900.0
    )


@pytest.fixture
def sample_event(valid_impact):
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    ext_time = pub_time + timedelta(seconds=2.5)
    return InformationEvent(
        event_id="evt_bls_cpi_20260315",
        timestamp_publication=pub_time,
        timestamp_extraction=ext_time,
        source="Bureau of Labor Statistics",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=0.99,
        event_type="macro_indicator",
        title="US CPI Rose 0.4% in February 2026; Core CPI at 3.1%",
        raw_content="The Consumer Price Index for All Urban Consumers (CPI-U) increased 0.4 percent in February on a seasonally adjusted basis.",
        entities=["Bureau of Labor Statistics", "US CPI", "Federal Reserve"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Higher CPI increases probability of Federal Reserve holding rates higher for longer.",
        invalidation_conditions=["Subsequent data revision reduces core CPI below 2.8%"],
        resolution_relevance=0.95,
        metadata={"release_id": "cpi_2026_02"}
    )


# =============================================================================
# 10A.1 EVENT SCHEMA TESTS
# =============================================================================

def test_impact_distribution_validation(valid_impact):
    """Test valid bounded forecast distribution and immutability."""
    assert valid_impact.impact_point == 0.08
    assert valid_impact.impact_lower == 0.05
    assert valid_impact.impact_upper == 0.12

    # Inverted bounds must fail
    with pytest.raises(ValidationError):
        ImpactDistribution(
            impact_point=0.15,  # point > upper
            impact_lower=0.05,
            impact_upper=0.10,
            impact_confidence=0.8,
            impact_horizon_seconds=60.0
        )

    # Lower > point must fail
    with pytest.raises(ValidationError):
        ImpactDistribution(
            impact_point=0.04,  # lower > point
            impact_lower=0.05,
            impact_upper=0.10,
            impact_confidence=0.8,
            impact_horizon_seconds=60.0
        )

    # Immutability
    with pytest.raises(ValidationError):
        valid_impact.impact_point = 0.09


def test_information_event_temporal_causality(valid_impact):
    """Extraction timestamp cannot precede publication timestamp (lookahead prevention)."""
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    impossible_ext_time = pub_time - timedelta(seconds=1.0)  # Extraction before published!

    with pytest.raises(ValidationError) as exc:
        InformationEvent(
            event_id="evt_invalid_time",
            timestamp_publication=pub_time,
            timestamp_extraction=impossible_ext_time,
            source="BLS",
            source_type=SourceType.OFFICIAL_PRIMARY,
            source_reliability=0.95,
            event_type="macro",
            title="Invalid Timestamp Event",
            raw_content="Content",
            entities=["BLS"],
            direction=EventDirection.INCREASE,
            impact_distribution=valid_impact,
            mechanism="Valid economic transmission mechanism",
            resolution_relevance=0.9
        )
    assert "Temporal causality violation" in str(exc.value)


def test_information_event_serialization_and_latency(sample_event):
    """Test full audit serialization and information latency measurement."""
    assert sample_event.information_latency_seconds == 2.5
    data = sample_event.model_dump()
    assert data["event_id"] == "evt_bls_cpi_20260315"
    assert data["source_type"] == SourceType.OFFICIAL_PRIMARY
    assert data["impact_distribution"]["impact_point"] == 0.08

    # Re-serialization round-trip
    restored = InformationEvent.model_validate(data)
    assert restored == sample_event


# =============================================================================
# 10A.2 CONTRACT MAPPER TESTS
# =============================================================================

def test_mapper_exact_match(sample_event):
    """Test exact match between BLS CPI release and active Polymarket CPI contract."""
    mapper = DeterministicContractMapper()
    market = CanonicalMarket(
        market_id="poly_cpi_mar26",
        platform=Platform.POLYMARKET,
        title="Will US CPI be 3.0% or higher in February 2026?",
        underlying_event="US Consumer Price Index report by Bureau of Labor Statistics",
        entities=["Bureau of Labor Statistics", "US CPI"],
        geographic_scope="United States",
        time_horizon="February 2026",
        event_type="macro_indicator",
        threshold="3.0%",
        resolution_date="2026-03-31",
        resolution_source="Bureau of Labor Statistics official release",
        resolution_methodology="Resolved using the 12-month unadjusted Core CPI number released by BLS."
    )

    mapping = mapper.map_event_to_market(sample_event, market)
    assert mapping.mapping_decision == MappingDecision.ACCEPTED
    assert mapping.entity_match is True
    assert mapping.temporal_match is True
    assert mapping.resolution_match is True
    assert len(mapping.ambiguity_flags) == 0
    assert mapping.is_inverted is False


def test_mapper_superficial_wording_trap(valid_impact):
    """Test popular vote event vs presidential win contract (superficial similarity rejection)."""
    mapper = DeterministicContractMapper()
    pub_time = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    event = InformationEvent(
        event_id="evt_election_pop_vote",
        timestamp_publication=pub_time,
        timestamp_extraction=pub_time + timedelta(seconds=1),
        source="Associated Press",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="election_outcome",
        title="Candidate A Projected to Win National Popular Vote by 2.5%",
        raw_content="National popular vote tallies indicate Candidate A has secured the popular vote plurality.",
        entities=["Candidate A", "US Election"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Popular vote plurality projection.",
        resolution_relevance=0.70
    )

    market = CanonicalMarket(
        market_id="poly_presidency_win",
        platform=Platform.POLYMARKET,
        title="Will Candidate A win the presidency?",
        underlying_event="US Presidential Election resolution",
        entities=["Candidate A"],
        geographic_scope="United States",
        time_horizon="2026-11-20",
        event_type="election_outcome",
        resolution_date="2026-12-15",
        resolution_source="Electoral College vote certification",
        resolution_methodology="Resolves YES only if Candidate A is certified as the electoral college winner."
    )

    mapping = mapper.map_event_to_market(event, market)
    assert mapping.mapping_decision == MappingDecision.REJECTED
    assert AmbiguityFlag.WORDING_AMBIGUITY in mapping.ambiguity_flags
    assert "fatal criteria failures" in mapping.decision_reason


def test_mapper_temporal_expired_contract(sample_event):
    """Test rejection when contract resolution date has already passed."""
    mapper = DeterministicContractMapper()
    # Contract resolved on 2026-03-01, but event published on 2026-03-15
    market = CanonicalMarket(
        market_id="poly_cpi_expired",
        platform=Platform.POLYMARKET,
        title="Will US CPI be 3.0% or higher?",
        underlying_event="CPI",
        entities=["Bureau of Labor Statistics", "US CPI"],
        geographic_scope="US",
        time_horizon="Historical",
        event_type="macro",
        resolution_date="2026-03-01",  # Expired!
        resolution_source="BLS"
    )

    mapping = mapper.map_event_to_market(sample_event, market)
    assert mapping.mapping_decision == MappingDecision.REJECTED
    assert mapping.temporal_match is False
    assert AmbiguityFlag.TEMPORAL_EXPIRED in mapping.ambiguity_flags


def test_mapper_resolution_source_divergence(sample_event, valid_impact):
    """Test rejection when event source is unverified social media."""
    mapper = DeterministicContractMapper()
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    social_event = InformationEvent(
        event_id="evt_social_rumor",
        timestamp_publication=pub_time,
        timestamp_extraction=pub_time + timedelta(seconds=1),
        source="Twitter User @MacroLeaks",
        source_type=SourceType.SOCIAL_MEDIA,  # Low hierarchy tier
        source_reliability=0.25,
        event_type="macro_rumor",
        title="Leaked: Fed to cut rates by 75 bps tomorrow",
        raw_content="Rumors circulating from DC insider that emergency rate cut is planned.",
        entities=["Federal Reserve", "Jerome Powell"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Emergency rate cut rumor.",
        resolution_relevance=0.40
    )

    market = CanonicalMarket(
        market_id="poly_fed_rate_cut",
        platform=Platform.POLYMARKET,
        title="Will Federal Reserve cut rates at next meeting?",
        underlying_event="FOMC Meeting Decision",
        entities=["Federal Reserve"],
        geographic_scope="United States",
        time_horizon="Next FOMC",
        event_type="rate_decision",
        resolution_date="2026-04-01",
        resolution_source="Federal Reserve official press release"
    )

    mapping = mapper.map_event_to_market(social_event, market)
    assert mapping.mapping_decision == MappingDecision.REJECTED
    assert AmbiguityFlag.UNVERIFIED_SOURCE_HIERARCHY in mapping.ambiguity_flags


def test_mapper_threshold_mismatch(valid_impact):
    """Test rejection when event magnitude severely conflicts with contract strike threshold."""
    mapper = DeterministicContractMapper()
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    # Event reports 25 bps rate cut
    event = InformationEvent(
        event_id="evt_fed_25bps",
        timestamp_publication=pub_time,
        timestamp_extraction=pub_time + timedelta(seconds=1),
        source="Federal Reserve Press Release",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=0.99,
        event_type="rate_decision",
        title="Federal Reserve Cuts Interest Rates by 25 bps",
        raw_content="The Federal Open Market Committee decided to lower the target range by 25 basis points.",
        entities=["Federal Reserve", "FOMC"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Rate cut announced.",
        resolution_relevance=0.90
    )

    # Contract requires 100 bps cut
    market = CanonicalMarket(
        market_id="poly_fed_100bps",
        platform=Platform.POLYMARKET,
        title="Will Federal Reserve cut rates by 100 bps or more?",
        underlying_event="FOMC Decision",
        entities=["Federal Reserve"],
        geographic_scope="US",
        time_horizon="2026",
        event_type="rate_decision",
        threshold="100 bps",  # Threshold conflict
        resolution_date="2026-04-01",
        resolution_source="Federal Reserve Press Release"
    )

    mapping = mapper.map_event_to_market(event, market)
    assert mapping.mapping_decision == MappingDecision.REJECTED
    assert AmbiguityFlag.THRESHOLD_MISMATCH in mapping.ambiguity_flags


def test_mapper_yes_no_inversion_polarity(valid_impact):
    """Test correct detection of YES/NO polarity inversion for 'below' / 'under' phrasing."""
    mapper = DeterministicContractMapper()
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    event = InformationEvent(
        event_id="evt_cpi_surge",
        timestamp_publication=pub_time,
        timestamp_extraction=pub_time + timedelta(seconds=1),
        source="Bureau of Labor Statistics",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=0.99,
        event_type="macro",
        title="US CPI Rose sharply to 3.8%",
        raw_content="Inflation rose to 3.8% exceeding consensus expectations.",
        entities=["Bureau of Labor Statistics", "US CPI"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Inflation surge.",
        resolution_relevance=0.95
    )

    # Contract asks if CPI will be BELOW 3.0%
    market = CanonicalMarket(
        market_id="poly_cpi_below_3",
        platform=Platform.POLYMARKET,
        title="Will US CPI be below 3.0%?",
        underlying_event="CPI",
        entities=["Bureau of Labor Statistics", "US CPI"],
        geographic_scope="US",
        time_horizon="2026",
        event_type="macro",
        resolution_date="2026-03-31",
        resolution_source="Bureau of Labor Statistics"
    )

    mapping = mapper.map_event_to_market(event, market)
    assert mapping.is_inverted is True  # Inversion detected!


def test_mapper_unrelated_entity_rejection(valid_impact):
    """Test rejection when event entity has zero overlap with contract entity."""
    mapper = DeterministicContractMapper()
    pub_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    event = InformationEvent(
        event_id="evt_ethereum_upgrade",
        timestamp_publication=pub_time,
        timestamp_extraction=pub_time + timedelta(seconds=1),
        source="Ethereum Foundation",
        source_type=SourceType.OFFICIAL_INSTITUTIONAL,
        source_reliability=0.95,
        event_type="protocol_upgrade",
        title="Ethereum Dencun Hardfork Successfully Activated on Mainnet",
        raw_content="The upgrade has been deployed successfully across all client validators.",
        entities=["Ethereum"],
        direction=EventDirection.INCREASE,
        impact_distribution=valid_impact,
        mechanism="Protocol upgrade succeeds.",
        resolution_relevance=0.90
    )

    # Contract is on Bitcoin reaching $100k
    market = CanonicalMarket(
        market_id="poly_btc_100k",
        platform=Platform.POLYMARKET,
        title="Will Bitcoin reach $100,000 by end of March 2026?",
        underlying_event="Bitcoin Price Milestone",
        entities=["Bitcoin"],  # Discrepancy!
        geographic_scope="Global",
        time_horizon="2026-03-31",
        event_type="price_milestone",
        resolution_date="2026-03-31",
        resolution_source="Coinbase / Binance Index"
    )

    mapping = mapper.map_event_to_market(event, market)
    assert mapping.mapping_decision == MappingDecision.REJECTED
    assert mapping.entity_match is False
    assert AmbiguityFlag.ENTITY_DISCREPANCY in mapping.ambiguity_flags
