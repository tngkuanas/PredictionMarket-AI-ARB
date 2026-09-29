"""Resolution-Rule Analysis Engine.
Compares contractual settlement mechanics, deadlines, sources, and definitions
between two markets to explicitly model basis risk and estimate P(resolution divergence).
"""
import re
import logging
from typing import Optional, List, Dict, Any

from src.normalization.schema import (
    Market,
    CanonicalMarket,
    ResolutionRuleAnalysis,
    OpportunityClass,
)

logger = logging.getLogger(__name__)

class ResolutionRuleAnalyzer:
    """Analyzes contractual text and settlement sources to quantify basis risk."""

    def analyze_pair(
        self,
        market_a: Market,
        market_b: Market,
        canonical_a: Optional[CanonicalMarket] = None,
        canonical_b: Optional[CanonicalMarket] = None,
        opportunity_class: OpportunityClass = OpportunityClass.AI_SEMANTIC
    ) -> ResolutionRuleAnalysis:
        """Compare resolution rules between Market A and Market B."""
        divergence_reasons: List[str] = []

        # 1. Deadline / Expiry Divergence
        deadline_divergence = False
        if market_a.close_time and market_b.close_time:
            time_diff_hours = abs((market_a.close_time - market_b.close_time).total_seconds()) / 3600.0
            if time_diff_hours > 24.0:
                deadline_divergence = True
                divergence_reasons.append(
                    f"Substantial expiry mismatch: Market A closes {market_a.close_time.strftime('%Y-%m-%d')}, "
                    f"Market B closes {market_b.close_time.strftime('%Y-%m-%d')} (diff: {time_diff_hours:.1f}h)"
                )
            elif time_diff_hours > 1.0:
                deadline_divergence = True
                divergence_reasons.append(f"Minor intraday expiry mismatch ({time_diff_hours:.1f}h difference)")

        # 2. Source Divergence
        source_a = (market_a.resolution_rules or market_a.description or "").lower()
        source_b = (market_b.resolution_rules or market_b.description or "").lower()

        source_divergence = False
        # Check oracle types (UMA vs internal vs official exchange vs news)
        uma_a = "uma" in source_a or "optimistic oracle" in source_a
        uma_b = "uma" in source_b or "optimistic oracle" in source_b
        if uma_a != uma_b:
            source_divergence = True
            divergence_reasons.append("Oracle divergence: One market relies on decentralized optimistic oracle (UMA), the other on centralized/exchange oracle.")

        # Check primary settlement sources
        sources_keywords = ["ap", "reuters", "bloomberg", "bls", "fed", "fomc", "sec", "coingecko", "binance", "coinbase"]
        matched_sources_a = {kw for kw in sources_keywords if kw in source_a}
        matched_sources_b = {kw for kw in sources_keywords if kw in source_b}
        if matched_sources_a and matched_sources_b and not (matched_sources_a & matched_sources_b):
            source_divergence = True
            divergence_reasons.append(f"Primary data feed mismatch: '{list(matched_sources_a)[0]}' vs '{list(matched_sources_b)[0]}'")

        # 3. Definition Divergence (e.g. Intraday touch vs Daily close)
        definition_divergence = False
        touch_a = bool(re.search(r"\b(reach|hit|touch|dip to)\b", source_a + " " + market_a.title.lower()))
        touch_b = bool(re.search(r"\b(reach|hit|touch|dip to)\b", source_b + " " + market_b.title.lower()))
        close_a = bool(re.search(r"\b(close at|end of day|settle above|price on)\b", source_a + " " + market_a.title.lower()))
        close_b = bool(re.search(r"\b(close at|end of day|settle above|price on)\b", source_b + " " + market_b.title.lower()))

        if touch_a and close_b:
            definition_divergence = True
            divergence_reasons.append("Execution definition divergence: Market A resolves on any intraday touch, while Market B requires settlement at close.")
        elif touch_b and close_a:
            definition_divergence = True
            divergence_reasons.append("Execution definition divergence: Market B resolves on any intraday touch, while Market A requires settlement at close.")

        # Check revision risk
        if ("preliminary" in source_a and "final" in source_b) or ("revision" in source_a and "first print" in source_b):
            definition_divergence = True
            divergence_reasons.append("Data revision divergence: One contract resolves on preliminary print, the other allows revisions.")

        # 4. Calculate P(resolution divergence) and Basis Risk Score
        # For STRUCTURAL tautologies (e.g. identical series BTC >= 88k vs 82k on same date):
        is_struct = (opportunity_class == OpportunityClass.STRUCTURAL)
        same_date = (market_a.close_time == market_b.close_time)

        if is_struct and same_date and not definition_divergence:
            p_divergence = 0.0
            basis_risk_score = 0.0
            is_guaranteed = True
        else:
            base_prob = 0.05
            if deadline_divergence:
                base_prob += 0.25
            if source_divergence:
                base_prob += 0.15
            if definition_divergence:
                base_prob += 0.20

            # Second-order and cross-domain relationships carry inherent economic basis risk
            if opportunity_class in [OpportunityClass.SECOND_ORDER, OpportunityClass.AI_SEMANTIC]:
                base_prob = max(base_prob, 0.35)

            p_divergence = min(0.95, base_prob)
            basis_risk_score = p_divergence
            is_guaranteed = False

        if not divergence_reasons and not is_guaranteed:
            divergence_reasons.append("Standard economic basis risk: different underlying event drivers.")

        return ResolutionRuleAnalysis(
            market_a=market_a.market_id,
            market_b=market_b.market_id,
            prob_divergence=p_divergence,
            basis_risk_score=basis_risk_score,
            deadline_divergence=deadline_divergence,
            source_divergence=source_divergence,
            definition_divergence=definition_divergence,
            is_mathematically_guaranteed=is_guaranteed,
            divergence_reasons=divergence_reasons
        )
