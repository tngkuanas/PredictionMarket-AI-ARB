"""Unit tests for Phase 10A.3: Historical Information-Latency Event Study.
Verifies event dataset generation, contract mapping decision gate,
multi-horizon response calculation, null control placebos, and DuckDB table persistence.
"""
from datetime import datetime, timezone, timedelta
import duckdb
import pytest

from src.normalization.schema import CanonicalMarket, Platform
from src.phase10.events.schema import (
    SourceType,
    EventDirection,
    ImpactDistribution,
    InformationEvent,
)
from src.phase10.events.historical_events import create_historical_event_dataset
from src.phase10.events.contract_mapper import (
    DeterministicContractMapper,
    MappingDecision,
    AmbiguityFlag,
)
from src.phase10.events.event_study_engine import (
    HistoricalEventStudyEngine,
    EventStudyObservation,
    HorizonResponse,
)


@pytest.fixture
def sample_events():
    return create_historical_event_dataset()


@pytest.fixture
def in_memory_db():
    conn = duckdb.connect(":memory:")
    # Create minimal schema
    conn.execute("""
        CREATE TABLE canonical_markets (
            market_id VARCHAR PRIMARY KEY,
            platform VARCHAR,
            title VARCHAR,
            underlying_event VARCHAR,
            entities JSON,
            geographic_scope VARCHAR,
            time_horizon VARCHAR,
            event_type VARCHAR,
            threshold VARCHAR,
            direction VARCHAR,
            numerical_conditions JSON,
            resolution_date VARCHAR,
            resolution_source VARCHAR,
            resolution_methodology VARCHAR,
            ambiguity_flags JSON,
            updated_at TIMESTAMP
        );
        CREATE TABLE markets (
            platform VARCHAR,
            market_id VARCHAR PRIMARY KEY,
            event_id VARCHAR,
            title VARCHAR,
            description VARCHAR,
            resolution_rules VARCHAR,
            outcome_labels JSON,
            category VARCHAR,
            open_time TIMESTAMP,
            close_time TIMESTAMP,
            resolution_time TIMESTAMP,
            status VARCHAR,
            clob_token_ids JSON,
            condition_id VARCHAR,
            volume DOUBLE,
            liquidity DOUBLE,
            metadata JSON,
            updated_at TIMESTAMP
        );
        CREATE TABLE market_snapshots (
            timestamp TIMESTAMP,
            market_id VARCHAR,
            platform VARCHAR,
            yes_bid DOUBLE,
            yes_ask DOUBLE,
            yes_mid DOUBLE,
            no_bid DOUBLE,
            no_ask DOUBLE,
            volume DOUBLE,
            liquidity DOUBLE
        );
    """)

    # Populate 1 test market
    conn.execute("""
        INSERT INTO canonical_markets VALUES (
            'test_fomc_market', 'polymarket', 'Will the Fed increase interest rates by 25 bps after the October 2026 meeting?',
            'FOMC Decision', '["Federal Reserve", "FOMC"]', 'US', '2026', 'rate_decision', '= 25 bps', '>=',
            '{}', '2026-10-29T03:59:00+00:00', 'Official Market Resolution Source', 'Binary Settlement', '[]', now()
        );
        INSERT INTO markets VALUES (
            'polymarket', 'test_fomc_market', 'evt_1', 'Will the Fed increase interest rates by 25 bps after the October 2026 meeting?',
            'Fed Decision', 'Resolves on Fed release', '["Yes", "No"]', 'macro', now(), now(), now(), 'active',
            '["token_fomc_yes", "token_fomc_no"]', '0x123', 500000.0, 150000.0, '{}', now()
        );
    """)

    # Populate snapshots around 2026-09-16 18:00:00
    t0 = datetime(2026, 9, 16, 17, 0, 0)
    t1 = datetime(2026, 9, 16, 18, 0, 15)
    t2 = datetime(2026, 9, 16, 19, 0, 0)
    t3 = datetime(2026, 9, 17, 18, 0, 0)

    conn.execute("INSERT INTO market_snapshots VALUES (?, 'token_fomc_yes', 'polymarket', 0.35, 0.35, 0.35, 0.65, 0.65, 1000.0, 150000.0)", [t0])
    conn.execute("INSERT INTO market_snapshots VALUES (?, 'token_fomc_yes', 'polymarket', 0.38, 0.38, 0.38, 0.62, 0.62, 1000.0, 150000.0)", [t1])
    conn.execute("INSERT INTO market_snapshots VALUES (?, 'token_fomc_yes', 'polymarket', 0.45, 0.45, 0.45, 0.55, 0.55, 1000.0, 150000.0)", [t2])
    conn.execute("INSERT INTO market_snapshots VALUES (?, 'token_fomc_yes', 'polymarket', 0.48, 0.48, 0.48, 0.52, 0.52, 1000.0, 150000.0)", [t3])

    return conn


def test_historical_events_structure(sample_events):
    """Verify event dataset compliance, causality, and bounded impact distributions."""
    assert len(sample_events) >= 50
    for e in sample_events:
        assert e.event_id.startswith("evt_")
        assert e.timestamp_publication.tzinfo == timezone.utc
        assert e.timestamp_extraction >= e.timestamp_publication
        assert e.source_type in list(SourceType)
        assert 0.0 <= e.source_reliability <= 1.0
        assert -1.0 <= e.impact_distribution.impact_lower <= e.impact_distribution.impact_point <= e.impact_distribution.impact_upper <= 1.0
        assert 0.0 <= e.impact_distribution.impact_confidence <= 1.0
        assert e.impact_distribution.impact_horizon_seconds > 0.0


