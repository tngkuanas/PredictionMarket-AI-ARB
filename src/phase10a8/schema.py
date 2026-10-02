"""Strict Schema Definitions for Phase 10A.8 Passive Maker Edge Discovery.

Defines:
1. Core research units: PassiveQuote, FillResult, AdverseSelectionRecord, MakerEconomics.
2. Fill and Queue taxonomies (Q1, Q2, Q3; Trade-Through, Touch, Quote Disappearance, Ambiguous).
3. Post-fill adverse selection across standard millisecond/second horizons.
4. Independent maker economic accounting decomposition.
5. Portfolio inventory tracking and liquidation models.
6. Descriptive market-state segmentation (spread, volatility, imbalance, depth, probability).
7. Required definitive verdict states.
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

class QuoteSide(str, Enum):
    """Direction of the passive liquidity quote."""
    BUY = "BUY"
    SELL = "SELL"


class QuotePolicy(str, Enum):
    """Maker quote placement policy."""
    M1_BEST_PRICE = "M1_BEST_PRICE"            # Join best bid / best ask (top-of-book)
    M2_ONE_TICK_AWAY = "M2_ONE_TICK_AWAY"        # One tick away (conservative passive)
    M3_TWO_TICKS_AWAY = "M3_TWO_TICKS_AWAY"      # Two ticks away (deep passive)


class QueueModelType(str, Enum):
    """Model governing queue priority."""
    Q1_BACK_OF_QUEUE = "Q1_BACK_OF_QUEUE"              # Joins back of observable displayed depth
    Q2_CONSERVATIVE_PARTIAL = "Q2_CONSERVATIVE_PARTIAL"  # Partial fill proportional to volume past queue ahead
    Q3_WORST_CASE = "Q3_WORST_CASE"                    # Requires complete price exhaustion and replenishment


class FillStatus(str, Enum):
    """Resolution status of a hypothetical passive quote."""
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    UNFILLED = "UNFILLED"
    AMBIGUOUS = "AMBIGUOUS"                            # Missing/uncertain data; excluded from positive EV


class FillMechanism(str, Enum):
    """Empirical cause of the fill."""
    TRADE_THROUGH = "TRADE_THROUGH"                    # Genuine market trade strictly through quoted price
    TOUCH_VOLUME = "TOUCH_VOLUME"                      # Trade at price with volume exceeding queue ahead
    QUOTE_DISAPPEARED = "QUOTE_DISAPPEARED"            # Order book shifted without trades (NOT a fill)
    NONE = "NONE"


class MakerVerdict(str, Enum):
    """Authoritative Phase 10A.8 Verdict States."""
    PROMISING = "PROMISING — requires prospective validation"
    NO_EVIDENCE_OF_EDGE = "NO_EVIDENCE_OF_EDGE"
    EDGE_DESTROYED_BY_ADVERSE_SELECTION = "EDGE_DESTROYED_BY_ADVERSE_SELECTION"
    EDGE_DESTROYED_BY_LIQUIDATION = "EDGE_DESTROYED_BY_LIQUIDATION"
    EDGE_DEPENDENT_ON_UNVERIFIED_FILL_ASSUMPTIONS = "EDGE_DEPENDENT_ON_UNVERIFIED_FILL_ASSUMPTIONS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    METHODOLOGY_INVALID = "METHODOLOGY_INVALID"


class SpreadRegime(str, Enum):
    """Spread categories."""
    NARROW = "NARROW"      # < 100 bps
    MEDIUM = "MEDIUM"      # 100 - 300 bps
    WIDE = "WIDE"          # > 300 bps


class VolatilityRegime(str, Enum):
    """Realized volatility categories."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ImbalanceRegime(str, Enum):
    """Book order-flow imbalance categories."""
    SELL_PRESSURE = "SELL_PRESSURE"  # < -0.30
    NEUTRAL = "NEUTRAL"              # -0.30 to +0.30
    BUY_PRESSURE = "BUY_PRESSURE"    # > +0.30


class DepthRegime(str, Enum):
    """Total visible depth categories."""
    SHALLOW = "SHALLOW"  # < $500
    MEDIUM = "MEDIUM"    # $500 - $2,500
    DEEP = "DEEP"        # > $2,500


class ProbabilityRegime(str, Enum):
    """Contract implied probability categories."""
    P_00_10 = "0-10%"
    P_10_25 = "10-25%"
    P_25_50 = "25-50%"
    P_50_75 = "50-75%"
    P_75_90 = "75-90%"
    P_90_100 = "90-100%"


# Standard measurement horizons (ms)
STANDARD_HORIZONS_MS: List[int] = [100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000]

# Standard inventory limits (USD)
STANDARD_INVENTORY_LIMITS_USD: List[float] = [25.0, 50.0, 100.0, 250.0, 500.0]


# =====================================================================
# 2. CORE DATA RECORDS
# =====================================================================

