"""Strict Schema Definitions for Phase 10A.6b Hypothesis Engine & Stat-Arb Framework.

Enforces:
1. Strict hypothesis typing with all 20+ mandatory causal & execution specifications.
2. 7 designated hypothesis families.
3. Multi-stage anti-overfitting lifecycle (Discovery -> Frozen -> Adversarial -> Execution).
4. Machine-readable categorical hypothesis scorecard (no composite numerical ranking).
"""

from enum import Enum
import hashlib
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, model_validator


class HypothesisFamily(str, Enum):
    """The 7 designated causal hypothesis families for prediction market stat-arb."""
    EXACT_CONTRACT_ARB = "exact_contract_arb"            # Mutually exclusive outcomes, complementary YES/NO, identical exposure
    RESOLUTION_ARB = "resolution_arb"                    # Deterministic bounds/implications from settlement rule logic
    CONDITIONAL_STAT_ARB = "conditional_stat_arb"        # Spread mean reversion, cointegration, conditional dependence
    CROSS_MARKET_LEAD_LAG = "cross_market_lead_lag"      # Temporal ordering: Market A moves before Market B
    ORDER_FLOW_MICROSTRUCTURE = "order_flow_microstructure" # Order book imbalance, depth, aggressive flow response
    EVENT_CONDITIONAL_STAT_ARB = "event_conditional_stat_arb" # Activates around macro/news/resolution developments
    CROSS_VENUE_PLATFORM = "cross_venue_platform"        # Equivalent economic contracts across Polymarket/Kalshi


class HypothesisStatus(str, Enum):
    """Lifecycle stages enforcing the discovery / validation split."""
    DISCOVERY = "DISCOVERY"                              # Newly proposed candidate
    EXPLORATORY_VALIDATED = "EXPLORATORY_VALIDATED"      # Screened on exploratory in-sample partition
    FROZEN = "FROZEN"                                    # Parameters and config locked via SHA-256 hash
    OUT_OF_SAMPLE_TESTED = "OUT_OF_SAMPLE_TESTED"        # Evaluated on held-out out-of-sample data
    ADVERSARIAL_TESTED = "ADVERSARIAL_TESTED"            # Evaluated under the 10 adversarial stress tests
    EXECUTION_TESTED = "EXECUTION_TESTED"                # Passed full L2 book walk, fee, slippage, and depth gates
    ACCEPTED = "ACCEPTED"                                # Formally verified across all independent criteria
    REJECTED = "REJECTED"                                # Falsified by statistical, adversarial, or execution failure


class ScorecardStatus(str, Enum):
    """Categorical states for independent scorecard validation dimensions."""
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_TESTED = "NOT_TESTED"


class ScorecardVerdict(str, Enum):
    """Final determination of hypothesis scorecard without numerical ranking."""
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class AdversarialVerdict(str, Enum):
    """Diagnostic categorization of adversarial test failures."""
    PASS = "PASS"
    NON_EXECUTABLE = "NON_EXECUTABLE"                    # Fails under realistic spread, fees, or latency
    OVERFIT = "OVERFIT"                                  # Survives in-sample but collapses out-of-sample
    STRUCTURAL_ARTIFACT = "STRUCTURAL_ARTIFACT"          # Survives placebo or reverse direction tests incorrectly
    INVALID = "INVALID"                                  # Falsified by feature removal or randomized pairs


