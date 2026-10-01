"""Relationship Discovery Engine.
Generates falsifiable second-order economic relationship hypotheses between prediction markets.
Produces two distinct outputs:
Output A: Conceptual Relationship Discovery
Output B: Falsifiable Mathematical Pricing Constraint
"""
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from src.normalization.schema import (
    CanonicalMarket,
    CandidateRelationship,
    OutputARelationshipDiscovery,
    OutputBEconomicConstraint,
    RelationshipType,
    ConstraintType,
    OpportunityClass,
)
from src.llm.base import BaseLLMClient, get_llm_client, HeuristicDomainLLMClient
from src.statarb.schema import (
    StructuredHypothesis,
    HypothesisFamily,
    HypothesisStatus,
)
from src.statarb.boundary_validator import BoundaryValidator

logger = logging.getLogger(__name__)

class RelationshipDiscoveryEngine:
    """Discovers indirect, economically meaningful cross-market hypotheses and translates them
    into falsifiable pricing constraints.
    """

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self.llm = llm_client or get_llm_client()

    def discover_hypotheses(
        self,
        canonical_markets: List[CanonicalMarket],
        max_candidates: int = 50
    ) -> List[CandidateRelationship]:
        """Scan canonical markets universe and generate structured falsifiable hypotheses."""
        if not canonical_markets:
            return []

        # If using real LLM API (Gemini or OpenAI), batch candidate clusters
        if not isinstance(self.llm, HeuristicDomainLLMClient):
            return self._discover_via_api(canonical_markets, max_candidates)
        else:
            return self._discover_via_domain_engine(canonical_markets, max_candidates)

    def _discover_via_api(
        self,
        markets: List[CanonicalMarket],
        max_candidates: int
    ) -> List[CandidateRelationship]:
        """Use LLM prompt to discover second-order constraints."""
        # Summarize markets for prompt
        market_summaries = [
            f"ID: {m.market_id} | Title: {m.title} | Entities: {','.join(m.entities)} | Event: {m.event_type} | Horizon: {m.time_horizon}"
            for m in markets[:60]
        ]
        prompt = (
            "You are an elite quantitative researcher in prediction markets. "
            "Analyze these prediction market contracts and generate non-obvious, indirect, second-order economic hypotheses. "
            "DO NOT suggest trivial exact synonyms or obvious complements (like candidate win vs lose). "
            "Focus on macro transmission, geopolitical supply disruption, regulatory spillover, or cross-asset liquidity. "
            "For every hypothesis, you must provide:\n"
            "OUTPUT A (Relationship Discovery): Conceptual mechanism and why word-embedding similarity misses it.\n"
            "OUTPUT B (Economic Pricing Constraint): A falsifiable, testable mathematical pricing constraint: "
            "'If Market A implied probability moves by >= X pp, Market B implied probability should move by >= Y pp within T hours.'\n\n"
            "Markets:\n" + "\n".join(market_summaries)
        )
        schema_desc = """
        {
          "candidates": [
            {
              "market_a_id": "...",
              "market_b_id": "...",
              "relationship_type": "positive_economic | negative_economic | conditional_dependence | second_order | temporal_lead_lag",
              "constraint_type": "directional_impulse | monotone_bound | conditional_prob_shift | spread_mean_reversion",
              "economic_mechanism": "...",
              "domain_cluster": "Macro/CentralBanking | Geopolitics/Energy | Crypto/Liquidity | Politics/Legislation",
              "why_embedding_misses": "...",
              "confidence": 0.85,
              "trigger_threshold_delta_a": 0.04,
              "expected_delta_b": 0.03,
              "lead_time_hours": 6.0,
              "testable_null_hypothesis": "E[ΔP(B) | ΔP(A) >= 0.04] <= baseline drift",
              "mathematical_expression": "P(B)_{t+6h} - P(B)_t >= 0.03",
              "invalidation_criteria": ["Empirical return correlation near zero", "Spurious macro drift artifact"]
            }
          ]
        }
        """
        try:
            res = self.llm.generate_json(prompt, schema_desc)
            candidates: List[CandidateRelationship] = []
            for item in res.get("candidates", [])[:max_candidates]:
                cand = self._parse_candidate_dict(item)
                if cand:
                    candidates.append(cand)
            return candidates
        except Exception as e:
            logger.warning(f"LLM API discovery failed ({e}), falling back to domain engine.")
            return self._discover_via_domain_engine(markets, max_candidates)

    def _discover_via_domain_engine(
        self,
        markets: List[CanonicalMarket],
        max_candidates: int
    ) -> List[CandidateRelationship]:
        """Domain-grounded hypothesis generator capturing multi-domain economic transmission channels."""
        candidates: List[CandidateRelationship] = []
        # Prioritize long-horizon multi-month markets first (Dec 2026, 2027, long-dated catalysts)
        def horizon_score(m: CanonicalMarket) -> int:
            t = f"{m.title} {m.time_horizon}".lower()
            score = 1
            if "2027" in t:
                score += 3
            if "december" in t or "2026" in t:
                score += 2
            if "fall" in t or "invade" in t or "regime" in t or "election" in t:
                score += 1
            return score

        m_list = sorted(markets, key=horizon_score, reverse=True)

        # Economic transmission rules:
        # 1. Macro (Fed Rate / Inflation) -> Crypto (Bitcoin / Ethereum)
        # 2. Geopolitical conflict (Iran / Chokepoint / Hormuz) -> Crude Oil / Energy
        # 3. Geopolitical conflict -> Safe-haven assets / Risk sentiment
        # 4. Tech / Tariff executive actions -> Equity / Tech firms (Tesla / Nvidia)
        # 5. Complementary electoral candidates in multi-candidate races

        # Track hypothesis count per source market to guarantee diverse representation
        source_counts: Dict[str, int] = {}

        for i in range(len(m_list)):
            for j in range(len(m_list)):
                if i == j:
                    continue
                ma = m_list[i]
                mb = m_list[j]

                cnt = source_counts.get(ma.market_id, 0)
                if cnt >= 2:
                    continue

                text_a = f"{ma.title} {ma.underlying_event}".lower()
                text_b = f"{mb.title} {mb.underlying_event}".lower()

                import re

                # Rule 1: Crypto Threshold Ladders (STRUCTURAL BASELINE CONTROL GROUP)
                match_val_a = re.search(r"\$([0-9]{2,3}(?:,[0-9]{3})*)", text_a)
                match_val_b = re.search(r"\$([0-9]{2,3}(?:,[0-9]{3})*)", text_b)
                if re.search(r"\b(bitcoin|btc)\b", text_a) and re.search(r"\b(bitcoin|btc)\b", text_b):
                    if match_val_a and match_val_b and match_val_a.group(1) != match_val_b.group(1):
                        val_a = float(match_val_a.group(1).replace(",", ""))
                        val_b = float(match_val_b.group(1).replace(",", ""))
                        is_reach_ladder = (("above" in text_a or "reach" in text_a) and ("above" in text_b or "reach" in text_b) and val_a > val_b)
                        is_dip_ladder = (("below" in text_a or "dip" in text_a) and ("below" in text_b or "dip" in text_b) and val_a < val_b)
                        if is_reach_ladder or is_dip_ladder:
                            candidates.append(self._create_hypothesis(
                                ma, mb,
                                opp_class=OpportunityClass.STRUCTURAL, # Control group baseline!
                                rel_type=RelationshipType.IMPLICATION,
                                constraint_type=ConstraintType.MONOTONE_BOUND,
                                mechanism=f"Deterministic Structural Arbitrage: BTC event at ${val_a:,.0f} tautologically implies event at ${val_b:,.0f}. Baseline control bound.",
                                domain="Structural Threshold Ladder (Baseline)",
                                why_misses="Trivial deterministic numerical monotonicity.",
                                trigger_delta=0.02,
                                expected_delta=0.02,
                                lead_time=2.0,
                                confidence=0.99
                            ))
                            source_counts[ma.market_id] = cnt + 1
                            continue

                # Rule 2: Cross-Asset Crypto Lead/Lag: Bitcoin -> Ethereum (NOVEL INFORMATION LATENCY)
                if re.search(r"\b(bitcoin|btc)\b", text_a) and re.search(r"\b(ethereum|eth)\b", text_b):
                    candidates.append(self._create_hypothesis(
                        ma, mb,
                        opp_class=OpportunityClass.INFORMATION_LATENCY,
                        rel_type=RelationshipType.TEMPORAL_LEAD_LAG,
                        constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
                        mechanism="Bitcoin operates as the market bellwether; institutional spot inflows and momentum in BTC propagate to secondary layer-1 assets (ETH) with a 2-6 hour repricing latency.",
                        domain="Cross-Asset Crypto Lead-Lag",
                        why_misses="Embedding models recognize them as distinct cryptocurrencies but have no temporal lead-lag structure or capital rotation graph.",
                        trigger_delta=0.03,
                        expected_delta=0.025,
                        lead_time=4.0,
                        confidence=0.86
                    ))
                    source_counts[ma.market_id] = cnt + 1
                    continue

                # Rule 3: Fed policy rate hike / cut -> Bitcoin milestone
                if re.search(r"\b(fed|interest rate|fomc)\b", text_a) and re.search(r"\b(bitcoin|btc)\b", text_b):
                    if "increase" in text_a or "hike" in text_a:
                        candidates.append(self._create_hypothesis(
                            ma, mb,
                            opp_class=OpportunityClass.AI_SEMANTIC,
                            rel_type=RelationshipType.NEGATIVE_ECONOMIC,
                            constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
                            mechanism="Higher interest rate expectations tighten monetary conditions, reducing speculative liquidity into non-yielding crypto assets.",
                            domain="Macro/Fed -> Crypto Liquidity",
                            why_misses="No keyword overlap; macro policy vs crypto asset.",
                            trigger_delta=0.03,
                            expected_delta=-0.02,
                            lead_time=6.0,
                            confidence=0.82
                        ))
                    else:
                        candidates.append(self._create_hypothesis(
                            ma, mb,
                            opp_class=OpportunityClass.AI_SEMANTIC,
                            rel_type=RelationshipType.POSITIVE_ECONOMIC,
                            constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
                            mechanism="Accommodative monetary stance preserves USD liquidity and supports risk assets.",
                            domain="Macro/Fed -> Crypto Liquidity",
                            why_misses="Macro policy vs crypto asset.",
                            trigger_delta=0.03,
                            expected_delta=0.02,
                            lead_time=6.0,
                            confidence=0.78
                        ))
                    source_counts[ma.market_id] = cnt + 1
                    continue

                # Rule 4: Geopolitics (Strait of Hormuz / Iran / Kharg Island) -> Crude Oil
                if ("hormuz" in text_a or "iran" in text_a or "kharg" in text_a) and ("oil" in text_b or "crude" in text_b):
                    candidates.append(self._create_hypothesis(
                        ma, mb,
                        opp_class=OpportunityClass.SECOND_ORDER,
                        rel_type=RelationshipType.SECOND_ORDER,
                        constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
                        mechanism="Disruption or military escalation in Persian Gulf chokepoints threatens global petroleum transit, creating a rapid supply risk premium in crude oil contracts.",
                        domain="Geopolitics -> Energy/Commodities",
                        why_misses="Embeddings encode naval geography vs commodity market pricing without physical supply chain flow modeling.",
                        trigger_delta=0.04,
                        expected_delta=0.03,
                        lead_time=4.0,
                        confidence=0.88
                    ))
                    source_counts[ma.market_id] = cnt + 1
                    continue

                # Rule 5: French Presidential Candidate Zero-Sum Electoral Competition
                if "french" in text_a and "french" in text_b and ("presiden" in text_a or "win" in text_a) and ("presiden" in text_b or "win" in text_b):
                    candidates.append(self._create_hypothesis(
                        ma, mb,
                        opp_class=OpportunityClass.CROSS_MARKET_LOGICAL,
                        rel_type=RelationshipType.NEGATIVE_ECONOMIC,
                        constraint_type=ConstraintType.SPREAD_MEAN_REVERSION,
                        mechanism="Zero-sum electoral competition in single-seat presidential runoff: probability gain by candidate A directly subtracts from remaining candidate pool.",
                        domain="Electoral Competition / Politics",
                        why_misses="Embeddings see similar political biographies rather than mutual exclusivity of winner-take-all election.",
                        trigger_delta=0.03,
                        expected_delta=-0.025,
                        lead_time=4.0,
                        confidence=0.91
                    ))
                    source_counts[ma.market_id] = cnt + 1
                    continue

                # Rule 6: Trump / Trade Policy -> Tesla
                if ("trump" in text_a or "trade" in text_a) and ("tesla" in text_b or "tsla" in text_b):
                    candidates.append(self._create_hypothesis(
                        ma, mb,
                        opp_class=OpportunityClass.AI_SEMANTIC,
                        rel_type=RelationshipType.POSITIVE_ECONOMIC,
                        constraint_type=ConstraintType.DIRECTIONAL_IMPULSE,
                        mechanism="Executive tariff policies and regulatory stance on domestic manufacturing impact EV valuation.",
                        domain="Policy -> Corporate Equities",
                        why_misses="Political figure vs automotive stock ticker.",
                        trigger_delta=0.04,
                        expected_delta=0.03,
                        lead_time=8.0,
                        confidence=0.75
                    ))
                    source_counts[ma.market_id] = cnt + 1
                    continue

                if len(candidates) >= max_candidates:
                    break
            if len(candidates) >= max_candidates:
                break

        logger.info(f"Generated {len(candidates)} structured falsifiable relationship hypotheses.")
        return candidates

    def _create_hypothesis(
        self,
        ma: CanonicalMarket,
        mb: CanonicalMarket,
        opp_class: OpportunityClass,
        rel_type: RelationshipType,
        constraint_type: ConstraintType,
        mechanism: str,
        domain: str,
        why_misses: str,
        trigger_delta: float,
        expected_delta: float,
        lead_time: float,
        confidence: float
    ) -> CandidateRelationship:
        disc_id = f"disc_{uuid.uuid4().hex[:8]}"
        const_id = f"const_{uuid.uuid4().hex[:8]}"
        direction_sign = "+" if expected_delta > 0 else "-"

        discovery = OutputARelationshipDiscovery(
            discovery_id=disc_id,
            market_a_id=ma.market_id,
            market_b_id=mb.market_id,
            opportunity_class=opp_class,
            relationship_type=rel_type,
            economic_mechanism=mechanism,
            domain_cluster=domain,
            why_embedding_misses=why_misses,
            confidence=confidence,
            discovery_timestamp=datetime.utcnow()
        )

        constraint = OutputBEconomicConstraint(
            constraint_id=const_id,
            discovery_id=disc_id,
            market_a_id=ma.market_id,
            market_b_id=mb.market_id,
            constraint_type=constraint_type,
            trigger_threshold_delta_a=trigger_delta,
            expected_delta_b=expected_delta,
            lead_time_hours=lead_time,
            testable_null_hypothesis=f"H0: E[ΔP(B) | ΔP(A) >= {trigger_delta}] <= baseline drift (or opposite direction)",
            mathematical_expression=f"P(B)_{{t+{int(lead_time)}h}} - P(B)_t {direction_sign}= {abs(expected_delta):.3f}",
            invalidation_criteria=[
                "First-differenced return correlation r < 0.10 (spurious unit-root trend)",
                "Sample size N < 15 impulse events",
                "95% CI contains 0 or opposite sign",
                "Net edge <= round-trip friction costs"
            ],
            is_active=True
        )

        return CandidateRelationship(
            discovery=discovery,
            constraint=constraint,
            intermediate_nodes=[],
            hop_count=1
        )

    def _parse_candidate_dict(self, data: Dict[str, Any]) -> Optional[CandidateRelationship]:
        try:
            disc_id = f"disc_{uuid.uuid4().hex[:8]}"
            const_id = f"const_{uuid.uuid4().hex[:8]}"
            rel_type = RelationshipType(data.get("relationship_type", "positive_economic"))
            const_type = ConstraintType(data.get("constraint_type", "directional_impulse"))

            discovery = OutputARelationshipDiscovery(
                discovery_id=disc_id,
                market_a_id=str(data["market_a_id"]),
                market_b_id=str(data["market_b_id"]),
                relationship_type=rel_type,
                economic_mechanism=str(data.get("economic_mechanism", "")),
                domain_cluster=str(data.get("domain_cluster", "Cross-Domain")),
                why_embedding_misses=str(data.get("why_embedding_misses", "")),
                confidence=float(data.get("confidence", 0.7)),
                discovery_timestamp=datetime.utcnow()
            )

            constraint = OutputBEconomicConstraint(
                constraint_id=const_id,
                discovery_id=disc_id,
                market_a_id=str(data["market_a_id"]),
                market_b_id=str(data["market_b_id"]),
                constraint_type=const_type,
                trigger_threshold_delta_a=float(data.get("trigger_threshold_delta_a", 0.03)),
                expected_delta_b=float(data.get("expected_delta_b", 0.02)),
                lead_time_hours=float(data.get("lead_time_hours", 6.0)),
                testable_null_hypothesis=str(data.get("testable_null_hypothesis", "H0: Effect <= baseline")),
                mathematical_expression=str(data.get("mathematical_expression", "ΔP(B) >= 0.02")),
                invalidation_criteria=data.get("invalidation_criteria", []),
                is_active=True
            )

            return CandidateRelationship(
                discovery=discovery,
                constraint=constraint,
                intermediate_nodes=[],
                hop_count=1
            )
        except Exception as e:
            logger.warning(f"Failed to parse LLM candidate: {e}")
            return None

    def discover_structured_hypotheses(
        self,
        canonical_markets: List[CanonicalMarket],
        max_hypotheses: int = 10
    ) -> List[StructuredHypothesis]:
        """Discovers structured, testable hypotheses classified into the 7 hypothesis families
        and verified by BoundaryValidator.
        """
        if not canonical_markets:
            return []

        if not isinstance(self.llm, HeuristicDomainLLMClient):
            try:
                return self._discover_structured_via_api(canonical_markets, max_hypotheses)
            except Exception as e:
                logger.warning(f"Structured LLM discovery failed ({e}), falling back to domain engine.")
                return self._discover_structured_via_domain(canonical_markets, max_hypotheses)
        else:
            return self._discover_structured_via_domain(canonical_markets, max_hypotheses)

    def _discover_structured_via_api(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int
    ) -> List[StructuredHypothesis]:
        """Queries LLM using the operational template: INPUT -> TRANSFORMATION -> PREDICTION -> HORIZON -> COST -> FALSIFICATION."""
        market_summaries = [
            f"ID: {m.market_id} | Title: {m.title} | Entities: {','.join(m.entities)} | Event: {m.event_type} | Horizon: {m.time_horizon}"
            for m in markets[:50]
        ]
        prompt = (
            "You are an elite quantitative researcher in prediction markets.\n"
            "Generate structured testable hypotheses for statistical arbitrage.\n"
            "Classify each hypothesis into exactly one of the 7 designated families:\n"
            "exact_contract_arb, resolution_arb, conditional_stat_arb, cross_market_lead_lag, "
            "order_flow_microstructure, event_conditional_stat_arb, cross_venue_platform.\n"
            "CRITICAL: Do NOT declare profitability or guaranteed alpha. Confidence is DISCOVERY PRIOR ONLY.\n"
            "Every hypothesis MUST adhere to the operational template:\n"
            "INPUT -> TRANSFORMATION -> PREDICTION -> HORIZON -> COST_MODEL -> FALSIFICATION_TEST.\n\n"
            "Markets:\n" + "\n".join(market_summaries)
        )
        schema_desc = """
        {
          "hypotheses": [
            {
              "hypothesis_id": "hyp_btc_eth_leadlag_001",
              "hypothesis_family": "cross_market_lead_lag",
              "source_markets": ["..."],
              "target_markets": ["..."],
              "causal_mechanism": "...",
              "required_observations": ["order_book_l2", "trades"],
              "observable_variables": ["signed_order_flow_imbalance", "mid_price"],
              "expected_relationship": "...",
              "direction": "positive | negative | mean_reverting | lead_lag | monotone_bound",
              "expected_time_horizon": "5-30s | 1m-5m | 1h-4h",
              "falsification_condition": "...",
              "minimum_sample_requirement": 30,
              "proposed_statistical_test": "permutation_test",
              "proposed_placebo_control": "time_shift_24h",
              "execution_dependency": "taker_l2_walk",
              "expected_friction_sensitivity": "medium",
              "capacity_dependency": 1000.0,
              "known_confounders": ["macro_drift"],
              "lookahead_risk": "None, calculated strictly on lagged observations",
              "confidence": 0.8,
              "input_signal": "5-minute signed order-flow imbalance in contract A",
              "transformation": "standardized imbalance > 2.0 sigma",
              "prediction": "contract B executable mid moves in same direction by >= 25 bps",
              "horizon": "5-30 seconds",
              "cost_model": "actual observed L2 ladder + 20 bps taker fee",
              "falsification_test": "randomized timestamps + reverse direction + matched controls",
              "lineage_family_id": "fam_btc_eth_leadlag"
            }
          ]
        }
        """
        res = self.llm.generate_json(prompt, schema_desc)
        hypotheses: List[StructuredHypothesis] = []
        for item in res.get("hypotheses", [])[:max_hypotheses]:
            try:
                hyp = BoundaryValidator.sanitize_and_construct(item)
                hypotheses.append(hyp)
            except Exception as e:
                logger.warning(f"Boundary validation failed for AI hypothesis proposal: {e}")
        return hypotheses

    def _discover_structured_via_domain(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int
    ) -> List[StructuredHypothesis]:
        """Domain generator producing verified hypotheses across designated families."""
        raw_candidates = self._discover_via_domain_engine(markets, max_candidates=max_hypotheses * 2)
        structured: List[StructuredHypothesis] = []

        for cand in raw_candidates:
            # Map candidate to structured hypothesis
            opp = cand.discovery.opportunity_class
            rel = cand.discovery.relationship_type

            if opp == OpportunityClass.STRUCTURAL:
                fam = HypothesisFamily.EXACT_CONTRACT_ARB
            elif opp in (OpportunityClass.RESOLUTION_ARBITRAGE, OpportunityClass.CROSS_MARKET_LOGICAL):
                fam = HypothesisFamily.RESOLUTION_ARB
            elif rel == RelationshipType.TEMPORAL_LEAD_LAG or opp == OpportunityClass.INFORMATION_LATENCY:
                fam = HypothesisFamily.CROSS_MARKET_LEAD_LAG
            elif opp == OpportunityClass.SECOND_ORDER or rel == RelationshipType.EVENT_CHAIN:
                fam = HypothesisFamily.EVENT_CONDITIONAL_STAT_ARB
            elif rel == RelationshipType.CROSS_PLATFORM_EQUIVALENCE:
                fam = HypothesisFamily.CROSS_VENUE_PLATFORM
            else:
                fam = HypothesisFamily.CONDITIONAL_STAT_ARB

            short_id = f"hyp_{cand.discovery.discovery_id[-6:]}"
            fam_id = f"fam_{fam.value}_{cand.discovery.market_a_id[:6]}_{cand.discovery.market_b_id[:6]}"

            proposal_dict = {
                "hypothesis_id": short_id,
                "hypothesis_family": fam.value,
                "source_markets": [cand.discovery.market_a_id],
                "target_markets": [cand.discovery.market_b_id],
                "causal_mechanism": cand.discovery.economic_mechanism,
                "required_observations": ["order_book_l2", "trades"],
                "observable_variables": ["mid_price", "spread", "delta_p"],
                "expected_relationship": cand.constraint.mathematical_expression,
                "direction": "lead_lag" if fam == HypothesisFamily.CROSS_MARKET_LEAD_LAG else "mean_reverting",
                "expected_time_horizon": f"{int(cand.constraint.lead_time_hours)}h",
                "falsification_condition": cand.constraint.testable_null_hypothesis,
                "minimum_sample_requirement": 30,
                "proposed_statistical_test": "permutation_test",
                "proposed_placebo_control": "time_shift_24h_placebo",
                "execution_dependency": "taker_l2_walk",
                "expected_friction_sensitivity": "medium",
                "capacity_dependency": 1000.0,
                "known_confounders": ["macro_trend", "common_liquidity_shock"],
                "lookahead_risk": "Strict zero-lookahead: leading market trigger strictly precedes evaluation window.",
                "confidence": cand.discovery.confidence,
                "input_signal": f"Leading market {cand.discovery.market_a_id} price delta >= {cand.constraint.trigger_threshold_delta_a}",
                "transformation": "Standardized difference over baseline drift",
                "prediction": f"Target market {cand.discovery.market_b_id} moves by >= {cand.constraint.expected_delta_b}",
                "horizon": f"{cand.constraint.lead_time_hours} hours",
                "cost_model": "Observed L2 ladder depth + 20 bps taker fee + 5 bps latency penalty",
                "falsification_test": "Time-shifted placebo + reverse-direction symmetric test + randomized pairs",
                "lineage_family_id": fam_id,
            }

            try:
                hyp = BoundaryValidator.sanitize_and_construct(proposal_dict)
                structured.append(hyp)
                if len(structured) >= max_hypotheses:
                    break
            except Exception as e:
                logger.warning(f"Failed to construct structured hypothesis: {e}")

        return structured
