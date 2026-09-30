"""Data schemas for Phase 10A.6 Deterministic High-Frequency Event-Study Engine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple


class EventStudyQualityStatus(str, Enum):
    VALID = "VALID"
    MISSING_PRE = "MISSING_PRE"
    MISSING_POST = "MISSING_POST"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    STALE_BOOK = "STALE_BOOK"
    CROSSED_BOOK = "CROSSED_BOOK"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    OVERLAPPING_EVENT = "OVERLAPPING_EVENT"
    OTHER_INVALID = "OTHER_INVALID"


@dataclass
class EventStudyConfig:
    """Configurable execution parameters for the event-study engine."""
    # Pre-event search windows: (Name, offset_seconds, tolerance_seconds)
    pre_horizons: List[Tuple[str, int, int]] = field(default_factory=lambda: [
        ("T-60m", -3600, 300),
        ("T-30m", -1800, 180),
        ("T-15m", -900, 120),
        ("T-5m", -300, 60),
        ("T-1m", -60, 15),
    ])

    # Post-event search windows: (Name, offset_seconds, tolerance_seconds)
    post_horizons: List[Tuple[str, int, int]] = field(default_factory=lambda: [
        ("T+5s", 5, 2),
        ("T+15s", 15, 3),
        ("T+30s", 30, 5),
        ("T+60s", 60, 10),
        ("T+5m", 300, 30),
        ("T+15m", 900, 60),
        ("T+30m", 1800, 120),
        ("T+60m", 3600, 300),
        ("T+24h", 86400, 1800),
    ])

    # Execution latencies to test (in milliseconds)
    latencies_ms: List[int] = field(default_factory=lambda: [
        0, 100, 250, 500, 1000, 2000, 5000, 10000, 30000
    ])

    # Standard test order sizes in USD
    order_sizes_usd: List[float] = field(default_factory=lambda: [
        100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0
    ])

    min_depth_usd: float = 100.0
    max_spread: float = 0.15
    max_staleness_seconds: float = 300.0
    fee_rate_bps: float = 20.0  # 0.20% Polymarket taker fee round-trip
    confidence_level: float = 0.95
    bootstrap_iterations: int = 1000
    random_seed: int = 42
    engine_version: str = "Phase10A6-v1.0-Deterministic"


@dataclass
class EventStudyObservation:
    """Pre-event and post-event order book state observation for an event."""
    observation_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    direction: str                     # "BUY" / "SELL"
    event_timestamp: datetime
    horizon_name: str
    target_offset_sec: int
    status: EventStudyQualityStatus
    status_reason: Optional[str] = None

    # Pre-event book state
    pre_timestamp: Optional[datetime] = None
    pre_exchange_timestamp: Optional[datetime] = None
    pre_mid: Optional[float] = None
    pre_bid: Optional[float] = None
    pre_ask: Optional[float] = None
    pre_spread: Optional[float] = None
    pre_spread_bps: Optional[float] = None
    pre_bid_depth_usd: Optional[float] = None
    pre_ask_depth_usd: Optional[float] = None
    pre_imbalance: Optional[float] = None

    # Post-event book state
    post_timestamp: Optional[datetime] = None
    post_exchange_timestamp: Optional[datetime] = None
    post_mid: Optional[float] = None
    post_bid: Optional[float] = None
    post_ask: Optional[float] = None
    post_spread: Optional[float] = None
    post_spread_bps: Optional[float] = None
    post_bid_depth_usd: Optional[float] = None
    post_ask_depth_usd: Optional[float] = None
    post_imbalance: Optional[float] = None

    # Midpoint repricing response
    gross_mid_movement_bps: Optional[float] = None
    signed_mid_movement_bps: Optional[float] = None

    # Provenance
    pre_snapshot_id: Optional[str] = None
    post_snapshot_id: Optional[str] = None
    pre_session_id: Optional[str] = None
    post_session_id: Optional[str] = None
    engine_version: str = "10A.6-v1.0"


@dataclass
class ExecutableResponse:
    """Microstructure-accurate taker execution response across depth and latency."""
    response_id: str
    observation_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    horizon_name: str
    latency_ms: int
    order_size_usd: float
    direction: str                     # "BUY" or "SELL"

    is_fillable: bool
    fill_price_vwap: Optional[float] = None
    gross_notional_filled: Optional[float] = None
    filled_shares: Optional[float] = None
    depth_consumed_usd: Optional[float] = None

    spread_cost_usd: Optional[float] = None
    spread_cost_bps: Optional[float] = None
    slippage_usd: Optional[float] = None
    slippage_bps: Optional[float] = None
    fee_usd: Optional[float] = None
    fee_bps: Optional[float] = None

    gross_pnl_usd: Optional[float] = None
    gross_return_bps: Optional[float] = None
    net_pnl_usd: Optional[float] = None
    net_return_bps: Optional[float] = None

    capacity_limit_usd: Optional[float] = None
    status: EventStudyQualityStatus = EventStudyQualityStatus.VALID
    status_reason: Optional[str] = None


@dataclass
class StatisticalResult:
    """Rigorous sample statistics and hypothesis tests with multiple-testing correction."""
    metric_name: str
    sample_size: int
    mean: float
    median: float
    std_dev: float
    hit_rate: float
    ci_lower: float
    ci_upper: float
    bootstrap_ci_lower: float
    bootstrap_ci_upper: float
    p_value: float
    adjusted_p_value: float            # Holm-Bonferroni adjusted
    test_type: str                     # "ONE_SAMPLE_T" or "WILCOXON" or "BOOTSTRAP"
    is_significant: bool


@dataclass
class ControlResult:
    """Empirical control evaluation result."""
    control_type: str                  # "PLACEBO_TIMESTAMPS", "REVERSE_DIRECTION", "NON_EVENT", "PRE_EVENT_LEAKAGE"
    sample_size: int
    mean_return_bps: float
    median_return_bps: float
    hit_rate: float
    p_value: float
    verdict: str                       # "COLLAPSED_TO_NULL", "REVERSED", "NO_LEAKAGE", "LEAKAGE_DETECTED"
    details: Dict[str, Any] = field(default_factory=dict)
