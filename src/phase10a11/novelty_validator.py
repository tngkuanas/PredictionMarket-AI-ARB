"""Novelty and Closed-Family Validator for Phase 10A.11.

Enforces strict novelty validation against previously closed/falsified strategy families:
- 10A.7: Directional microstructure (momentum, order-flow imbalance, volume surge)
- 10A.8: Passive maker (static inside-spread quoting)
- 10A.9: Hedged passive (passive maker with immediate complementary taker hedge)
- 10A.10: Deterministic resolution lag (external deterministic state sniping)
- Phase 3-9: Semantic / statistical arbitrage (cointegration breakdown)
- 10A.6: Cross-venue exact arbitrage (Kalshi vs Polymarket)

If a proposed candidate is materially the same as a closed family (even if renamed,
re-parameterized, or using a different threshold/ML model), it is flagged as
DUPLICATE_FAMILY and rejected.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
from src.phase10a11 import ClosedFamily, NoveltyVerdict


@dataclass
class ClosedFamilySignature:
    family: ClosedFamily
    name: str
    fatal_flaw: str
    forbidden_drivers: Set[str]
    forbidden_signals: Set[str]
    description: str


CLOSED_FAMILY_REGISTRY: Dict[ClosedFamily, ClosedFamilySignature] = {
    ClosedFamily.PHASE10A7_DIRECTIONAL_MICROSTRUCTURE: ClosedFamilySignature(
        family=ClosedFamily.PHASE10A7_DIRECTIONAL_MICROSTRUCTURE,
        name="Directional Microstructure",
        fatal_flaw="Destroyed by adverse selection and taker fees upon fill",
        forbidden_drivers={
            "momentum",
            "order_flow_imbalance",
            "volume_surge",
            "short_term_trend",
            "signed_volume",
            "microstructure_drift",
            "imbalance_taker",
        },
        forbidden_signals={
            "price_velocity_following",
            "net_taker_volume_direction",
            "ofi_threshold",
            "burst_following",
        },
        description="Predicting short-term price continuation from recent trades or book imbalance.",
    ),
    ClosedFamily.PHASE10A8_PASSIVE_MAKER: ClosedFamilySignature(
        family=ClosedFamily.PHASE10A8_PASSIVE_MAKER,
        name="Passive Market Maker",
        fatal_flaw="Adverse selection on fills and queue position decay",
        forbidden_drivers={
            "passive_maker",
            "spread_capture",
            "static_quotes",
            "inside_spread_quoting",
            "limit_order_provision",
        },
        forbidden_signals={
            "best_bid_ask_spread_harvest",
            "symmetric_quoting",
            "resting_liquidity_provision",
        },
        description="Posting resting limit orders at inside bid/ask to capture the bid-ask spread.",
    ),
    ClosedFamily.PHASE10A9_HEDGED_PASSIVE: ClosedFamilySignature(
        family=ClosedFamily.PHASE10A9_HEDGED_PASSIVE,
        name="Hedged Passive Taker",
        fatal_flaw="Edge destroyed by taker fee and crossing spread on complementary leg",
        forbidden_drivers={
            "hedged_passive",
            "complementary_taker_hedge",
            "maker_taker_hedge",
            "yes_no_hedge",
            "immediate_hedge",
        },
        forbidden_signals={
            "passive_fill_with_instant_taker_cross",
            "complementary_contract_hedge",
            "parity_arbitrage",
        },
        description="Making passively on primary token and immediately taking cross on complementary token.",
    ),
    ClosedFamily.PHASE10A10_DETERMINISTIC_RESOLUTION: ClosedFamilySignature(
        family=ClosedFamily.PHASE10A10_DETERMINISTIC_RESOLUTION,
        name="Deterministic Resolution Lag",
        fatal_flaw="Genuinely sparse; liquid contracts converge immediately, illiquid lack depth",
        forbidden_drivers={
            "deterministic_resolution",
            "resolution_lag",
            "state_b_sniping",
            "post_event_settlement",
            "terminal_payoff_convergence",
            "oracle_lag",
        },
        forbidden_signals={
            "external_state_change_sniping",
            "verified_outcome_buy",
            "deterministic_settlement_arb",
        },
        description="Sniping contracts after an authoritative real-world outcome is already determined.",
    ),
    ClosedFamily.PHASES3_9_SEMANTIC_STATARB: ClosedFamilySignature(
        family=ClosedFamily.PHASES3_9_SEMANTIC_STATARB,
        name="Semantic & Statistical Arbitrage",
        fatal_flaw="Cointegration breakdown in bounded binary [0, 1] contracts",
        forbidden_drivers={
            "semantic_embedding",
            "cointegration",
            "stat_arb_spread",
            "longshot_favorite",
            "cross_asset_correlation",
        },
        forbidden_signals={
            "embedding_distance_spread",
            "residual_spread_mean_reversion",
            "favorite_underdog_bias",
        },
        description="Statistical pair trading or semantic similarity cointegration across prediction markets.",
    ),
    ClosedFamily.PHASE10A6_CROSS_VENUE_ARBITRAGE: ClosedFamilySignature(
        family=ClosedFamily.PHASE10A6_CROSS_VENUE_ARBITRAGE,
        name="Cross-Venue Arbitrage",
        fatal_flaw="Zero executable overlap between Kalshi and Polymarket order books",
        forbidden_drivers={
            "cross_venue",
            "kalshi_polymarket",
            "venue_discrepancy",
            "inter_exchange_arb",
            "dual_venue_latency",
        },
        forbidden_signals={
            "kalshi_bid_higher_than_polymarket_ask",
            "polymarket_bid_higher_than_kalshi_ask",
        },
        description="Executing simultaneous opposite trades on Kalshi and Polymarket for identical events.",
    ),
}


@dataclass
class NoveltyAssessment:
    candidate_id: str
    verdict: NoveltyVerdict
    matched_closed_family: Optional[ClosedFamily] = None
    similarity_reason: str = ""
    novelty_score: float = 1.0
    violating_drivers: List[str] = field(default_factory=list)
    violating_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "verdict": self.verdict.value,
            "matched_closed_family": self.matched_closed_family.value if self.matched_closed_family else None,
            "similarity_reason": self.similarity_reason,
            "novelty_score": round(self.novelty_score, 3),
            "violating_drivers": self.violating_drivers,
            "violating_signals": self.violating_signals,
        }


class NoveltyValidator:
    """Validates candidate mechanisms against all closed and falsified families."""

    def __init__(self, registry: Optional[Dict[ClosedFamily, ClosedFamilySignature]] = None):
        self.registry = registry or CLOSED_FAMILY_REGISTRY

    def assess_candidate(
        self,
        candidate_id: str,
        drivers: List[str],
        signals: List[str],
        causal_description: str,
    ) -> NoveltyAssessment:
        """Evaluates a candidate mechanism against all closed families."""
        drivers_set = {d.strip().lower() for d in drivers}
        signals_set = {s.strip().lower() for s in signals}
        desc_lower = causal_description.lower()

        # Check against each closed family
        for family, sig in self.registry.items():
            driver_overlap = sorted(list(drivers_set.intersection(sig.forbidden_drivers)))
            signal_overlap = sorted(list(signals_set.intersection(sig.forbidden_signals)))

            # Semantic match in description
            desc_match = any(d in desc_lower for d in sig.forbidden_drivers)

            if len(driver_overlap) >= 1 or len(signal_overlap) >= 1:
                return NoveltyAssessment(
                    candidate_id=candidate_id,
                    verdict=NoveltyVerdict.DUPLICATE_FAMILY,
                    matched_closed_family=family,
                    similarity_reason=(
                        f"Candidate duplicates closed family '{sig.name}' ({family.value}). "
                        f"Matched forbidden drivers: {driver_overlap}; signals: {signal_overlap}. "
                        f"Fatal flaw of closed family: {sig.fatal_flaw}."
                    ),
                    novelty_score=0.0,
                    violating_drivers=driver_overlap,
                    violating_signals=signal_overlap,
                )
            
            # Check strong phrase match in description
            matching_phrases = [d for d in sig.forbidden_drivers if d in desc_lower]
            if len(matching_phrases) >= 2:
                return NoveltyAssessment(
                    candidate_id=candidate_id,
                    verdict=NoveltyVerdict.DUPLICATE_FAMILY,
                    matched_closed_family=family,
                    similarity_reason=(
                        f"Candidate causal mechanism description matches closed family '{sig.name}'. "
                        f"Matched phrases: {matching_phrases}. "
                        f"Fatal flaw: {sig.fatal_flaw}."
                    ),
                    novelty_score=0.1,
                    violating_drivers=matching_phrases,
                    violating_signals=[],
                )

        # Genuinely novel mechanism
        return NoveltyAssessment(
            candidate_id=candidate_id,
            verdict=NoveltyVerdict.NOVEL,
            matched_closed_family=None,
            similarity_reason="Candidate mechanism operates on distinct economic drivers not previously falsified.",
            novelty_score=1.0,
            violating_drivers=[],
            violating_signals=[],
        )
