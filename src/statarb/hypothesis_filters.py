"""Pre-Test Filters & Quality Validators for Phase 10A.6d.

Implements:
1. Friction-First Filter: Evaluates theoretical minimum edge against realistic friction.
2. Capacity-Aware Filter: Validates executable order size and observable book depth.
3. Causal Direction Validator: Enforces asymmetric lead/lag justification (X -> Y vs Y -> X).
4. Confounding Auditor: Maps potential confounders, expected distortions, and control methods.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging

from src.statarb.schema import (
    StructuredHypothesis,
    EdgeType,
    HypothesisFamily,
    QualityGateStatus,
    HypothesisQualityState,
)

logger = logging.getLogger(__name__)


class FrictionFirstFilter:
    """Calculates theoretical minimum edge and rejects frictionally implausible hypotheses."""

    @staticmethod
    def calculate_required_gross_edge(
        expected_spread_bps: float,
        expected_fee_bps: float,
        expected_slippage_bps: float,
        latency_penalty_bps: float,
        safety_margin_bps: float,
    ) -> float:
        """Calculates theoretical minimum gross edge required to survive friction.
        
        formula: required_gross_edge >= spread + fee + slippage + latency + safety_margin
        """
        return float(
            expected_spread_bps
            + expected_fee_bps
            + expected_slippage_bps
            + latency_penalty_bps
            + safety_margin_bps
        )

    @classmethod
    def evaluate(cls, hypothesis: StructuredHypothesis) -> Tuple[bool, float, float, str]:
        """Evaluates whether expected edge survives theoretical minimum friction.
        
        Returns: (is_plausible, expected_gross_edge, required_gross_edge, reason)
        """
        # Calculate minimum required edge using conservative assumptions
        required = cls.calculate_required_gross_edge(
            expected_spread_bps=max(hypothesis.expected_spread_bps, 2.0),
            expected_fee_bps=max(hypothesis.expected_fee_bps, 0.0),
            expected_slippage_bps=max(hypothesis.expected_slippage_bps, 1.0),
            latency_penalty_bps=max(hypothesis.latency_penalty_bps, 1.0),
            safety_margin_bps=max(hypothesis.safety_margin_bps, 2.0),
        )

        expected = float(hypothesis.expected_gross_edge_bps)

        if expected < required:
            reason = (
                f"FRICTIONALLY_IMPLAUSIBLE: Expected gross edge {expected:.1f} bps < "
                f"minimum required edge {required:.1f} bps (Spread: {hypothesis.expected_spread_bps:.1f}, "
                f"Fee: {hypothesis.expected_fee_bps:.1f}, Slippage: {hypothesis.expected_slippage_bps:.1f}, "
                f"Latency: {hypothesis.latency_penalty_bps:.1f}, Safety: {hypothesis.safety_margin_bps:.1f})."
            )
            return False, expected, required, reason

        return True, expected, required, "Passed theoretical friction gate."


class CapacityGate:
    """Validates operational capital capacity, order size, and depth requirements."""

    @staticmethod
    def evaluate(hypothesis: StructuredHypothesis) -> Tuple[bool, str]:
        """Validates that proposed order size does not exceed observable market depth."""
        if hypothesis.expected_order_size_usd <= 0:
            return False, "Capacity Gate Failure: expected_order_size_usd must be strictly positive."

        if hypothesis.minimum_required_depth_usd <= 0:
            return False, "Capacity Gate Failure: minimum_required_depth_usd must be strictly positive."

        if hypothesis.expected_order_size_usd > hypothesis.minimum_required_depth_usd:
            return False, (
                f"Capacity Gate Failure: Expected order size ${hypothesis.expected_order_size_usd:,.2f} "
                f"exceeds minimum required observable depth ${hypothesis.minimum_required_depth_usd:,.2f}."
            )

        if hypothesis.expected_capacity_usd < hypothesis.expected_order_size_usd:
            return False, (
                f"Capacity Gate Failure: Expected capacity ${hypothesis.expected_capacity_usd:,.2f} "
                f"is smaller than single order size ${hypothesis.expected_order_size_usd:,.2f}."
            )

        if not hypothesis.capacity_failure_condition or len(hypothesis.capacity_failure_condition.strip()) < 10:
            return False, "Capacity Gate Failure: Explicit capacity_failure_condition must be provided."

        return True, "Passed capacity gate."


class CausalDirectionValidator:
    """Validates causal directionality and enforces asymmetry justification for directional hypotheses."""

    @staticmethod
    def evaluate(hypothesis: StructuredHypothesis) -> Tuple[bool, bool, str]:
        """Evaluates causal directionality.
        
        Returns: (is_valid, is_directional, reason)
        If relationship is symmetric, routes it to NON_DIRECTIONAL_RELATIONSHIP.
        """
        # Exact arbitrage and structural resolution bounds are non-directional bounds
        if hypothesis.edge_type in (EdgeType.EXACT_ARBITRAGE, EdgeType.RESOLUTION_ARBITRAGE):
            return True, False, "Structural pricing bound (non-directional mathematical constraint)."

        forward = hypothesis.forward_causal_rationale.strip()
        reverse = hypothesis.reverse_causal_rationale.strip()

        if not forward:
            return False, False, "Causal Direction Failure: Missing forward causal rationale (X -> Y)."

        # Check for directional edges
        if hypothesis.edge_type in (EdgeType.PREDICTIVE_INFORMATION_EDGE, EdgeType.MICROSTRUCTURE_EDGE) or \
           hypothesis.hypothesis_family == HypothesisFamily.CROSS_MARKET_LEAD_LAG:
            if not reverse:
                return False, False, (
                    "Causal Direction Failure: Directional hypothesis must provide reverse causal rationale (Y -> X) "
                    "explaining why the relationship is asymmetric."
                )

            # Check if forward and reverse are essentially claiming symmetry or identical mechanisms
            if forward.lower() == reverse.lower() or "symmetric" in reverse.lower() or "two-way" in reverse.lower():
                return True, False, "NON_DIRECTIONAL_RELATIONSHIP: Symmetric mechanism detected. Routed to Stat-Arb."

            return True, True, "Valid asymmetric directional mechanism."

        # Stat-arb / spread mean reversion
        return True, False, "Stat-arb relative-value relationship (non-directional)."


class ConfoundingAuditor:
    """Audits potential confounders and verifies matched control methodologies."""

    MANDATORY_CONFOUNDER_CATEGORIES = [
        "macro_shock",
        "market_wide_drift",
        "time_of_day_liquidity",
        "resolution_proximity",
        "event_clustering",
    ]

    @classmethod
    def evaluate(cls, hypothesis: StructuredHypothesis) -> Tuple[bool, List[str], str]:
        """Audits confounders map.
        
        Returns: (is_sufficient, unaddressed_confounders, summary)
        """
        audit = hypothesis.confounders_audit
        if not audit:
            # If known_confounders is provided but not detailed audit
            if not hypothesis.known_confounders:
                return False, cls.MANDATORY_CONFOUNDER_CATEGORIES, (
                    "INSUFFICIENT_IDENTIFICATION: No confounders or identification controls specified."
                )

        unaddressed = []
        for cat in cls.MANDATORY_CONFOUNDER_CATEGORIES:
            found = False
            for k in audit.keys():
                if cat in k.lower():
                    entry = audit[k]
                    if isinstance(entry, dict) and entry.get("control_method"):
                        found = True
                        break
            if not found:
                unaddressed.append(cat)

        if unaddressed:
            return False, unaddressed, (
                f"INSUFFICIENT_IDENTIFICATION: Missing explicit control methods for confounders: {unaddressed}."
            )

        return True, [], "Confounders adequately identified with control methods."
