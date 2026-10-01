"""Strict Schema Definitions for Phase 10A.7 Genuine Polymarket Edge Discovery.

Enforces:
1. Economic mechanism requirements for every hypothesis.
2. 7 distinct research branches (A through G).
3. 7 mutually exclusive candidate classifications.
4. Evaluation across multiple millisecond/second horizons.
5. Deterministic L2 executable pricing with fee, spread, slippage, and latency decomposition.
6. Adversarial controls (placebo, permutation, sign reversal, stress dimensions).
7. Multiple-testing accountability.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


# =====================================================================
# 1. ENUMS & TAXONOMIES
# =====================================================================

class ResearchBranch(str, Enum):
    """The 7 defined Phase 10A.7 research branches."""
    BRANCH_A_INFORMATION_EVENT = "BRANCH_A_INFORMATION_EVENT"
    BRANCH_B_ORDER_FLOW = "BRANCH_B_ORDER_FLOW"
    BRANCH_C_LIQUIDITY_BOOK = "BRANCH_C_LIQUIDITY_BOOK"
    BRANCH_D_MARKET_LIFECYCLE = "BRANCH_D_MARKET_LIFECYCLE"
    BRANCH_E_LOGICAL_CONDITIONAL = "BRANCH_E_LOGICAL_CONDITIONAL"
    BRANCH_F_PROBABILITY_EXTREMES = "BRANCH_F_PROBABILITY_EXTREMES"
    BRANCH_G_CROSS_MARKET = "BRANCH_G_CROSS_MARKET"


class CandidateClassification(str, Enum):
    """Definitive classification of candidate edge (Phase 10A.7 Edge Ranking)."""
    REJECTED_MECHANISM = "REJECTED_MECHANISM"              # Mechanism economically implausible or invalidated
    REJECTED_EXECUTION = "REJECTED_EXECUTION"              # Positive midpoint return wiped out by spread/fees/depth
    REJECTED_OOS = "REJECTED_OOS"                          # Edge fails to generalize to out-of-sample period
    REJECTED_ADVERSARIAL = "REJECTED_ADVERSARIAL"          # Edge fails placebo, permutation, or latency stress
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"                # N < 30 independent observations
    PROMISING_REQUIRES_MORE_DATA = "PROMISING_REQUIRES_MORE_DATA"  # Significant edge in Discovery/OOS but marginal N
    SURVIVING_RESEARCH_CANDIDATE = "SURVIVING_RESEARCH_CANDIDATE"  # Passes discovery, freeze, OOS, execution, & adversarial


class TradeDirection(str, Enum):
    """Direction of execution."""
    BUY = "BUY"
    SELL = "SELL"


class ProbabilityRegime(str, Enum):
    """Defined probability intervals for Branch F analysis."""
    REGIME_01_05 = "1-5%"
    REGIME_05_10 = "5-10%"
    REGIME_10_25 = "10-25%"
    REGIME_25_50 = "25-50%"
    REGIME_50_75 = "50-75%"
    REGIME_75_90 = "75-90%"
    REGIME_90_95 = "90-95%"
    REGIME_95_99 = "95-99%"


# Standard measurement horizons (ms)
EVALUATION_HORIZONS_MS: List[int] = [10, 25, 50, 100, 250, 500, 1000, 5000, 10000, 30000, 60000]


# =====================================================================
# 2. HYPOTHESIS SPECIFICATION
# =====================================================================

class HypothesisDefinition(BaseModel):
    """Economic mechanism and parameter configuration for an edge hypothesis."""
    hypothesis_id: str
    branch: ResearchBranch
    name: str
    economic_mechanism: str = Field(description="Explanation of why mispricing exists and how it is captured")
    observable_trigger: str = Field(description="Objective trigger condition initiating candidate evaluation")
    directional_prediction: TradeDirection
    expected_horizon_ms: int = 1000
    expected_magnitude_bps: float = 50.0
    execution_mechanism: str = "Taker market order walking L2 book ladder"
    failure_conditions: str = "Adverse selection, spread crossing, toxic flow"
    capacity_constraint_usd: float = 1000.0
    parameters: Dict[str, Any] = Field(default_factory=dict)
    config_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_hash(self) -> str:
        """Deterministic SHA-256 hash freezing hypothesis definition."""
        payload = {
            "hypothesis_id": self.hypothesis_id,
            "branch": self.branch.value,
            "name": self.name,
            "economic_mechanism": self.economic_mechanism.strip().lower(),
            "observable_trigger": self.observable_trigger.strip().lower(),
            "directional_prediction": self.directional_prediction.value,
            "expected_horizon_ms": self.expected_horizon_ms,
            "expected_magnitude_bps": self.expected_magnitude_bps,
            "parameters": self.parameters,
        }
        raw_json = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


# =====================================================================
# 3. OBSERVATIONS & EXECUTABLE EVALUATION
# =====================================================================

class SignalObservationRecord(BaseModel):
    """Trigger occurrence captured from live/archived market data."""
    observation_id: str
    hypothesis_id: str
    market_id: str
    token_id: str
    trigger_timestamp: datetime
    local_receive_timestamp: datetime
    exchange_timestamp: Optional[datetime] = None
    signal_value: float
    predicted_direction: TradeDirection
    midpoint_entry: float
    best_bid_entry: float
    best_ask_entry: float
    spread_entry_bps: float
    available_depth_entry_usd: float
    source_session_id: str
    source_message_hash: str
    is_out_of_sample: bool = False
    provenance: str = "POLYMARKET_LIVE"


class ExecutableEvaluationRecord(BaseModel):
    """Realistic taker execution and post-entry performance across horizons."""
    evaluation_id: str
    observation_id: str
    hypothesis_id: str
    horizon_ms: int
    target_size_usd: float
    executable_entry_vwap: float
    executable_exit_vwap: float
    midpoint_return_bps: float
    gross_executable_return_bps: float
    spread_cost_bps: float
    fee_bps: float
    slippage_bps: float
    latency_penalty_bps: float
    adverse_selection_bps: float
    net_executable_return_bps: float
    is_profitable_net: bool
    depth_exhausted: bool = False


# =====================================================================
# 4. ADVERSARIAL & MULTIPLE TESTING
# =====================================================================

class AdversarialControlRecord(BaseModel):
    """Result of adversarial stress testing for a candidate hypothesis."""
    test_id: str
    hypothesis_id: str
    test_type: str  # "PLACEBO_TIMESTAMPS", "SIGN_REVERSAL", "PERMUTATION", "LATENCY_STRESS", "SPREAD_STRESS", "DEPTH_STRESS"
    baseline_net_bps: float
    stressed_net_bps: float
    survived: bool
    p_value: float
    details: Dict[str, Any] = Field(default_factory=dict)


class BranchResearchResult(BaseModel):
    """Comprehensive empirical research report for a hypothesis across Discovery & OOS."""
    hypothesis: HypothesisDefinition
    discovery_n: int
    discovery_gross_bps: float
    discovery_net_bps: float
    oos_n: int
    oos_gross_bps: float
    oos_net_bps: float
    t_stat: float
    p_value: float
    fdr_adjusted_p: float
    adversarial_controls_passed: int
    adversarial_controls_total: int
    classification: CandidateClassification
    classification_reason: str
    horizon_breakdown: Dict[int, Dict[str, float]] = Field(default_factory=dict)
    summary_notes: List[str] = Field(default_factory=list)
