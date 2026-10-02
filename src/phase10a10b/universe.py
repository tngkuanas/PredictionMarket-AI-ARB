"""Target Event Taxonomy, Schemas, and Rejection Categories for Phase 10A.10-B.

Defines:
- Preregistered 10-category event taxonomy (A-J).
- Complete Rejection Reason enum with 16 deterministic categories.
- Data structures for expanded events, source evidence, market mapping, and independence tracking.
- Phase 10A.10-B verdicts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional


class EventTaxonomyCategory(str, Enum):
    """Preregistered event categories (A-J) defined prior to candidate scoring."""
    A_SPORTS = "sports_competitions"
    B_ELECTIONS = "elections_official_results"
    C_GOV_STATS = "government_statistical_releases"
    D_CENTRAL_BANK = "central_bank_rate_outcomes"
    E_ECONOMIC_DATA = "scheduled_economic_data"
    F_CORPORATE = "corporate_institutional_outcomes"
    G_WEATHER = "weather_mechanical_observations"
    H_NUMERICAL_THRESHOLDS = "numerical_threshold_contracts"
    I_APPOINTMENTS = "official_appointments"
    J_MECHANICAL_PUBLIC = "mechanical_public_events"


class RejectionCategory(str, Enum):
    """Deterministic rejection ledger categories."""
    NO_HISTORICAL_SOURCE = "NO_HISTORICAL_SOURCE"
    SOURCE_TIMESTAMP_UNVERIFIABLE = "SOURCE_TIMESTAMP_UNVERIFIABLE"
    SOURCE_NOT_AUTHORITATIVE = "SOURCE_NOT_AUTHORITATIVE"
    AMBIGUOUS_RESOLUTION = "AMBIGUOUS_RESOLUTION"
    MARKET_MISMATCH = "MARKET_MISMATCH"
    DATE_MISMATCH = "DATE_MISMATCH"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    GEOGRAPHY_MISMATCH = "GEOGRAPHY_MISMATCH"
    THRESHOLD_MISMATCH = "THRESHOLD_MISMATCH"
    REVISION_AMBIGUITY = "REVISION_AMBIGUITY"
    CANCELLATION_AMBIGUITY = "CANCELLATION_AMBIGUITY"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    LOOKAHEAD = "LOOKAHEAD"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"
    INSUFFICIENT_MARKET_DATA = "INSUFFICIENT_MARKET_DATA"
    OTHER = "OTHER"


class Phase10A10BVerdict(str, Enum):
    """Required Phase 10A.10-B research verdicts."""
    EVENT_UNIVERSE_NOW_SUFFICIENT = "EVENT_UNIVERSE_NOW_SUFFICIENT"
    EVENT_UNIVERSE_STILL_SPARSE = "EVENT_UNIVERSE_STILL_SPARSE"
    EDGE_NOT_REPRODUCED = "EDGE_NOT_REPRODUCED"
    EDGE_REPRODUCED_BUT_CAPACITY_LIMITED = "EDGE_REPRODUCED_BUT_CAPACITY_LIMITED"
    EDGE_DESTROYED_BY_EXECUTION = "EDGE_DESTROYED_BY_EXECUTION"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"
    UNIVERSE_EXPANSION_FAILED = "UNIVERSE_EXPANSION_FAILED"


@dataclass
class ExpandedEventRecord:
    """An expanded empirical deterministic-resolution event."""
    event_id: str
    source_event_id: str
    event_family: str
    category: EventTaxonomyCategory
    title: str
    source_tier: str
    source_timestamp: datetime
    source_observation_timestamp: datetime
    market_id: str
    token_id: str
    winning_outcome: str
    deterministic_state: str  # STATE_A or STATE_B
    deterministic_settlement_value: float  # 1.0 or 0.0
    actual_value: Optional[float] = None
    threshold_value: Optional[float] = None
    is_out_of_sample: bool = False
    cluster_5m_id: str = ""
    cluster_1m_id: str = ""
    provenance: str = "POLYMARKET_LIVE"


@dataclass
class SourceEvidenceRecord:
    """Historical source evidence for an accepted event."""
    source_id: str
    event_id: str
    source_url: str
    source_domain: str
    source_tier: str
    published_at: datetime
    source_observation_timestamp: datetime
    retrieved_at: datetime
    content_hash: str
    raw_payload_snippet: str
    is_verified: bool = True


@dataclass
class MarketMappingRecord:
    """Deterministic contract mapping metadata."""
    mapping_id: str
    event_id: str
    market_id: str
    token_id: str
    market_title: str
    condition_text: str
    resolved_outcome: str
    mapping_confidence: float
    is_exact_match: bool


@dataclass
class EventIndependenceRecord:
    """Tracks clustering and independence for each event."""
    event_id: str
    market_id: str
    source_event_id: str
    event_family: str
    event_date: str
    cluster_5m: str
    cluster_1m: str
    is_independent_event: bool = True


@dataclass
class CandidateRejectionRecord:
    """Rejection ledger record capturing why a candidate failed inclusion."""
    candidate_id: str
    market_id: str
    event_type: str
    rejection_reason: RejectionCategory
    rejection_stage: str
    timestamp: datetime
    detail: Optional[str] = None
