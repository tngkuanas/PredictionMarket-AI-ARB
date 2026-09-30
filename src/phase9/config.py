"""Phase 9 Configuration: Pre-Live Adversarial Validation.
Contains frozen configuration parameters, split ratios, test grids, and adversarial bounds.
"""
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any


class FillModel(str, Enum):
    CONSERVATIVE_TRADE_THROUGH = "conservative_trade_through"
    MODERATE_BROWNIAN_BRIDGE = "moderate_brownian_bridge"
    ADVERSARIAL_VOLUME_DEPTH = "adversarial_volume_depth"


class CostRegime(str, Enum):
    OPTIMISTIC = "optimistic"
    BASE = "base"
    CONSERVATIVE = "conservative"
    SEVERE = "severe"


class TradingSession(str, Enum):
    ASIA = "asia"          # 00:00 - 08:00 UTC
    EUROPE = "europe"      # 08:00 - 14:00 UTC
    US = "us"              # 14:00 - 21:00 UTC
    OVERNIGHT = "overnight" # 21:00 - 00:00 UTC


class ContractMaturity(str, Enum):
    LONG_DATED = "long_dated"       # > 90 days
    MEDIUM_DATED = "medium_dated"   # 30 to 90 days
    SHORT_DATED = "short_dated"     # 7 to 30 days
    IMMINENT = "imminent"           # < 7 days


@dataclass(frozen=True)
class Phase9Config:
    config_version: str = "v5.0.0-phase9"
    candidate_quote_distance_d: int = 1
    tick_size: float = 0.005  # 0.5 cents
    order_size_usd: float = 500.0
    portfolio_capital_usd: float = 10000.0
    max_concurrent_exposure_usd: float = 2500.0

    # Three-way partition
    train_dev_ratio: float = 0.50
    untouched_val_ratio: float = 0.25
    locked_test_ratio: float = 0.25

    # Bootstrapping & Permutation
    bootstrap_iterations: int = 2000
    permutation_iterations: int = 2000
    random_seed: int = 42

    # Fill models to compare
    fill_models: List[FillModel] = field(default_factory=lambda: [
        FillModel.CONSERVATIVE_TRADE_THROUGH,
        FillModel.MODERATE_BROWNIAN_BRIDGE,
        FillModel.ADVERSARIAL_VOLUME_DEPTH
    ])

    # Dynamic Queue Mechanics
    queue_depletion_velocity: float = 150.0  # shares/sec executed volume
    queue_cancellation_rate: float = 0.20    # 20% of queue cancels per 5m
    queue_new_arrival_rate: float = 0.15     # 15% new orders arriving ahead

    # Sizing / Capacity Curve Grid (USD)
    capacity_curve_sizes_usd: List[float] = field(default_factory=lambda: [
        10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0
    ])

    # Multi-Horizon Attack Grid (minutes)
    evaluation_horizons_min: List[int] = field(default_factory=lambda: [
        1, 2, 5, 10, 15, 20, 30, 60
    ])

    # Cost Stress Matrix
    cost_regimes: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "optimistic": {
            "half_spread": 0.0025,
            "maker_fee_rate": 0.0,
            "slippage_drag": 0.0005,
            "latency_ms": 50.0,
            "cancel_latency_ms": 25.0
        },
        "base": {
            "half_spread": 0.0075,
            "maker_fee_rate": 0.0,
            "slippage_drag": 0.0010,
            "latency_ms": 150.0,
            "cancel_latency_ms": 100.0
        },
        "conservative": {
            "half_spread": 0.0100,
            "maker_fee_rate": 0.0005,
            "slippage_drag": 0.0025,
            "latency_ms": 500.0,
            "cancel_latency_ms": 300.0
        },
        "severe": {
            "half_spread": 0.0150,
            "maker_fee_rate": 0.0015,
            "slippage_drag": 0.0050,
            "latency_ms": 2000.0,
            "cancel_latency_ms": 1500.0
        }
    })

    # Pre-Live Shadow Protocol
    shadow_risk_budget_usd: float = 100.0
    shadow_min_order_usd: float = 10.0
    shadow_max_order_usd: float = 25.0
    hard_kill_switch_drawdown_usd: float = 50.0

    @property
    def config_hash(self) -> str:
        """Deterministic cryptographic hash representing Phase 9 configuration."""
        raw = f"{self.config_version}_{self.candidate_quote_distance_d}_{self.order_size_usd}_{self.bootstrap_iterations}_{self.random_seed}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
