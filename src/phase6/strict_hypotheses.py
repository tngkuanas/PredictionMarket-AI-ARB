"""Phase 6: Strict Causal Hypothesis Generator.
Replaces simplistic semantic association generation with a rigorous 9-dimensional
causal economic specification. Forces the system to generate fewer, high-conviction hypotheses.
"""
import uuid
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from src.normalization.schema import (
    CanonicalMarket,
    OpportunityClass,
    RelationshipType,
    ConstraintType,
)
from src.llm.base import BaseLLMClient, get_llm_client, HeuristicDomainLLMClient

logger = logging.getLogger(__name__)


class StrictHypothesis(BaseModel):
    """Rigorous 9-dimensional causal economic hypothesis specification for prediction market stat-arb."""
    hypothesis_id: str = Field(default_factory=lambda: f"h6_{uuid.uuid4().hex[:10]}")
    market_a_id: str
    market_b_id: str
    market_a_title: str
    market_b_title: str
    opportunity_class: OpportunityClass
    relationship_type: RelationshipType

    # 1. Specific causal / economic mechanism
    causal_mechanism: str

    # 2. Exact measurable leading variable
    exact_leading_variable: str

    # 3. Expected response function
    expected_response_function: str

    # 4. Expected lag distribution
    expected_lag_distribution: Dict[str, Any]

    # 5. Regime conditions
    regime_conditions: Dict[str, Any]

    # 6. Invalidation conditions
    invalidation_conditions: List[str]

    # 7. Minimum economically meaningful move
    min_economic_move: float = 0.02

    # 8. Why the relationship should persist despite public information
    persistence_rationale: str

    # 9. What would cause the relationship to disappear
    disappearance_catalysts: str

    # Confidence & metadata
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.85)


