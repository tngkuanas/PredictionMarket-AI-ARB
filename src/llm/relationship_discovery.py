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
    DiscoveryMode,
    EdgeType,
    DecayProfile,
    NoveltyClassification,
    QualityGateStatus,
    HypothesisQualityState,
)
from src.statarb.boundary_validator import BoundaryValidator
from src.statarb.self_critique import AISelfCritiqueValidator
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
        max_hypotheses: int = 10,
        mode: Optional[DiscoveryMode] = None,
    ) -> List[StructuredHypothesis]:
        """Discovers structured, testable hypotheses classified into the 7 hypothesis families
        and verified by BoundaryValidator and AISelfCritiqueValidator.
        """
        if not canonical_markets:
            return []

        if not isinstance(self.llm, HeuristicDomainLLMClient):
            try:
                return self._discover_structured_via_api(canonical_markets, max_hypotheses, mode=mode)
            except Exception as e:
                logger.warning(f"Structured LLM discovery failed ({e}), falling back to domain engine.")
                return self._discover_structured_via_domain(canonical_markets, max_hypotheses, mode=mode)
        else:
            return self._discover_structured_via_domain(canonical_markets, max_hypotheses, mode=mode)

    def _discover_structured_via_api(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int,
        mode: Optional[DiscoveryMode] = None,
    ) -> List[StructuredHypothesis]:
        """Queries LLM using operational template: INPUT -> TRANSFORMATION -> PREDICTION -> HORIZON -> COST -> FALSIFICATION."""
        market_summaries = [
            f"ID: {m.market_id} | Title: {m.title} | Entities: {','.join(m.entities)} | Event: {m.event_type} | Horizon: {m.time_horizon}"
            for m in markets[:50]
        ]
        mode_str = f"Target Discovery Mode: {mode.value}" if mode else "Distribute across the 7 discovery modes"
        prompt = (
            "You are an elite quantitative researcher in prediction markets.\n"
            f"{mode_str}\n"
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
                critique_res = AISelfCritiqueValidator.critique(hyp)
                hyp.quality_state = critique_res.quality_state
                if critique_res.passed_structural_critique:
                    hypotheses.append(hyp)
                else:
                    logger.info(f"Hypothesis {hyp.hypothesis_id} rejected by self-critique: {critique_res.rejection_reasons}")
            except Exception as e:
                logger.warning(f"Boundary validation failed for AI hypothesis proposal: {e}")
        return hypotheses

    def _discover_structured_via_domain(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int,
        mode: Optional[DiscoveryMode] = None,
    ) -> List[StructuredHypothesis]:
        """Domain generator producing verified hypotheses across the 7 designated modes (Phase 10A.6d)."""
        raw_candidates = self._discover_via_domain_engine(markets, max_candidates=max_hypotheses * 3)
        structured: List[StructuredHypothesis] = []

        # Determine target modes
        target_modes = [mode] if mode else list(DiscoveryMode)

        # Standard Confounder Audit
        default_confounders = {
            "macro_shock": {
                "expected_distortion": "Broad market re-pricing causing spurious co-movement",
                "control_method": "Residualize against macro index / matched non-event window"
            },
            "market_wide_drift": {
                "expected_distortion": "Persistent secular trend inflating correlation",
                "control_method": "High-pass differencing and stationary detrending"
            },
            "time_of_day_liquidity": {
                "expected_distortion": "Wider spreads during low-volume hours creating false edge",
                "control_method": "Time-of-day matched sampling and spread stratification"
            },
            "resolution_proximity": {
                "expected_distortion": "Non-linear delta acceleration near expiration",
                "control_method": "Filter out contracts within 48h of settlement"
            },
            "event_clustering": {
                "expected_distortion": "Multiple news items triggering serial autocorrelation",
                "control_method": "Cluster-robust Newey-West standard errors and event isolation"
            }
        }

        # Standard Pre-Test Controls
        default_controls = {
            "primary_test": "Permutation test of conditional forward return difference",
            "placebo_test": "24-hour time-shifted lead/lag correlation",
            "reverse_test": "Reverse-direction Granger causality and regression",
            "matched_control": "Matched non-event volatility and volume control window",
            "OOS_test": "Strict forward temporal split on unseen chronologically later data",
            "friction_stress": "Walk executable L2 order ladder with 2x observed spread and 20 bps fees",
            "capacity_stress": "Simulate $1,000 order walking book depth to measure slippage degradation"
        }

        mode_idx = 0
        for cand in raw_candidates:
            current_mode = target_modes[mode_idx % len(target_modes)]
            mode_idx += 1

            m_a = cand.discovery.market_a_id
            m_b = cand.discovery.market_b_id
            short_id = f"hyp_{current_mode.value.lower()}_{m_a[:6]}_{m_b[:6]}"
            fam_id = f"fam_{current_mode.value.lower()}_{m_a[:6]}_{m_b[:6]}"

            # Mode-specific attributes
            if current_mode == DiscoveryMode.MODE_A_LOGICAL:
                edge_type = EdgeType.RESOLUTION_ARBITRAGE
                fam = HypothesisFamily.RESOLUTION_ARB
                mech_type = "SETTLEMENT_LOGIC"
                mech = "Contract settlement rules enforce deterministic payout bounds between mutually exclusive or conditional outcomes."
                pers_rationale = "Settlement rule logic defines immutable payoff bound that persists until contract resolution."
                target_var = "P(Target)_{expiry}"
                cond = "P(Source) + P(Target) > 1.05 or P(Source) < P(Target)"
                exp_eff = "Deterministic convergence to settlement bound"
                min_eff = 25.0
                cost_bps = 15.0
                decay = DecayProfile.PERSISTENT
                horizon = "1h-24h"
                lat_rationale = "Structural bound survives until active capital arbitrage; not sensitive to sub-second latency."
                exp_gross = 40.0
                spread = 6.0
                fee = 0.0
                slip = 4.0
                lat_pen = 2.0
                safety = 5.0
                req_gross = 17.0
                fwd_rat = "Settlement criteria deterministically link outcome payouts."
                rev_rat = "Structural non-directional payoff identity."
                is_dir = False
                nec_cond = ["Authoritative settlement terms remain unchanged", "Executable depth >= $500", "No dispute ambiguity"]
                fail_cond = ["Settlement criteria changed by resolution source", "Spread exceeds pricing disparity", "Placebo shows identical spread"]

            elif current_mode == DiscoveryMode.MODE_B_ECONOMIC:
                edge_type = EdgeType.PREDICTIVE_INFORMATION_EDGE
                fam = HypothesisFamily.EVENT_CONDITIONAL_STAT_ARB
                mech_type = "COMMON_FUNDAMENTAL"
                mech = "Macro policy surprises and inflation expectations propagate sequentially to secondary contracts."
                pers_rationale = "Macro fundamental adjustments take minutes to hours to fully filter into niche prediction contracts."
                target_var = "Delta P(Target)_{t+15m}"
                cond = "|Delta P(Source)_t| >= 20 bps"
                exp_eff = "Target contract adjusts in direction of macro surprise by >= 25 bps"
                min_eff = 20.0
                cost_bps = 20.0
                decay = DecayProfile.GRADUAL_DECAY
                horizon = "15m-1h"
                lat_rationale = "Transmission occurs over multiple minutes through secondary liquidity rebalancing."
                exp_gross = 38.0
                spread = 10.0
                fee = 2.0
                slip = 5.0
                lat_pen = 4.0
                safety = 5.0
                req_gross = 26.0
                fwd_rat = "Macro fundamental shift directly impacts target contract asset valuation."
                rev_rat = "Target contract trading does not feed back into global macroeconomic parameters."
                is_dir = True
                nec_cond = ["Macro surprise is statistically detectable", "Target contract remains liquid", "Survives time-shifted placebo"]
                fail_cond = ["Friction consumes full return", "Reverse direction exhibits identical correlation", "OOS drift accounts for move"]

            elif current_mode == DiscoveryMode.MODE_C_EVENT:
                edge_type = EdgeType.PREDICTIVE_INFORMATION_EDGE
                fam = HypothesisFamily.EVENT_CONDITIONAL_STAT_ARB
                mech_type = "EVENT_RESPONSE"
                mech = "Scheduled release announcements trigger immediate repricing in primary market with delayed spillover to target."
                pers_rationale = "Staggered participant attention and retail order queues preserve a 15-60s execution window."
                target_var = "Delta P(Target)_{t+30s}"
                cond = "Official event release deviation >= 2.0 sigma"
                exp_eff = "Target contract executable price jumps by >= 30 bps"
                min_eff = 25.0
                cost_bps = 25.0
                decay = DecayProfile.FAST_DECAY
                horizon = "15s-60s"
                lat_rationale = "Automated taker execution within 250ms captures post-event adjustment before makers cancel quotes."
                exp_gross = 45.0
                spread = 12.0
                fee = 2.0
                slip = 6.0
                lat_pen = 5.0
                safety = 5.0
                req_gross = 30.0
                fwd_rat = "Official release instantly updates conditional probability state."
                rev_rat = "Exogenous release cannot be predicted by pre-event target price fluctuations."
                is_dir = True
                nec_cond = ["Official timestamp precedes price move", "Executable depth survives event shock", "Survives reverse direction test"]
                fail_cond = ["Edge disappears after 250ms latency delay", "Pre-event drift accounts for entire response", "Randomized timestamps match response"]

            elif current_mode == DiscoveryMode.MODE_D_MICROSTRUCTURE:
                edge_type = EdgeType.MICROSTRUCTURE_EDGE
                fam = HypothesisFamily.ORDER_FLOW_MICROSTRUCTURE
                mech_type = "ORDER_FLOW_TRANSMISSION"
                mech = "Aggressive order book sweeps deplete liquidity in contract A, prompting market makers to lean quotes in contract B."
                pers_rationale = "Market makers update quotes across correlated books sequentially, leaving a 5-30s window."
                target_var = "P(Target)_{t+15s} - Mid(Target)_t"
                cond = "Signed order flow imbalance >= 2.0 sigma"
                exp_eff = "Target contract executable price moves in direction of flow by >= 25 bps"
                min_eff = 20.0
                cost_bps = 20.0
                decay = DecayProfile.FAST_DECAY
                horizon = "5-30s"
                lat_rationale = "Order flow transmission across books survives 5-30s before replenishment."
                exp_gross = 32.0
                spread = 8.0
                fee = 2.0
                slip = 4.0
                lat_pen = 5.0
                safety = 5.0
                req_gross = 24.0
                fwd_rat = "Aggressive book sweep reveals informed inventory flow to makers."
                rev_rat = "Secondary contract has low organic flow and does not lead primary order books."
                is_dir = True
                nec_cond = ["Signed imbalance precedes target quote shift", "Target book maintains observable depth", "Survives feature removal"]
                fail_cond = ["Edge vanishes when walking full L2 ladder instead of mid-price", "Reversal occurs immediately upon fill", "Latency > 500ms destroys edge"]

            elif current_mode == DiscoveryMode.MODE_E_CROSS_MARKET:
                edge_type = EdgeType.PREDICTIVE_INFORMATION_EDGE
                fam = HypothesisFamily.CROSS_MARKET_LEAD_LAG
                mech_type = "LEAD_LAG"
                mech = "Leading market A processes information faster due to higher liquidity, establishing temporal lead over market B."
                pers_rationale = "Capital allocation latency and differing attention pools maintain 15-90s lead/lag."
                target_var = "Delta P(Target)_{t+30s}"
                cond = "Delta P(Source)_t >= 20 bps"
                exp_eff = "Target contract adjusts in same direction by >= 25 bps"
                min_eff = 20.0
                cost_bps = 22.0
                decay = DecayProfile.FAST_DECAY
                horizon = "15-90s"
                lat_rationale = "Lead/lag persists due to distinct retail participants and lack of cross-market high-frequency market makers."
                exp_gross = 36.0
                spread = 10.0
                fee = 2.0
                slip = 5.0
                lat_pen = 5.0
                safety = 5.0
                req_gross = 27.0
                fwd_rat = "Source market possesses higher trading volume and institutional discovery."
                rev_rat = "Target market does not drive price formation in primary benchmark."
                is_dir = True
                nec_cond = ["Source update strictly precedes target response", "Target executable spread narrower than move", "Survives reverse test"]
                fail_cond = ["Reverse direction produces equal predictive power", "Gross edge consumed by taker fees", "Lead disappears out-of-sample"]

            elif current_mode == DiscoveryMode.MODE_F_CROSS_VENUE:
                edge_type = EdgeType.CROSS_VENUE_ARBITRAGE
                fam = HypothesisFamily.CROSS_VENUE_PLATFORM
                mech_type = "CROSS_VENUE_PRICE_DISCOVERY"
                mech = "Price discovery across Polymarket and Kalshi exhibits temporary divergence due to fiat/crypto capital segmentation."
                pers_rationale = "Inter-platform capital transfer delays preserve price disparities for 10-60s."
                target_var = "P(Venue_B)_t - P(Venue_A)_t"
                cond = "|P(Venue_A) - P(Venue_B)| >= 35 bps"
                exp_eff = "Cross-venue spread mean-reverts to zero within 60s"
                min_eff = 30.0
                cost_bps = 30.0
                decay = DecayProfile.FAST_DECAY
                horizon = "10-60s"
                lat_rationale = "Simultaneous dual-venue execution requires 8 bps latency penalty to model transfer/fill risks."
                exp_gross = 48.0
                spread = 14.0
                fee = 4.0
                slip = 6.0
                lat_pen = 8.0
                safety = 5.0
                req_gross = 37.0
                fwd_rat = "Primary offshore crypto venue incorporates global order flow faster than domestic venue."
                rev_rat = "Domestic venue has lower velocity and follows primary venue price adjustments."
                is_dir = True
                nec_cond = ["Contracts are economically identical in settlement terms", "Both platforms maintain active books", "Friction < spread disparity"]
                fail_cond = ["Settlement rule divergence between platforms", "Leg execution desynchronization", "Dual taker fees eliminate edge"]

            else: # MODE_G_STAT_ARB
                edge_type = EdgeType.STATISTICAL_ARBITRAGE
                fam = HypothesisFamily.CONDITIONAL_STAT_ARB
                mech_type = "RISK_TRANSFER"
                mech = "Temporary liquidity imbalances dislocate cointegrated price ratio before statistical arbitrageurs restore equilibrium."
                pers_rationale = "Mean-reverting spread dynamics unfold over minutes as market makers replenish depth."
                target_var = "Spread_t = P(Target)_t - beta * P(Source)_t"
                cond = "|Z(Spread_t)| >= 2.0 sigma"
                exp_eff = "Spread mean-reverts toward long-run equilibrium with half-life < 30 steps"
                min_eff = 25.0
                cost_bps = 20.0
                decay = DecayProfile.GRADUAL_DECAY
                horizon = "5m-30m"
                lat_rationale = "Mean reversion horizon of minutes permits conservative execution without sub-second latency sensitivity."
                exp_gross = 36.0
                spread = 10.0
                fee = 2.0
                slip = 5.0
                lat_pen = 4.0
                safety = 5.0
                req_gross = 26.0
                fwd_rat = "Spread deviations reflect temporary inventory imbalances rather than structural breaks."
                rev_rat = "Relative-value mean reversion is inherently symmetric (non-directional)."
                is_dir = False
                nec_cond = ["Spread exhibits empirical stationarity (ADF p-value < 0.05)", "Estimated half-life is finite (< 60 steps)", "Survives OOS cointegration"]
                fail_cond = ["Spread is non-stationary / random walk", "Divergence expands beyond stop-loss z-score", "Trading costs exceed reversion amplitude"]

            proposal_dict = {
                "hypothesis_id": short_id,
                "hypothesis_family": fam.value,
                "source_markets": [m_a],
                "target_markets": [m_b],
                "causal_mechanism": mech,
                "required_observations": ["order_book_l2", "trades"],
                "observable_variables": ["mid_price", "spread", "delta_p"],
                "expected_relationship": cand.constraint.mathematical_expression,
                "direction": "lead_lag" if is_dir else "mean_reverting",
                "expected_time_horizon": horizon,
                "falsification_condition": cand.constraint.testable_null_hypothesis,
                "minimum_sample_requirement": 30,
                "proposed_statistical_test": "permutation_test",
                "proposed_placebo_control": "time_shift_24h_placebo",
                "execution_dependency": "taker_l2_walk",
                "expected_friction_sensitivity": "medium",
                "capacity_dependency": 1000.0,
                "known_confounders": list(default_confounders.keys()),
                "lookahead_risk": "Strict zero-lookahead: leading market trigger strictly precedes evaluation window.",
                "confidence": cand.discovery.confidence,
                "input_signal": f"Leading market {m_a} trigger condition",
                "transformation": "Standardized difference over baseline drift",
                "prediction": f"Target market {m_b} conditional adjustment",
                "horizon": horizon,
                "cost_model": f"Observed L2 ladder depth + {fee:.1f} bps fee + {lat_pen:.1f} bps latency penalty",
                "falsification_test": "Time-shifted placebo + reverse-direction test + matched controls",
                "lineage_family_id": fam_id,
                "discovery_mode": current_mode.value,
                "edge_type": edge_type.value,
                "economic_mechanism_type": mech_type,
                "mechanism_persistence_rationale": pers_rationale,
                "target_variable": target_var,
                "condition": cond,
                "expected_effect": exp_eff,
                "minimum_effect_size_bps": min_eff,
                "cost_assumption_bps": cost_bps,
                "novelty_classification": NoveltyClassification.NEW.value,
                "necessary_conditions": nec_cond,
                "failure_conditions": fail_cond,
                "expected_response_horizon": horizon,
                "expected_decay_profile": decay.value,
                "latency_sensitivity_rationale": lat_rationale,
                "expected_gross_edge_bps": exp_gross,
                "expected_spread_bps": spread,
                "expected_fee_bps": fee,
                "expected_slippage_bps": slip,
                "latency_penalty_bps": lat_pen,
                "safety_margin_bps": safety,
                "required_gross_edge_bps": req_gross,
                "is_frictionally_plausible": (exp_gross >= req_gross),
                "expected_order_size_usd": 250.0,
                "minimum_required_depth_usd": 750.0,
                "expected_capacity_usd": 2500.0,
                "capacity_failure_condition": "Observable depth in target book drops below $500, causing severe ladder walk slippage.",
                "forward_causal_rationale": fwd_rat,
                "reverse_causal_rationale": rev_rat,
                "causal_asymmetry_established": True,
                "confounders_audit": default_confounders,
                "pre_test_controls": default_controls,
            }

            try:
                hyp = BoundaryValidator.sanitize_and_construct(proposal_dict)
                critique_res = AISelfCritiqueValidator.critique(hyp)
                hyp.quality_state = critique_res.quality_state
                if critique_res.passed_structural_critique:
                    structured.append(hyp)
                else:
                    logger.info(f"Hypothesis {hyp.hypothesis_id} rejected by structural self-critique: {critique_res.rejection_reasons}")
                if len(structured) >= max_hypotheses:
                    break
            except Exception as e:
                logger.warning(f"Failed to construct structured hypothesis: {e}")

        return structured
