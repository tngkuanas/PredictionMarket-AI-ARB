"""Phase 6: Attack the Current Model - Configuration.
Independent, upgraded research configuration exploring relative-value stat-arb,
strict causal hypotheses, multi-horizon signal decay, and separated trade construction.
Phase 5 remains completely frozen as the uncorrupted control experiment.
"""
import hashlib
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any


@dataclass(frozen=True)
class Phase6Config:
    """Immutable configuration for Phase 6 relative-value stat-arb research."""
    config_version: str = "v2.0.0-phase6"
    hypothesis_generator_version: str = "v2.0.0-strict-causal-9dim"
    stat_arb_model_version: str = "v2.0.0-state-conditional-relative-value"
    trade_engine_version: str = "v2.0.0-separated-fair-value-execution"
    decay_analyzer_version: str = "v2.0.0-multi-horizon-decay"

    # Strict hypothesis parameters
    max_curated_hypotheses: int = 15           # Force model to propose fewer, stronger hypotheses
    min_economic_move_threshold: float = 0.02  # Target market move must be >= 2.0 pp

    # State-conditional relative-value regression & residual params
    residual_zscore_threshold: float = 1.5     # Large residual trigger (|epsilon| >= 1.5 * sigma)
    min_mean_reversion_kappa: float = 0.05     # Minimum mean reversion speed parameter
    max_half_life_hours: float = 48.0          # Half-life of residual reversion must be <= 48h
    stationarity_pvalue_hurdle: float = 0.05   # ADF test p-value threshold on residuals

    # Execution & trade construction params
    min_net_edge_hurdle: float = 0.015         # 1.5% net executable edge required
    min_independent_epochs_k: int = 15         # Minimum 15 independent 72h macro event epochs
    simulated_latency_ms: float = 250.0        # 250ms simulated execution latency
    taker_fee_rate: float = 0.001              # 10 bps taker fee
    default_order_size_usd: float = 500.0      # Capital per simulated order
    fdr_alpha: float = 0.05                    # Benjamini-Hochberg FDR control rate

    # Multi-horizon signal age decay evaluation (in hours)
    # 1 min (1/60), 5 min (5/60), 15 min (0.25), 1 hour (1.0), 6 hours (6.0), 24 hours (24.0), resolution (72.0)
    evaluation_horizons_hours: Tuple[float, ...] = (
        1.0 / 60.0,
        5.0 / 60.0,
        0.25,
        1.0,
        6.0,
        24.0,
        72.0,
    )

    # Sensitivity / Perturbation test grid
    perturbation_hurdles: Tuple[float, ...] = (0.010, 0.015, 0.020)
    perturbation_latencies_ms: Tuple[float, ...] = (100.0, 250.0, 500.0)
    perturbation_residual_triggers: Tuple[float, ...] = (1.0, 1.5, 2.0)

    @property
    def config_hash(self) -> str:
        payload = (
            f"{self.config_version}:{self.residual_zscore_threshold}:"
            f"{self.min_net_edge_hurdle}:{self.min_independent_epochs_k}:"
            f"{self.simulated_latency_ms}:{self.taker_fee_rate}:{self.max_curated_hypotheses}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
