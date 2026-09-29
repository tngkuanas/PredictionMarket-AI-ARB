"""Core schemas for prediction market models, observations, relationships, and executions."""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Platform(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"

class MarketStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OutcomeType(str, Enum):
    YES = "YES"
    NO = "NO"

# ==========================================
# 2. RAW / NORMALIZED MARKET SCHEMA
# ==========================================

class Market(BaseModel):
    platform: Platform
    market_id: str
    event_id: str
    title: str
    description: str
    resolution_rules: str
    outcome_labels: List[str]
    category: str
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    resolution_time: Optional[datetime] = None
    status: MarketStatus = MarketStatus.ACTIVE
    # Metadata helpers
    clob_token_ids: Optional[List[str]] = None
    condition_id: Optional[str] = None
    volume: Optional[float] = 0.0
    liquidity: Optional[float] = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Observation(BaseModel):
    timestamp: datetime
    market_id: str
    platform: Platform = Platform.POLYMARKET
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    yes_mid: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    volume: Optional[float] = 0.0
    liquidity: Optional[float] = 0.0

class Trade(BaseModel):
    timestamp: datetime
    market_id: str
    platform: Platform = Platform.POLYMARKET
    side: OrderSide
    price: float
    quantity: float

# ==========================================
# 3. CANONICAL MARKET REPRESENTATION
# ==========================================

class CanonicalMarket(BaseModel):
    market_id: str
    platform: Platform
    title: str
    underlying_event: str
    entities: List[str]
    geographic_scope: str
    time_horizon: str
    event_type: str
    threshold: Optional[str] = None
    direction: Optional[str] = None
    numerical_conditions: Optional[Dict[str, Any]] = None
    resolution_date: Optional[str] = None
    resolution_source: Optional[str] = None
    resolution_methodology: Optional[str] = None
    ambiguity_flags: List[str] = Field(default_factory=list)

# ==========================================
# 4. RELATIONSHIP CLASSES & HYPOTHESIS
# ==========================================

class RelationshipType(str, Enum):
    DIRECT_EQUIVALENCE = "direct_equivalence"          # A ≈ B
    COMPLEMENT = "complement"                          # A ≈ NOT B
    IMPLICATION = "implication"                        # A -> B
    CONDITIONAL_DEPENDENCE = "conditional_dependence"  # P(B|A) != P(B)
    POSITIVE_ECONOMIC = "positive_economic"            # A up -> B up
    NEGATIVE_ECONOMIC = "negative_economic"            # A up -> B down
    SECOND_ORDER = "second_order"                      # A -> X -> B
    EVENT_CHAIN = "event_chain"                        # Event A changes P(B)
    TEMPORAL_LEAD_LAG = "temporal_lead_lag"            # A moves before B
    CROSS_PLATFORM_EQUIVALENCE = "cross_platform_equivalence" # Poly A ≈ Kalshi B
    RESOLUTION_RULE = "resolution_rule"                # Similar economic event, divergent settlement

class ConstraintType(str, Enum):
    DIRECTIONAL_IMPULSE = "directional_impulse"      # ΔP(A) >= X implies ΔP(B) in direction within T hours
    MONOTONE_BOUND = "monotone_bound"                # P(B) <= P(A) + epsilon (implication bound)
    SPREAD_MEAN_REVERSION = "spread_mean_reversion"  # P(A) - P(B) cointegrated / mean reverts
    COMPLEMENT_SUM = "complement_sum"                # P(A) + P(B) == 1.0 (exact sum)
    CONDITIONAL_PROBABILITY_SHIFT = "conditional_prob_shift" # P(B | ΔA > 0) != P(B | ΔA <= 0)

class OpportunityClass(str, Enum):
    STRUCTURAL = "structural"                      # Baseline Control: Monotonic threshold ladder ($88k -> $82k)
    CROSS_MARKET_LOGICAL = "cross_market_logical"  # Baseline Control: Exact complement / logical negation
    AI_SEMANTIC = "ai_semantic"                    # Novel: Macro event -> Cross-market repricing
    SECOND_ORDER = "second_order"                  # Novel: Indirect transmission (A -> X -> B)
    INFORMATION_LATENCY = "information_latency"    # Novel: Event repricing in fast market vs stale quote
    RESOLUTION_ARBITRAGE = "resolution_arbitrage"  # Novel: Settlement rule divergence exploitation

class OutputARelationshipDiscovery(BaseModel):
    """Output A: The conceptual economic discovery."""
    discovery_id: str
    market_a_id: str
    market_b_id: str
    opportunity_class: OpportunityClass = OpportunityClass.AI_SEMANTIC
    relationship_type: RelationshipType
    economic_mechanism: str
    domain_cluster: str
    why_embedding_misses: str
    confidence: float = Field(ge=0.0, le=1.0)
    discovery_timestamp: datetime = Field(default_factory=datetime.utcnow)

class OutputBEconomicConstraint(BaseModel):
    """Output B: Falsifiable pricing constraint that can generate a trade."""
    constraint_id: str
    discovery_id: str
    market_a_id: str
    market_b_id: str
    constraint_type: ConstraintType
    trigger_threshold_delta_a: float = 0.03
    expected_delta_b: float = 0.02
    lead_time_hours: float = 6.0
    testable_null_hypothesis: str
    mathematical_expression: str
    invalidation_criteria: List[str] = Field(default_factory=list)
    is_active: bool = True

class HypothesisVerdict(str, Enum):
    TRADEABLE = "TRADEABLE"
    REJECTED_SPURIOUS = "REJECTED_SPURIOUS"
    REJECTED_COSTS = "REJECTED_COSTS"
    REJECTED_UNDERPOWERED = "REJECTED_UNDERPOWERED"
    REJECTED_DIRECTION_MISMATCH = "REJECTED_DIRECTION_MISMATCH"
    REJECTED_BASIS_RISK = "REJECTED_BASIS_RISK"
    REJECTED_OOS_DECAY = "REJECTED_OOS_DECAY"

class FalsificationResult(BaseModel):
    constraint_id: str
    market_a: str
    market_b: str
    opportunity_class: OpportunityClass = OpportunityClass.AI_SEMANTIC
    sample_size_n: int
    is_sample_size_n: int = 0
    oos_sample_size_n: int = 0
    # In-Sample (IS) Metrics
    observed_effect_pp: float
    baseline_drift_pp: float
    net_effect_pp: float
    ci_95_low_pp: float
    ci_95_high_pp: float
    p_value: float
    # Out-of-Sample (OOS) Replication Metrics
    oos_observed_effect_pp: float = 0.0
    oos_net_effect_pp: float = 0.0
    oos_p_value: float = 1.0
    lead_time_hours: float
    is_cointegrated: bool
    is_spurious_drift: bool
    # Basis Risk & Resolution divergence
    resolution_divergence_prob: float = 0.0
    basis_risk_score: float = 0.0
    # Friction & Final EV
    raw_edge_pp: float
    friction_costs_pp: float
    net_expected_edge_pp: float
    verdict: HypothesisVerdict
    kill_reason: Optional[str] = None
    evidence_summary: str
    test_timestamp: datetime = Field(default_factory=datetime.utcnow)

class CandidateRelationship(BaseModel):
    discovery: OutputARelationshipDiscovery
    constraint: OutputBEconomicConstraint
    intermediate_nodes: List[str] = Field(default_factory=list)
    hop_count: int = 1

# ==========================================
# 6 & 7. RESOLUTION ANALYSIS & QUANT VALIDATION
# ==========================================

class ResolutionRuleAnalysis(BaseModel):
    market_a: str
    market_b: str
    prob_divergence: float = Field(ge=0.0, le=1.0) # P(resolution divergence)
    basis_risk_score: float = Field(ge=0.0, le=1.0)
    deadline_divergence: bool = False
    source_divergence: bool = False
    definition_divergence: bool = False
    is_mathematically_guaranteed: bool = False
    divergence_reasons: List[str] = Field(default_factory=list)

class ValidationResult(BaseModel):
    market_a: str
    market_b: str
    relationship_type: RelationshipType
    # Statistical Metrics
    price_correlation: float
    return_correlation: float
    rolling_correlation_mean: float
    lead_lag_correlation_peak: float
    optimal_lag_steps: int
    p_b_given_a: float
    p_b_given_not_a: float
    market_implied_p_b: float
    conditional_mispricing: float # P(B|A) - market P(B)
    spread_mean: float
    spread_zscore: float
    is_cointegrated: bool
    cointegration_pvalue: Optional[float] = None
    stationarity_pvalue: Optional[float] = None
    volatility_a: float
    volatility_b: float
    historical_hit_rate: float
    max_adverse_excursion: float
    time_to_convergence_hours: float
    relationship_break_frequency: float
    # Resolution checks
    resolution_analysis: Optional[ResolutionRuleAnalysis] = None
    # Validation status
    is_statistically_valid: bool
    validation_timestamp: datetime = Field(default_factory=datetime.utcnow)
    evidence_summary: str

# ==========================================
# 8 & 9. MISPRICING / SIGNALS
# ==========================================

class Signal(BaseModel):
    signal_id: str
    timestamp: datetime
    strategy_name: str # "second_order_arb", "information_latency", "baseline_..."
    market_target: str
    market_anchor: Optional[str] = None
    side: OrderSide
    model_fair_value: float
    market_implied_value: float
    raw_edge: float
    # Cost & risk adjustments
    spread_cost: float
    fee_cost: float
    slippage_cost: float
    basis_risk_discount: float
    uncertainty_discount: float
    net_expected_value: float # Raw edge - all friction
    recommended_size_usd: float
    confidence: float
    expiration_window_seconds: float
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ==========================================
# 12 & 18. EXECUTION & DATABASE LOGS
# ==========================================

class PaperOrder(BaseModel):
    order_id: str
    timestamp: datetime
    signal_id: str
    market_id: str
    platform: Platform
    side: OrderSide
    order_type: str = "LIMIT" # LIMIT or IOC
    limit_price: float
    quantity: float
    status: str = "PENDING" # PENDING, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED

class PaperFill(BaseModel):
    fill_id: str
    order_id: str
    timestamp: datetime
    market_id: str
    platform: Platform
    side: OrderSide
    fill_price: float
    quantity: float
    fee: float
    slippage: float
    net_pnl: Optional[float] = 0.0

class PortfolioSnapshot(BaseModel):
    timestamp: datetime
    cash: float
    portfolio_value: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_fees_paid: float
    total_slippage_paid: float
    open_positions_count: int
    exposure_usd: float
    daily_drawdown_pct: float
    max_drawdown_pct: float


# ==========================================
# 19. PHASE 5 SHADOW TRADING AUDIT LOGS
# ==========================================

class ShadowCandidate(BaseModel):
    candidate_id: str
    t0_timestamp: datetime = Field(default_factory=datetime.utcnow)
    market_id: str
    token_id: str
    title: str
    opportunity_class: OpportunityClass
    predicted_fair_value: float
    market_mid_price: float
    raw_edge: float
    frozen_min_edge_threshold: float
    status: str # "FILTERED_OUT", "CANDIDATE_ACTIVE", "ORDER_GENERATED"
    rejection_reason: Optional[str] = None
    target_horizon_hours: float = 24.0
    target_timestamp: Optional[datetime] = None

class ShadowOrder(BaseModel):
    order_id: str
    candidate_id: str
    market_id: str
    token_id: str
    side: OrderSide
    placed_at: datetime = Field(default_factory=datetime.utcnow)
    limit_price: float
    target_size_usd: float
    status: str = "PENDING" # "PENDING", "FILLED", "CANCELLED", "REJECTED"
    simulated_latency_ms: float = 250.0

class ShadowFill(BaseModel):
    fill_id: str
    order_id: str
    candidate_id: str
    market_id: str
    filled_at: datetime = Field(default_factory=datetime.utcnow)
    side: OrderSide
    fill_price: float
    size_usd: float
    fee_usd: float
    slippage_usd: float
    levels_swept: int = 1
    status: str = "FILLED" # "FILLED", "PARTIAL_FILL", "REJECTED_DEPTH"
    realized_edge: Optional[float] = None

class ShadowRunRecord(BaseModel):
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    config_version: str
    config_hash: str
    candidate_generator_version: str
    execution_model_version: str
    markets_scanned: int
    candidates_generated: int
    filtered_out_count: int
    active_candidates_count: int
    orders_placed: int
    fills_executed: int
    rejections_json: Dict[str, Any] = Field(default_factory=dict)
