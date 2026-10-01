"""Phase 10A.7: Genuine Polymarket Edge Discovery Framework.

Exports core classes, schemas, research engine, execution model, data loader, and store.
"""

from src.edge_discovery.schema import (
    ResearchBranch,
    CandidateClassification,
    TradeDirection,
    ProbabilityRegime,
    EVALUATION_HORIZONS_MS,
    HypothesisDefinition,
    SignalObservationRecord,
    ExecutableEvaluationRecord,
    AdversarialControlRecord,
    BranchResearchResult,
)
from src.edge_discovery.execution_model import (
    LadderFillResult,
    OrderBookTakerExecutor,
)
from src.edge_discovery.data_loader import (
    EdgeDiscoveryDataLoader,
)
from src.edge_discovery.db_store import (
    EdgeContaminationError,
    ProductionContaminationGuard,
    EdgeDiscoveryStore,
)
from src.edge_discovery.research_engine import (
    EdgeDiscoveryEngine,
)

__all__ = [
    "ResearchBranch",
    "CandidateClassification",
    "TradeDirection",
    "ProbabilityRegime",
    "EVALUATION_HORIZONS_MS",
    "HypothesisDefinition",
    "SignalObservationRecord",
    "ExecutableEvaluationRecord",
    "AdversarialControlRecord",
    "BranchResearchResult",
    "LadderFillResult",
    "OrderBookTakerExecutor",
    "EdgeDiscoveryDataLoader",
    "EdgeContaminationError",
    "ProductionContaminationGuard",
    "EdgeDiscoveryStore",
    "EdgeDiscoveryEngine",
]
