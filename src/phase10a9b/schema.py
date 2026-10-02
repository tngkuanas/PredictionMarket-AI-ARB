"""Data Models and Schema Definitions for Phase 10A.9-B Forward-Causal Revalidation.

Enforces:
- Explicit execution statuses: COMPLETED, PARTIAL, FAILED_NO_FORWARD_BOOK, FAILED_INSUFFICIENT_DEPTH, AMBIGUOUS.
- Comprehensive audit trail fields: target timestamp, selected snapshot timestamp, delta ms, was_forward flag.
- Hard causality assertion: selected_snapshot_timestamp >= hedge_target_timestamp for completed and partial hedges.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, model_validator


class CausalHedgeExecutionStatus(str, Enum):
    """Explicit outcome status for forward-causal hedge execution."""
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED_NO_FORWARD_BOOK = "FAILED_NO_FORWARD_BOOK"
    FAILED_INSUFFICIENT_DEPTH = "FAILED_INSUFFICIENT_DEPTH"
    AMBIGUOUS = "AMBIGUOUS"


class CausalRevalidationVerdict(str, Enum):
    """Authoritative Verdict states for Phase 10A.9-B."""
    HEDGED_EDGE_DESTROYED_BY_HEDGE_COST = "HEDGED_EDGE_DESTROYED_BY_HEDGE_COST"
    HEDGED_EDGE_NOT_FOUND = "HEDGED_EDGE_NOT_FOUND"
    METHODOLOGY_CORRECTION_REVEALS_POTENTIAL_EDGE = "METHODOLOGY_CORRECTION_REVEALS_POTENTIAL_EDGE"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"


class CausalHedgeExecutionRecord(BaseModel):
    """Execution record with mandatory audit trail and hard forward-causality assertion."""
    hedge_id: str
    relationship_id: str
    passive_fill_id: str
    passive_token_id: str
    hedge_token_id: str
    passive_fill_timestamp: datetime
    hedge_latency_ms: int
    hedge_target_timestamp: datetime
    selected_snapshot_timestamp: Optional[datetime] = None
    snapshot_delta_ms: float = 0.0
    snapshot_was_forward: bool = True
    passive_fill_side: str
    hedge_side: str
    passive_fill_price: float
    passive_filled_shares: float
    passive_filled_usd: float
    required_quantity: float
    available_quantity: float = 0.0
    filled_quantity: float = 0.0
    VWAP: float = 0.0
    hedge_slippage_bps: float = 0.0
    hedge_spread_bps: float = 0.0
    hedge_status: CausalHedgeExecutionStatus
    residual_unhedged_shares: float = 0.0
    residual_unhedged_usd: float = 0.0
    pre_target_rejected_count: int = 0
    provenance: str = "POLYMARKET_LIVE"

    @model_validator(mode="after")
    def verify_forward_causality_invariant(self) -> "CausalHedgeExecutionRecord":
        """Hard assertion ensuring strict forward causality for completed and partial hedges."""
        if self.hedge_status in [CausalHedgeExecutionStatus.COMPLETED, CausalHedgeExecutionStatus.PARTIAL]:
            if self.selected_snapshot_timestamp is None:
                raise ValueError(f"Hedge {self.hedge_id} marked as {self.hedge_status} but has None snapshot timestamp.")
            if self.selected_snapshot_timestamp < self.hedge_target_timestamp:
                raise AssertionError(
                    f"CRITICAL CAUSALITY VIOLATION! Selected snapshot ({self.selected_snapshot_timestamp}) "
                    f"is prior to target timestamp ({self.hedge_target_timestamp})."
                )
            if not self.snapshot_was_forward:
                raise AssertionError(f"Hedge {self.hedge_id} snapshot_was_forward is False for {self.hedge_status}.")
        return self


class CausalHedgedEconomicsRecord(BaseModel):
    """Complete factor P&L decomposition under strict forward causality."""
    evaluation_id: str
    relationship_id: str
    passive_fill_id: str
    hedge_id: str
    hedge_latency_ms: int
    quote_policy: str
    queue_model: str
    hedge_status: CausalHedgeExecutionStatus
    is_fully_hedged: bool
    passive_gross_spread_bps: float
    passive_adverse_selection_bps: float
    hedge_spread_cost_bps: float
    hedge_slippage_bps: float
    hedge_fee_bps: float
    hedge_latency_cost_bps: float
    residual_inventory_cost_bps: float
    residual_liquidation_cost_bps: float
    unhedged_net_ev_bps: float
    hedged_net_ev_bps: float
    ev_improvement_bps: float
    hedged_pnl_usd: float
    is_out_of_sample: bool
    event_cluster_id: str
    provenance: str = "POLYMARKET_LIVE"


class CausalLatencyGridRecord(BaseModel):
    """Latency tier performance record under strict forward causality."""
    latency_ms: int
    n_passive_fills: int
    completed_count: int
    partial_count: int
    failed_no_book_count: int
    failed_depth_count: int
    completion_rate_pct: float
    mean_hedge_vwap: float
    mean_hedge_cost_bps: float
    mean_residual_cost_bps: float
    net_hedged_ev_bps: float


class CausalAdversarialControlRecord(BaseModel):
    """Adversarial stress test evaluation record under strict forward causality."""
    control: str
    stress_parameter: str
    n_observations: int
    mean_hedged_ev_bps: float
    delta_vs_baseline_bps: float
    behavior_matches_expectation: bool
    notes: str


class CausalHypothesisResultRecord(BaseModel):
    """Primary hypothesis test evaluation record under strict forward causality."""
    hypothesis: str
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

