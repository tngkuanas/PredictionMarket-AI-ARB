"""Phase 10A.11-C: M3 Atomic Multi-Outcome Routing & Prospective Validation.

Domain enums and data definitions for multi-outcome asynchronous rebalancing,
atomic basket routing, leg-order simulation, partial-fill analysis,
and prospective tracking.
"""

from enum import Enum


class TradeStructure(str, Enum):
    """Enumeration of possible multi-outcome trade structures."""
    STRUCTURE_A_BUY_ALL = "STRUCTURE_A_BUY_ALL"              # Buy all outcomes (complete-set arbitrage)
    STRUCTURE_B_SHORT_ALL = "STRUCTURE_B_SHORT_ALL"          # Sell all outcomes (unsupported without minting)
    STRUCTURE_C_LAG_LEAD = "STRUCTURE_C_LAG_LEAD"            # Buy lagging outcome / sell leading outcome
    STRUCTURE_D_PARTIAL_BASKET = "STRUCTURE_D_PARTIAL_BASKET"# Partial basket with residual exposure


class RoutingMode(str, Enum):
    """Multi-leg routing modes."""
    IDEAL_ATOMIC = "IDEAL_ATOMIC"
    SEQUENTIAL_ORDERED = "SEQUENTIAL_ORDERED"
    INDEPENDENT_PARALLEL = "INDEPENDENT_PARALLEL"


class M3Verdict(str, Enum):
    """Official preregistered verdicts for Phase 10A.11-C."""
    M3_EXECUTABLE_EDGE_SUPPORTED = "M3_EXECUTABLE_EDGE_SUPPORTED"
    M3_PROMISING_BUT_INSUFFICIENT_EVIDENCE = "M3_PROMISING_BUT_INSUFFICIENT_EVIDENCE"
    M3_EXECUTION_EDGE_ABSENT = "M3_EXECUTION_EDGE_ABSENT"
    M3_ARTIFACT = "M3_ARTIFACT"
    M3_INVALIDATED = "M3_INVALIDATED"


class PaperTradingEligibility(str, Enum):
    """Paper-trading eligibility states."""
    PAPER_READY_PENDING_PROSPECTIVE_SAMPLE = "PAPER_READY_PENDING_PROSPECTIVE_SAMPLE"
    NOT_PAPER_READY = "NOT_PAPER_READY"


class FailureScenario(str, Enum):
    """Multi-leg execution failure scenarios."""
    FIRST_LEG_FILLS_SECOND_FAILS = "FIRST_LEG_FILLS_SECOND_FAILS"
    FIRST_TWO_FILL_FINAL_FAILS = "FIRST_TWO_FILL_FINAL_FAILS"
    PARTIAL_DEPTH_FILL = "PARTIAL_DEPTH_FILL"
    STALE_QUOTE = "STALE_QUOTE"
    QUOTE_WITHDRAWAL = "QUOTE_WITHDRAWAL"
    ADVERSE_PRICE_MOVE_BEFORE_FINAL_LEG = "ADVERSE_PRICE_MOVE_BEFORE_FINAL_LEG"
    WEBSOCKET_LATENCY = "WEBSOCKET_LATENCY"
    ORDER_REJECTION = "ORDER_REJECTION"


class DataSourcePartition(str, Enum):
    """Partitioning between historical baseline and prospective stream."""
    HISTORICAL = "HISTORICAL"
    PROSPECTIVE = "PROSPECTIVE"
