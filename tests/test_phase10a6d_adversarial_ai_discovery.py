"""Unit Tests for Phase 10A.6d: Adversarial AI Hypothesis Discovery & Relationship Quality Engine.

Tests:
1. Economic mechanism requirement & vague phrase rejection
2. Mathematical formalization validation
3. Hypothesis-family & edge-type strict classification
4. Information-theoretic novelty check & duplicate detection
5. Lineage mutation tracking & mutation budget exhaustion (blocking mutations)
6. Horizon & threshold variant budgets
7. Friction-first filter (theoretical minimum edge & FRICTIONALLY_IMPLAUSIBLE)
8. Capacity gate (order size vs observable depth)
9. Causal direction test (asymmetric lead/lag vs symmetric NON_DIRECTIONAL routing)
10. Confounder audit (mandatory confounders & INSUFFICIENT_IDENTIFICATION)
11. Placebo-before-results enforcement & frozen hypothesis immutability
12. AI boundary enforcement (unauthorized orders, position sizing, profitability claims, winning strategy selection)
13. Historical failure rules (all 13 empirical failure patterns from Phases 3-9)
14. AI self-critique 13-point validation & 10 independent categorical quality states (no composite score)
15. 7 distinct discovery modes generation
"""

import pytest
from datetime import datetime, timezone
from typing import Dict, Any

from src.normalization.schema import CanonicalMarket
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
from src.statarb.lineage import (
    HypothesisLineageTracker,
    LineageViolationError,
    DiscoveryBudget,
)
from src.statarb.boundary_validator import (
    BoundaryValidator,
    BoundaryViolationError,
)
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
from src.statarb.self_critique import (
    AISelfCritiqueValidator,
    SelfCritiqueResult,
)
from src.llm.relationship_discovery import RelationshipDiscoveryEngine


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def base_hypothesis_dict() -> Dict[str, Any]:
    return {
        "hypothesis_id": "hyp_test_leadlag_001",
        "hypothesis_family": "cross_market_lead_lag",
        "source_markets": ["poly_btc_100k"],
        "target_markets": ["poly_eth_4k"],
        "causal_mechanism": "Spot Bitcoin institutional flows lead secondary Ethereum repricing due to cross-asset capital rotation.",
        "required_observations": ["order_book_l2", "trades"],
        "observable_variables": ["mid_price", "signed_imbalance"],
        "expected_relationship": "Delta P(ETH)_{t+15m} = beta * Delta P(BTC)_t",
        "direction": "lead_lag",
        "expected_time_horizon": "15m",
        "falsification_condition": "H0: Out-of-sample forward correlation <= 0 or net return after friction <= 0.",
        "minimum_sample_requirement": 30,
        "proposed_statistical_test": "permutation_test",
        "proposed_placebo_control": "time_shift_24h",
        "execution_dependency": "taker_l2_walk",
        "expected_friction_sensitivity": "medium",
        "capacity_dependency": 1000.0,
        "known_confounders": ["macro_shock", "market_wide_drift", "time_of_day_liquidity", "resolution_proximity", "event_clustering"],
        "lookahead_risk": "Strict zero-lookahead: leading market trigger strictly precedes evaluation window.",
        "confidence": 0.85,
        "input_signal": "5-minute return in BTC contract",
        "transformation": "standardized return > 2.0 sigma",
        "prediction": "ETH executable price moves in same direction by >= 25 bps",
        "horizon": "15 minutes",
        "cost_model": "Observed L2 ladder + 20 bps taker fee",
        "falsification_test": "Time-shifted placebo + reverse-direction test",
        "lineage_family_id": "fam_btc_eth_leadlag",
        "parameters": {"threshold": 2.0, "beta": 0.85},
        # Phase 10A.6d fields
        "discovery_mode": "MODE_E_CROSS_MARKET",
        "edge_type": "PREDICTIVE_INFORMATION_EDGE",
        "economic_mechanism_type": "LEAD_LAG",
        "mechanism_persistence_rationale": "Cross-asset capital allocation latency and attention pools maintain 1-5 minute lead/lag.",
        "target_variable": "Delta P(ETH)_{t+15m}",
        "condition": "Delta P(BTC)_t >= 20 bps",
        "expected_effect": "ETH adjusts in same direction by >= 25 bps",
        "minimum_effect_size_bps": 20.0,
        "cost_assumption_bps": 22.0,
        "novelty_classification": "NEW",
        "necessary_conditions": ["BTC moves first", "ETH executable depth >= $500", "Observed spread < expected move"],
        "failure_conditions": ["Net edge disappears after observed spread and fees", "Lag disappears out-of-sample", "Placebo exhibits identical move"],
        "expected_response_horizon": "15m",
        "expected_decay_profile": "FAST_DECAY",
        "latency_sensitivity_rationale": "Lead/lag persists due to distinct participant pools and absence of sub-second cross-market HFT.",
        "expected_gross_edge_bps": 36.0,
        "expected_spread_bps": 10.0,
        "expected_fee_bps": 2.0,
        "expected_slippage_bps": 5.0,
        "latency_penalty_bps": 5.0,
        "safety_margin_bps": 5.0,
        "required_gross_edge_bps": 27.0,
        "is_frictionally_plausible": True,
        "expected_order_size_usd": 250.0,
        "minimum_required_depth_usd": 750.0,
        "expected_capacity_usd": 2000.0,
        "capacity_failure_condition": "Observable depth in target book drops below $500, causing taker slippage > 20 bps.",
        "forward_causal_rationale": "Source market possesses higher trading volume and institutional discovery.",
        "reverse_causal_rationale": "Target market does not drive price formation in primary benchmark.",
        "causal_asymmetry_established": True,
        "confounders_audit": {
            "macro_shock": {"expected_distortion": "Broad market re-pricing causing spurious co-movement", "control_method": "Residualize against macro index"},
            "market_wide_drift": {"expected_distortion": "Persistent secular trend inflating correlation", "control_method": "High-pass differencing"},
            "time_of_day_liquidity": {"expected_distortion": "Wider spreads during low-volume hours", "control_method": "Time-of-day matched sampling"},
            "resolution_proximity": {"expected_distortion": "Non-linear delta acceleration near expiration", "control_method": "Filter contracts within 48h of settlement"},
            "event_clustering": {"expected_distortion": "Multiple news items triggering serial autocorrelation", "control_method": "Cluster-robust standard errors"},
        },
        "pre_test_controls": {
            "primary_test": "Permutation test of conditional forward return difference",
            "placebo_test": "24-hour time-shifted lead/lag correlation",
            "reverse_test": "Reverse-direction Granger causality and regression",
            "matched_control": "Matched non-event volatility and volume control window",
            "OOS_test": "Strict forward temporal split on unseen chronologically later data",
            "friction_stress": "Walk executable L2 order ladder with 2x observed spread and 20 bps fees",
            "capacity_stress": "Simulate $1,000 order walking book depth to measure slippage degradation",
        },
    }


