"""Kalshi Market Data Schemas for Phase 10A.6F.

Defines schemas for raw messages, book updates, reconstructed snapshots, trades,
connection sessions, reconnect events, data quality records, and market universe.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional


class KalshiSupervisorState(str, Enum):
    """Lifecycle states for Kalshi WebSocket connection supervisor."""
    STARTING = "STARTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class KalshiDataQualityStatus(str, Enum):
    """Data quality and structural integrity status flags."""
    VALID = "VALID"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    MISSING_DATA = "MISSING_DATA"
    STALE = "STALE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    MALFORMED = "MALFORMED"
    CROSSED_BOOK = "CROSSED_BOOK"
    LOCKED_BOOK = "LOCKED_BOOK"
    IMPOSSIBLE_PRICE = "IMPOSSIBLE_PRICE"
    DUPLICATE_UPDATE = "DUPLICATE_UPDATE"
    UPDATE_BEFORE_SNAPSHOT = "UPDATE_BEFORE_SNAPSHOT"
    SESSION_CONTAMINATION = "SESSION_CONTAMINATION"


@dataclass
class KalshiRawMessageRecord:
    """Raw append-only WebSocket message frame."""
    raw_message_id: str
    session_id: str
    receive_timestamp: datetime
    exchange_timestamp: Optional[datetime]
    channel: str
    market_id: Optional[str]
    message_type: str
    raw_payload: str
    payload_sha256: str
    message_seq: int = 0


@dataclass
class KalshiBookUpdateRecord:
    """Incremental book level update."""
    update_id: str
    session_id: str
    market_id: str
    receive_timestamp: datetime
    exchange_timestamp: Optional[datetime]
    side: str                          # "yes" or "no"
    action: str                        # "add", "modify", "delete"
    price: float                       # 0.01 to 0.99
    delta_quantity: float
    remaining_quantity: float
    sequence: Optional[int]
    raw_message_id: str


@dataclass
class KalshiReconstructedBookSnapshot:
    """Deterministic reconstructed L2 order book snapshot for Kalshi."""
    snapshot_id: str
    session_id: str
    market_id: str
    receive_timestamp: datetime
    exchange_timestamp: Optional[datetime]
    sequence: Optional[int]
    yes_bids: List[Dict[str, float]]   # [{"price": p, "quantity": q}]
    yes_asks: List[Dict[str, float]]   # Derived executable side or explicit asks
    no_bids: List[Dict[str, float]]
    no_asks: List[Dict[str, float]]
    best_yes_bid: Optional[float]
    best_yes_ask: Optional[float]
    best_no_bid: Optional[float]
    best_no_ask: Optional[float]
    yes_spread: Optional[float]
    yes_bid_depth: float
    yes_ask_depth: float
    top_n_depth: float
    book_imbalance: float
    quality_status: KalshiDataQualityStatus
    quality_reason: Optional[str]
    raw_message_id: str
    book_hash: str


@dataclass
class KalshiTradeRecord:
    """Executed trade from Kalshi trade channel."""
    trade_id: str
    session_id: str
    market_id: str
    price: float
    quantity: float
    side: Optional[str]                # "yes", "no", or None if unstated
    taker_side: Optional[str]          # "yes", "no", or None (never fabricated)
    exchange_timestamp: Optional[datetime]
    receive_timestamp: datetime
    raw_message_id: str


@dataclass
class KalshiConnectionSessionRecord:
    """Tracking record for WebSocket connection session."""
    session_id: str
    start_timestamp: datetime
    end_timestamp: Optional[datetime]
    endpoint_url: str
    status: str                        # KalshiSupervisorState
    total_messages_received: int = 0
    total_messages_persisted: int = 0
    disconnect_count: int = 0
    reconnect_count: int = 0


@dataclass
class KalshiReconnectEventRecord:
    """Explicit reconnect event entry."""
    reconnect_id: str
    session_id: str
    disconnect_timestamp: datetime
    reconnect_attempt: int
    reconnect_timestamp: datetime
    reconnect_reason: str
    reconnect_latency_seconds: float
    success: bool


@dataclass
class KalshiDataQualityRecord:
    """Logged data quality anomaly."""
    record_id: str
    session_id: str
    market_id: Optional[str]
    timestamp: datetime
    component: str                     # "MESSAGE", "BOOK", "TRADE", "SUPERVISOR", "SYNCHRONIZATION"
    status: KalshiDataQualityStatus
    details: str


@dataclass
class KalshiMarketUniverseRecord:
    """Discovered Kalshi market universe metadata."""
    entry_id: str
    session_id: str
    market_id: str                     # Ticker
    title: str
    status: str                        # "open", "closed", "settled"
    open_time: Optional[datetime]
    close_time: Optional[datetime]
    expiration_time: Optional[datetime]
    settlement_source: str
    resolution_rules: str
    strike_type: Optional[str]
    floor_strike: Optional[float]
    cap_strike: Optional[float]
    tick_size: float
    volume: float
    open_interest: float
    liquidity: float
    raw_metadata_hash: str
    retrieval_timestamp: datetime


@dataclass
class KalshiNormalizedTimestamp:
    """Normalized timestamp conforming to cross-venue synchronization requirements."""
    exchange_timestamp: Optional[datetime]
    receive_timestamp: datetime
    timestamp_source: str              # "exchange", "local_receipt", "interpolated"
    timestamp_precision: str           # "microsecond", "millisecond", "second"
    clock_skew_estimate_ms: float
