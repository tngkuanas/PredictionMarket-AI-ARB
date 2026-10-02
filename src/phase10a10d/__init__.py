"""Phase 10A.10-D Resolution/Payoff Methodology Repair and Revalidation.

This module provides the repaired execution, settlement, outcome-mapping,
and deduplication framework to establish a valid baseline following the
forensic audit findings of Phase 10A.10-C.
"""

from enum import Enum


class Phase10A10DVerdict(str, Enum):
    """Allowed verdicts for Phase 10A.10-D."""
    CORRECTED_EDGE_SUPPORTED = "CORRECTED_EDGE_SUPPORTED"
    CORRECTED_EDGE_NOT_SUPPORTED = "CORRECTED_EDGE_NOT_SUPPORTED"
    CORRECTED_EDGE_INSUFFICIENT_DATA = "CORRECTED_EDGE_INSUFFICIENT_DATA"
    CORRECTED_MODEL_INVALID = "CORRECTED_MODEL_INVALID"


class SettlementStatus(str, Enum):
    """Status returned by the authoritative terminal payoff function."""
    RESOLVED_WIN = "RESOLVED_WIN"
    RESOLVED_LOSS = "RESOLVED_LOSS"
    NOT_RESOLVED = "NOT_RESOLVED"
    UNKNOWN = "UNKNOWN"


class DeterministicStateRepair(str, Enum):
    """Four-tier deterministic state taxonomy."""
    STATE_A = "STATE_A_ACTUALLY_RESOLVED"
    STATE_B = "STATE_B_MECHANICALLY_DETERMINED"
    STATE_C = "STATE_C_NEAR_DETERMINISTIC"
    STATE_D = "STATE_D_UNRESOLVED_FUTURE_DEPENDENT"


class ContaminationExclusionReason(str, Enum):
    """Exclusion reasons for contamination accounting."""
    UNRESOLVED_TERMINAL_PAYOFF = "unresolved terminal payoff"
    FUTURE_DEPENDENT_OUTCOME = "future-dependent outcome"
    IN_PLAY_NON_DETERMINISTIC = "in-play non-deterministic"
    INVALID_OUTCOME_MAPPING = "invalid outcome mapping"
    DUPLICATE_EXECUTION = "duplicate execution"
    MISSING_SOURCE_EVIDENCE = "missing source evidence"
    TIMESTAMP_VIOLATION = "timestamp violation"
    MISSING_L2 = "missing L2"
    INSUFFICIENT_DEPTH = "insufficient depth"
    OTHER = "other"
