"""Phase 10A.10-E STATE_B Coverage, Collapse, and Eligibility Audit.

Investigates why 105 STATE_B candidates collapsed to 1 valid OOS event and 7 canonical executions.
Audits every candidate, builds the rejection waterfall, assesses deduplication validity,
and provides a formal verdict on whether the collapse reflects genuine economic sparsity
or an over-restrictive implementation defect.
"""

from enum import Enum


class Phase10A10EConclusion(str, Enum):
    """Allowed final conclusions for Phase 10A.10-E."""
    GENUINELY_SPARSE = "GENUINELY_SPARSE"
    FALSE_REJECTIONS_FOUND = "FALSE_REJECTIONS_FOUND"
    EVENT_MAPPING_ERROR = "EVENT_MAPPING_ERROR"
    DEDUPLICATION_ERROR = "DEDUPLICATION_ERROR"
    EXECUTION_ELIGIBILITY_ERROR = "EXECUTION_ELIGIBILITY_ERROR"
    STATE_CLASSIFICATION_ERROR = "STATE_CLASSIFICATION_ERROR"
    SOURCE_EVIDENCE_ERROR = "SOURCE_EVIDENCE_ERROR"
    MULTIPLE_IMPLEMENTATION_ERRORS = "MULTIPLE_IMPLEMENTATION_ERRORS"


class WaterfallStatus(str, Enum):
    """Terminal statuses for the Rejection Waterfall."""
    VALID_EXECUTION = "VALID_EXECUTION"
    REJECT_UNRESOLVED = "REJECT_UNRESOLVED"
    REJECT_FUTURE_DEPENDENT = "REJECT_FUTURE_DEPENDENT"
    REJECT_OUTCOME_MAPPING = "REJECT_OUTCOME_MAPPING"
    REJECT_DUPLICATE = "REJECT_DUPLICATE"
    REJECT_NO_L2 = "REJECT_NO_L2"
    REJECT_INSUFFICIENT_DEPTH = "REJECT_INSUFFICIENT_DEPTH"
    REJECT_TIMESTAMP = "REJECT_TIMESTAMP"
    REJECT_SOURCE_EVIDENCE = "REJECT_SOURCE_EVIDENCE"
    REJECT_EVENT_MAPPING = "REJECT_EVENT_MAPPING"
    REJECT_OTHER = "REJECT_OTHER"


class CounterfactualClass(str, Enum):
    """Classification for rejected candidates in counterfactual evaluation."""
    GENUINE_REJECTION = "GENUINE_REJECTION"
    POSSIBLE_FALSE_REJECTION = "POSSIBLE_FALSE_REJECTION"
    CLEAR_FALSE_REJECTION = "CLEAR_FALSE_REJECTION"
