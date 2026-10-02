"""Phase 10A.9 — Hedged Passive / Cross-Contract Neutralization Research Module."""

from src.phase10a9.schema import (
    RelationshipType,
    RelationshipValidationStatus,
    RelationshipRejectionReason,
    HedgeExecutionStatus,
    HedgedVerdict,
    PrimaryHypothesis,
    AdversarialControl,
    ContractRelationshipRecord,
    HedgeExecutionRecord,
    HedgedEconomicsRecord,
    HedgeInventoryStateRecord,
    BasisRiskRecord,
    HypothesisResultRecord,
    AdversarialControlRecord,
    STANDARD_HEDGE_LATENCIES_MS,
    STANDARD_INVENTORY_LIMITS_USD,
)
from src.phase10a9.relationship_engine import DeterministicRelationshipEngine
from src.phase10a9.hedge_executor import HedgeExecutionEngine
from src.phase10a9.economics_engine import HedgedEconomicsEngine
from src.phase10a9.statistical_engine import Phase10A9StatisticalEngine
from src.phase10a9.data_loader import Phase10A9DataLoader
from src.phase10a9.db_store import (
    Phase10A9DbStore,
    ProductionContaminationGuard,
    Phase10A9ContaminationError,
)
from src.phase10a9.pipeline import Phase10A9ResearchPipeline

__all__ = [
    "RelationshipType",
    "RelationshipValidationStatus",
    "RelationshipRejectionReason",
    "HedgeExecutionStatus",
    "HedgedVerdict",
    "PrimaryHypothesis",
    "AdversarialControl",
    "ContractRelationshipRecord",
    "HedgeExecutionRecord",
    "HedgedEconomicsRecord",
    "HedgeInventoryStateRecord",
    "BasisRiskRecord",
    "HypothesisResultRecord",
    "AdversarialControlRecord",
    "STANDARD_HEDGE_LATENCIES_MS",
    "STANDARD_INVENTORY_LIMITS_USD",
    "DeterministicRelationshipEngine",
    "HedgeExecutionEngine",
    "HedgedEconomicsEngine",
    "Phase10A9StatisticalEngine",
    "Phase10A9DataLoader",
    "Phase10A9DbStore",
    "ProductionContaminationGuard",
    "Phase10A9ContaminationError",
    "Phase10A9ResearchPipeline",
]
