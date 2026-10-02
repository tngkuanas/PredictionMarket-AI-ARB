"""Strict Schema Definitions for Phase 10A.9 Hedged Passive / Cross-Contract Neutralization.

Defines:
1. Candidate relationship taxonomies (R1, R2, R3, R4, R5).
2. Deterministic validation gates and rejection taxonomies.
3. Execution records for passive and hedge legs (VWAP, depth exhaustion, partial fills).
4. Complete hedged economic lifecycle decomposition and accounting identities.
5. Multi-leg inventory tracking and basis risk models.
6. Authoritative hypothesis, adversarial control, and verdict definitions.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


# =====================================================================
# 1. TAXONOMIES & ENUMS
# =====================================================================

class RelationshipType(str, Enum):
    """Deterministic contract relationship class."""
    R1_COMPLEMENTARY_BINARY = "R1_COMPLEMENTARY_BINARY"       # YES + NO = $1 within same binary market
    R2_COMPLEMENTARY_CROSS_MARKET = "R2_COMPLEMENTARY_CROSS_MARKET" # Cross-market complementary outcome
    R3_NESTED_MONOTONIC = "R3_NESTED_MONOTONIC"               # Strike corridor: P(X > 70) <= P(X > 60)
    R4_MUTUALLY_EXCLUSIVE_SET = "R4_MUTUALLY_EXCLUSIVE_SET"   # Partitioned outcomes: sum(P_i) = 1
    R5_CONDITIONAL_STRUCTURED = "R5_CONDITIONAL_STRUCTURED"   # Formal implication / structured payoff


class RelationshipValidationStatus(str, Enum):
    """Deterministic validation verdict for contract relationship."""
    EXACT_HEDGEABLE = "EXACT_HEDGEABLE"                       # Mathematically exact, riskless terminal payoff
    BOUNDED_HEDGEABLE = "BOUNDED_HEDGEABLE"                   # Known strict payoff bounds (e.g., vertical corridor)
    CONDITIONALLY_HEDGEABLE = "CONDITIONALLY_HEDGEABLE"       # Hedgeable conditional on verifiable state
    NON_HEDGEABLE = "NON_HEDGEABLE"                           # Violates semantic, legal, or settlement criteria
    AMBIGUOUS = "AMBIGUOUS"                                   # Missing or conflicting criteria; excluded from P&L


class RelationshipRejectionReason(str, Enum):
    """Specific cause for rejecting a candidate relationship."""
    NONE = "NONE"
    EVENT_MISMATCH = "EVENT_MISMATCH"
    VARIABLE_MISMATCH = "VARIABLE_MISMATCH"
    THRESHOLD_MISMATCH = "THRESHOLD_MISMATCH"
    INEQUALITY_MISMATCH = "INEQUALITY_MISMATCH"
    TIME_MISMATCH = "TIME_MISMATCH"
    GEOGRAPHY_MISMATCH = "GEOGRAPHY_MISMATCH"
    RESOLUTION_MISMATCH = "RESOLUTION_MISMATCH"
    SETTLEMENT_MISMATCH = "SETTLEMENT_MISMATCH"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    HEDGE_RATIO_UNRESOLVED = "HEDGE_RATIO_UNRESOLVED"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"


class HedgeExecutionStatus(str, Enum):
    """Outcome of attempting to execute the hedge leg."""
    COMPLETE_HEDGE = "COMPLETE_HEDGE"                         # 100% of passive exposure neutralized
    PARTIAL_HEDGE = "PARTIAL_HEDGE"                           # Depth exhausted; partial exposure neutralized
    HEDGE_DEPTH_INSUFFICIENT = "HEDGE_DEPTH_INSUFFICIENT"     # Zero depth at or near market; no hedge filled
    FAILED_HEDGE = "FAILED_HEDGE"                             # Technical or data error executing hedge leg


class HedgedVerdict(str, Enum):
    """Authoritative Phase 10A.9 Verdict States."""
    HEDGED_EDGE_SUPPORTED = "HEDGED_EDGE_SUPPORTED"
    HEDGED_EDGE_NOT_FOUND = "HEDGED_EDGE_NOT_FOUND"
    HEDGED_EDGE_DESTROYED_BY_HEDGE_COST = "HEDGED_EDGE_DESTROYED_BY_HEDGE_COST"
    HEDGED_EDGE_DESTROYED_BY_LATENCY = "HEDGED_EDGE_DESTROYED_BY_LATENCY"
    HEDGED_EDGE_DESTROYED_BY_RESIDUAL_RISK = "HEDGED_EDGE_DESTROYED_BY_RESIDUAL_RISK"
    HEDGE_RELATIONSHIPS_TOO_SPARSE = "HEDGE_RELATIONSHIPS_TOO_SPARSE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"


class PrimaryHypothesis(str, Enum):
    """Formal research hypotheses tested in Phase 10A.9."""
    H1_EXACT_COMPLEMENTARY_HEDGE = "H1_EXACT_COMPLEMENTARY_HEDGE"
    H2_CROSS_CONTRACT_COMPLEMENTARY = "H2_CROSS_CONTRACT_COMPLEMENTARY"
    H3_NESTED_PAYOFF_HEDGE = "H3_NESTED_PAYOFF_HEDGE"
    H4_MULTI_OUTCOME_NEUTRALIZATION = "H4_MULTI_OUTCOME_NEUTRALIZATION"
    H5_LATENCY_TOLERANT_HEDGING = "H5_LATENCY_TOLERANT_HEDGING"


class AdversarialControl(str, Enum):
    """Stress tests and falsification controls."""
    C1_RANDOM_PAIRING = "C1_RANDOM_PAIRING"
    C2_REVERSE_HEDGE_DIRECTION = "C2_REVERSE_HEDGE_DIRECTION"
    C3_HEDGE_LATENCY_STRESS = "C3_HEDGE_LATENCY_STRESS"
    C4_DEPTH_STRESS = "C4_DEPTH_STRESS"
    C5_PARTIAL_HEDGE_STRESS = "C5_PARTIAL_HEDGE_STRESS"
    C6_SPREAD_STRESS = "C6_SPREAD_STRESS"


# Standard evaluated hedge latencies (ms)
STANDARD_HEDGE_LATENCIES_MS: List[int] = [0, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000]

# Standard inventory limits (USD)
STANDARD_INVENTORY_LIMITS_USD: List[float] = [25.0, 50.0, 100.0, 250.0, 500.0]


# =====================================================================
# 2. CORE DATA RECORDS
# =====================================================================

class ContractRelationshipRecord(BaseModel):
    """Audit record formalizing the economic and deterministic relationship between two contracts."""
    relationship_id: str
    contract_a: str                         # Passive leg token_id
    contract_b: str                         # Hedge leg token_id
    market_id_a: str
    market_id_b: str
    relationship_type: RelationshipType
    event_identity: str
    variable: str
    threshold: Optional[float] = None
    inequality: Optional[str] = None
    time_window: str
    timezone: str = "UTC"
    geography: str = "GLOBAL"
    resolution_source: str
    resolution_date: str
    payout_formula: str                     # e.g., "Payoff(A) + Payoff(B) == 1.0"
    hedge_ratio: float                      # e.g., 1.0 for binary complement
    relationship_confidence: float = 1.0
    validation_status: RelationshipValidationStatus
    reason: str
    provenance: str = "POLYMARKET_LIVE"


class HedgeExecutionRecord(BaseModel):
    """Execution details of the hedge leg following a passive fill."""
    hedge_id: str
    relationship_id: str
    passive_fill_id: str
    passive_token_id: str
    hedge_token_id: str
    passive_fill_timestamp: datetime
    hedge_timestamp: datetime
    hedge_latency_ms: int
    passive_fill_side: str                  # "BUY" or "SELL"
    hedge_side: str                         # "BUY" or "SELL"
    passive_fill_price: float
    passive_filled_shares: float
    passive_filled_usd: float
    hedge_required_shares: float
    hedge_filled_shares: float
    hedge_filled_usd: float
    hedge_vwap: float
    hedge_slippage_bps: float
    hedge_spread_bps: float
    hedge_depth_exhausted: bool = False
    residual_unhedged_shares: float = 0.0
    residual_unhedged_usd: float = 0.0
    execution_status: HedgeExecutionStatus
    provenance: str = "POLYMARKET_LIVE"


class HedgedEconomicsRecord(BaseModel):
    """Complete economic decomposition of a paired passive-maker and hedge execution."""
    evaluation_id: str
    relationship_id: str
    passive_fill_id: str
    hedge_id: str
    hedge_latency_ms: int
    quote_policy: str                       # M1_BEST_PRICE, M2, M3
    queue_model: str                        # Q1, Q2, Q3
    is_fully_hedged: bool
    passive_gross_spread_bps: float
    passive_adverse_selection_bps: float
    hedge_spread_cost_bps: float
    hedge_slippage_bps: float
    hedge_fee_bps: float = 0.0              # Polymarket 0 bps maker/taker fee
    hedge_latency_cost_bps: float
    residual_inventory_cost_bps: float = 0.0
    residual_liquidation_cost_bps: float = 0.0
    unhedged_net_ev_bps: float
    hedged_net_ev_bps: float
    ev_improvement_bps: float               # hedged_net_ev_bps - unhedged_net_ev_bps
    hedged_pnl_usd: float
    is_out_of_sample: bool = False
    event_cluster_id: str = "cluster_default"
    provenance: str = "POLYMARKET_LIVE"


class HedgeInventoryStateRecord(BaseModel):
    """Multi-leg portfolio inventory tracking."""
    record_id: str
    market_id: str
    timestamp: datetime
    inventory_limit_usd: float
    gross_passive_usd: float
    gross_hedge_usd: float
    net_directional_usd: float
    residual_unhedged_usd: float
    cumulative_passive_fills: int
    cumulative_hedges_executed: int
    rejected_fills_limit_breach: int
    forced_liquidations_count: int
    forced_liquidation_cost_usd: float = 0.0


class BasisRiskRecord(BaseModel):
    """Residual payoff risk analysis for non-exact hedges."""
    relationship_id: str
    relationship_type: RelationshipType
    maximum_residual_payoff_usd: float
    expected_residual_exposure_usd: float
    worst_case_settlement_mismatch_bps: float
    is_risk_acceptable: bool


class HypothesisResultRecord(BaseModel):
    """Empirical testing results for Primary Hypotheses H1-H5."""
    hypothesis: PrimaryHypothesis
    n_observations: int
    n_clusters: int
    mean_hedged_ev_bps: float
    median_hedged_ev_bps: float
    cluster_robust_se: float
    t_stat: float
    p_value: float
    ci_95_lower_bps: float
    ci_95_upper_bps: float
    hedge_completion_rate_pct: float
    mean_ev_improvement_bps: float
    is_supported: bool
    summary: str


class AdversarialControlRecord(BaseModel):
    """Stress test and falsification audit record."""
    control: AdversarialControl
    stress_parameter: str
    n_observations: int
    mean_hedged_ev_bps: float
    delta_vs_baseline_bps: float
    behavior_matches_expectation: bool
    notes: str
