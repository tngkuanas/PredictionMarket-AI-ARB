"""Strict AI vs Deterministic Engine Boundary Enforcement.

Guarantees the core architectural boundary:
AI:
- discovers candidate mechanisms
- maps semantic and economic concepts
- proposes structured hypotheses and falsification tests

DETERMINISTIC ENGINE:
- calculates variables and estimations
- evaluates order book ladders and execution costs
- enforces risk, depth, and capacity limits
- accepts or rejects candidates

PROHIBITED AI ACTIONS (STRICTLY REJECTED):
- Generating real trade orders or execution signals
- Specifying portfolio position sizes, quantities, or leverage
- Overriding execution friction, spread, or depth checks
- Modifying or tampering with empirical statistical results
- Declaring profitability or claiming guaranteed alpha
- Selecting a winning strategy or tuning against OOS results
- Bypassing failed validation gates
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple

from src.statarb.schema import (
    StructuredHypothesis,
    HypothesisFamily,
    HypothesisStatus,
)
from src.statarb.historical_rules import (
    HistoricalRuleEngine,
    HistoricalFailurePattern,
)

logger = logging.getLogger(__name__)


class BoundaryViolationError(Exception):
    """Raised when an AI module attempts an unauthorized operational action."""
    pass


class BoundaryValidator:
    """Enforces non-negotiable boundaries between AI discovery and deterministic validation."""

    PROHIBITED_CLAIM_PATTERNS = [
        r"\bguaranteed\s+profit\b",
        r"\brisk-free\s+money\b",
        r"\bproven\s+alpha\b",
        r"\bprofitable\s+strategy\b",
        r"\bcertain\s+gain\b",
        r"\b100%\s+win\b",
        r"\balpha\s+discovered\b",
        r"\bguaranteed\s+edge\b",
        r"\bwinning\s+strategy\b",
        r"\bdeclare\s+profitability\b",
        r"\btune\s+against\s+oos\b",
        r"\brank\s+winning\b",
    ]

    PROHIBITED_ORDER_KEYS = [
        "place_order",
        "submit_order",
        "trade_size_usd",
        "position_size",
        "leverage",
        "override_risk",
        "bypass_validation",
        "override_spread",
        "override_fees",
        "execute_order",
        "order_quantity",
        "target_position",
        "modify_statistical_result",
        "override_pvalue",
        "tune_oos",
        "override_depth",
        "select_winning_strategy",
    ]

    @classmethod
    def validate_ai_proposal(cls, proposal: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Audits an AI hypothesis proposal before it enters the deterministic engine.
        
        Returns (is_valid, rejection_reason).
        """
        # 1. Check for unauthorized order placement keys
        for key in cls.PROHIBITED_ORDER_KEYS:
            if key in proposal:
                msg = f"Boundary Violation: AI proposal contains prohibited execution key '{key}'."
                logger.error(msg)
                return False, msg

        # 2. Check for prohibited profitability claims
        text_corpus = " ".join([str(v) for v in proposal.values() if isinstance(v, (str, list, dict))]).lower()
        for pattern in cls.PROHIBITED_CLAIM_PATTERNS:
            if re.search(pattern, text_corpus):
                msg = f"Boundary Violation: AI proposal makes unauthorized profitability claim matching '{pattern}'."
                logger.error(msg)
                return False, msg

        # 3. Verify hypothesis family is one of the 7 designated families
        family = proposal.get("hypothesis_family")
        valid_families = [f.value for f in HypothesisFamily]
        if family not in valid_families:
            msg = f"Invalid Hypothesis Family: '{family}' is not one of {valid_families}."
            return False, msg

        # 4. Verify operational template fields
        required_template_fields = [
            "input_signal",
            "transformation",
            "prediction",
            "horizon",
            "cost_model",
            "falsification_test"
        ]
        for field in required_template_fields:
            val = proposal.get(field, "")
            if not val or len(str(val).strip()) < 3:
                msg = f"Incomplete Operational Template: Missing or blank required field '{field}'."
                return False, msg

        # 5. Check falsification condition
        falsification = proposal.get("falsification_condition", "")
        if not falsification or len(str(falsification).strip()) < 10:
            msg = "Missing Falsification Condition: AI proposal must specify quantitative falsification criteria."
            return False, msg

        # 6. Check economic mechanism against vague claims
        causal_mech = proposal.get("causal_mechanism", "").lower()
        for pat in HistoricalRuleEngine.PROHIBITED_MECHANISM_PHRASES:
            if re.search(pat, causal_mech):
                msg = f"Vague Mechanism Rejected: Mechanism contains prohibited phrase matching '{pat}'."
                return False, msg

        return True, None

    @classmethod
    def sanitize_and_construct(cls, proposal: Dict[str, Any]) -> StructuredHypothesis:
        """Validates AI proposal and converts it into a StructuredHypothesis instance."""
        is_valid, reason = cls.validate_ai_proposal(proposal)
        if not is_valid:
            raise BoundaryViolationError(reason)

        # Enforce discovery prior interpretation
        if "confidence" in proposal:
            proposal["confidence"] = float(proposal["confidence"])

        # Enforce discovery initial status
        proposal["status"] = HypothesisStatus.DISCOVERY
        proposal["config_hash"] = None
        proposal["frozen_timestamp"] = None

        return StructuredHypothesis(**proposal)
