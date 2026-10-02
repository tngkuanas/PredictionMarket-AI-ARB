"""Hypothesis Registry and Alias Accounting for Phase 10A.10-D.

Formally defines H1-H5 and explicitly audits alias relationships:
- H1: Official result lag
- H2: Mechanical-value lag
- H3: Event-completion lag
- H4: Resolution-source lag
- H5: Cross-source confirmation lag

Records alias relationships where candidate generation is identical,
preventing redundant hypotheses from inflating degrees of freedom or evidence.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Set, Tuple


@dataclass
class HypothesisDefinition:
    """Definition of a research hypothesis in the resolution lag framework."""
    hypothesis_id: str
    name: str
    description: str
    target_state: str
    is_alias: bool = False
    alias_of: str = ""


class HypothesisRegistry:
    """Tracks and separates hypotheses and their alias relationships."""

    HYPOTHESES: Dict[str, HypothesisDefinition] = {
        "H1": HypothesisDefinition(
            hypothesis_id="H1",
            name="Official result lag",
            description="Trades post-event upon formal certification/release by governing authority.",
            target_state="STATE_A",
            is_alias=False,
        ),
        "H2": HypothesisDefinition(
            hypothesis_id="H2",
            name="Mechanical-value lag",
            description="Trades threshold/index contracts where numerical value mechanically forces terminal settlement.",
            target_state="STATE_B",
            is_alias=False,
        ),
        "H3": HypothesisDefinition(
            hypothesis_id="H3",
            name="Event-completion lag",
            description="Trades upon completion of scheduled event prior to oracle settlement.",
            target_state="STATE_A",
            is_alias=False,
        ),
        "H4": HypothesisDefinition(
            hypothesis_id="H4",
            name="Resolution-source lag",
            description="Trades upon resolution-source publication (e.g. UMA proposer evidence).",
            target_state="STATE_A",
            is_alias=True,
            alias_of="H3",
        ),
        "H5": HypothesisDefinition(
            hypothesis_id="H5",
            name="Cross-source confirmation lag",
            description="Trades when secondary independent source confirms primary official outcome.",
            target_state="STATE_A",
            is_alias=True,
            alias_of="H1",
        ),
    }

    @classmethod
    def compute_jaccard_similarity(cls, set_a: Set[str], set_b: Set[str]) -> float:
        """Computes Jaccard similarity J(A, B) = |A n B| / |A u B|."""
        if not set_a and not set_b:
            return 1.0
        union = set_a.union(set_b)
        if not union:
            return 0.0
        intersection = set_a.intersection(set_b)
        return len(intersection) / len(union)

    @classmethod
    def audit_alias_matrix(
        cls,
        candidate_ids_by_hyp: Dict[str, Set[str]]
    ) -> Dict[str, Any]:
        """Computes 5x5 overlap matrix and identifies exact aliases."""
        hyp_keys = ["H1", "H2", "H3", "H4", "H5"]
        matrix: Dict[str, Dict[str, float]] = {h: {} for h in hyp_keys}
        aliases: List[Tuple[str, str, float]] = []

        for h1 in hyp_keys:
            s1 = candidate_ids_by_hyp.get(h1, set())
            for h2 in hyp_keys:
                s2 = candidate_ids_by_hyp.get(h2, set())
                jaccard = cls.compute_jaccard_similarity(s1, s2)
                matrix[h1][h2] = jaccard
                if h1 < h2 and jaccard >= 0.999:
                    aliases.append((h1, h2, jaccard))

        return {
            "matrix": matrix,
            "detected_aliases": aliases,
            "registry_definitions": cls.HYPOTHESES,
        }
