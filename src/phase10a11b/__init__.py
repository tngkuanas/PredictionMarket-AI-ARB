"""Phase 10A.11-B: Forensic Validation of M2 and M3 Candidate Mechanisms.

Defines core enums, domain constants, and status types for the forensic validation
of M2 (Structural Fee Discreteness & Sub-Penny Tick Wedges) and M3 (Multi-Outcome
Asynchronous Rebalancing Overhang).
"""

from enum import Enum


class ForensicVerdict(str, Enum):
    """Preregistered final forensic verdict options for Phase 10A.11-B."""
    VALIDATED = "VALIDATED"
    PROMISING_BUT_INSUFFICIENT_EVIDENCE = "PROMISING_BUT_INSUFFICIENT_EVIDENCE"
    INVALIDATED = "INVALIDATED"
    ARTIFACT = "ARTIFACT"
    EXECUTION_EDGE_ABSENT = "EXECUTION_EDGE_ABSENT"


class PriceGridRegion(str, Enum):
    """Discrete price/tick regions for M2 price-grid analysis."""
    NEAR_0 = "NEAR_0"      # p < 0.05
    NEAR_10 = "NEAR_10"    # 0.05 <= p < 0.15
    NEAR_25 = "NEAR_25"    # 0.20 <= p < 0.30
    NEAR_50 = "NEAR_50"    # 0.45 <= p <= 0.55
    NEAR_75 = "NEAR_75"    # 0.70 <= p < 0.80
    NEAR_90 = "NEAR_90"    # 0.85 <= p < 0.95
    NEAR_100 = "NEAR_100"  # p >= 0.95


class TickBoundaryPosition(str, Enum):
    """Tick boundary positions relative to discrete tick increments."""
    EXACT_BOUNDARY = "EXACT_BOUNDARY"
    ONE_TICK_INSIDE = "ONE_TICK_INSIDE"
    ONE_TICK_OUTSIDE = "ONE_TICK_OUTSIDE"


class ConsistencyType(str, Enum):
    """M3 multi-outcome mechanical consistency classification."""
    TRUE_EXECUTABLE_INCONSISTENCY = "TRUE_EXECUTABLE_INCONSISTENCY"
    APPARENT_MIDPOINT_INCONSISTENCY = "APPARENT_MIDPOINT_INCONSISTENCY"
    SPREAD_INDUCED_INCONSISTENCY = "SPREAD_INDUCED_INCONSISTENCY"
    STALE_QUOTE_INCONSISTENCY = "STALE_QUOTE_INCONSISTENCY"
    GENUINE_ARBITRAGE = "GENUINE_ARBITRAGE"
