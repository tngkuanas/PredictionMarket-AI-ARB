"""Data Models and Schema Definitions for Phase 10A.9-C Forensic Audit.

Covers:
- Latency tier execution path tracing and snapshot delay quantification.
- Order book depth ratio and level consumption metrics.
- Payoff neutralization and binary settlement verification.
- Multiple-testing Holm-Bonferroni correction and discovery/OOS decomposition.
- Adversarial control validation and provenance records.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field


class Phase10A9CAuditVerdict(str, Enum):
    """Authoritative verdict states for Phase 10A.9-C forensic audit."""
    EXECUTION_MODEL_VALIDATED_EDGE_ABSENT = "EXECUTION_MODEL_VALIDATED_EDGE_ABSENT"
    EXECUTION_MODEL_HAS_LATENCY_ARTIFACTS = "EXECUTION_MODEL_HAS_LATENCY_ARTIFACTS"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"


class LatencyTierAuditRecord(BaseModel):
    """Latency tier performance and delay distribution record."""
    latency_ms: int
    requested_latency_sec: float
    n_observations: int
    completed_count: int
    partial_count: int
    failed_count: int
    pre_target_snapshots: int
    min_delay_sec: float
    med_delay_sec: float
    mean_delay_sec: float
    p95_delay_sec: float
    p99_delay_sec: float
    max_delay_sec: float
    actual_median_latency_sec: float
    actual_p95_latency_sec: float
    actual_p99_latency_sec: float
    mean_maker_ev_bps: float
    mean_hedge_spread_cost_bps: float
    mean_depth_slippage_bps: float
    mean_latency_drift_bps: float
    mean_residual_cost_bps: float
    net_hedged_ev_bps: float
    discovery_ev_bps: float
    oos_mean_ev_bps: float
    oos_median_ev_bps: float
    oos_std_bps: float
    oos_t_stat: float
    oos_raw_p: float
    oos_adj_p: float
    oos_ci_lower: float
    oos_ci_upper: float
    oos_ci_crosses_zero: bool


class DepthAuditRecord(BaseModel):
    """L2 book depth ratio and level consumption distribution."""
    min_ratio: float
    p5_ratio: float
    p10_ratio: float
    p25_ratio: float
    med_ratio: float
    p75_ratio: float
    p95_ratio: float
    max_ratio: float
    count_below_1: int
    count_eq_1: int
    count_1_to_2: int
    count_2_to_5: int
    count_above_5: int
    med_levels_consumed: float
    p95_levels_consumed: float
    max_levels_consumed: int
    med_slippage_bps: float
    p95_slippage_bps: float
    max_slippage_bps: float
    med_top_quantity: float
    p95_top_quantity: float


class PayoffNeutralizationRecord(BaseModel):
    """Binary payoff settlement and directional exposure neutralization record."""
    total_hedges: int
    neutralized_count: int
    neutralization_rate_pct: float
    max_residual_payoff: float
    min_residual_payoff: float
    mean_abs_residual: float
    r1_neutralized_count: int
    r3_residual_states: str


class LatencySampleAuditRecord(BaseModel):
    """Record verifying sample consistency across latency tiers."""
    latency_ms: int
    passive_fills_evaluated: int
    same_fills_as_0ms: bool
    unique_fills: int
    missing_fills: int
    completed: int
    partial: int
    failed: int


class ProvenanceAuditRecord(BaseModel):
    """Record validating data provenance of audited observations."""
    tier_ms: int
    sample_size: int
    verified_polymarket_live_count: int
    success_rate_pct: float
    zero_fixture_confirmed: bool
