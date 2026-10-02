"""Phase 10A.10-B — Genuine Event-Universe Expansion Package."""

from src.phase10a10b.universe import (
    EventTaxonomyCategory,
    RejectionCategory,
    Phase10A10BVerdict,
    ExpandedEventRecord,
    SourceEvidenceRecord,
    MarketMappingRecord,
    EventIndependenceRecord,
    CandidateRejectionRecord,
)
from src.phase10a10b.config_freeze import (
    FROZEN_PHASE10A10_CONFIG,
    PHASE10A10B_CONFIG_HASH,
    compute_config_hash,
    assert_config_unmodified,
)
from src.phase10a10b.historical_source_validator import HistoricalSourceValidator
from src.phase10a10b.market_matcher import DeterministicMarketMatcher
from src.phase10a10b.source_discovery import SourceDiscoveryEngine
from src.phase10a10b.event_discovery import CandidateEventDiscoveryEngine
from src.phase10a10b.independence import EventIndependenceTracker
from src.phase10a10b.chronology import ChronologyManager
from src.phase10a10b.provenance import Phase10A10BDbStore
from src.phase10a10b.report import Phase10A10BReportGenerator
from src.phase10a10b.pipeline import Phase10A10BPipeline

__all__ = [
    "EventTaxonomyCategory",
    "RejectionCategory",
    "Phase10A10BVerdict",
    "ExpandedEventRecord",
    "SourceEvidenceRecord",
    "MarketMappingRecord",
    "EventIndependenceRecord",
    "CandidateRejectionRecord",
    "FROZEN_PHASE10A10_CONFIG",
    "PHASE10A10B_CONFIG_HASH",
    "compute_config_hash",
    "assert_config_unmodified",
    "HistoricalSourceValidator",
    "DeterministicMarketMatcher",
    "SourceDiscoveryEngine",
    "CandidateEventDiscoveryEngine",
    "EventIndependenceTracker",
    "ChronologyManager",
    "Phase10A10BDbStore",
    "Phase10A10BReportGenerator",
    "Phase10A10BPipeline",
]