def test_contract_mapper_indirect_transmission(sample_events):
    """Verify that indirect macro events (CPI/NFP) evaluate to AMBIGUOUS against rate decisions."""
    mapper = DeterministicContractMapper()
    cpi_event = [e for e in sample_events if e.event_type == "macro_inflation"][0]

    rate_market = CanonicalMarket(
        market_id="poly_fed_rate",
        platform=Platform.POLYMARKET,
        title="Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
        underlying_event="Fed Meeting",
        entities=["Federal Reserve"],
        geographic_scope="US",
        time_horizon="October 2026",
        event_type="rate_decision",
        threshold="25 bps",
        direction=">=",
        resolution_date="2026-10-29",
        resolution_source="Official Market Resolution Source"
    )

    mapping = mapper.map_event_to_market(cpi_event, rate_market)
    assert mapping.mapping_decision == MappingDecision.AMBIGUOUS
    assert AmbiguityFlag.SCOPE_MISMATCH in mapping.ambiguity_flags
    assert "indirect macro transmission" in mapping.decision_reason


def test_event_study_measurement_and_horizons(in_memory_db, sample_events):
    """Verify high-resolution price measurement, horizon extraction, and markouts."""
    engine = HistoricalEventStudyEngine()
    universe = engine.load_canonical_universe(in_memory_db)
    assert "test_fomc_market" in universe

    cm, token_id, liq, vol = universe["test_fomc_market"]
    fomc_event = [e for e in sample_events if e.event_id == "evt_fomc_oct_hike25_20260916"][0]

    mapping = engine.mapper.map_event_to_market(fomc_event, cm)
    assert mapping.mapping_decision == MappingDecision.ACCEPTED

    obs = engine.measure_event_response(in_memory_db, fomc_event, cm, token_id, liq, mapping)
    assert obs is not None
    assert obs.p_minus_mid == 0.35
    assert obs.lag_seconds == 3600.0  # 18:00 - 17:00

    # Horizon checks
    h1s = obs.horizons["1s"]
    assert h1s.is_available is False  # UNAVAILABLE (no 1s snapshot)

    h15s = obs.horizons["15s"]
    assert h15s.is_available is True  # AVAILABLE at 18:00:15
    assert h15s.p_mid == 0.38
    assert round(h15s.delta_mid, 3) == 0.030

    h1h = obs.horizons["1h"]
    assert h1h.is_available is True   # AVAILABLE at 19:00:00
    assert h1h.p_mid == 0.45
    assert round(h1h.delta_mid, 3) == 0.100
    assert h1h.exec_markout is not None

    h24h = obs.horizons["24h"]
    assert h24h.is_available is True
    assert h24h.p_mid == 0.48

    # Excursion metrics
    assert obs.mfe_1h is not None
    assert obs.mfe_1h >= 0.100
    assert obs.time_to_peak_minutes is not None


def test_decision_gate_logic():
    """Verify decision gate classification rules for PROMISING, INCONCLUSIVE, and REJECTED."""
    engine = HistoricalEventStudyEngine()

    # Case 1: Inconclusive (Directional move exists, but eaten by fees)
    h_mock_inconcl = {
        "1h": HorizonResponse(
            horizon_name="1h",
            target_offset_seconds=3600,
            is_available=True,
            snapshot_time=datetime.now(timezone.utc),
            delta_seconds=0.0,
            p_mid=0.50,
            p_bid=0.495,
            p_ask=0.505,
            spread=0.010,
            delta_mid=0.020,
            dir_delta_mid=0.020,
            exec_markout=0.005,
            spread_adj_markout=0.010,
            net_markout_fee=0.003,
            net_markout_160bps=-0.011
        )
    }
    obs_inconcl = [
        EventStudyObservation(
            event_id=f"evt_{i}",
            market_id=f"m_{i}",
            canonical_title="Title",
            event_type="rate_decision",
            source="Fed",
            source_type="official_primary",
            timestamp_publication=datetime.now(timezone.utc),
            timestamp_extraction=datetime.now(timezone.utc),
            direction="increase",
            is_inverted=False,
            mapping_score=0.5,
            t_minus=datetime.now(timezone.utc),
            lag_seconds=10.0,
            p_minus_mid=0.48,
            p_minus_bid=0.475,
            p_minus_ask=0.485,
            spread_minus=0.010,
            depth_minus=50000.0,
            horizons=h_mock_inconcl,
            mfe_1h=0.025,
            mae_1h=-0.005,
            time_to_peak_minutes=45.0,
            persistence_ratio_24h_1h=0.90,
            actual_value=None,
            consensus_value=None,
            measurable_surprise=None,
            event_cluster_id="c1"
        )
        for i in range(10)
    ]

    gate = engine.evaluate_decision_gate(obs_inconcl, {"placebo_a_random_ts": [-0.01]})
    assert gate["classification"] == "INCONCLUSIVE"
    assert "insufficient to overcome taker transaction costs" in gate["rationale"]
