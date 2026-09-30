"""Data schemas for Phase 10A.5 genuine high-frequency market data acquisition."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional


class DataQualityStatus(str, Enum):
    VALID = "VALID"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    MISSING_DATA = "MISSING_DATA"
    STALE = "STALE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    MALFORMED = "MALFORMED"
    CROSSED_BOOK = "CROSSED_BOOK"


@dataclass
class RawMessageRecord:
    message_id: str
    ingestion_session_id: str
    venue: str
    market_id: Optional[str]
    token_id: Optional[str]
    message_type: str
    receive_timestamp: datetime
    exchange_timestamp: Optional[datetime]
    raw_message_json: str
    sha256_hash: str
    raw_file_path: str
    message_seq: int = 0


@dataclass
class BookUpdateRecord:
    update_id: str
    session_id: str
    market_id: str
    token_id: str
    receive_timestamp: datetime
    exchange_timestamp: Optional[datetime]
    side: str                          # "BUY" or "SELL"
    price: float
    size: float
    delta_type: str                    # "insert", "update", "delete"
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    hash: Optional[str] = None


@dataclass
class ReconstructedBookSnapshot:
    snapshot_id: str
    session_id: str
    market_id: str
    token_id: str
    timestamp: datetime                # Local receive timestamp
    exchange_timestamp: Optional[datetime]
    best_bid: float
    best_ask: float
    midpoint: float
    spread: float
    spread_bps: float
    depth_bid_usd: float
    depth_ask_usd: float
    book_imbalance: float              # (bid_depth - ask_depth) / (bid_depth + ask_depth)
    bids: List[Dict[str, float]]       # [{'price': p, 'size': s, 'size_usd': u}, ...]
    asks: List[Dict[str, float]]
    quality_status: DataQualityStatus
    quality_reason: Optional[str] = None


@dataclass
class GenuineTradeRecord:
    trade_id: str
    session_id: str
    market_id: str
    token_id: str
    receive_timestamp: datetime
    exchange_timestamp: datetime
    price: float
    size: float
    size_usd: float
    side: str                          # "BUY" or "SELL"
    fee_rate_bps: float
    transaction_hash: Optional[str] = None


@dataclass
class MarketUniverseEntry:
    entry_id: str
    session_id: str
    market_id: str
    token_id: str
    outcome: str
    title: str
    category: str
    volume_24h_usd: float
    liquidity_usd: float
    is_active: bool
    is_tradable: bool
    action: str                        # "ADDED", "REMOVED", "UPDATED"
    timestamp: datetime


@dataclass
class ConnectionSessionRecord:
    session_id: str
    start_timestamp: datetime
    end_timestamp: Optional[datetime]
    endpoint_url: str
    resolved_ip: str
    total_messages_received: int
    total_messages_persisted: int
    total_bytes_received: int
    disconnect_count: int
    reconnect_count: int
    status: str                        # "CONNECTED", "DISCONNECTED", "COMPLETED", "FAILED"
    markets_count: int = 0
    tokens_count: int = 0
    messages_rejected: int = 0
    book_states_count: int = 0
    trades_count: int = 0


@dataclass
class UniverseChangeEventRecord:
    event_id: str
    timestamp: datetime
    session_id: str
    market_id: str
    token_id: str
    market_added: Optional[str]
    market_removed: Optional[str]
    reason: str


@dataclass
class HealthHeartbeatRecord:
    heartbeat_id: str
    timestamp: datetime
    session_id: str
    elapsed_seconds: float
    messages_per_hour: float
    books_per_hour: float
    trades_per_hour: float
    active_markets: int
    active_tokens: int
    disconnects: int
    reconnects: int
    downtime_seconds: float
    sequence_gaps: int
    malformed_messages: int
    one_sided_books: int
    crossed_books: int
    skew_mean_ms: float
    skew_median_ms: float
    skew_p95_ms: float
    skew_p99_ms: float
    negative_skew_count: int
    disk_storage_bytes: int


@dataclass
class ReconnectEventRecord:
    reconnect_id: str
    session_id: str
    disconnect_timestamp: datetime
    reconnect_attempt: int
    reconnect_timestamp: datetime
    reconnect_reason: str
    reconnect_latency_seconds: float
    subscription_success: bool
    snapshot_success: bool


@dataclass
class DataQualityRecord:
    record_id: str
    session_id: str
    market_id: Optional[str]
    token_id: Optional[str]
    timestamp: datetime
    status: DataQualityStatus
    component: str                     # "MESSAGE", "BOOK", "TRADE", "TIMESTAMP", "UNIVERSE"
    details: str


@dataclass
class GenuineEventRecord:
    event_id: str
    source: str
    source_url: str
    publication_timestamp: datetime
    event_category: str
    description: str
    affected_entity: str
    event_created_timestamp: datetime

