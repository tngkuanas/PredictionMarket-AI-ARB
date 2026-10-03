"""Phase 10A.11: New Executable Alpha Discovery Module.

This package implements the discovery framework for novel executable alpha
mechanisms on genuine Polymarket order-book and trade event data.

Hard Constraints:
- Strict forward causality: feature_ts <= signal_ts <= exec_ts
- Read-only database access
- Mandatory novelty validation against closed strategy families
- Pre-registered candidate registry (max 10 mechanisms)
- Multi-tier capacity modeling ($10 to $1,000) using actual L2 depth
- Adversarial and baseline controls (placebo, reverse, shuffle, stress)
- Hard profitability standard: No candidate declared PROFITABLE during discovery
"""

from enum import Enum
from typing import NamedTuple, Optional, List, Dict, Any


class NoveltyVerdict(str, Enum):
    NOVEL = "NOVEL"
    DUPLICATE_FAMILY = "DUPLICATE_FAMILY"


class CandidateStatus(str, Enum):
    REJECTED = "REJECTED"
    PROMISING_BUT_UNVALIDATED = "PROMISING_BUT_UNVALIDATED"
    OOS_CANDIDATE = "OOS_CANDIDATE"


class ClosedFamily(str, Enum):
    PHASE10A7_DIRECTIONAL_MICROSTRUCTURE = "10A.7 directional microstructure"
    PHASE10A8_PASSIVE_MAKER = "10A.8 passive maker"
    PHASE10A9_HEDGED_PASSIVE = "10A.9 hedged passive"
    PHASE10A10_DETERMINISTIC_RESOLUTION = "10A.10 deterministic resolution"
    PHASES3_9_SEMANTIC_STATARB = "Phase 3-9 semantic/stat-arb"
    PHASE10A6_CROSS_VENUE_ARBITRAGE = "10A.6 cross-venue arbitrage"


class SplitPhase(str, Enum):
    DISCOVERY = "DISCOVERY"
    VALIDATION = "VALIDATION"
    OOS = "OOS"


class FillStatus(str, Enum):
    FULL_FILL = "FULL_FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    UNFILLED = "UNFILLED"


class ExecutionStyle(str, Enum):
    TAKER_CROSS = "TAKER_CROSS"
    PASSIVE_POST = "PASSIVE_POST"
    MULTI_LEG_TAKER = "MULTI_LEG_TAKER"


__all__ = [
    "NoveltyVerdict",
    "CandidateStatus",
    "ClosedFamily",
    "SplitPhase",
    "FillStatus",
    "ExecutionStyle",
]