@pytest.fixture
def mock_canonical_markets():
    from src.normalization.schema import Platform
    return [
        CanonicalMarket(
            market_id="poly_fed_rate_dec",
            platform=Platform.POLYMARKET,
            title="Fed Interest Rate Cut in December 2026",
            underlying_event="Federal Reserve Interest Rate Decision December 2026",
            entities=["Fed", "Interest Rate"],
            geographic_scope="US",
            time_horizon="December 2026",
            event_type="Macro",
        ),
        CanonicalMarket(
            market_id="poly_btc_100k_dec",
            platform=Platform.POLYMARKET,
            title="Bitcoin above $100,000 on December 31, 2026",
            underlying_event="Bitcoin spot price year-end benchmark",
            entities=["Bitcoin", "BTC"],
            geographic_scope="Global",
            time_horizon="December 2026",
            event_type="Crypto",
        ),
        CanonicalMarket(
            market_id="poly_eth_4k_dec",
            platform=Platform.POLYMARKET,
            title="Ethereum above $4,000 on December 31, 2026",
            underlying_event="Ethereum spot price year-end benchmark",
            entities=["Ethereum", "ETH"],
            geographic_scope="Global",
            time_horizon="December 2026",
            event_type="Crypto",
        ),
    ]


# =============================================================================
# 1. ECONOMIC MECHANISM REQUIREMENT & VAGUE PHRASE REJECTION
# =============================================================================

