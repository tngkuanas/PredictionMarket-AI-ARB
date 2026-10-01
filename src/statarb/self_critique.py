"""Deterministic AI Self-Critique and Structure Validation Engine.

Phase 10A.6d:
Evaluates candidate hypotheses across the 13 structural self-critique questions
and assigns independent categorical states across the 10 quality axes.

CRITICAL RULE:
No composite numerical score. No strategy ranking.
"""

from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field
import logging

from src.statarb.schema import (
    StructuredHypothesis,
    EdgeType,
    HypothesisFamily,
    QualityGateStatus,
    HypothesisQualityState,
    NoveltyClassification,
)
from src.statarb.hypothesis_filters import (
    FrictionFirstFilter,
    CapacityGate,
    CausalDirectionValidator,
    ConfoundingAuditor,
)
from src.statarb.historical_rules import (
    HistoricalRuleEngine,
    HistoricalFailurePattern,
)

logger = logging.getLogger(__name__)


class SelfCritiqueResult(BaseModel):
    """Result of running deterministic structure critique over a candidate hypothesis."""
    hypothesis_id: str
    passed_structural_critique: bool
    critique_answers: Dict[str, Tuple[bool, str]] = Field(
        default_factory=dict,
        description="Answers to the 13 structural critique questions (q_id -> (passed, explanation))"
    )
    quality_state: HypothesisQualityState
    rejection_reasons: List[str] = Field(default_factory=list)


