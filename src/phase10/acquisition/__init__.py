"""Phase 10A.5 Genuine High-Frequency Market Data Acquisition Package."""
from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    GenuineTradeRecord,
    MarketUniverseEntry,
    ConnectionSessionRecord,
    DataQualityRecord,
    GenuineEventRecord,
    DataQualityStatus,
)

__all__ = [
    "RawMessageRecord",
    "BookUpdateRecord",
    "ReconstructedBookSnapshot",
    "GenuineTradeRecord",
    "MarketUniverseEntry",
    "ConnectionSessionRecord",
    "DataQualityRecord",
    "GenuineEventRecord",
    "DataQualityStatus",
]