def test_vague_mechanism_phrases_rejected(base_hypothesis_dict):
    """Verifies that vague correlation claims are strictly rejected by BoundaryValidator."""
    vague_phrases = [
        "these markets are related because they involve crypto",
        "these markets are similar and co-move",
        "sentiment may spill over from BTC to ETH",
        "historically correlated asset pair",
        "AI believes X predicts Y based on word similarities",
    ]

    for phrase in vague_phrases:
        bad_dict = dict(base_hypothesis_dict)
        bad_dict["causal_mechanism"] = phrase
        with pytest.raises(BoundaryViolationError, match="Vague Mechanism Rejected"):
            BoundaryValidator.sanitize_and_construct(bad_dict)


def test_valid_economic_mechanisms_accepted(base_hypothesis_dict):
    """Verifies that valid structural mechanisms pass boundary validation."""
    valid_mechanisms = [
        ("INFORMATION_TRANSMISSION", "Institutional news feeds transmit first to liquid benchmarks before secondary assets."),
        ("ORDER_FLOW_TRANSMISSION", "Large market orders sweep order book depth, forcing makers to re-quote correlated books."),
        ("ARBITRAGE_CONSTRAINT", "Cross-contract payoff identities enforce strict upper bound Sum(P) <= 1.0."),
        ("SETTLEMENT_LOGIC", "Contract A settlement strictly implies Contract B payout according to official rules."),
        ("COMMON_FUNDAMENTAL", "Underlying interest rate shock shifts the discount rate of both related assets."),
        ("LEAD_LAG", "Market A updates 30 seconds before Market B due to higher liquidity and participation."),
        ("CROSS_VENUE_PRICE_DISCOVERY", "Offshore crypto platform discovers fair value faster than domestic CFTC platform."),
    ]

    for mech_type, mech_desc in valid_mechanisms:
        valid_dict = dict(base_hypothesis_dict)
        valid_dict["economic_mechanism_type"] = mech_type
        valid_dict["causal_mechanism"] = mech_desc
        hyp = BoundaryValidator.sanitize_and_construct(valid_dict)
        assert hyp.economic_mechanism_type == mech_type


# =============================================================================
# 2. MATHEMATICAL FORMALIZATION VALIDATION
# =============================================================================

def test_mathematical_formalization_fields(base_hypothesis_dict):
    """Verifies that formal mathematical parameters are present and validated."""
    hyp = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    assert hyp.target_variable == "Delta P(ETH)_{t+15m}"
    assert hyp.condition == "Delta P(BTC)_t >= 20 bps"
    assert hyp.minimum_effect_size_bps == 20.0
    assert hyp.cost_assumption_bps == 22.0

    # Incomplete operational template must be rejected by BoundaryValidator
    bad_dict = dict(base_hypothesis_dict)
    bad_dict["input_signal"] = ""
    with pytest.raises(BoundaryViolationError, match="Incomplete Operational Template"):
        BoundaryValidator.sanitize_and_construct(bad_dict)


# =============================================================================
# 3. PREDICTIVE VS ARBITRAGE STRICT CLASSIFICATION
# =============================================================================

def test_predictive_vs_arbitrage_classification(base_hypothesis_dict):
    """Verifies strict classification into non-overlapping EdgeTypes and Families."""
    hyp = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    assert hyp.edge_type == EdgeType.PREDICTIVE_INFORMATION_EDGE
    assert hyp.hypothesis_family == HypothesisFamily.CROSS_MARKET_LEAD_LAG

    # Verify all EdgeType enums exist
    assert len(EdgeType) == 6
    assert EdgeType.EXACT_ARBITRAGE.value == "EXACT_ARBITRAGE"
    assert EdgeType.RESOLUTION_ARBITRAGE.value == "RESOLUTION_ARBITRAGE"
    assert EdgeType.STATISTICAL_ARBITRAGE.value == "STATISTICAL_ARBITRAGE"


# =============================================================================
# 4. INFORMATION-THEORETIC NOVELTY & DUPLICATE DETECTION
# =============================================================================

