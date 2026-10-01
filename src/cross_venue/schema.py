"""Strict Schema Definitions for Phase 10A.6e Cross-Venue Polymarket-Kalshi Arbitrage.

Enforces:
1. Exact canonical economic contract representation.
2. Equivalence class taxonomy (EXACT_EQUIVALENT, COMPLEMENTARY, NESTED, etc.).
3. Machine-readable contract mapping and configuration locking.
4. Venue-neutral quote synchronization and stale-quote tracking.
5. 10 independent categorical validation statuses (no composite score).
"""

from enum import Enum
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Union
from pydantic import BaseModel, Field, model_validator


class EquivalenceClass(str, Enum):
    """Deterministic contract equivalence taxonomy (Phase 10A.6e Section 2)."""
    EXACT_EQUIVALENT = "EXACT_EQUIVALENT"                    # Provably identical settlement state and payoff
    COMPLEMENTARY = "COMPLEMENTARY"                          # P(X >= K) vs P(X < K)
    NESTED = "NESTED"                                        # P(X >= 80) vs P(X >= 70)
    CONDITIONALLY_EQUIVALENT = "CONDITIONALLY_EQUIVALENT"    # Equivalent conditional on secondary state
    SEMANTIC_ONLY = "SEMANTIC_ONLY"                          # Topical similarity without settlement proof
    NON_EQUIVALENT = "NON_EQUIVALENT"                        # Distinct payoff outcomes


class MappingStatus(str, Enum):
    """Operational status of a cross-venue mapping proposal (Phase 10A.6e Section 4)."""
    EXACT_EQUIVALENT = "EXACT_EQUIVALENT"
    COMPLEMENTARY = "COMPLEMENTARY"
    NESTED = "NESTED"
    CONDITIONALLY_EQUIVALENT = "CONDITIONALLY_EQUIVALENT"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    NON_EQUIVALENT = "NON_EQUIVALENT"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class StaleStatus(str, Enum):
    """Freshness status of synchronized quotes across venues (Phase 10A.6e Section 10)."""
    FRESH = "FRESH"                                          # Both venue quotes updated within threshold
    STALE = "STALE"                                          # One or both quotes older than threshold
    ONE_SIDED_STALE = "ONE_SIDED_STALE"                      # Single venue is stale while the other is active
    UNAVAILABLE = "UNAVAILABLE"                              # Quote missing or order book empty


class CategoryStatus(str, Enum):
    """Independent categorical states for the 10 quality gates (Phase 10A.6e Section 18)."""
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FinalArbitrageVerdict(str, Enum):
    """Final determination of cross-venue arbitrage candidate without numerical ranking."""
    ELIGIBLE = "ELIGIBLE"                                    # Passes all 10 independent categorical gates
    REJECTED = "REJECTED"                                    # Fails one or more deterministic gates
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"                  # Incomplete quote or settlement metadata