class StructuredHypothesis(BaseModel):
    """Strictly typed structured hypothesis specification.
    
    CRITICAL RULE: AI confidence is a DISCOVERY PRIOR ONLY and must NEVER
    be interpreted as probability of profitability or justification for trading.
    """
    # 1. Identity & Classification
    hypothesis_id: str = Field(description="Unique hypothesis identifier, e.g. hyp_btc_eth_leadlag_001")
    hypothesis_family: HypothesisFamily = Field(description="One of the 7 designated hypothesis families")
    source_markets: List[str] = Field(description="IDs or tokens of source/leading markets")
    target_markets: List[str] = Field(description="IDs or tokens of target/lagging markets")

    # 2. Causal Mechanism & Variables
    causal_mechanism: str = Field(description="Specific causal, economic, or market-microstructure transmission chain")
    required_observations: List[str] = Field(description="Required observation types, e.g. ['order_book_l2', 'trades']")
    observable_variables: List[str] = Field(description="Measurable input variables, e.g. ['book_imbalance', 'spread']")
    expected_relationship: str = Field(description="Mathematical or structural form of the expected relationship")
    direction: str = Field(description="Directionality: positive, negative, mean_reverting, lead_lag, monotone_bound")
    expected_time_horizon: str = Field(description="Expected persistence horizon, e.g. '5-30s', '1m-5m', '1h-4h'")

    # 3. Falsification & Controls
    falsification_condition: str = Field(description="Exact quantitative condition under which the hypothesis is rejected")
    minimum_sample_requirement: int = Field(ge=5, default=30, description="Minimum independent observations required")
    proposed_statistical_test: str = Field(description="Primary statistical test, e.g. 'permutation_test', 'augmented_dickey_fuller'")
    proposed_placebo_control: str = Field(description="Proposed placebo specification, e.g. 'time_shift_24h', 'randomized_pair'")

    # 4. Microstructure, Execution & Friction Dependencies
    execution_dependency: str = Field(description="Execution mechanism, e.g. 'taker_l2_walk', 'top_of_book_passive'")
    expected_friction_sensitivity: str = Field(description="Sensitivity to transaction costs: high, medium, low")
    capacity_dependency: float = Field(ge=0.0, description="Estimated maximum capital capacity in USD before impact degrades edge")
    known_confounders: List[str] = Field(default_factory=list, description="Known potential confounding factors")
    lookahead_risk: str = Field(description="Audit of potential lookahead leakage in feature construction")
    data_requirements: List[str] = Field(default_factory=list, description="Specific data schema requirements")

    # 5. Discovery Prior (Strictly NOT profitability)
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=0.5,
        description="DISCOVERY PRIOR ONLY. Must NEVER be interpreted as probability of profitability."
    )

    # 6. Structured Operational Template (Input -> Transformation -> Prediction -> Horizon -> Cost -> Falsification)
    input_signal: str = Field(default="", description="Precise input signal definition")
    transformation: str = Field(default="", description="Mathematical transformation or filter applied to input")
    prediction: str = Field(default="", description="Expected conditional change in target asset")
    horizon: str = Field(default="", description="Time horizon for the predicted response")
    cost_model: str = Field(default="", description="Cost model applied (spread + VWAP slippage + taker fees)")
    falsification_test: str = Field(default="", description="Adversarial and null controls to falsify")

    # 7. Lineage Tracking & Anti-Overfitting State
    lineage_family_id: str = Field(description="Identifier of the hypothesis family lineage to group mutations")
    parent_hypothesis_id: Optional[str] = Field(default=None, description="Parent hypothesis ID if this is a mutation")
    version: int = Field(default=1, ge=1, description="Iteration/version number in the lineage family")
    mutation_rationale: Optional[str] = Field(default=None, description="Detailed justification for mutation if version > 1")
    status: HypothesisStatus = Field(default=HypothesisStatus.DISCOVERY)
    config_hash: Optional[str] = Field(default=None, description="SHA-256 hash of configuration once FROZEN")
    frozen_timestamp: Optional[str] = Field(default=None, description="ISO timestamp when hypothesis was frozen")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Frozen model parameters (thresholds, betas, etc.)")

    @model_validator(mode="after")
    def validate_schema_integrity(self):
        """Validates critical safety constraints and operational fields."""
        if not self.source_markets:
            raise ValueError("Hypothesis must specify at least one source market.")
        if not self.target_markets:
            raise ValueError("Hypothesis must specify at least one target market.")
        if not self.falsification_condition or len(self.falsification_condition.strip()) < 10:
            raise ValueError("Hypothesis must provide a concrete quantitative falsification condition.")
        if not self.causal_mechanism or len(self.causal_mechanism.strip()) < 15:
            raise ValueError("Hypothesis must provide an explicit causal economic mechanism.")
        if self.version > 1 and not self.mutation_rationale:
            raise ValueError("Mutated hypothesis (version > 1) must provide an explicit mutation_rationale.")
        return self

    def compute_config_hash(self) -> str:
        """Computes a deterministic SHA-256 hash of all configuration parameters.
        
        This prevents parameter cherry-picking or subtle mutations once entering FROZEN state.
        """
        payload = {
            "hypothesis_family": self.hypothesis_family.value,
            "source_markets": sorted(self.source_markets),
            "target_markets": sorted(self.target_markets),
            "direction": self.direction,
            "expected_time_horizon": self.expected_time_horizon,
            "falsification_condition": self.falsification_condition,
            "minimum_sample_requirement": self.minimum_sample_requirement,
            "proposed_statistical_test": self.proposed_statistical_test,
            "execution_dependency": self.execution_dependency,
            "parameters": self.parameters,
            "input_signal": self.input_signal,
            "transformation": self.transformation,
            "prediction": self.prediction,
            "horizon": self.horizon,
            "cost_model": self.cost_model,
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


class HypothesisScorecard(BaseModel):
    """Machine-readable candidate scorecard across 10 independent validation axes.
    
    CRITICAL RULE: No composite numerical strategy score is produced.
    Strategies are accepted or rejected based on categorical state thresholds.
    """
    hypothesis_id: str
    lineage_family_id: str
    config_hash: Optional[str] = None
    
    # 10 Independent Categorical Validation Axes
    statistical_evidence: ScorecardStatus = ScorecardStatus.NOT_TESTED
    economic_mechanism: ScorecardStatus = ScorecardStatus.NOT_TESTED
    oos_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    placebo_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    execution_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    capacity_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    latency_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    data_quality_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    multiple_testing_status: ScorecardStatus = ScorecardStatus.NOT_TESTED
    robustness_status: ScorecardStatus = ScorecardStatus.NOT_TESTED

    # Adversarial Diagnostic Classification
    adversarial_verdict: AdversarialVerdict = AdversarialVerdict.PASS

    # Final Categorical Determination
    verdict: ScorecardVerdict = ScorecardVerdict.INCONCLUSIVE
    rejection_reasons: List[str] = Field(default_factory=list)
    
    # Detailed Quantitative Metrics (Audit Trail Only — Not Weighted Into A Composite Score)
    details: Dict[str, Any] = Field(default_factory=dict)


class SpreadModelConfig(BaseModel):
    """Configuration for statistical spread modeling and estimation."""
    spread_type: str = "linear"                          # "linear" (Y - beta * X) or "log" (log(Y) - beta * log(X))
    estimation_method: str = "ols"                       # "ols", "theil_sen", "huber"
    rolling_window: int = 60                             # Rolling estimation window steps
    min_observations: int = 30
    z_score_threshold: float = 2.0
    exit_z_score: float = 0.5
    stop_loss_z_score: float = 4.0
    use_robust_mad: bool = False
    max_holding_period_steps: int = 120


class ExecutionGateResult(BaseModel):
    """Deterministic result of passing through the multi-tier execution gate."""
    is_executable: bool
    rejection_stage: Optional[str] = None
    gross_return_bps: float = 0.0
    spread_cost_bps: float = 0.0
    slippage_bps: float = 0.0
    taker_fee_bps: float = 0.0
    latency_cost_bps: float = 0.0
    net_return_bps: float = 0.0
    fill_vwap: float = 0.0
    total_depth_available_usd: float = 0.0
    capacity_limit_usd: float = 0.0
    reason: str = ""


class StatArbMetrics(BaseModel):
    """Summary metrics computed by the deterministic statistical engine."""
    sample_size: int
    mean_spread: float
    std_spread: float
    beta: float
    half_life_steps: float
    is_stationary: bool
    adf_statistic: float
    adf_pvalue: float
    is_cointegrated: bool
    cointegration_pvalue: float
    autocorrelation_lag1: float
    lead_lag_optimal_lag: int
    lead_lag_max_correlation: float
    gross_spread_capture_bps: float
    net_spread_capture_bps: float
    hit_rate: float
    turnover: float
    max_drawdown_bps: float
    capacity_limit_usd: float
