"""Phase 10A.10 Data Schema and Type Definitions.

Covers:
- Deterministic resolution state taxonomy (STATE_A, STATE_B, STATE_C, STATE_D).
- Source authority hierarchy (TIER_1, TIER_2, TIER_3).
- Strict timestamp provenance and anti-lookahead models.
- Execution, convergence, capital lockup, and statistical models.
- Formal research verdicts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional


class DeterministicState(str, Enum):
    """Deterministic resolution state taxonomy."""
    STATE_A = "ALREADY_SETTLED_BY_FACT"       # Objectively settled (official match end, certified result)
    STATE_B = "MECHANICALLY_DETERMINED"       # Calculated from authoritative value (e.g. fix > strike)
    STATE_C = "NEAR_DETERMINISTIC"           # High probability bounded by rules; separated from primary
    STATE_D = "REJECTED"                      # Forecasting, opinion, sentiment, ambiguous news


class SourceTier(str, Enum):
    """Authoritative source hierarchy."""
    TIER_1 = "TIER_1_OFFICIAL"               # Official gov / regulator / exchange / league / authority
    TIER_2 = "TIER_2_PRIMARY"                # Primary publishing organization / official wire release
    TIER_3 = "TIER_3_SECONDARY"              # Aggregator / social media / secondary reporting (rejected for primary)


class LatencyBucket(str, Enum):
    """Required latency buckets for reaction delay analysis."""
    B_0_100MS = "0_100ms"
    B_100_250MS = "100_250ms"
    B_250_500MS = "250_500ms"
    B_500MS_1S = "500ms_1s"
    B_1_2S = "1_2s"
    B_2_5S = "2_5s"
    B_5_10S = "5_10s"
    B_10_30S = "10_30s"
    B_30S_1M = "30s_1m"
    B_1_5M = "1_5m"
    B_5_15M = "5_15m"
    B_15M_PLUS = "15m_plus"


class Phase10A10Verdict(str, Enum):
    """Required research verdicts."""
    DETERMINISTIC_RESOLUTION_EDGE_SUPPORTED = "DETERMINISTIC_RESOLUTION_EDGE_SUPPORTED"
    DETERMINISTIC_RESOLUTION_EDGE_NOT_FOUND = "DETERMINISTIC_RESOLUTION_EDGE_NOT_FOUND"
    EDGE_DESTROYED_BY_EXECUTION_COST = "EDGE_DESTROYED_BY_EXECUTION_COST"
    EDGE_DESTROYED_BY_LATENCY = "EDGE_DESTROYED_BY_LATENCY"
    EDGE_DESTROYED_BY_CAPITAL_LOCKUP = "EDGE_DESTROYED_BY_CAPITAL_LOCKUP"
    EVENT_UNIVERSE_TOO_SPARSE = "EVENT_UNIVERSE_TOO_SPARSE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"


@dataclass
class SourceRecord:
    """Authoritative source metadata and provenance."""
    source_id: str
    source_tier: SourceTier
    source_domain: str
    source_name: str
    source_url: str
    source_timestamp: datetime
    retrieval_timestamp: datetime
    content_hash: str
    raw_payload: str
    is_authoritative: bool
    rejection_reason: Optional[str] = None


@dataclass
class ContractResolutionRules:
    """Parsed deterministic resolution criteria for a Polymarket contract."""
    market_id: str
    token_id: str
    condition: str
    outcome: str
    threshold: Optional[float] = None
    inequality: Optional[str] = None  # 'GT', 'GTE', 'LT', 'LTE', 'EQ'
    measurement_variable: Optional[str] = None
    measurement_unit: Optional[str] = None
    measurement_date: Optional[str] = None
    measurement_timezone: str = "UTC"
    geography: Optional[str] = None
    resolution_source: Optional[str] = None
    resolution_date: Optional[datetime] = None
    revision_rule: Optional[str] = None
    cancellation_rule: Optional[str] = None
    is_deterministic_eligible: bool = True
    rejection_reason: Optional[str] = None


@dataclass
class ResolutionLagEvent:
    """Authoritative resolution event tied to a contract."""
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    outcome: str
    event_category: str
    title: str
    deterministic_state: DeterministicState
    source_tier: SourceTier
    source_id: str
    source_timestamp: datetime
    observation_timestamp: datetime
    deterministic_value: float  # 1.0 for winning contract, 0.0 for losing contract
    actual_value: Optional[float] = None
    threshold_value: Optional[float] = None
    is_scheduled: bool = True
    invalidation_reason: Optional[str] = None


@dataclass
class MarketStateSnapshot:
    """Reconstructed L2 market state around an event."""
    snapshot_id: str
    market_id: str
    token_id: str
    timestamp: datetime
    horizon_label: str  # e.g. 'T-60m', 'T', 'T+1s', etc.
    best_bid: float
    best_ask: float
    midpoint: float
    spread_bps: float
    depth_bid_usd: float
    depth_ask_usd: float
    bids: List[Dict[str, float]] = field(default_factory=list)
    asks: List[Dict[str, float]] = field(default_factory=list)
    provenance: str = "POLYMARKET_LIVE"


@dataclass
class CandidateOpportunity:
    """An executable mispricing candidate identified upon authoritative event arrival."""
    candidate_id: str
    event_id: str
    market_id: str
    token_id: str
    outcome: str
    deterministic_state: DeterministicState
    source_tier: SourceTier
    source_timestamp: datetime
    market_observation_timestamp: datetime
    latency_ms: float
    latency_bucket: LatencyBucket
    entry_threshold_bps: float
    target_size_usd: float
    best_ask: float
    executable_vwap: float
    available_depth_usd: float
    gross_edge_bps: float
    net_ev_bps: float
    is_out_of_sample: bool
    execution_status: str  # 'EXECUTED', 'INSUFFICIENT_DEPTH', 'THRESHOLD_NOT_MET', 'REJECTED'


@dataclass
class ExecutionRecord:
    """Execution simulation record with ladder walking and transaction costs."""
    execution_id: str
    candidate_id: str
    event_id: str
    market_id: str
    token_id: str
    outcome: str
    execution_timestamp: datetime
    position_size_usd: float
    filled_shares: float
    vwap: float
    slippage_bps: float
    fee_bps: float
    gross_deterministic_edge_bps: float
    net_ev_bps: float
    levels_consumed: int
    is_out_of_sample: bool


@dataclass
class ConvergenceRecord:
    """Market price convergence tracking toward deterministic settlement value."""
    convergence_id: str
    event_id: str
    market_id: str
    token_id: str
    source_timestamp: datetime
    first_market_timestamp: Optional[datetime] = None
    first_executable_edge_timestamp: Optional[datetime] = None
    first_convergence_timestamp: Optional[datetime] = None
    formal_resolution_timestamp: Optional[datetime] = None
    epsilon_bps: float = 10.0
    reaction_delay_sec: Optional[float] = None
    formal_delay_sec: Optional[float] = None
    has_converged: bool = False


@dataclass
class CapitalLockupRecord:
    """Capital utilization and resolution delay opportunity cost."""
    lockup_id: str
    event_id: str
    market_id: str
    position_size_usd: float
    entry_timestamp: datetime
    resolution_timestamp: datetime
    expected_delay_hours: float
    actual_delay_hours: float
    cost_of_capital_bps: float  # based on risk-free rate annualized
    gross_pnl_usd: float
    net_pnl_usd: float
    annualized_return_pct: float


@dataclass
class NegativeControlRecord:
    """Record for adversarial control verification (C1 - C6)."""
    control_id: str
    control_type: str  # 'C1_PRE_EVENT', 'C2_RANDOM_TS', 'C3_REVERSE', 'C4_SHUFFLE', 'C5_STATE_D', 'C6_COST_STRESS'
    event_id: str
    parameter_stress: float  # e.g. cost multiplier 1.0, 1.5, 2.0, 3.0
    gross_edge_bps: float
    net_ev_bps: float
    expected_result_valid: bool
    rejection_reason: Optional[str] = None


@dataclass
class HypothesisResultRecord:
    """Aggregated statistical evaluation record for primary hypotheses H1 - H5."""
    hypothesis_id: str
    hypothesis_name: str  # 'H1_OFFICIAL_RESULT', 'H2_MECHANICAL_VALUE', etc.
    entry_threshold_bps: float
    latency_bucket: LatencyBucket
    position_size_usd: float
    sample_size: int
    mean_gross_edge_bps: float
    median_gross_edge_bps: float
    mean_net_ev_bps: float
    median_net_ev_bps: float
    std_dev_bps: float
    hit_rate: float
    ci_lower_bps: float
    ci_upper_bps: float
    t_stat: float
    p_value: float
    holm_bonferroni_p: float
    cluster_count: int
    is_significant: bool
    verdict: Phase10A10Verdict
