"""Phase 10A.11-A: Forensic Validation of M1 Post-Sweep Resiliency.

Strict independent forensic validation of the Phase 10A.11 OOS candidate:
M1_POST_SWEEP_RESILIENCY (Transient Depth Exhaustion & Post-Sweep Resiliency).
"""

from enum import Enum


class ForensicVerdict(str, Enum):
    M1_VALIDATED = "M1_VALIDATED"
    M1_PROMISING_BUT_INSUFFICIENT_EVIDENCE = "M1_PROMISING_BUT_INSUFFICIENT_EVIDENCE"
    M1_INVALIDATED = "M1_INVALIDATED"
    M1_ARTIFACT = "M1_ARTIFACT"
    M1_EXECUTION_EDGE_ABSENT = "M1_EXECUTION_EDGE_ABSENT"


class MarkoutRegime(str, Enum):
    IMMEDIATE_CONTINUATION = "IMMEDIATE_CONTINUATION"
    TEMPORARY_CONTINUATION_THEN_REVERSAL = "TEMPORARY_CONTINUATION_THEN_REVERSAL"
    IMMEDIATE_REVERSAL = "IMMEDIATE_REVERSAL"
    PERSISTENT_REVERSAL = "PERSISTENT_REVERSAL"


__all__ = [
    "ForensicVerdict",
    "MarkoutRegime",
]
