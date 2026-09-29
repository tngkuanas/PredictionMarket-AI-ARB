"""Phase 7: Passive Execution & Market-Making Attack - Configuration.
Independent research configuration testing liquidity-provision capture of the 15-minute stat-arb signal.
Phases 5 and 6 remain completely frozen as control experiments.
"""
import hashlib
from dataclasses import dataclass, field
from typing import Tuple, List, Dict, Any


@dataclass(frozen=True)
class Phase7Config:
    """Immutable configuration for Phase 7 passive execution and market making."""
    config_version: str = "v3.0.0-phase7"
    event_response_version: str = "v3.0.0-event-specific-beta"
    passive_simulator_version: str = "v3.0.0-l2-queue-markout"
    evaluator_version: str = "v3.0.0-passive-adverse-selection"

    # Passive quote distance grid (in ticks; 1 tick = 0.5 cents / 0.005)
    tick_size: float = 0.005
    passive_tick_distances: Tuple[int, ...] = (0, 1, 2, 3)

    # Fee structures (Polymarket CLOB)
    maker_fee_rate: float = 0.000      # 0 bps maker fee on Polymarket
    taker_fee_rate: float = 0.001      # 10 bps taker fee for comparison
    order_size_usd: float = 500.0      # Standard order size per trade

    # Evaluation horizons for post-fill markout (in hours)
    markout_horizons_hours: Tuple[float, ...] = (
        1.0 / 60.0,   # 1m
        5.0 / 60.0,   # 5m
        0.25,         # 15m (primary signal peak)
        1.0,          # 1h (decay horizon)
    )

    # Adverse selection and execution parameters
    target_signal_horizon_hours: float = 0.25    # 15m target peak
    adverse_selection_loss_threshold: float = -0.005 # Markout < -50 bps classified as toxic adverse fill
    simulated_order_latency_ms: float = 150.0   # 150ms network round-trip to place passive limit order
    queue_participation_factor: float = 0.75    # Conservative: 75% of existing queue must trade before us

    # Event shock threshold
    catalyst_min_impulse: float = 0.03          # Minimum 3.0 pp move in leading contract A

    @property
    def config_hash(self) -> str:
        payload = (
            f"{self.config_version}:{self.tick_size}:{self.passive_tick_distances}:"
            f"{self.maker_fee_rate}:{self.taker_fee_rate}:{self.order_size_usd}:"
            f"{self.target_signal_horizon_hours}:{self.adverse_selection_loss_threshold}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