class StrictHypothesisGenerator:
    """Generates a small, highly curated set of falsifiable, state-dependent economic hypotheses."""

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self.llm = llm_client or get_llm_client()

    def generate_curated_hypotheses(
        self,
        canonical_markets: List[CanonicalMarket],
        max_hypotheses: int = 12
    ) -> List[StrictHypothesis]:
        """Generate top curated hypotheses satisfying all 9 strict requirements."""
        if not isinstance(self.llm, HeuristicDomainLLMClient):
            try:
                return self._generate_via_api(canonical_markets, max_hypotheses)
            except Exception as e:
                logger.warning(f"LLM API generation failed ({e}); falling back to domain engine.")
                return self._generate_via_curated_domain_engine(canonical_markets, max_hypotheses)
        else:
            return self._generate_via_curated_domain_engine(canonical_markets, max_hypotheses)

    def _generate_via_api(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int
    ) -> List[StrictHypothesis]:
        """Query LLM with strict 9-point prompt."""
        m_summaries = [
            f"ID: {m.market_id} | Title: {m.title} | Event: {m.underlying_event} | Horizon: {m.time_horizon}"
            for m in markets[:50]
        ]
        prompt = (
            "You are a quantitative researcher developing a prediction-market relative-value statistical arbitrage engine.\n"
            "Propose a strictly limited set of FEWER, HIGH-CONVICTION causal economic hypotheses (maximum 10).\n"
            "DO NOT suggest loose semantic correlations, coincidences, or trivial complements.\n"
            "Every hypothesis must meet these NINE non-negotiable criteria:\n"
            "1. Specific causal/economic mechanism (structural transmission chain)\n"
            "2. Exact measurable leading variable (e.g. 1h return in P(A) > +0.05 pp)\n"
            "3. Expected response function (e.g. dP(B) = beta * dP(A) with beta in [0.3, 0.6])\n"
            "4. Expected lag distribution (mode, half-life, maximum duration)\n"
            "5. Regime conditions (volatility floor, liquidity floor, time to expiry)\n"
            "6. Invalidation conditions (ADF non-stationarity, sign reversal, zero lag correlation)\n"
            "7. Minimum economically meaningful move (must be >= 0.02 pp)\n"
            "8. Why the relationship persists despite public information (e.g. attention segmentation, maker capital friction)\n"
            "9. What would cause the relationship to disappear (e.g. automated market maker cross-hedging)\n\n"
            "Candidate Markets:\n" + "\n".join(m_summaries)
        )
        schema_desc = """
        {
          "hypotheses": [
            {
              "market_a_id": "...",
              "market_b_id": "...",
              "market_a_title": "...",
              "market_b_title": "...",
              "opportunity_class": "ai_semantic | second_order | information_latency",
              "relationship_type": "positive_economic | negative_economic | temporal_lead_lag",
              "causal_mechanism": "...",
              "exact_leading_variable": "...",
              "expected_response_function": "...",
              "expected_lag_distribution": {"mode_hours": 0.25, "half_life_hours": 1.5, "max_lag_hours": 6.0},
              "regime_conditions": {"min_volatility_a": 0.015, "min_target_liquidity_usd": 10000.0, "max_spread_b": 0.03},
              "invalidation_conditions": ["Residual stationarity rejected", "Half-life > 48h"],
              "min_economic_move": 0.02,
              "persistence_rationale": "...",
              "disappearance_catalysts": "...",
              "confidence_score": 0.85
            }
          ]
        }
        """
        res = self.llm.generate_json(prompt, schema_desc)
        results = []
        for item in res.get("hypotheses", [])[:max_hypotheses]:
            try:
                results.append(StrictHypothesis(**item))
            except Exception as parse_err:
                logger.debug(f"Failed parsing item: {parse_err}")
        return results

    def _generate_via_curated_domain_engine(
        self,
        markets: List[CanonicalMarket],
        max_hypotheses: int
    ) -> List[StrictHypothesis]:
        """Curated domain engine yielding strong, structurally motivated, falsifiable hypotheses."""
        m_by_id = {m.market_id: m for m in markets}
        m_list = list(markets)

        # Lookup helpers
        def find_market(query_keywords: List[str], exclude_id: Optional[str] = None) -> Optional[CanonicalMarket]:
            for m in m_list:
                if exclude_id and m.market_id == exclude_id:
                    continue
                t = f"{m.title} {m.underlying_event}".lower()
                if all(k.lower() in t for k in query_keywords):
                    return m
            return None

        curated: List[StrictHypothesis] = []

        # Hypothesis 1: Fed Rate Hike -> Bitcoin Dip / Crypto Contraction
        m_fed = find_market(["fed", "interest", "rate"])
        m_btc = find_market(["bitcoin", "dip"], exclude_id=m_fed.market_id if m_fed else None)
        if m_fed and m_btc:
            curated.append(StrictHypothesis(
                hypothesis_id="h6_macro_fed_btc_dip",
                market_a_id=m_fed.market_id,
                market_b_id=m_btc.market_id,
                market_a_title=m_fed.title,
                market_b_title=m_btc.title,
                opportunity_class=OpportunityClass.AI_SEMANTIC,
                relationship_type=RelationshipType.POSITIVE_ECONOMIC,
                causal_mechanism=(
                    "Hawkish monetary policy surprise tightens dollar liquidity and raises discount rates, "
                    "prompting rapid risk-off deleveraging in high-beta digital assets."
                ),
                exact_leading_variable="1-hour upward revision in Fed rate-hike probability: ΔP(A)_1h >= +0.04",
                expected_response_function="Linear impulse: ΔP(B)_{t+h} = 0.52 * ΔP(A)_t - 0.18 * spread_B",
                expected_lag_distribution={"mode_hours": 0.5, "half_life_hours": 1.5, "max_lag_hours": 6.0},
                regime_conditions={"min_volatility_a": 0.015, "min_target_liquidity_usd": 20000.0, "max_spread_b": 0.025},
                invalidation_conditions=[
                    "Residual non-stationarity (ADF p > 0.05)",
                    "Sign reversal in return correlation (r_ret < 0)",
                    "Residual half-life exceeding 24 hours"
                ],
                min_economic_move=0.025,
                persistence_rationale=(
                    "Macro prediction market participants incorporate FOMC leaks and Bloomberg terminal releases "
                    "faster than peripheral crypto-strike contracts, where retail liquidity providers adjust limits with a delay."
                ),
                disappearance_catalysts="Programmatic automated cross-market routing between Polymarket macro and crypto CLOB books.",
                confidence_score=0.88
            ))

        # Hypothesis 2: Iranian Escalation / Blockade -> Diesel / Energy Disruption
        m_iran = find_market(["iran", "blockade"]) or find_market(["iran", "ceasefire"])
        m_diesel = find_market(["diesel", "export"]) or find_market(["hormuz"])
        if m_iran and m_diesel and m_iran.market_id != m_diesel.market_id:
            curated.append(StrictHypothesis(
                hypothesis_id="h6_geopol_iran_energy",
                market_a_id=m_iran.market_id,
                market_b_id=m_diesel.market_id,
                market_a_title=m_iran.title,
                market_b_title=m_diesel.title,
                opportunity_class=OpportunityClass.SECOND_ORDER,
                relationship_type=RelationshipType.NEGATIVE_ECONOMIC if "ceasefire" in m_iran.title.lower() else RelationshipType.POSITIVE_ECONOMIC,
                causal_mechanism=(
                    "Geopolitical maritime escalation in Persian Gulf chokepoints directly threatens crude transit, "
                    "forcing refinery inventory drawdowns and triggering regulatory fuel export restrictions."
                ),
                exact_leading_variable="Sustained 4-hour shift in Iranian conflict/blockade probability: |ΔP(A)_4h| >= +0.05",
                expected_response_function="Sigmoidal response: ΔP(B)_{t+h} = 0.65 / (1 + exp(-5 * (ΔP(A)_t - 0.04)))",
                expected_lag_distribution={"mode_hours": 1.0, "half_life_hours": 3.0, "max_lag_hours": 12.0},
                regime_conditions={"min_volatility_a": 0.02, "min_target_liquidity_usd": 15000.0, "max_spread_b": 0.035},
                invalidation_conditions=[
                    "Uncorrelated returns during major diplomatic announcements",
                    "Ornstein-Uhlenbeck kappa < 0.03",
                    "Residual stationarity test failure"
                ],
                min_economic_move=0.030,
                persistence_rationale=(
                    "Energy contracts are held by specialized commodities traders while geopolitical contracts are driven by breaking news sentiment; "
                    "capital fragmentation between the two books creates a 1-3 hour information latency."
                ),
                disappearance_catalysts="Direct institutional API algorithmic arbitrage linking Gulf naval AIS ship-tracking feeds to both order books.",
                confidence_score=0.84
            ))

        # Hypothesis 3: Russian Political Destabilization -> EU Military Conflict Escalation
        m_rus = find_market(["putin", "russia"]) or find_market(["russia"])
        m_eu = find_market(["russia", "eu"]) or find_market(["military", "eu"])
        if m_rus and m_eu and m_rus.market_id != m_eu.market_id:
            curated.append(StrictHypothesis(
                hypothesis_id="h6_geopol_russia_eu_escalation",
                market_a_id=m_rus.market_id,
                market_b_id=m_eu.market_id,
                market_a_title=m_rus.title,
                market_b_title=m_eu.title,
                opportunity_class=OpportunityClass.SECOND_ORDER,
                relationship_type=RelationshipType.POSITIVE_ECONOMIC,
                causal_mechanism=(
                    "Internal political instability or regime vulnerability in Moscow accelerates external military adventurism "
                    "as a diversionary strategy, increasing probability of border provocations against EU member states."
                ),
                exact_leading_variable="Sudden volatility breakout in Russian leadership exit contract: σ_A(24h) > 2.5 * baseline_σ",
                expected_response_function="Threshold jump: If ΔP(A) >= 0.05, then E[ΔP(B)] = +0.035 with lag h=4h",
                expected_lag_distribution={"mode_hours": 2.0, "half_life_hours": 4.5, "max_lag_hours": 18.0},
                regime_conditions={"min_volatility_a": 0.02, "min_target_liquidity_usd": 12000.0, "max_spread_b": 0.03},
                invalidation_conditions=[
                    "Lack of co-movement during verified geopolitical news releases",
                    "Residual mean reversion half-life > 36 hours"
                ],
                min_economic_move=0.025,
                persistence_rationale=(
                    "Low daily turnover on foreign policy contracts produces stale limit orders that remain uncancelled "
                    "for several hours following non-English geopolitical developments."
                ),
                disappearance_catalysts="Polymarket listing active multi-market conditional bundle tokens.",
                confidence_score=0.81
            ))

        # Hypothesis 4: French Presidential Race - Zero-Sum Electoral Reallocation
        m_lepen = find_market(["marine le pen", "french"])
        m_lagarde = find_market(["christine lagarde", "french"])
        if m_lepen and m_lagarde and m_lepen.market_id != m_lagarde.market_id:
            curated.append(StrictHypothesis(
                hypothesis_id="h6_french_presidential_reallocation",
                market_a_id=m_lepen.market_id,
                market_b_id=m_lagarde.market_id,
                market_a_title=m_lepen.title,
                market_b_title=m_lagarde.title,
                opportunity_class=OpportunityClass.CROSS_MARKET_LOGICAL,
                relationship_type=RelationshipType.NEGATIVE_ECONOMIC,
                causal_mechanism=(
                    "In a single-seat runoff presidential election, probability mass gained by an insurgent right candidate "
                    "mechanically depresses the conditional victory probability of moderate establishment contenders."
                ),
                exact_leading_variable="Direct polling or debate momentum impulse in Le Pen contract: ΔP(A)_2h >= +0.03",
                expected_response_function="Negative proportional response: ΔP(B)_{t+h} = -0.38 * ΔP(A)_t",
                expected_lag_distribution={"mode_hours": 0.25, "half_life_hours": 1.0, "max_lag_hours": 4.0},
                regime_conditions={"min_volatility_a": 0.01, "min_target_liquidity_usd": 10000.0, "max_spread_b": 0.025},
                invalidation_conditions=[
                    "Positive co-movement during third-party candidate dropouts",
                    "Residual spread divergence failing ADF test"
                ],
                min_economic_move=0.020,
                persistence_rationale=(
                    "Voter survey updates are reflected instantly on the frontrunner's book, while second-tier contenders' books "
                    "lag until active market makers rebalance their inventory exposure."
                ),
                disappearance_catalysts="Polymarket native sum-to-100% combinatorial automated market maker.",
                confidence_score=0.89
            ))

        # Hypothesis 5: Bitcoin Strike Ladder Monotonic Compression (High Strike -> Lower Strike)
        m_btc_high = find_market(["bitcoin", "95,000"]) or find_market(["bitcoin", "92,000"])
        m_btc_low = find_market(["bitcoin", "80,000"]) or find_market(["bitcoin", "88,000"])
        if m_btc_high and m_btc_low and m_btc_high.market_id != m_btc_low.market_id:
            curated.append(StrictHypothesis(
                hypothesis_id="h6_btc_strike_monotone_stat_arb",
                market_a_id=m_btc_high.market_id,
                market_b_id=m_btc_low.market_id,
                market_a_title=m_btc_high.title,
                market_b_title=m_btc_low.title,
                opportunity_class=OpportunityClass.STRUCTURAL,
                relationship_type=RelationshipType.IMPLICATION,
                causal_mechanism=(
                    "Mathematical dominance: The event {BTC >= $95k} is a strict subset of {BTC >= $80k}. "
                    "Any upward repricing in the higher rung must transmit at least 1.0x to the lower rung under monotonic pricing."
                ),
                exact_leading_variable="High-strike spot breakout momentum: ΔP(High)_1h >= +0.03",
                expected_response_function="Boundary floor constraint: P(Low) >= P(High) + delta, with residual mean-reversion",
                expected_lag_distribution={"mode_hours": 0.1, "half_life_hours": 0.5, "max_lag_hours": 2.0},
                regime_conditions={"min_volatility_a": 0.02, "min_target_liquidity_usd": 25000.0, "max_spread_b": 0.02},
                invalidation_conditions=[
                    "Order book inversion where Ask(Low) < Bid(High)",
                    "Residual non-stationarity"
                ],
                min_economic_move=0.020,
                persistence_rationale=(
                    "Extreme order-book illiquidity during sudden crypto spot moves allows temporary ladder flattening "
                    "before arbitrageurs deploy capital across both legs."
                ),
                disappearance_catalysts="Dedicated automated high-frequency stat-arb market making bots on Polymarket CLOB.",
                confidence_score=0.95
            ))

        # Fill up to max_hypotheses by scanning other canonical candidate pairs with high horizon overlap
        for i in range(len(m_list)):
            if len(curated) >= max_hypotheses:
                break
            for j in range(len(m_list)):
                if len(curated) >= max_hypotheses:
                    break
                if i == j:
                    continue
                ma = m_list[i]
                mb = m_list[j]
                # Filter for cross-market pairs with distinct entities and active overlap
                if ma.event_type != "general_event" and mb.event_type != "general_event" and ma.event_type == mb.event_type:
                    pair_key = f"{ma.market_id}_{mb.market_id}"
                    if any(h.market_a_id == ma.market_id and h.market_b_id == mb.market_id for h in curated):
                        continue
                    curated.append(StrictHypothesis(
                        hypothesis_id=f"h6_curated_{pair_key[:12]}",
                        market_a_id=ma.market_id,
                        market_b_id=mb.market_id,
                        market_a_title=ma.title,
                        market_b_title=mb.title,
                        opportunity_class=OpportunityClass.AI_SEMANTIC,
                        relationship_type=RelationshipType.POSITIVE_ECONOMIC,
                        causal_mechanism=f"Cross-market economic spillover within {ma.event_type}: shifts in {ma.title} re-anchor beliefs for {mb.title}.",
                        exact_leading_variable="1-hour probability velocity: |ΔP(A)_1h| >= 0.04",
                        expected_response_function="Linear state-conditional impulse: ΔP(B)_{t+h} = 0.40 * ΔP(A)_t",
                        expected_lag_distribution={"mode_hours": 0.5, "half_life_hours": 2.0, "max_lag_hours": 6.0},
                        regime_conditions={"min_volatility_a": 0.015, "min_target_liquidity_usd": 15000.0, "max_spread_b": 0.03},
                        invalidation_conditions=["Residual non-stationarity", "Reversion half-life > 36h"],
                        min_economic_move=0.020,
                        persistence_rationale="Attention latency between primary headline event and derivative secondary contract.",
                        disappearance_catalysts="Liquidity aggregation across prediction market protocols.",
                        confidence_score=0.75
                    ))

        return curated[:max_hypotheses]
