"""Schema definitions for Phase 10A.4 High-Frequency Event Response & Execution Validation."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple


class TimestampQuality(str, Enum):
    DIRECT = "DIRECT"              # <= 5000 ms (or <= 1000 ms)
    NEAR_EVENT = "NEAR_EVENT"      # 5s < delta <= 60s
    DELAYED = "DELAYED"            # 60s < delta <= 900s (15m)
    HOURLY_PROXY = "HOURLY_PROXY"  # > 900s (> 15m)
    UNAVAILABLE = "UNAVAILABLE"    # missing or outside tolerance


class QuoteLevel(str, Enum):
    AT_BEST = "AT_BEST"                    # Quote at best bid / ask
    ONE_TICK_OUTSIDE = "ONE_TICK_OUTSIDE"  # 1 tick worse than best price
    TWO_TICKS_OUTSIDE = "TWO_TICKS_OUTSIDE"# 2 ticks worse than best price


class OrderSideEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class L2PriceLevel:
    price: float
    size_shares: float
    size_usd: float

    def to_dict(self) -> Dict[str, float]:
        return {"price": self.price, "size_shares": self.size_shares, "size_usd": self.size_usd}


@dataclass
class BookSnapshot:
    snapshot_id: str
    market_id: str
    token_id: str
    venue: str
    timestamp_exchange: Optional[datetime]
    timestamp_local_receive: datetime
    best_bid: float
    best_ask: float
    midpoint: float
    spread: float
    spread_bps: float
    bids_l2: List[L2PriceLevel]
    asks_l2: List[L2PriceLevel]
    total_bid_depth_usd: float
    total_ask_depth_usd: float
    update_sequence: int
    raw_message_ref: Optional[str] = None


@dataclass
class BookUpdate:
    update_id: str
    market_id: str
    token_id: str
    venue: str
    timestamp_exchange: Optional[datetime]
    timestamp_local_receive: datetime
    side: OrderSideEnum
    price: float
    size: float
    delta_type: str # "add", "update", "delete"
    update_sequence: int


@dataclass
class HighFrequencyTrade:
    trade_id: str
    market_id: str
    token_id: str
    venue: str
    timestamp_exchange: Optional[datetime]
    timestamp_local_receive: datetime
    price: float
    size_shares: float
    size_usd: float
    side: OrderSideEnum
    transaction_hash: Optional[str] = None


@dataclass
class HighFrequencyEvent:
    event_id: str
    event_cluster_id: str          # Statistical unit ID (e.g., "fomc_20260916")
    source: str
    source_url: str
    timestamp_publication: datetime
    timestamp_extraction: datetime
    event_category: str
    event_type: str
    affected_entity: str
    mapped_market_id: str
    mapped_token_id: str
    direction: str                 # "INCREASE", "DECREASE"
    is_inverted: bool
    mapping_confidence: float
    mapping_status: str            # "ACCEPTED", "AMBIGUOUS", "REJECTED"
    numerical_surprise: Optional[float] = None


@dataclass
class EventWindowCapture:
    window_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    horizon_name: str              # e.g., "T-60s", "T-1s", "T+100ms", "T+1s", "T+60s"
    target_offset_ms: int
    is_available: bool
    snapshot_id: Optional[str]
    actual_timestamp: Optional[datetime]
    offset_from_target_ms: Optional[float]
    timestamp_quality: TimestampQuality
    midpoint: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread_bps: Optional[float]
    quantity_a_info_response: Optional[float] # mid(T+h) - mid(T_pre)


@dataclass
class TakerMarkoutRecord:
    markout_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    horizon_name: str
    entry_timestamp: datetime
    entry_price_ask: float
    exit_timestamp: Optional[datetime]
    exit_price_bid: Optional[float]
    quantity_b_taker_markout: Optional[float] # future_bid - entry_ask
    exchange_fee_bps: float
    slippage_bps: float
    net_taker_markout: Optional[float]


@dataclass
class MakerSimulationRecord:
    sim_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    quote_level: QuoteLevel
    side: OrderSideEnum
    quote_price: float
    quote_timestamp: datetime
    initial_queue_ahead_usd: float
    is_filled: bool
    fill_timestamp: Optional[datetime]
    is_cancelled: bool
    cancel_timestamp: Optional[datetime]
    cancellation_reason: Optional[str]
    filled_size_usd: float
    unfilled_size_usd: float
    fill_latency_ms: Optional[float]


@dataclass
class FillAnalysisRecord:
    fill_id: str
    sim_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    fill_timestamp: datetime
    fill_price: float
    filled_shares: float
    filled_usd: float
    queue_depletion_usd: float
    trades_through_count: int
    quantity_d_fill_pnl_15s: Optional[float]
    quantity_d_fill_pnl_60s: Optional[float]


@dataclass
class AdverseSelectionRecord:
    as_id: str
    fill_id: str
    event_id: str
    event_cluster_id: str
    market_id: str
    token_id: str
    fill_timestamp: datetime
    markout_100ms: Optional[float]
    markout_250ms: Optional[float]
    markout_500ms: Optional[float]
    markout_1s: Optional[float]
    markout_2s: Optional[float]
    markout_5s: Optional[float]
    markout_15s: Optional[float]
    markout_60s: Optional[float]
    is_adversely_selected: bool
    spread_captured_bps: float
    net_pnl_bps: Optional[float]
