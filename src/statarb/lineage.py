"""Hypothesis Lineage Tracking, Anti-Overfitting & Parameter Freezing.

Prevents p-hacking, correlation mining, cherry-picking, and repeated hypothesis
mutation without multiple-testing penalty. Enforces strict lifecycle gates and
cryptographic configuration locking via SHA-256 hashes.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Tuple, Any

from src.statarb.schema import (
    StructuredHypothesis,
    HypothesisStatus,
    ScorecardStatus,
)

logger = logging.getLogger(__name__)


class LineageViolationError(Exception):
    """Raised when an illegal lifecycle transition or parameter mutation is attempted."""
    pass


class HypothesisLineageTracker:
    """Tracks hypothesis mutation lineages, enforces parameter freezing, and applies
    multiple-testing penalties across variant families.
    """

    def __init__(self):
        # Maps hypothesis_id -> StructuredHypothesis
        self.hypotheses: Dict[str, StructuredHypothesis] = {}
        # Maps lineage_family_id -> List of hypothesis_ids in chronological order
        self.families: Dict[str, List[str]] = {}
        # Maps config_hash -> hypothesis_id to detect duplicate parameter tests
        self.config_registry: Dict[str, str] = {}

    def register_hypothesis(self, hypothesis: StructuredHypothesis) -> StructuredHypothesis:
        """Registers a new discovery hypothesis into the lineage tracking system."""
        if hypothesis.hypothesis_id in self.hypotheses:
            raise LineageViolationError(f"Hypothesis {hypothesis.hypothesis_id} is already registered.")

        # If it has a parent, verify parent exists
        if hypothesis.parent_hypothesis_id:
            parent = self.hypotheses.get(hypothesis.parent_hypothesis_id)
            if not parent:
                raise LineageViolationError(f"Parent hypothesis {hypothesis.parent_hypothesis_id} not found.")
            if hypothesis.lineage_family_id != parent.lineage_family_id:
                raise LineageViolationError(
                    f"Lineage family mismatch: child {hypothesis.lineage_family_id} != parent {parent.lineage_family_id}"
                )
            if hypothesis.version <= parent.version:
                raise LineageViolationError(
                    f"Mutated version {hypothesis.version} must be strictly greater than parent version {parent.version}."
                )

        # Register
        self.hypotheses[hypothesis.hypothesis_id] = hypothesis
        family = self.families.setdefault(hypothesis.lineage_family_id, [])
        family.append(hypothesis.hypothesis_id)
        
        logger.info(
            f"Registered hypothesis {hypothesis.hypothesis_id} (Family: {hypothesis.lineage_family_id}, "
            f"Version: {hypothesis.version}, Total Family Variants: {len(family)})"
        )
        return hypothesis

    def mutate_hypothesis(
        self,
        parent_id: str,
        new_hypothesis_id: str,
        mutation_rationale: str,
        parameter_updates: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> StructuredHypothesis:
        """Creates a mutated hypothesis from an existing parent.
        
        Enforces lineage grouping and accumulates the family multiple-testing penalty.
        """
        parent = self.hypotheses.get(parent_id)
        if not parent:
            raise LineageViolationError(f"Parent {parent_id} not found.")

        if not mutation_rationale or len(mutation_rationale.strip()) < 15:
            raise LineageViolationError("Mutation requires a detailed economic/empirical mutation_rationale.")

        # Create new dict from parent
        data = parent.model_dump()
        data["hypothesis_id"] = new_hypothesis_id
        data["parent_hypothesis_id"] = parent_id
        data["version"] = parent.version + 1
        data["mutation_rationale"] = mutation_rationale
        data["status"] = HypothesisStatus.DISCOVERY
        data["config_hash"] = None
        data["frozen_timestamp"] = None

        # Apply parameter updates
        if parameter_updates:
            params = dict(parent.parameters)
            params.update(parameter_updates)
            data["parameters"] = params

        # Apply optional kwargs
        for k, v in kwargs.items():
            if k in data:
                data[k] = v

        child = StructuredHypothesis(**data)
        return self.register_hypothesis(child)

    def freeze_hypothesis(self, hypothesis_id: str) -> StructuredHypothesis:
        """Transitions hypothesis to FROZEN state and computes its immutable SHA-256 hash.
        
        Once frozen, parameters, thresholds, and horizons cannot be modified.
        """
        hyp = self.hypotheses.get(hypothesis_id)
        if not hyp:
            raise LineageViolationError(f"Hypothesis {hypothesis_id} not found.")

        if hyp.status not in (HypothesisStatus.DISCOVERY, HypothesisStatus.EXPLORATORY_VALIDATED):
            raise LineageViolationError(
                f"Cannot freeze hypothesis in status {hyp.status}. Must be DISCOVERY or EXPLORATORY_VALIDATED."
            )

        config_hash = hyp.compute_config_hash()

        # Check for duplicate configuration testing
        if config_hash in self.config_registry and self.config_registry[config_hash] != hypothesis_id:
            prior_id = self.config_registry[config_hash]
            logger.warning(
                f"Hypothesis {hypothesis_id} shares identical config hash with prior hypothesis {prior_id}."
            )

        hyp.status = HypothesisStatus.FROZEN
        hyp.config_hash = config_hash
        hyp.frozen_timestamp = datetime.now(timezone.utc).isoformat()
        self.config_registry[config_hash] = hypothesis_id

        logger.info(f"FROZEN hypothesis {hypothesis_id} with SHA-256 config hash {config_hash[:12]}...")
        return hyp

    def verify_frozen_integrity(self, hypothesis_id: str) -> bool:
        """Verifies that a frozen hypothesis has not suffered parameter tampering."""
        hyp = self.hypotheses.get(hypothesis_id)
        if not hyp:
            return False
        if hyp.status == HypothesisStatus.DISCOVERY:
            return True
        if not hyp.config_hash:
            return False
        current_hash = hyp.compute_config_hash()
        return current_hash == hyp.config_hash

    def advance_lifecycle_stage(
        self,
        hypothesis_id: str,
        target_stage: HypothesisStatus
    ) -> StructuredHypothesis:
        """Advances hypothesis through validation lifecycle ensuring strict stage monotonicity."""
        hyp = self.hypotheses.get(hypothesis_id)
        if not hyp:
            raise LineageViolationError(f"Hypothesis {hypothesis_id} not found.")

        # Ensure parameters are not tampered
        if hyp.config_hash and not self.verify_frozen_integrity(hypothesis_id):
            hyp.status = HypothesisStatus.REJECTED
            raise LineageViolationError(
                f"Config hash mismatch for {hypothesis_id}! Tampering detected. Marking REJECTED."
            )

        valid_transitions = {
            HypothesisStatus.DISCOVERY: [HypothesisStatus.EXPLORATORY_VALIDATED, HypothesisStatus.FROZEN, HypothesisStatus.REJECTED],
            HypothesisStatus.EXPLORATORY_VALIDATED: [HypothesisStatus.FROZEN, HypothesisStatus.REJECTED],
            HypothesisStatus.FROZEN: [HypothesisStatus.OUT_OF_SAMPLE_TESTED, HypothesisStatus.REJECTED],
            HypothesisStatus.OUT_OF_SAMPLE_TESTED: [HypothesisStatus.ADVERSARIAL_TESTED, HypothesisStatus.REJECTED],
            HypothesisStatus.ADVERSARIAL_TESTED: [HypothesisStatus.EXECUTION_TESTED, HypothesisStatus.REJECTED],
            HypothesisStatus.EXECUTION_TESTED: [HypothesisStatus.ACCEPTED, HypothesisStatus.REJECTED],
            HypothesisStatus.ACCEPTED: [],
            HypothesisStatus.REJECTED: [],
        }

        allowed = valid_transitions.get(hyp.status, [])
        if target_stage not in allowed:
            raise LineageViolationError(
                f"Illegal lifecycle transition for {hypothesis_id}: {hyp.status} -> {target_stage}. "
                f"Allowed transitions: {allowed}"
            )

        hyp.status = target_stage
        logger.info(f"Advanced hypothesis {hypothesis_id} lifecycle to {target_stage}.")
        return hyp

    def get_family_multiple_testing_penalty(self, lineage_family_id: str) -> int:
        """Returns the number of attempted hypothesis variations in this lineage family.
        
        This count m is used for family-wise Bonferroni/Holm-Bonferroni correction
        to penalize iterative parameter adjustments.
        """
        variants = self.families.get(lineage_family_id, [])
        return max(1, len(variants))

    def compute_adjusted_family_p_value(self, p_value: float, lineage_family_id: str) -> float:
        """Computes family-adjusted p-value using the Bonferroni inequality across family mutations."""
        m = self.get_family_multiple_testing_penalty(lineage_family_id)
        return min(1.0, float(p_value) * m)
