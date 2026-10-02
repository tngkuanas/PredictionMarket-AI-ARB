"""Deterministic Resolution State Classifier for Phase 10A.10.

Implements the strict four-state taxonomy:
- STATE_A: ALREADY_SETTLED_BY_FACT (Official match finished, certified result, elapsed date)
- STATE_B: MECHANICALLY_DETERMINED (Authoritative numerical value definitively satisfies strike)
- STATE_C: NEAR_DETERMINISTIC (Bounded probability; segregated from primary dataset)
- STATE_D: REJECTED (Forecasting, opinion, sentiment, ambiguous news)

Strictly zero LLM decision authority: 100% deterministic rule-based evaluation.
"""

from typing import Dict, Any, Optional, Tuple
from src.phase10a10.schema import DeterministicState, SourceTier, ContractResolutionRules
from src.phase10a10.resolution_rules import ResolutionRulesParser


class DeterministicStateClassifier:
    """Deterministic state evaluation engine."""

    @classmethod
    def classify_event(
        cls,
        rules: ContractResolutionRules,
        source_tier: SourceTier,
        event_type: str,
        is_official_final: bool,
        actual_numerical_value: Optional[float] = None,
        probability_estimate: Optional[float] = None,
        is_forecast_or_opinion: bool = False,
    ) -> Tuple[DeterministicState, float, Optional[str]]:
        """Classifies an event and determines its exact deterministic settlement value (1.0 or 0.0).
        
        Returns:
            (DeterministicState, settlement_value, rejection_reason)
        """
        # Hard Rule: Forecasts, opinions, model predictions, or Tier 3 sources are rejected
        if is_forecast_or_opinion or source_tier == SourceTier.TIER_3:
            return DeterministicState.STATE_D, 0.0, "Rejected: Subjective forecast, sentiment, or Tier 3 source"

        if not rules.is_deterministic_eligible:
            return DeterministicState.STATE_D, 0.0, f"Rejected: Contract rules ineligible: {rules.rejection_reason}"

        # STATE_B: Mechanically determined by authoritative numerical measurement
        if actual_numerical_value is not None and rules.threshold is not None and rules.inequality is not None:
            is_met, settlement_val = ResolutionRulesParser.evaluate_numerical_condition(
                actual_value=actual_numerical_value,
                threshold=rules.threshold,
                inequality=rules.inequality,
                outcome_name=rules.outcome
            )
            return DeterministicState.STATE_B, settlement_val, None

        # STATE_A: Settled by objective fact (official match final, official announcement)
        if is_official_final and source_tier in (SourceTier.TIER_1, SourceTier.TIER_2):
            # For match winners or certified outcomes:
            # If the outcome matches the winner, value = 1.0, else 0.0
            return DeterministicState.STATE_A, 1.0, None

        # STATE_C: Near-deterministic (bounded state space)
        if probability_estimate is not None and probability_estimate >= 0.99:
            return DeterministicState.STATE_C, 1.0, "Segregated: STATE_C near-deterministic bounded state"

        # Otherwise, insufficient evidence -> STATE_D
        return DeterministicState.STATE_D, 0.0, "Rejected: Outcome is not deterministically resolved"

    @classmethod
    def is_primary_eligible(cls, state: DeterministicState) -> bool:
        """Only STATE_A and STATE_B are permitted in the primary deterministic lag result."""
        return state in (DeterministicState.STATE_A, DeterministicState.STATE_B)