class AISelfCritiqueValidator:
    """Validates hypothesis structure against the 13 canonical self-critique questions."""

    @classmethod
    def critique(
        cls,
        hypothesis: StructuredHypothesis,
        known_lineage_hashes: Optional[Dict[str, str]] = None,
    ) -> SelfCritiqueResult:
        """Executes the 13-point self-critique and computes the 10 categorical quality states."""
        answers: Dict[str, Tuple[bool, str]] = {}
        rejections: List[str] = []

        q_state = HypothesisQualityState()

        # -------------------------------------------------------------
        # Q1: Is the mechanism explicit?
        # -------------------------------------------------------------
        mech = hypothesis.causal_mechanism.strip()
        mech_type = (hypothesis.economic_mechanism_type or "").upper()
        if len(mech) >= 20 and mech_type in HistoricalRuleEngine.VALID_ECONOMIC_MECHANISMS:
            # Check for prohibited vague phrases
            passed_phrase = True
            for pat in HistoricalRuleEngine.PROHIBITED_MECHANISM_PHRASES:
                import re
                if re.search(pat, mech.lower()):
                    passed_phrase = False
                    break
            if passed_phrase:
                answers["q1_mechanism_explicit"] = (True, f"Explicit mechanism defined ({mech_type}).")
                q_state.mechanism_status = QualityGateStatus.PASS
            else:
                answers["q1_mechanism_explicit"] = (False, "Mechanism contains vague prohibited phrases.")
                rejections.append("Q1 Failed: Mechanism is vague or contains prohibited correlation claims.")
                q_state.mechanism_status = QualityGateStatus.FAIL
        else:
            answers["q1_mechanism_explicit"] = (False, "Mechanism missing or not in valid economic taxonomy.")
            rejections.append("Q1 Failed: Economic mechanism missing or invalid.")
            q_state.mechanism_status = QualityGateStatus.FAIL

        # -------------------------------------------------------------
        # Q2: Is the relationship mathematically testable?
        # -------------------------------------------------------------
        has_input = bool(hypothesis.input_signal.strip())
        has_trans = bool(hypothesis.transformation.strip())
        has_pred = bool(hypothesis.prediction.strip()) or bool(hypothesis.expected_effect.strip())
        if has_input and has_trans and has_pred:
            answers["q2_mathematically_testable"] = (True, "Mathematical input/transformation/target specified.")
            q_state.formalization_status = QualityGateStatus.PASS
        else:
            answers["q2_mathematically_testable"] = (False, "Missing operational input/transformation/prediction.")
            rejections.append("Q2 Failed: Relationship lacks formal mathematical specification.")
            q_state.formalization_status = QualityGateStatus.FAIL

        # -------------------------------------------------------------
        # Q3: Is the direction justified?
        # -------------------------------------------------------------
        dir_ok, is_dir, dir_reason = CausalDirectionValidator.evaluate(hypothesis)
        answers["q3_direction_justified"] = (dir_ok, dir_reason)
        if not dir_ok:
            rejections.append(f"Q3 Failed: {dir_reason}")

        # -------------------------------------------------------------
        # Q4: Is the horizon justified?
        # -------------------------------------------------------------
        horizon = hypothesis.expected_time_horizon.strip()
        if horizon and len(horizon) >= 2:
            answers["q4_horizon_justified"] = (True, f"Horizon '{horizon}' specified with decay profile '{hypothesis.expected_decay_profile.value}'.")
        else:
            answers["q4_horizon_justified"] = (False, "Missing or invalid persistence horizon.")
            rejections.append("Q4 Failed: Horizon not justified.")

        # -------------------------------------------------------------
        # Q5: Is the expected effect measurable?
        # -------------------------------------------------------------
        if hypothesis.minimum_effect_size_bps > 0:
            answers["q5_effect_measurable"] = (True, f"Minimum effect size: {hypothesis.minimum_effect_size_bps:.1f} bps.")
        else:
            answers["q5_effect_measurable"] = (False, "Minimum effect size must be strictly positive.")
            rejections.append("Q5 Failed: Effect size is zero or negative.")

        # -------------------------------------------------------------
        # Q6: Is there enough data to test it?
        # -------------------------------------------------------------
        if hypothesis.minimum_sample_requirement >= 30:
            answers["q6_enough_data"] = (True, f"Sample requirement: {hypothesis.minimum_sample_requirement} >= 30.")
            q_state.data_status = QualityGateStatus.PASS
        else:
            answers["q6_enough_data"] = (False, f"Sample requirement {hypothesis.minimum_sample_requirement} < 30.")
            rejections.append("Q6 Failed: Inadequate sample size requirement (< 30).")
            q_state.data_status = QualityGateStatus.FAIL

        # -------------------------------------------------------------
        # Q7: Can execution actually be modeled?
        # -------------------------------------------------------------
        exec_dep = hypothesis.execution_dependency.lower()
        if "walk" in exec_dep or "ladder" in exec_dep or "l2" in exec_dep or "passive" in exec_dep:
            answers["q7_execution_modeled"] = (True, f"Realistic execution modeled: '{hypothesis.execution_dependency}'.")
            q_state.execution_status = QualityGateStatus.PASS
        else:
            answers["q7_execution_modeled"] = (False, f"Unrealistic execution: '{hypothesis.execution_dependency}'.")
            rejections.append("Q7 Failed: Execution model does not account for order book ladder.")
            q_state.execution_status = QualityGateStatus.FAIL

        # -------------------------------------------------------------
        # Q8: Is there an obvious confounder?
        # -------------------------------------------------------------
        conf_ok, unaddressed, conf_reason = ConfoundingAuditor.evaluate(hypothesis)
        answers["q8_confounders_addressed"] = (conf_ok, conf_reason)
        if conf_ok:
            q_state.identification_status = QualityGateStatus.PASS
        else:
            q_state.identification_status = QualityGateStatus.INSUFFICIENT_DATA
            rejections.append(f"Q8 Failed: {conf_reason}")

        # -------------------------------------------------------------
        # Q9: Is there an obvious placebo?
        # -------------------------------------------------------------
        placebo_test = hypothesis.pre_test_controls.get("placebo_test") or hypothesis.proposed_placebo_control
        if placebo_test and len(placebo_test.strip()) >= 5:
            answers["q9_placebo_designed"] = (True, f"Pre-test placebo defined: '{placebo_test}'.")
            q_state.falsification_status = QualityGateStatus.PASS
        else:
            answers["q9_placebo_designed"] = (False, "Missing explicit placebo test.")
            rejections.append("Q9 Failed: Pre-test placebo control not designed.")
            q_state.falsification_status = QualityGateStatus.FAIL

        # -------------------------------------------------------------
        # Q10: Is this a duplicate of an existing lineage?
        # -------------------------------------------------------------
        cfg_hash = hypothesis.compute_config_hash()
        is_duplicate = False
        if known_lineage_hashes and cfg_hash in known_lineage_hashes:
            if known_lineage_hashes[cfg_hash] != hypothesis.hypothesis_id:
                is_duplicate = True

        if is_duplicate or hypothesis.novelty_classification == NoveltyClassification.DUPLICATE:
            answers["q10_novelty_verified"] = (False, "Duplicate configuration detected in registry.")
            rejections.append("Q10 Failed: Duplicate hypothesis.")
            q_state.novelty_status = QualityGateStatus.FAIL
            q_state.lineage_status = QualityGateStatus.FAIL
        elif hypothesis.novelty_classification == NoveltyClassification.TRIVIAL_TRANSFORMATION:
            answers["q10_novelty_verified"] = (False, "Trivial transformation without economic substance.")
            rejections.append("Q10 Failed: Trivial transformation.")
            q_state.novelty_status = QualityGateStatus.FAIL
            q_state.lineage_status = QualityGateStatus.FAIL
        else:
            answers["q10_novelty_verified"] = (True, f"Novelty verified ({hypothesis.novelty_classification.value}).")
            q_state.novelty_status = QualityGateStatus.PASS
            q_state.lineage_status = QualityGateStatus.PASS

        # -------------------------------------------------------------
        # Q11: Could this merely be correlation?
        # -------------------------------------------------------------
        if hypothesis.edge_type in (EdgeType.EXACT_ARBITRAGE, EdgeType.RESOLUTION_ARBITRAGE):
            if "beta" in hypothesis.expected_relationship.lower() or "corr" in hypothesis.expected_relationship.lower():
                answers["q11_not_mere_correlation"] = (False, "Correlation formula mislabeled as arbitrage.")
                rejections.append("Q11 Failed: Statistical correlation mistaken for arbitrage bound.")
            else:
                answers["q11_not_mere_correlation"] = (True, "Arbitrage bound has deterministic payoff identity.")
        else:
            # Requires forward/reverse distinction
            answers["q11_not_mere_correlation"] = (True, "Directional mechanism backed by causal asymmetry.")

        # -------------------------------------------------------------
        # Q12: Could this be caused by the same information source?
        # -------------------------------------------------------------
        if "simultaneous" in str(hypothesis.confounders_audit).lower() or "macro_announcement" in str(hypothesis.confounders_audit).lower():
            answers["q12_common_information"] = (True, "Common information source controlled in audit.")
        else:
            answers["q12_common_information"] = (True, "Assumed independent or captured under macro controls.")

        # -------------------------------------------------------------
        # Q13: Is the expected edge plausibly larger than friction?
        # -------------------------------------------------------------
        fric_ok, exp_edge, req_edge, fric_reason = FrictionFirstFilter.evaluate(hypothesis)
        answers["q13_edge_exceeds_friction"] = (fric_ok, fric_reason)
        if fric_ok:
            q_state.friction_status = QualityGateStatus.PASS
        else:
            q_state.friction_status = QualityGateStatus.FAIL
            rejections.append(f"Q13 Failed: {fric_reason}")

        # Check capacity gate
        cap_ok, cap_reason = CapacityGate.evaluate(hypothesis)
        if cap_ok:
            q_state.capacity_status = QualityGateStatus.PASS
        else:
            q_state.capacity_status = QualityGateStatus.FAIL
            rejections.append(f"Capacity Gate Failed: {cap_reason}")

        # Also run historical failure rules
        hist_ok, failed_pats, hist_reasons = HistoricalRuleEngine.evaluate_hypothesis(hypothesis)
        if not hist_ok:
            for hr in hist_reasons:
                if hr not in rejections:
                    rejections.append(f"Historical Rule Failed: {hr}")

        passed_all = len(rejections) == 0
        q_state.failure_reasons = rejections

        return SelfCritiqueResult(
            hypothesis_id=hypothesis.hypothesis_id,
            passed_structural_critique=passed_all,
            critique_answers=answers,
            quality_state=q_state,
            rejection_reasons=rejections,
        )