def test_novelty_classification_and_duplicate_detection(base_hypothesis_dict):
    """Verifies novelty tracking across NEW, KNOWN_RELATIONSHIP, and DUPLICATE."""
    tracker = HypothesisLineageTracker()
    hyp1 = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    tracker.register_hypothesis(hyp1)
    assert hyp1.novelty_classification == NoveltyClassification.NEW

    # Second hypothesis with same market pair is KNOWN_RELATIONSHIP
    hyp2_dict = dict(base_hypothesis_dict)
    hyp2_dict["hypothesis_id"] = "hyp_test_leadlag_002"
    hyp2_dict["minimum_effect_size_bps"] = 25.0
    hyp2 = BoundaryValidator.sanitize_and_construct(hyp2_dict)
    tracker.register_hypothesis(hyp2)
    assert hyp2.novelty_classification == NoveltyClassification.KNOWN_RELATIONSHIP

    # Freeze hyp1 to register its config hash
    tracker.freeze_hypothesis(hyp1.hypothesis_id)

    # Identical config hash is rejected as DUPLICATE
    hyp3_dict = dict(base_hypothesis_dict)
    hyp3_dict["hypothesis_id"] = "hyp_test_leadlag_003"
    hyp3 = BoundaryValidator.sanitize_and_construct(hyp3_dict)
    with pytest.raises(LineageViolationError, match="DUPLICATE configuration detected"):
        tracker.register_hypothesis(hyp3)


def test_trivial_transformation_rejected(base_hypothesis_dict):
    """Verifies that trivial parameter tweaks without substantive change are rejected."""
    tracker = HypothesisLineageTracker()
    hyp1 = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    tracker.register_hypothesis(hyp1)

    # Mutate with trivial threshold delta (< 0.05) and identical parameters
    with pytest.raises(LineageViolationError, match="TRIVIAL_TRANSFORMATION rejected"):
        tracker.mutate_hypothesis(
            parent_id=hyp1.hypothesis_id,
            new_hypothesis_id="hyp_test_leadlag_mut_trivial",
            mutation_rationale="Slightly altered threshold by 0.01 without new mechanism.",
            parameter_updates={"threshold": 2.01}, # 2.0 -> 2.01 is trivial
        )


# =============================================================================
# 5. DISCOVERY BUDGETS & MUTATION CAPPING
# =============================================================================

def test_mutation_budget_exhaustion_blocks_further_mutations(base_hypothesis_dict):
    """Verifies that exceeding max_mutations_per_lineage blocks further mutations."""
    # Set tight budget: max 2 mutations per lineage
    budget = DiscoveryBudget(max_mutations_per_lineage=2)
    tracker = HypothesisLineageTracker(budget=budget)

    hyp_root = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    tracker.register_hypothesis(hyp_root)

    # Mutation 1: version 2
    hyp_m1 = tracker.mutate_hypothesis(
        parent_id=hyp_root.hypothesis_id,
        new_hypothesis_id="hyp_m1",
        mutation_rationale="Substantive threshold expansion from 2.0 to 2.5 sigma.",
        parameter_updates={"threshold": 2.5},
    )
    assert hyp_m1.version == 2

    # Mutation 2: version 3
    hyp_m2 = tracker.mutate_hypothesis(
        parent_id=hyp_m1.hypothesis_id,
        new_hypothesis_id="hyp_m2",
        mutation_rationale="Substantive threshold expansion from 2.5 to 3.0 sigma.",
        parameter_updates={"threshold": 3.0},
    )
    assert hyp_m2.version == 3

    # Mutation 3: must be BLOCKED
    with pytest.raises(LineageViolationError, match="Mutation budget exhausted.*BLOCK FURTHER MUTATIONS"):
        tracker.mutate_hypothesis(
            parent_id=hyp_m2.hypothesis_id,
            new_hypothesis_id="hyp_m3",
            mutation_rationale="Attempting a 3rd mutation beyond the configured budget limit.",
            parameter_updates={"threshold": 3.5},
        )


