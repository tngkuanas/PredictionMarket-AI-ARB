"""Next-Generation Deterministic Statistical Arbitrage Framework.

Phase 10A.6b: Strict AI Hypothesis Engine & Deterministic Stat-Arb Framework.
"""

from src.statarb.schema import (
    HypothesisFamily,
    HypothesisStatus,
    ScorecardStatus,
    ScorecardVerdict,
    AdversarialVerdict,
    StructuredHypothesis,
    HypothesisScorecard,
    SpreadModelConfig,
    ExecutionGateResult,
    StatArbMetrics,
)
from src.statarb.lineage import HypothesisLineageTracker
from src.statarb.engine import DeterministicStatArbEngine
from src.statarb.executability import ExecutabilityGate
from src.statarb.adversarial import AdversarialTestingBattery
from src.statarb.scorecard import ScorecardEvaluator
from src.statarb.boundary_validator import BoundaryValidator
from src.statarb.phase10a5_feed import Phase10A5DataFeed

__all__ = [
    "HypothesisFamily",
    "HypothesisStatus",
    "ScorecardStatus",
    "ScorecardVerdict",
    "AdversarialVerdict",
    "StructuredHypothesis",
    "HypothesisScorecard",
    "SpreadModelConfig",
    "ExecutionGateResult",
    "StatArbMetrics",
    "HypothesisLineageTracker",
    "DeterministicStatArbEngine",
    "ExecutabilityGate",
    "AdversarialTestingBattery",
    "ScorecardEvaluator",
    "BoundaryValidator",
    "Phase10A5DataFeed",
]
