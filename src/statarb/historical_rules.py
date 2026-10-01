"""Deterministic Rejection Rules Derived from Phase 3-9 Historical Failures.

Encodes the 13 empirical failure patterns identified across multi-month live & shadow testing:
1. SEMANTIC_SIMILARITY_WITHOUT_ECONOMIC_MECHANISM
2. GROSS_EDGE_CONSUMED_BY_FRICTION
3. PLACEBO_POSITIVE
4. REVERSE_DIRECTION_POSITIVE
5. SYNTHETIC_DATA_ARTIFACT
6. EXCESSIVE_PARAMETER_FREEDOM
7. TINY_SAMPLE_SIZE
8. CAPACITY_FAILURE
9. LATENCY_DESTRUCTION
10. OVERLAPPING_OBSERVATIONS
11. EVENT_LEAKAGE
12. MID_PRICE_ALPHA_WITHOUT_EXECUTABLE_ALPHA
13. CORRELATION_MISTAKEN_FOR_ARBITRAGE
"""

from enum import Enum
import re
from typing import List, Dict, Any, Tuple
import logging

from src.statarb.schema import (
    StructuredHypothesis,
    EdgeType,
    HypothesisFamily,
    DecayProfile,
)

logger = logging.getLogger(__name__)


class HistoricalFailurePattern(str, Enum):
    """The 13 canonical historical failure patterns from Phases 3-9."""
    SEMANTIC_SIMILARITY_WITHOUT_ECONOMIC_MECHANISM = "semantic_similarity_without_economic_mechanism"
    GROSS_EDGE_CONSUMED_BY_FRICTION = "gross_edge_consumed_by_friction"
    PLACEBO_POSITIVE = "placebo_positive"
    REVERSE_DIRECTION_POSITIVE = "reverse_direction_positive"
    SYNTHETIC_DATA_ARTIFACT = "synthetic_data_artifact"
    EXCESSIVE_PARAMETER_FREEDOM = "excessive_parameter_freedom"
    TINY_SAMPLE_SIZE = "tiny_sample_size"
    CAPACITY_FAILURE = "capacity_failure"
    LATENCY_DESTRUCTION = "latency_destruction"
    OVERLAPPING_OBSERVATIONS = "overlapping_observations"
    EVENT_LEAKAGE = "event_leakage"
    MID_PRICE_ALPHA_WITHOUT_EXECUTABLE_ALPHA = "mid_price_alpha_without_executable_alpha"
    CORRELATION_MISTAKEN_FOR_ARBITRAGE = "correlation_mistaken_for_arbitrage"