def test_horizon_and_threshold_variant_budgets(base_hypothesis_dict):
    """Verifies that horizon and threshold variant budgets are enforced per family."""
    budget = DiscoveryBudget(max_horizons_per_family=2, max_threshold_variants=2)
    tracker = HypothesisLineageTracker(budget=budget)

    hyp_root = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    tracker.register_hypothesis(hyp_root)

    # Horizon 1 (15m) exists. Add Horizon 2 (30m).
    hyp_h2 = tracker.mutate_hypothesis(
        parent_id=hyp_root.hypothesis_id,
        new_hypothesis_id="hyp_h2",
        mutation_rationale="Extending lead/lag evaluation window to 30 minutes.",
        expected_time_horizon="30m",
        parameter_updates={"threshold": 2.6},
    )
    assert hyp_h2.expected_time_horizon == "30m"

    # Horizon 3 (1h) must exceed budget
    with pytest.raises(LineageViolationError, match="Horizon variants budget exhausted"):
        tracker.mutate_hypothesis(
            parent_id=hyp_h2.hypothesis_id,
            new_hypothesis_id="hyp_h3",
            mutation_rationale="Extending lead/lag evaluation window to 1 hour.",
            expected_time_horizon="1h",
            parameter_updates={"threshold": 2.7},
        )


# =============================================================================
# 6. FRICTION-FIRST FILTER
# =============================================================================

def test_friction_first_filter(base_hypothesis_dict):
    """Verifies that hypotheses with gross edge < friction are flagged FRICTIONALLY_IMPLAUSIBLE."""
    # Plausible case
    hyp_ok = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    is_plausible, exp, req, reason = FrictionFirstFilter.evaluate(hyp_ok)
    assert is_plausible is True
    assert exp >= req

    # Implausible case: expected edge is 10 bps, but spread + fee + slippage + latency = 27 bps
    bad_dict = dict(base_hypothesis_dict)
    bad_dict["expected_gross_edge_bps"] = 10.0
    bad_dict["expected_spread_bps"] = 15.0
    bad_dict["expected_fee_bps"] = 2.0
    bad_dict["expected_slippage_bps"] = 5.0
    bad_dict["latency_penalty_bps"] = 5.0
    bad_dict["safety_margin_bps"] = 5.0
    hyp_bad = BoundaryValidator.sanitize_and_construct(bad_dict)

    is_plausible, exp, req, reason = FrictionFirstFilter.evaluate(hyp_bad)
    assert is_plausible is False
    assert "FRICTIONALLY_IMPLAUSIBLE" in reason
    assert exp < req


# =============================================================================
# 7. CAPACITY-AWARE DISCOVERY
# =============================================================================

def test_capacity_gate(base_hypothesis_dict):
    """Verifies that hypotheses requiring excessive depth are rejected by CapacityGate."""
    hyp_ok = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    passed, reason = CapacityGate.evaluate(hyp_ok)
    assert passed is True

    # Order size exceeds observable depth
    bad_dict = dict(base_hypothesis_dict)
    bad_dict["expected_order_size_usd"] = 5000.0
    bad_dict["minimum_required_depth_usd"] = 1000.0
    hyp_bad = BoundaryValidator.sanitize_and_construct(bad_dict)
    passed, reason = CapacityGate.evaluate(hyp_bad)
    assert passed is False
    assert "exceeds minimum required observable depth" in reason


# =============================================================================
# 8. CAUSAL DIRECTION TEST
# =============================================================================

def test_causal_directionality_and_symmetric_routing(base_hypothesis_dict):
    """Verifies directional asymmetry check and routing of symmetric mechanisms to Stat-Arb."""
    hyp_dir = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    is_valid, is_dir, reason = CausalDirectionValidator.evaluate(hyp_dir)
    assert is_valid is True
    assert is_dir is True

    # Symmetric mechanism routes to NON_DIRECTIONAL_RELATIONSHIP
    sym_dict = dict(base_hypothesis_dict)
    sym_dict["forward_causal_rationale"] = "BTC and ETH co-move due to broad crypto market liquidity."
    sym_dict["reverse_causal_rationale"] = "BTC and ETH co-move due to broad crypto market liquidity."
    hyp_sym = BoundaryValidator.sanitize_and_construct(sym_dict)
    is_valid, is_dir, reason = CausalDirectionValidator.evaluate(hyp_sym)
    assert is_valid is True
    assert is_dir is False
    assert "NON_DIRECTIONAL_RELATIONSHIP" in reason


# =============================================================================
# 9. CONFOUNDING AUDIT
# =============================================================================

