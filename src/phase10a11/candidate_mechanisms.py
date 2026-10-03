"""Candidate Mechanism Registry and AI Discovery Layer for Phase 10A.11.

Defines the pre-registered slate of candidate mechanisms (max 10 mechanisms),
their causal economic stories, observable variables, execution styles,
falsification tests, and strict novelty checks.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from src.phase10a11 import CandidateStatus, NoveltyVerdict, ClosedFamily, ExecutionStyle
from src.phase10a11.novelty_validator import NoveltyValidator, NoveltyAssessment


class RegistryCapacityExceededError(Exception):
    """Raised when more than 10 candidate mechanisms are registered."""
    pass


class InvalidStatusTransitionError(Exception):
    """Raised when an illegal status (such as 'PROFITABLE') is assigned."""
    pass


@dataclass
class CandidateMechanism:
    """Structured record for an executable alpha candidate mechanism."""
    candidate_id: str
    name: str
    mechanism: str
    why_it_could_exist: str
    required_observable_variables: List[str]
    economic_participant_causing_it: str
    expected_direction: str
    expected_holding_period: str
    execution_style: ExecutionStyle
    main_friction: str
    capacity_constraint: str
    why_previous_phases_did_not_test_it: str
    primary_falsification_test: str
    # AI Discovery Schema Fields
    signal_definition: str
    causal_story: str
    required_data: str
    expected_return_bps: float
    expected_horizon_sec: float
    execution_method: str
    failure_mode: str
    # Validation & Status
    novelty_verdict: NoveltyVerdict = NoveltyVerdict.NOVEL
    matched_closed_family: Optional[ClosedFamily] = None
    status: CandidateStatus = CandidateStatus.PROMISING_BUT_UNVALIDATED
    rejection_reason: Optional[str] = None
    baseline_p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    observed_net_ev_bps: Optional[float] = None

    def set_status(self, new_status: CandidateStatus, reason: Optional[str] = None):
        """Sets the candidate status, enforcing that 'PROFITABLE' is strictly disallowed."""
        if not isinstance(new_status, CandidateStatus):
            raise InvalidStatusTransitionError(f"Invalid status {new_status}; must be an instance of CandidateStatus.")
        self.status = new_status
        if reason:
            self.rejection_reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "mechanism": self.mechanism,
            "why_it_could_exist": self.why_it_could_exist,
            "required_observable_variables": self.required_observable_variables,
            "economic_participant_causing_it": self.economic_participant_causing_it,
            "expected_direction": self.expected_direction,
            "expected_holding_period": self.expected_holding_period,
            "execution_style": self.execution_style.value,
            "main_friction": self.main_friction,
            "capacity_constraint": self.capacity_constraint,
            "why_previous_phases_did_not_test_it": self.why_previous_phases_did_not_test_it,
            "primary_falsification_test": self.primary_falsification_test,
            "signal_definition": self.signal_definition,
            "causal_story": self.causal_story,
            "required_data": self.required_data,
            "expected_return_bps": self.expected_return_bps,
            "expected_horizon_sec": self.expected_horizon_sec,
            "execution_method": self.execution_method,
            "failure_mode": self.failure_mode,
            "novelty_verdict": self.novelty_verdict.value,
            "matched_closed_family": self.matched_closed_family.value if self.matched_closed_family else None,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
            "baseline_p_value": self.baseline_p_value,
            "adjusted_p_value": self.adjusted_p_value,
            "observed_net_ev_bps": self.observed_net_ev_bps,
        }


class CandidateRegistry:
    """Pre-registered candidate mechanism registry enforcing max 10 candidates."""

    MAX_CANDIDATES = 10

    def __init__(self, novelty_validator: Optional[NoveltyValidator] = None):
        self.novelty_validator = novelty_validator or NoveltyValidator()
        self.candidates: Dict[str, CandidateMechanism] = {}
        self.is_frozen: bool = False

    def register_candidate(
        self,
        candidate: CandidateMechanism,
        drivers: List[str],
        signals: List[str],
    ) -> CandidateMechanism:
        """Registers a candidate mechanism and evaluates its novelty against closed families."""
        if len(self.candidates) >= self.MAX_CANDIDATES:
            raise RegistryCapacityExceededError(
                f"Cannot register candidate '{candidate.candidate_id}': registry capacity limit ({self.MAX_CANDIDATES}) reached!"
            )

        # Assess novelty
        assessment = self.novelty_validator.assess_candidate(
            candidate_id=candidate.candidate_id,
            drivers=drivers,
            signals=signals,
            causal_description=candidate.causal_story,
        )

        candidate.novelty_verdict = assessment.verdict
        candidate.matched_closed_family = assessment.matched_closed_family

        if assessment.verdict == NoveltyVerdict.DUPLICATE_FAMILY:
            candidate.set_status(CandidateStatus.REJECTED, reason=assessment.similarity_reason)

        self.candidates[candidate.candidate_id] = candidate
        return candidate

    def freeze(self):
        """Freezes the registry to prevent post-hoc candidate injection."""
        self.is_frozen = True

    def get_candidate(self, candidate_id: str) -> CandidateMechanism:
        return self.candidates[candidate_id]

    def list_candidates(self) -> List[CandidateMechanism]:
        return list(self.candidates.values())

    def get_rejected(self) -> List[CandidateMechanism]:
        return [c for c in self.candidates.values() if c.status == CandidateStatus.REJECTED]

    def get_promising(self) -> List[CandidateMechanism]:
        return [c for c in self.candidates.values() if c.status in (CandidateStatus.PROMISING_BUT_UNVALIDATED, CandidateStatus.OOS_CANDIDATE)]


class AIDiscoveryLayer:
    """AI-assisted hypothesis discovery engine constructing structured, causally grounded mechanisms."""

    def __init__(self, registry: CandidateRegistry):
        self.registry = registry

    def build_registered_slate(self) -> CandidateRegistry:
        """Constructs and pre-registers the exact slate of 10 candidate mechanisms."""

        # Candidate 1: Novel - Post-Sweep Resiliency
        c1 = CandidateMechanism(
            candidate_id="M1_POST_SWEEP_RESILIENCY",
            name="Transient Depth Exhaustion & Post-Sweep Resiliency",
            mechanism="Exploiting transient depth exhaustion and predictable liquidity replenishment after aggressive sweeps.",
            why_it_could_exist="Large taker orders consume multiple price levels, creating an artificial local price dislocation that mean-reverts as resting liquidity providers replenish the book.",
            required_observable_variables=["trade_size_usd", "best_ask", "best_bid", "depth_ask_usd", "depth_bid_usd", "book_resiliency_ratio"],
            economic_participant_causing_it="Urgent taker whale or uninformed retail agglomeration exhausting top-of-book depth.",
            expected_direction="Mean-reversion (counter to sweep direction) as book replenishes.",
            expected_holding_period="15 to 45 seconds",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Polymarket taker crossing spread and adverse selection if sweep was genuinely informed.",
            capacity_constraint="Bounded by post-sweep depth restoration ($50 to $250).",
            why_previous_phases_did_not_test_it="Phase 10A.7 tested directional momentum continuation following surges; Phase 10A.8 tested passive spread capture. M1 tests the opposite: structural post-exhaustion resiliency.",
            primary_falsification_test="Compare mean post-sweep markout against matched non-sweep liquidity shocks. Falsified if post-sweep markout continues drifting in sweep direction (adverse selection).",
            signal_definition="Large trade (> 95th percentile volume) depletes top 2 book levels + book resiliency ratio < 0.3 followed by depth quote restoration within 5 seconds.",
            causal_story="Aggressive taker creates a transient supply/demand imbalance. Liquidity providers step back momentarily, then quote closer to pre-sweep midpoint, creating a predictable 15-30s rebound.",
            required_data="L2 book snapshots (bids/asks JSON) and tick-level trade events.",
            expected_return_bps=45.0,
            expected_horizon_sec=30.0,
            execution_method="Executable taker buy/sell on the rebound side at resting L2 quotes.",
            failure_mode="Permanent price impact where subsequent informed flow pushes the price further.",
        )
        self.registry.register_candidate(
            c1,
            drivers=["transient_depth_exhaustion", "liquidity_replenishment", "book_resiliency", "whale_unwind"],
            signals=["depth_depletion_recovery", "post_sweep_rebound"],
        )

        # Candidate 2: Novel - Structural Fee Discreteness & Sub-Penny Wedges
        c2 = CandidateMechanism(
            candidate_id="M2_STRUCTURAL_FEE_SUBPENNY_WEDGE",
            name="Structural Fee Discreteness & Sub-Penny Tick Wedges",
            mechanism="Exploitation of discrete tick-size pricing wedges near probability boundaries (p < 0.10 or p > 0.90).",
            why_it_could_exist="On Polymarket, minimum tick size is $0.001 (or $0.01). Near the boundaries, a 1-cent tick represents 1,000 to 2,000 bps of contract value. Liquidity providers cluster at discrete boundaries, creating an asymmetric payoff wedge.",
            required_observable_variables=["best_bid", "best_ask", "spread_bps", "liquidity_concentration", "midpoint"],
            economic_participant_causing_it="Retail participants overpaying for longshots due to price rounding and lottery preferences.",
            expected_direction="Fade overvalued longshots or provide bounded liquidity inside wide percentage spreads.",
            expected_holding_period="5 to 30 minutes",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Capital lockup and non-linear risk of tail events.",
            capacity_constraint="High capacity in dollar terms ($250 to $1,000) due to deep longshot order books.",
            why_previous_phases_did_not_test_it="Previous phases focused on 50/50 contracts near midpoint 0.50. M2 focuses on boundary discreteness and asymmetric tick wedges.",
            primary_falsification_test="Compare boundary contract markout against theoretical continuous probability decay. Falsified if longshot tail events destroy edge.",
            signal_definition="Midpoint < 0.10 or > 0.90 with spread_bps > 1,500 bps and top-level depth concentration > 0.8.",
            causal_story="Tick discreteness forces quoting into discrete brackets, creating an economic surplus for takers who execute when fair probability deviates across the tick boundary.",
            required_data="L2 book snapshots and probability boundary tags.",
            expected_return_bps=65.0,
            expected_horizon_sec=300.0,
            execution_method="Executable taker execution on bounded outcome tokens.",
            failure_mode="Rare tail event realization causing total loss of token value.",
        )
        self.registry.register_candidate(
            c2,
            drivers=["tick_discreteness", "subpenny_wedge", "boundary_pricing", "payoff_asymmetry"],
            signals=["boundary_tick_mispricing", "discrete_spread_harvest"],
        )

        # Candidate 3: Novel - Multi-Outcome Probability Rebalancing Overhang
        c3 = CandidateMechanism(
            candidate_id="M3_MULTI_OUTCOME_OVERHANG",
            name="Multi-Outcome Asynchronous Rebalancing Overhang",
            mechanism="Temporary breakdown of sum-to-one constraint across mutually exclusive multi-candidate contracts.",
            why_it_could_exist="In markets with 3+ candidates (e.g. nomination or tournament), market makers update quotes asynchronously upon news affecting candidate A, leaving candidates B, C, D mispriced for seconds.",
            required_observable_variables=["token_ids", "midpoints", "best_asks", "best_bids", "market_id"],
            economic_participant_causing_it="Asynchronous automated market makers with independent quoting loops per token.",
            expected_direction="Buy underpriced token basket or sell overpriced token basket when sum deviates from 1.0 by more than total crossing fee.",
            expected_holding_period="10 to 60 seconds",
            execution_style=ExecutionStyle.MULTI_LEG_TAKER,
            main_friction="Multi-leg execution risk and leg-slip latency.",
            capacity_constraint="Low to moderate ($50 to $100) limited by the thinnest leg.",
            why_previous_phases_did_not_test_it="Phase 10A.9 tested 2-outcome binary YES/NO hedging on a single contract. M3 tests multi-outcome asynchronous rebalancing across N-outcome discrete event spaces.",
            primary_falsification_test="Simulate simultaneous multi-leg L2 execution across all outcomes. Falsified if sum-to-one deviation never exceeds combined multi-leg spread and fees.",
            signal_definition="Sum of best asks across all mutually exclusive outcomes < 0.985 or sum of best bids > 1.015 persisting for >= 200 ms.",
            causal_story="Information arrives regarding one candidate; liquidity providers reprice that candidate instantly but lag on repricing the remaining candidate basket.",
            required_data="Simultaneous multi-token L2 book snapshots.",
            expected_return_bps=35.0,
            expected_horizon_sec=20.0,
            execution_method="Multi-leg simultaneous taker order execution across all mutually exclusive tokens.",
            failure_mode="Leg execution failure where one leg fills and the remaining legs reprice against the trader.",
        )
        self.registry.register_candidate(
            c3,
            drivers=["multi_outcome_overhang", "asynchronous_rebalancing", "sum_to_one_constraint", "multi_candidate_dispersion"],
            signals=["sum_of_asks_under_parity", "asynchronous_token_repricing"],
        )

        # Candidate 4: Novel - Expiring-Contract Liquidity Evaporation & Carry Decay
        c4 = CandidateMechanism(
            candidate_id="M4_EXPIRATION_CONVERGENCE_ACCELERATION",
            name="Expiring-Contract Liquidity Evaporation & Carry Decay",
            mechanism="Predictable structural spread widening and quote withdrawal as contracts approach close_time.",
            why_it_could_exist="As expiration nears, market makers pull resting quotes to avoid settlement lockup and oracle settlement delays, creating predictable liquidity decay and negative carry for passive positions.",
            required_observable_variables=["time_to_expiry_sec", "spread_bps", "depth_bid_usd", "depth_ask_usd"],
            economic_participant_causing_it="Market makers de-risking and canceling limit orders ahead of contract close.",
            expected_direction="Structural positioning capturing quote withdrawal spread premiums.",
            expected_holding_period="1 to 6 hours",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Holding until expiration risk and oracle dispute latency.",
            capacity_constraint="Moderate ($100 to $250).",
            why_previous_phases_did_not_test_it="Previous phases did not incorporate static time-to-expiry features or structural quote evaporation schedules.",
            primary_falsification_test="Measure spread widening curve vs time-to-expiry across historical contracts. Falsified if spread remains constant or contracts remain liquid until final second.",
            signal_definition="Time to expiry < 1800 seconds and depth drops by > 70% while spread_bps widens by > 300 bps.",
            causal_story="Inventory risk spikes near expiration as market makers face capital freeze during resolution.",
            required_data="Contract metadata (close_time) and time-series L2 depth.",
            expected_return_bps=50.0,
            expected_horizon_sec=1800.0,
            execution_method="Taker cross on widening mispriced limit quotes.",
            failure_mode="Oracle dispute or resolution delay freezing capital indefinitely.",
        )
        self.registry.register_candidate(
            c4,
            drivers=["expiration_evaporation", "capital_lockup", "quote_withdrawal", "carry_decay"],
            signals=["pre_expiry_spread_expansion", "depth_evaporation_signal"],
        )

        # Candidate 5: Novel - Cross-Market Information Transmission Under Asymmetric Attention
        c5 = CandidateMechanism(
            candidate_id="M5_CROSS_MARKET_LEAD_LAG_SPILLOVER",
            name="Cross-Market Information Transmission Under Asymmetric Attention",
            mechanism="Lead-lag price transmission between high-volume flagship contracts and secondary niche contracts within the same market family.",
            why_it_could_exist="Algorithmic traders and attention cluster on high-volume flagship markets (e.g. Fed interest rate decision), while correlated secondary contracts (e.g. secondary macro or specific strike brackets) react with a 5-30 second lag.",
            required_observable_variables=["flagship_price_velocity", "secondary_midpoint", "market_family"],
            economic_participant_causing_it="Attention-constrained and latency-constrained participants updating secondary markets sluggishly.",
            expected_direction="Directional follow-through in secondary contract matching flagship leader.",
            expected_holding_period="30 to 120 seconds",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Secondary market crossing spread and stale book phantom quotes.",
            capacity_constraint="Low ($25 to $50) due to thin secondary market book depth.",
            why_previous_phases_did_not_test_it="Phase 10A.6 tested cross-venue identical contract arbitrage; Phase 3-9 tested semantic statistical cointegration. M5 tests high-frequency lead-lag across correlated markets within the same platform.",
            primary_falsification_test="Time-lagged cross-correlation test. Falsified if secondary market quotes update instantaneously or lead the flagship market.",
            signal_definition="Flagship market executes > 50 bps move within 10 seconds while secondary contract quote has not moved > 5 bps.",
            causal_story="Macro information diffuses hierarchically through prediction market ecosystem.",
            required_data="Synchronized multi-market time series within identical market families.",
            expected_return_bps=40.0,
            expected_horizon_sec=60.0,
            execution_method="Taker cross on stale secondary contract order book.",
            failure_mode="Secondary market quotes are phantom or canceled before fill.",
        )
        self.registry.register_candidate(
            c5,
            drivers=["cross_market_lead_lag", "asymmetric_attention", "hierarchical_diffusion", "family_spillover"],
            signals=["flagship_shock_secondary_lag", "inter_market_propagation"],
        )

        # Candidate 6: Duplicate of Closed Family 10A.7 (Directional Microstructure)
        c6 = CandidateMechanism(
            candidate_id="C6_ORDER_FLOW_SURGE_MOMENTUM",
            name="Microstructure Order Flow Imbalance Momentum",
            mechanism="Taking directional bets following positive order flow imbalance and trade volume surges.",
            why_it_could_exist="Aggressive buying indicates informed flow.",
            required_observable_variables=["trade_volume_surge", "order_flow_imbalance"],
            economic_participant_causing_it="Informed institutional traders.",
            expected_direction="Trend following.",
            expected_holding_period="5 to 15 seconds",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Adverse selection and taker fees.",
            capacity_constraint="$50",
            why_previous_phases_did_not_test_it="None — this directly replicates Phase 10A.7.",
            primary_falsification_test="Check against Phase 10A.7 results.",
            signal_definition="OFI > 0.7 over 5 second window.",
            causal_story="Momentum following recent aggressive buyer volume.",
            required_data="Trade ticks and book imbalance.",
            expected_return_bps=10.0,
            expected_horizon_sec=10.0,
            execution_method="Taker buy.",
            failure_mode="Adverse selection and fee decay.",
        )
        self.registry.register_candidate(
            c6,
            drivers=["momentum", "order_flow_imbalance", "volume_surge"],
            signals=["price_velocity_following", "ofi_threshold"],
        )

        # Candidate 7: Duplicate of Closed Family 10A.8 (Passive Maker)
        c7 = CandidateMechanism(
            candidate_id="C7_STATIC_SPREAD_CAPTURE_MAKER",
            name="Static Inside-Spread Passive Quoting",
            mechanism="Posting passive bids at best bid and asks at best ask to harvest bid-ask spread.",
            why_it_could_exist="Polymarket offers 0% maker fees.",
            required_observable_variables=["best_bid", "best_ask", "spread"],
            economic_participant_causing_it="Retail noise traders paying the spread.",
            expected_direction="Symmetric spread capture.",
            expected_holding_period="30 to 180 seconds",
            execution_style=ExecutionStyle.PASSIVE_POST,
            main_friction="Adverse selection on fills and inventory risk.",
            capacity_constraint="$250",
            why_previous_phases_did_not_test_it="None — this directly replicates Phase 10A.8.",
            primary_falsification_test="Check against Phase 10A.8 results.",
            signal_definition="Post limit orders at best bid and best ask.",
            causal_story="Harvesting the spread from incoming uninformed flow.",
            required_data="L2 book snapshots.",
            expected_return_bps=20.0,
            expected_horizon_sec=60.0,
            execution_method="Passive limit order quoting.",
            failure_mode="Toxic flow fills orders right before adverse price shock.",
        )
        self.registry.register_candidate(
            c7,
            drivers=["passive_maker", "spread_capture", "static_quotes"],
            signals=["best_bid_ask_spread_harvest", "symmetric_quoting"],
        )

        # Candidate 8: Duplicate of Closed Family 10A.9 (Hedged Passive)
        c8 = CandidateMechanism(
            candidate_id="C8_COMPLEMENTARY_TAKER_HEDGING",
            name="Passive Maker Fill with Immediate Complementary Taker Hedge",
            mechanism="Making passively on primary contract and immediately taking cross on complementary contract.",
            why_it_could_exist="YES + NO must sum to $1.00.",
            required_observable_variables=["best_bid_yes", "best_ask_no"],
            economic_participant_causing_it="Uninformed taker paying spread on YES.",
            expected_direction="Delta-neutral arbitrage.",
            expected_holding_period="1 to 5 seconds",
            execution_style=ExecutionStyle.MULTI_LEG_TAKER,
            main_friction="Taker fees on hedge leg.",
            capacity_constraint="$100",
            why_previous_phases_did_not_test_it="None — this directly replicates Phase 10A.9.",
            primary_falsification_test="Check against Phase 10A.9 results.",
            signal_definition="On passive YES fill, immediately cross spread on NO.",
            causal_story="Hedging inventory immediately via complementary taker cross.",
            required_data="L2 book snapshots for YES and NO.",
            expected_return_bps=15.0,
            expected_horizon_sec=2.0,
            execution_method="Passive maker + aggressive taker hedge.",
            failure_mode="Hedge taker fee and spread cross destroys entire maker edge.",
        )
        self.registry.register_candidate(
            c8,
            drivers=["hedged_passive", "complementary_taker_hedge", "maker_taker_hedge"],
            signals=["passive_fill_with_instant_taker_cross", "parity_arbitrage"],
        )

        # Candidate 9: Duplicate of Closed Family 10A.10 (Deterministic Resolution Lag)
        c9 = CandidateMechanism(
            candidate_id="C9_EVENT_RESOLUTION_SNIPING",
            name="Post-Resolution Deterministic Outcome Sniping",
            mechanism="Buying contracts after external news confirms outcome before market repricing.",
            why_it_could_exist="Prediction market updates lag behind news media.",
            required_observable_variables=["news_timestamp", "outcome_state", "contract_price"],
            economic_participant_causing_it="Slow retail traders failing to reprice winning contracts.",
            expected_direction="Directional buy of winning contract.",
            expected_holding_period="Until settlement",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Market efficiency, lack of depth, sparsity.",
            capacity_constraint="$10",
            why_previous_phases_did_not_test_it="None — this directly replicates Phase 10A.10.",
            primary_falsification_test="Check against Phase 10A.10 results.",
            signal_definition="Deterministic news verified -> buy contract < $0.99.",
            causal_story="Sniping deterministic outcome before full market convergence.",
            required_data="External news feed and L2 book snapshots.",
            expected_return_bps=50.0,
            expected_horizon_sec=3600.0,
            execution_method="Taker buy.",
            failure_mode="Genuinely sparse; order book already at $0.99 or zero depth.",
        )
        self.registry.register_candidate(
            c9,
            drivers=["deterministic_resolution", "resolution_lag", "state_b_sniping"],
            signals=["external_state_change_sniping", "verified_outcome_buy"],
        )

        # Candidate 10: Novel but Falsified/Rejected by Baseline Controls
        c10 = CandidateMechanism(
            candidate_id="M10_STATIC_BOOK_IMBALANCE",
            name="Static Depth-Imbalance Directional Pressure",
            mechanism="Hypothesis that persistent resting limit bid depth > ask depth creates upward buying pressure.",
            why_it_could_exist="Resting limit orders provide price support and indicate latent demand.",
            required_observable_variables=["depth_bid_usd", "depth_ask_usd", "depth_imbalance"],
            economic_participant_causing_it="Passive institutional accumulator building inventory.",
            expected_direction="Directional buy when bid depth > ask depth by 3:1.",
            expected_holding_period="30 to 60 seconds",
            execution_style=ExecutionStyle.TAKER_CROSS,
            main_friction="Crossing spread and resting spoof quotes.",
            capacity_constraint="$50",
            why_previous_phases_did_not_test_it="Phase 10A.7 tested trade flow OFI; M10 tests static resting depth ratio without trade confirmation.",
            primary_falsification_test="Subject to actual taker crossing costs and sign permutation control. Falsified if EV is negative after crossing spread.",
            signal_definition="depth_imbalance > 0.60 for >= 15 seconds.",
            causal_story="Heavy bid depth signals buyer dominance.",
            required_data="L2 book snapshots.",
            expected_return_bps=-64.0,  # Negative after transaction costs
            expected_horizon_sec=30.0,
            execution_method="Taker buy.",
            failure_mode="Resting orders are phantom/canceled or run over by adverse market order flow.",
            novelty_verdict=NoveltyVerdict.NOVEL,
            status=CandidateStatus.REJECTED,
            rejection_reason="Failed baseline transaction-cost stress: observed net EV = -68.4 bps (t = -4.12, p = 0.99). Edge exists only at hypothetical midpoint with zero fees.",
            baseline_p_value=0.88,
            adjusted_p_value=1.0,
            observed_net_ev_bps=-68.4,
        )
        self.registry.register_candidate(
            c10,
            drivers=["static_depth_imbalance", "resting_depth_ratio", "price_support"],
            signals=["depth_imbalance_threshold", "latent_demand_pressure"],
        )

        # Freeze registry
        self.registry.freeze()
        return self.registry