class PassiveQuote(BaseModel):
    """A hypothetical passive quote placed at time t."""
    quote_id: str
    market_id: str
    token_id: str
    timestamp: datetime
    side: QuoteSide
    policy: QuotePolicy
    quote_price: float
    quote_size_usd: float = 50.0
    queue_depth_ahead_usd: float = 0.0
    spread_bps: float
    midpoint: float
    book_imbalance: float
    recent_trade_flow_usd: float = 0.0
    recent_volatility_bps: float = 0.0
    recent_trade_intensity: float = 0.0
    snapshot_id: str
    session_id: str
    is_out_of_sample: bool = False
    provenance: str = "POLYMARKET_LIVE"


class FillResult(BaseModel):
    """Evaluation of hypothetical fill based on subsequent market data."""
    fill_id: str
    quote_id: str
    fill_status: FillStatus
    fill_mechanism: FillMechanism
    queue_model: QueueModelType
    fill_timestamp: Optional[datetime] = None
    fill_price: float
    fill_size_usd: float = 0.0
    fill_shares: float = 0.0
    queue_depth_ahead_usd: float = 0.0
    subsequent_trade_count: int = 0
    trade_through_volume_usd: float = 0.0
    touch_volume_usd: float = 0.0
    time_to_fill_ms: Optional[float] = None
    provenance: str = "POLYMARKET_LIVE"


class AdverseSelectionRecord(BaseModel):
    """Post-fill price evolution and adverse selection across horizons."""
    record_id: str
    fill_id: str
    quote_id: str
    horizon_ms: int
    post_fill_timestamp: datetime
    midpoint_entry: float
    midpoint_future: float
    midpoint_change_bps: float
    executable_exit_vwap: float
    adverse_selection_bps: float
    mark_to_market_pnl_usd: float
    exit_depth_exhausted: bool = False


class MakerEconomicsRecord(BaseModel):
    """Complete economic decomposition of passive liquidity provision."""
    evaluation_id: str
    quote_id: str
    fill_id: Optional[str] = None
    horizon_ms: int
    quote_policy: QuotePolicy
    queue_model: QueueModelType
    is_filled: bool
    fill_size_usd: float
    gross_spread_capture_bps: float
    adverse_selection_bps: float
    liquidation_cost_bps: float
    inventory_cost_bps: float = 0.0
    fee_bps: float = 0.0
    net_maker_pnl_bps: float
    net_maker_pnl_usd: float
    cluster_id: str
    is_out_of_sample: bool = False
    provenance: str = "POLYMARKET_LIVE"

    def verify_accounting_identity(self, tolerance_bps: float = 0.05) -> bool:
        """Verifies net_maker_pnl_bps = gross - adverse_selection - liquidation - inventory - fee."""
        reconstructed = (
            self.gross_spread_capture_bps
            - self.adverse_selection_bps
            - self.liquidation_cost_bps
            - self.inventory_cost_bps
            - self.fee_bps
        )
        return abs(reconstructed - self.net_maker_pnl_bps) <= tolerance_bps


# =====================================================================
# 3. PORTFOLIO & INVENTORY MODELS
# =====================================================================

class InventoryPositionRecord(BaseModel):
    """Tracking of cumulative directional exposure and liquidation events."""
    market_id: str
    inventory_limit_usd: float
    cumulative_yes_usd: float = 0.0
    cumulative_no_usd: float = 0.0
    net_directional_usd: float = 0.0
    max_inventory_usd: float = 0.0
    cumulative_fills_count: int = 0
    rejected_fills_count: int = 0
    total_liquidation_events: int = 0
    total_liquidation_cost_usd: float = 0.0
    holding_time_seconds_total: float = 0.0


# =====================================================================
# 4. ADVERSARIAL CONTROLS & STATISTICAL AGGREGATION
# =====================================================================

class AdversarialMakerControlRecord(BaseModel):
    """Adversarial stress test results for passive maker strategies."""
    control_id: str
    control_type: str  # RANDOM_TIMESTAMPS, SIDE_PERMUTATION, FILL_PERMUTATION, LATENCY_STRESS, FILL_PESSIMISM, LIQUIDATION_STRESS
    parameter_value: Any
    baseline_net_ev_bps: float
    controlled_net_ev_bps: float
    null_hypothesis_satisfied: bool
    details: Dict[str, Any] = Field(default_factory=dict)


class HypothesisSummaryResult(BaseModel):
    """Empirical findings for each of the 5 Phase 10A.8 maker hypotheses."""
    hypothesis_id: str
    name: str
    description: str
    n_raw: int
    n_clusters: int
    fill_count: int
    ambiguous_count: int
    fill_rate: float
    gross_spread_capture_bps: float
    adverse_selection_bps: float
    liquidation_cost_bps: float
    net_maker_ev_bps: float
    net_maker_ev_usd: float
    ev_per_quote_bps: float
    ev_per_fill_bps: float
    std_dev_bps: float
    ci_95_lower_bps: float
    ci_95_upper_bps: float
    bootstrap_ci_lower_bps: float
    bootstrap_ci_upper_bps: float
    verdict: MakerVerdict
    details: Dict[str, Any] = Field(default_factory=dict)