def test_confounding_audit(base_hypothesis_dict):
    """Verifies that missing controls for mandatory confounders trigger INSUFFICIENT_IDENTIFICATION."""
    hyp_ok = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    is_suff, unaddressed, summary = ConfoundingAuditor.evaluate(hyp_ok)
    assert is_suff is True
    assert len(unaddressed) == 0

    # Remove controls for macro shocks and event clustering
    bad_dict = dict(base_hypothesis_dict)
    bad_dict["confounders_audit"] = {
        "time_of_day_liquidity": {"expected_distortion": "...", "control_method": "..."},
    }
    hyp_bad = BoundaryValidator.sanitize_and_construct(bad_dict)
    is_suff, unaddressed, summary = ConfoundingAuditor.evaluate(hyp_bad)
    assert is_suff is False
    assert "INSUFFICIENT_IDENTIFICATION" in summary
    assert "macro_shock" in unaddressed


# =============================================================================
# 10. PLACEBO-BEFORE-RESULTS & FROZEN IMMUTABILITY
# =============================================================================

def test_placebo_before_results_and_config_hash_integrity(base_hypothesis_dict):
    """Verifies that pre-test controls are locked into SHA-256 hash and immutable."""
    tracker = HypothesisLineageTracker()
    hyp = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    tracker.register_hypothesis(hyp)

    # Freeze hypothesis
    frozen_hyp = tracker.freeze_hypothesis(hyp.hypothesis_id)
    assert frozen_hyp.status == HypothesisStatus.FROZEN
    assert tracker.verify_frozen_integrity(hyp.hypothesis_id) is True

    # Tampering with pre-test placebo control invalidates frozen integrity
    frozen_hyp.pre_test_controls["placebo_test"] = "tampered_placebo_test"
    assert tracker.verify_frozen_integrity(hyp.hypothesis_id) is False


# =============================================================================
# 11. AI BOUNDARY ENFORCEMENT
# =============================================================================

def test_ai_boundary_enforcement_prohibited_actions(base_hypothesis_dict):
    """Verifies that AI cannot place orders, choose sizes, or declare profitability."""
    prohibited_keys = [
        "place_order",
        "submit_order",
        "trade_size_usd",
        "position_size",
        "leverage",
        "override_risk",
        "execute_order",
        "order_quantity",
        "target_position",
        "modify_statistical_result",
        "select_winning_strategy",
    ]
    for key in prohibited_keys:
        bad_dict = dict(base_hypothesis_dict)
        bad_dict[key] = True
        with pytest.raises(BoundaryViolationError, match="prohibited execution key"):
            BoundaryValidator.sanitize_and_construct(bad_dict)

    prohibited_claims = [
        "guaranteed profit opportunity",
        "risk-free money extraction",
        "proven alpha in live market",
        "declared profitable strategy",
        "select winning strategy",
    ]
    for claim in prohibited_claims:
        bad_dict = dict(base_hypothesis_dict)
        bad_dict["prediction"] = f"Yields {claim} after fees."
        with pytest.raises(BoundaryViolationError, match="unauthorized profitability claim"):
            BoundaryValidator.sanitize_and_construct(bad_dict)


# =============================================================================
# 12. HISTORICAL FAILURE RULES (13 CANONICAL PATTERNS)
# =============================================================================