class CanonicalEconomicContract(BaseModel):
    """Deterministic representation of an economic contract's settlement state (Phase 10A.6e Section 2)."""
    venue: str = Field(description="Venue platform: 'polymarket' or 'kalshi'")
    venue_contract_id: str = Field(description="Platform-specific contract or market ticker/token ID")
    underlying_event: str = Field(description="Specific underlying real-world event")
    observation_variable: str = Field(description="Precise metric measured, e.g. 'CPI YoY %', 'BTC spot price'")
    geographic_scope: str = Field(description="Jurisdiction / geography, e.g. 'US', 'Global'")
    temporal_scope: str = Field(description="Measurement period, e.g. 'December 2026', '2026-12-31'")
    measurement_timestamp: Optional[datetime] = Field(default=None, description="Exact timestamp metric is sampled")
    resolution_timestamp: Optional[datetime] = Field(default=None, description="Official contract resolution time")
    threshold: Optional[float] = Field(default=None, description="Numeric strike or cutoff value")
    inequality_direction: Optional[str] = Field(default=None, description="Direction: '>=', '>', '<=', '<', '=='")
    strike_value: Optional[str] = Field(default=None, description="Textual or discrete strike representation")
    units: str = Field(default="USD", description="Units of measurement, e.g. 'USD', 'percent', 'bps'")
    currency: str = Field(default="USD", description="Denomination currency: 'USD' or 'USDC'")
    source_of_resolution: str = Field(description="Authoritative entity: 'BLS', 'Binance', 'Federal Reserve'")
    resolution_rules: str = Field(description="Full text of resolution rules and edge-case handling")
    cancellation_rules: str = Field(default="", description="Rules governing market cancellation/voiding")
    invalidation_rules: str = Field(default="", description="Rules governing missing or revised data")

    def compute_contract_hash(self) -> str:
        """Deterministic SHA-256 hash of canonical economic terms."""
        payload = {
            "venue": self.venue.lower(),
            "venue_contract_id": self.venue_contract_id,
            "underlying_event": self.underlying_event.strip().lower(),
            "observation_variable": self.observation_variable.strip().lower(),
            "geographic_scope": self.geographic_scope.strip().upper(),
            "temporal_scope": self.temporal_scope.strip().lower(),
            "threshold": self.threshold,
            "inequality_direction": self.inequality_direction,
            "units": self.units.strip().upper(),
            "source_of_resolution": self.source_of_resolution.strip().lower(),
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def compute_economic_terms_hash(self) -> str:
        """Deterministic SHA-256 hash of economic payoff terms (independent of contract/market ID)."""
        payload = {
            "venue": self.venue.lower(),
            "underlying_event": self.underlying_event.strip().lower(),
            "observation_variable": self.observation_variable.strip().lower(),
            "geographic_scope": self.geographic_scope.strip().upper(),
            "temporal_scope": self.temporal_scope.strip().lower(),
            "threshold": self.threshold,
            "inequality_direction": self.inequality_direction,
            "units": self.units.strip().upper(),
            "source_of_resolution": self.source_of_resolution.strip().lower(),
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


class ContractMappingResult(BaseModel):
    """Machine-readable contract mapping outcome (Phase 10A.6e Section 4)."""
    mapping_id: str
    polymarket_market_id: str
    polymarket_token_id: str
    kalshi_market_id: str
    kalshi_contract_id: str
    canonical_contract_id: str
    equivalence_class: EquivalenceClass
    settlement_equivalence: bool = Field(description="True ONLY if provably identical settlement state")
    mapping_status: MappingStatus
    mapping_reason: str = Field(description="Explicit machine-readable justification for equivalence determination")
    resolution_source_polymarket: str
    resolution_source_kalshi: str
    resolution_time_polymarket: Optional[str] = None
    resolution_time_kalshi: Optional[str] = None
    threshold_polymarket: Optional[float] = None
    threshold_kalshi: Optional[float] = None
    direction_polymarket: Optional[str] = None
    direction_kalshi: Optional[str] = None
    currency_polymarket: str = "USDC"
    currency_kalshi: str = "USD"
    mapping_config_hash: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_mapping_hash(self) -> str:
        """Deterministic SHA-256 hash of mapping specification."""
        payload = {
            "polymarket_market_id": self.polymarket_market_id,
            "polymarket_token_id": self.polymarket_token_id,
            "kalshi_market_id": self.kalshi_market_id,
            "kalshi_contract_id": self.kalshi_contract_id,
            "equivalence_class": self.equivalence_class.value,
            "settlement_equivalence": self.settlement_equivalence,
            "mapping_reason": self.mapping_reason,
            "threshold_polymarket": self.threshold_polymarket,
            "threshold_kalshi": self.threshold_kalshi,
            "direction_polymarket": self.direction_polymarket,
            "direction_kalshi": self.direction_kalshi,
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


class SyncQuote(BaseModel):
    """Synchronized price quote from a single venue (Phase 10A.6e Section 9)."""
    venue: str                                               # "polymarket" or "kalshi"
    market_id: str
    contract_id: str
    side: str                                                # "bid" or "ask"
    outcome: str                                             # "YES" or "NO"
    price: float = Field(ge=0.0, le=1.0)
    size: float = Field(ge=0.0)
    bids: List[Dict[str, float]] = Field(default_factory=list)
    asks: List[Dict[str, float]] = Field(default_factory=list)
    venue_timestamp: Optional[datetime] = None
    exchange_timestamp: Optional[datetime] = None
    local_receive_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_frame_id: Optional[str] = None


class QuoteState(BaseModel):
    """Evaluated quote state and freshness tracking (Phase 10A.6e Section 10)."""
    venue: str
    age_ms: float
    last_update_timestamp: datetime
    update_frequency_hz: float = 0.0
    stale_status: StaleStatus
    is_available: bool


class CrossVenueCostBreakdown(BaseModel):
    """Venue-neutral explicit cost interface (Phase 10A.6e Section 11)."""
    venue_fee_bps: float = 0.0
    execution_slippage_bps: float = 0.0
    latency_penalty_bps: float = 0.0
    hedge_cost_bps: float = 0.0
    total_cost_bps: float = 0.0


class ArbitrageLeg(BaseModel):
    """Details of a single leg of a cross-venue arbitrage order."""
    venue: str
    outcome: str                                             # "YES" or "NO"
    direction: str                                           # "BUY" or "SELL"
    order_size_usd: float
    best_price: float
    vwap_price: float
    shares_filled: float
    available_depth_usd: float
    fee_bps: float
    slippage_bps: float
    notional_usd: float


class LegRiskResult(BaseModel):
    """Granular operational and execution leg-risk assessment (Phase 10A.6e Section 7)."""
    fill_risk_status: CategoryStatus
    max_hedge_latency_ms: float
    price_movement_allowance_bps: float
    residual_exposure_usd: float
    max_unhedged_qty: float
    reasons: List[str] = Field(default_factory=list)


class CapitalCapacityResult(BaseModel):
    """Capital constraints and multi-venue capacity analysis (Phase 10A.6e Section 8)."""
    capital_a: float
    capital_b: float
    required_capital_a: float
    required_capital_b: float
    available_depth_a: float
    available_depth_b: float
    maximum_common_size_usd: float
    capital_utilization_ratio: float
    settlement_lockup_hours: float
    max_simultaneous_positions: int
    is_capacity_sufficient: bool
    rejection_reason: Optional[str] = None


class CrossVenueArbitrageOpportunity(BaseModel):
    """Comprehensive cross-venue arbitrage candidate with independent gate statuses (Phase 10A.6e Section 18)."""
    opportunity_id: str
    mapping_id: str
    timestamp: datetime
    sync_window_ms: int
    leg_a: ArbitrageLeg
    leg_b: ArbitrageLeg
    settlement_gross_value: float = 1.0                      # Exact binary payoff = 1.0
    gross_edge_bps: float
    cost_breakdown: CrossVenueCostBreakdown
    net_deterministic_edge_bps: float
    capital_result: CapitalCapacityResult
    leg_risk_result: LegRiskResult

    # 10 Independent Categorical Quality Gates
    mapping_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    quote_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    synchronization_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    liquidity_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    fee_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    latency_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    capacity_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    settlement_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    executable_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA
    net_edge_status: CategoryStatus = CategoryStatus.INSUFFICIENT_DATA

    final_verdict: FinalArbitrageVerdict = FinalArbitrageVerdict.REJECTED
    rejection_reasons: List[str] = Field(default_factory=list)
