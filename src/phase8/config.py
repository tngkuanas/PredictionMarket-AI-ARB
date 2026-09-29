"""Phase 8: Microstructure Realism & Prospective Stress Testing - Configuration.
Audits the Phase 7 passive execution edge under realistic latency sweeps, queue-position
stress tests, dynamic cancellation policies, and an untouched prospective evaluation (N >= 100).
Phases 5, 6, and 7 remain completely frozen as historical controls.
"""
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple, List, Dict, Any


class CancellationPolicy(str, Enum):
    NEVER_CANCEL = "never_cancel"
    CANCEL_A_REVERSES = "cancel_a_reverses"
    CANCEL_EDGE_DECAYS = "cancel_edge_decays"
    CANCEL_TIME_LIMIT_5M = "cancel_time_limit_5m"
    CANCEL_B_ADVERSE = "cancel_b_adverse"


@dataclass(frozen=True)
class Phase8Config:
    """Immutable configuration for Phase 8 execution realism and stress testing."""
    config_version: str = "v4.0.0-phase8"
    latency_sweep_version: str = "v4.0.0-latency-half-life"
    queue_stress_version: str = "v4.0.0-queue-attenuation"
    cancellation_version: str = "v4.0.0-dynamic-cancellation"
    prospective_version: str = "v4.0.0-frozen-prospective-100"

    # Candidate quote distance (tested, not assumed optimal)
    candidate_quote_distance_d: int = 1
    tick_size: float = 0.005

    # Experiment 1: Latency Sweep Grid (in milliseconds)
    latency_sweep_ms: Tuple[float, ...] = (
        0.0,       # Theoretical zero latency
        50.0,      # Co-located / low-latency API
        100.0,     # Fast fiber API
        250.0,     # Typical baseline Polymarket REST
        500.0,     # Moderate network jitter
        1000.0,    # 1 second slow polling
        2000.0,    # 2 seconds congested network
        5000.0,    # 5 seconds severe staleness
    )

    # Experiment 2: Dynamic Cancellation Policies
    active_cancellation_policies: Tuple[CancellationPolicy, ...] = (
        CancellationPolicy.NEVER_CANCEL,
        CancellationPolicy.CANCEL_A_REVERSES,
        CancellationPolicy.CANCEL_EDGE_DECAYS,
        CancellationPolicy.CANCEL_TIME_LIMIT_5M,
        CancellationPolicy.CANCEL_B_ADVERSE,
    )
    cancellation_latency_ms: float = 100.0    # 100ms round-trip to send cancel order
    a_reversal_threshold: float = 0.015       # 1.5 pp adverse move in leading contract A
    b_adverse_threshold: float = 0.010        # 1.0 pp adverse move in target contract B

    # Experiment 3: Queue Position Stress Grid (fraction of queue ahead)
    queue_ahead_ratios: Tuple[float, ...] = (
        0.00,      # First in line (magical top of book)
        0.25,      # Front quartile
        0.50,      # Median queue position
        0.75,      # Back quartile (realistic conservative)
        0.90,      # Deep queue (crowded market maker book)
        0.99,      # Back of the line
    )

    # Experiment 4: Prospective Out-of-Sample Protocol
    min_prospective_events: int = 100         # Non-negotiable target: N >= 100 independent events
    order_size_usd: float = 500.0             # Order size per simulated trade
    portfolio_capital_usd: float = 10_000.0   # Total simulated capital
    max_concurrent_exposure_usd: float = 2500.0 # 25% max capital in flight
    maker_fee_rate: float = 0.000             # 0 bps maker fee on Polymarket
    evaluation_horizon_hours: float = 0.25    # 15-minute markout evaluation

    @property
    def config_hash(self) -> str:
        payload = (
            f"{self.config_version}:{self.candidate_quote_distance_d}:{self.latency_sweep_ms}:"
            f"{self.queue_ahead_ratios}:{self.min_prospective_events}:{self.order_size_usd}:"
            f"{self.portfolio_capital_usd}:{self.cancellation_latency_ms}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