class HistoricalRuleEngine:
    """Deterministic validator evaluating hypotheses against the 13 historical failure modes."""

    PROHIBITED_MECHANISM_PHRASES = [
        r"these markets are related",
        r"these markets are similar",
        r"sentiment (?:may )?spill\s*over",
        r"historically correlated",
        r"ai believes",
        r"semantic similarity",
        r"similar contracts",
        r"general correlation",
    ]

    VALID_ECONOMIC_MECHANISMS = {
        "INFORMATION_TRANSMISSION",
        "ORDER_FLOW_TRANSMISSION",
        "ARBITRAGE_CONSTRAINT",
        "SETTLEMENT_LOGIC",
        "COMMON_FUNDAMENTAL",
        "LEAD_LAG",
        "LIQUIDITY_IMBALANCE",
        "RISK_TRANSFER",
        "EVENT_RESPONSE",
        "CROSS_VENUE_PRICE_DISCOVERY",
    }

    @classmethod
    def evaluate_hypothesis(cls, hypothesis: StructuredHypothesis) -> Tuple[bool, List[HistoricalFailurePattern], List[str]]:
        """Audits a candidate hypothesis against all 13 historical failure patterns.
        
        Returns: (passed_all, list_of_failed_patterns, detailed_reasons)
        """
        failed_patterns: List[HistoricalFailurePattern] = []
        reasons: List[str] = []

        # 1. Semantic similarity without economic mechanism
        mech_text = hypothesis.causal_mechanism.lower()
        for phrase_pat in cls.PROHIBITED_MECHANISM_PHRASES:
            if re.search(phrase_pat, mech_text):
                failed_patterns.append(HistoricalFailurePattern.SEMANTIC_SIMILARITY_WITHOUT_ECONOMIC_MECHANISM)
                reasons.append(f"Mechanism contains prohibited vague phrase matching '{phrase_pat}'.")
                break

        mech_type = (hypothesis.economic_mechanism_type or "").upper().strip()
        if mech_type not in cls.VALID_ECONOMIC_MECHANISMS:
            if HistoricalFailurePattern.SEMANTIC_SIMILARITY_WITHOUT_ECONOMIC_MECHANISM not in failed_patterns:
                failed_patterns.append(HistoricalFailurePattern.SEMANTIC_SIMILARITY_WITHOUT_ECONOMIC_MECHANISM)
            reasons.append(f"Invalid economic mechanism type '{mech_type}'. Must be one of {cls.VALID_ECONOMIC_MECHANISMS}.")

        # 2. Gross edge consumed by friction
        if hypothesis.expected_gross_edge_bps < hypothesis.required_gross_edge_bps or not hypothesis.is_frictionally_plausible:
            failed_patterns.append(HistoricalFailurePattern.GROSS_EDGE_CONSUMED_BY_FRICTION)
            reasons.append(
                f"Gross edge ({hypothesis.expected_gross_edge_bps:.1f} bps) <= required friction threshold "
                f"({hypothesis.required_gross_edge_bps:.1f} bps)."
            )

        # 3. Placebo positive / missing placebo test
        placebo_def = hypothesis.pre_test_controls.get("placebo_test") or hypothesis.proposed_placebo_control
        if not placebo_def or len(placebo_def.strip()) < 5:
            failed_patterns.append(HistoricalFailurePattern.PLACEBO_POSITIVE)
            reasons.append("Missing explicit pre-test placebo specification to reject placebo-positive artifacts.")

        # 4. Reverse direction positive
        if hypothesis.edge_type in (EdgeType.PREDICTIVE_INFORMATION_EDGE, EdgeType.MICROSTRUCTURE_EDGE) or \
           hypothesis.hypothesis_family == HypothesisFamily.CROSS_MARKET_LEAD_LAG:
            if not hypothesis.causal_asymmetry_established and not hypothesis.reverse_causal_rationale:
                failed_patterns.append(HistoricalFailurePattern.REVERSE_DIRECTION_POSITIVE)
                reasons.append("Directional hypothesis lacks reverse-direction justification; prone to reverse-direction artifact.")

        # 5. Synthetic data artifact
        data_text = " ".join(hypothesis.required_observations + hypothesis.observable_variables + [hypothesis.input_signal]).lower()
        if "synthetic" in data_text or "interpolat" in data_text or "simulated_book" in data_text:
            failed_patterns.append(HistoricalFailurePattern.SYNTHETIC_DATA_ARTIFACT)
            reasons.append("Hypothesis relies on unverified synthetic or interpolated market data.")

        # 6. Excessive parameter freedom
        param_count = len(hypothesis.parameters)
        if param_count > 4:
            failed_patterns.append(HistoricalFailurePattern.EXCESSIVE_PARAMETER_FREEDOM)
            reasons.append(f"Excessive parameter freedom ({param_count} parameters > max allowed 4 without multiple-testing penalty).")

        # 7. Tiny sample size
        if hypothesis.minimum_sample_requirement < 30:
            failed_patterns.append(HistoricalFailurePattern.TINY_SAMPLE_SIZE)
            reasons.append(f"Sample size requirement ({hypothesis.minimum_sample_requirement}) < 30 independent observations.")

        # 8. Capacity failure
        if hypothesis.expected_order_size_usd > hypothesis.minimum_required_depth_usd or hypothesis.expected_capacity_usd <= 0:
            failed_patterns.append(HistoricalFailurePattern.CAPACITY_FAILURE)
            reasons.append(
                f"Capacity failure: order size (${hypothesis.expected_order_size_usd:,.2f}) > "
                f"depth (${hypothesis.minimum_required_depth_usd:,.2f}) or capacity (${hypothesis.expected_capacity_usd:,.2f}) <= 0."
            )

        # 9. Latency destruction
        if hypothesis.expected_decay_profile == DecayProfile.IMMEDIATE and hypothesis.latency_penalty_bps < 15.0:
            failed_patterns.append(HistoricalFailurePattern.LATENCY_DESTRUCTION)
            reasons.append("Immediate decay (<1s) without sufficient latency penalty modeling (>15 bps).")

        # 10. Overlapping observations
        horizon_str = hypothesis.expected_time_horizon.lower()
        if ("h" in horizon_str or "d" in horizon_str or "m" in horizon_str) and "cluster" not in hypothesis.proposed_statistical_test.lower():
            # If horizon is multi-step but test lacks robust standard errors
            if hypothesis.minimum_sample_requirement < 50 and "permutation" not in hypothesis.proposed_statistical_test.lower():
                failed_patterns.append(HistoricalFailurePattern.OVERLAPPING_OBSERVATIONS)
                reasons.append("Multi-step horizon without clustered/permutation test to adjust for serial overlap.")

        # 11. Event leakage
        if "lookahead" in hypothesis.lookahead_risk.lower() and "none" not in hypothesis.lookahead_risk.lower() and "zero" not in hypothesis.lookahead_risk.lower():
            failed_patterns.append(HistoricalFailurePattern.EVENT_LEAKAGE)
            reasons.append(f"Lookahead risk identified in feature pipeline: {hypothesis.lookahead_risk}.")

        # 12. Mid-price alpha without executable alpha
        if "mid" in hypothesis.execution_dependency.lower() and "ladder" not in hypothesis.execution_dependency.lower() and "walk" not in hypothesis.execution_dependency.lower():
            failed_patterns.append(HistoricalFailurePattern.MID_PRICE_ALPHA_WITHOUT_EXECUTABLE_ALPHA)
            reasons.append(
                f"Execution dependency '{hypothesis.execution_dependency}' relies on theoretical mid-price rather than executable L2 ladder walk."
            )

        # 13. Correlation mistaken for arbitrage
        if hypothesis.edge_type in (EdgeType.EXACT_ARBITRAGE, EdgeType.RESOLUTION_ARBITRAGE):
            if "corr" in hypothesis.expected_relationship.lower() or "beta" in hypothesis.expected_relationship.lower():
                failed_patterns.append(HistoricalFailurePattern.CORRELATION_MISTAKEN_FOR_ARBITRAGE)
                reasons.append(
                    f"Statistical correlation/beta formula '{hypothesis.expected_relationship}' misclassified as deterministic arbitrage."
                )

        passed = len(failed_patterns) == 0
        return passed, failed_patterns, reasons