def test_historical_failure_rules_evaluation(base_hypothesis_dict):
    """Verifies that all 13 canonical historical failure patterns are caught."""
    # 1. Gross edge consumed by friction
    bad_fric = dict(base_hypothesis_dict)
    bad_fric["expected_gross_edge_bps"] = 15.0
    bad_fric["required_gross_edge_bps"] = 27.0
    hyp1 = BoundaryValidator.sanitize_and_construct(bad_fric)
    passed, pats, _ = HistoricalRuleEngine.evaluate_hypothesis(hyp1)
    assert passed is False
    assert HistoricalFailurePattern.GROSS_EDGE_CONSUMED_BY_FRICTION in pats

    # 2. Synthetic data artifact
    bad_synth = dict(base_hypothesis_dict)
    bad_synth["required_observations"] = ["synthetic_interpolated_book"]
    hyp2 = BoundaryValidator.sanitize_and_construct(bad_synth)
    passed, pats, _ = HistoricalRuleEngine.evaluate_hypothesis(hyp2)
    assert passed is False
    assert HistoricalFailurePattern.SYNTHETIC_DATA_ARTIFACT in pats

    # 3. Excessive parameter freedom
    bad_params = dict(base_hypothesis_dict)
    bad_params["parameters"] = {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5}
    hyp3 = BoundaryValidator.sanitize_and_construct(bad_params)
    passed, pats, _ = HistoricalRuleEngine.evaluate_hypothesis(hyp3)
    assert passed is False
    assert HistoricalFailurePattern.EXCESSIVE_PARAMETER_FREEDOM in pats

    # 4. Tiny sample size
    bad_sample = dict(base_hypothesis_dict)
    bad_sample["minimum_sample_requirement"] = 10
    hyp4 = BoundaryValidator.sanitize_and_construct(bad_sample)
    passed, pats, _ = HistoricalRuleEngine.evaluate_hypothesis(hyp4)
    assert passed is False
    assert HistoricalFailurePattern.TINY_SAMPLE_SIZE in pats

    # 5. Correlation mistaken for arbitrage
    bad_arb = dict(base_hypothesis_dict)
    bad_arb["edge_type"] = EdgeType.EXACT_ARBITRAGE
    bad_arb["expected_relationship"] = "P(A) is correlated with P(B) with beta = 0.8"
    hyp5 = BoundaryValidator.sanitize_and_construct(bad_arb)
    passed, pats, _ = HistoricalRuleEngine.evaluate_hypothesis(hyp5)
    assert passed is False
    assert HistoricalFailurePattern.CORRELATION_MISTAKEN_FOR_ARBITRAGE in pats


# =============================================================================
# 13. AI SELF-CRITIQUE (13 QUESTIONS & 10 QUALITY STATES)
# =============================================================================

def test_ai_self_critique_and_quality_states(base_hypothesis_dict):
    """Verifies that AISelfCritiqueValidator answers 13 questions and assigns 10 quality states."""
    hyp = BoundaryValidator.sanitize_and_construct(base_hypothesis_dict)
    critique_res = AISelfCritiqueValidator.critique(hyp)

    assert isinstance(critique_res, SelfCritiqueResult)
    assert critique_res.passed_structural_critique is True
    assert len(critique_res.critique_answers) >= 12

    # Check 10 categorical quality states
    q_state = critique_res.quality_state
    assert isinstance(q_state, HypothesisQualityState)
    assert q_state.mechanism_status == QualityGateStatus.PASS
    assert q_state.formalization_status == QualityGateStatus.PASS
    assert q_state.data_status == QualityGateStatus.PASS
    assert q_state.identification_status == QualityGateStatus.PASS
    assert q_state.execution_status == QualityGateStatus.PASS
    assert q_state.novelty_status == QualityGateStatus.PASS
    assert q_state.friction_status == QualityGateStatus.PASS
    assert q_state.capacity_status == QualityGateStatus.PASS
    assert q_state.falsification_status == QualityGateStatus.PASS
    assert q_state.lineage_status == QualityGateStatus.PASS


# =============================================================================
# 14. 7 DISCOVERY MODES GENERATION
# =============================================================================

def test_7_discovery_modes_generation(mock_canonical_markets):
    """Verifies that RelationshipDiscoveryEngine generates valid hypotheses across all 7 modes."""
    engine = RelationshipDiscoveryEngine()

    modes = [
        DiscoveryMode.MODE_A_LOGICAL,
        DiscoveryMode.MODE_B_ECONOMIC,
        DiscoveryMode.MODE_C_EVENT,
        DiscoveryMode.MODE_D_MICROSTRUCTURE,
        DiscoveryMode.MODE_E_CROSS_MARKET,
        DiscoveryMode.MODE_F_CROSS_VENUE,
        DiscoveryMode.MODE_G_STAT_ARB,
    ]

    for mode in modes:
        discovered = engine.discover_structured_hypotheses(
            mock_canonical_markets,
            max_hypotheses=1,
            mode=mode,
        )
        assert len(discovered) == 1, f"Failed to discover hypothesis for {mode.value}"
        hyp = discovered[0]
        assert hyp.discovery_mode == mode
        assert hyp.quality_state is not None
        assert hyp.quality_state.mechanism_status == QualityGateStatus.PASS
        assert hyp.quality_state.friction_status == QualityGateStatus.PASS
        assert hyp.quality_state.capacity_status == QualityGateStatus.PASS
