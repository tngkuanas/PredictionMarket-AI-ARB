"""Deterministic Adversarial Execution Engine for Cross-Venue Arbitrage.

Phase 10A.6G:
Stress-tests apparent cross-venue arbitrage candidates between Polymarket and Kalshi
under progressively adverse execution conditions (latency, depth exhaustion, fee surges,
slippage spikes, quote staleness, asynchronous leg fills, price moves, and capital starvation).
Computes individual Edge Survival Bounds and structural false-positive rejections.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from typing import List, Dict, Any, Optional, Tuple

from pydantic import BaseModel, Field

from src.cross_venue.schema import (
    ContractMappingResult,
    SyncQuote,
    QuoteState,
    CategoryStatus,
    FinalArbitrageVerdict,
    ArbitrageLeg,
    CrossVenueCostBreakdown,
    CapitalCapacityResult,
    LegRiskResult,
    CrossVenueArbitrageOpportunity,
)
from src.cross_venue.cross_venue_arb_engine import CrossVenueArbEngine
from src.phase10.response_study.executable_price_model import ExecutablePriceModel

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. IMMUTABLE VERSIONED CONFIGURATION (Section 19)
# ==============================================================================

class AdversarialConfig(BaseModel):
    """Immutable frozen scenario configuration for Phase 10A.6G stress testing."""
    version: str = "1.0.0"
    created_timestamp: str = "2026-10-01T00:00:00Z"
    
    # Latency stress grid (ms) - Section 4
    latency_grid_ms: List[float] = [0.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0]
    
    # Available depth stress factors - Section 5
    depth_factors: List[float] = [1.00, 0.75, 0.50, 0.25, 0.10]
    
    # Fee multipliers - Section 6
    fee_multipliers: List[float] = [1.00, 1.10, 1.25, 1.50, 2.00, 2.50]
    
    # Slippage additions (bps) - Section 7
    slippage_stresses_bps: List[float] = [0.0, 5.0, 10.0, 15.0, 25.0, 50.0]
    
    # Quote ages to test (ms) - Section 8
    quote_ages_ms: List[float] = [0.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0]
    
    # Price movements between legs - Section 10
    adverse_movements_ticks: List[int] = [1, 2, 5, 10]
    adverse_movements_bps: List[float] = [25.0, 50.0, 100.0]
    
    # Capital stress factors - Section 11
    capital_factors: List[float] = [1.00, 0.75, 0.50, 0.25, 0.10]
    
    # Microstructure parameter: volatility rate for latency price moves (bps per sqrt(second))
    volatility_rate_bps_per_sqrt_sec: float = 30.0
    tick_size_usd: float = 0.01

    def compute_config_hash(self) -> str:
        """Deterministic SHA-256 hash of frozen configuration."""
        raw_repr = json.dumps(self.model_dump(), sort_keys=True)
        return hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()


# ==============================================================================
# 2. STRESS AUDIT OUTPUT SCHEMAS
# ==============================================================================

class BaselineExecutionResult(BaseModel):
    """Unmodified baseline execution candidate (Section 3)."""
    candidate_id: str
    mapping_id: str
    venue_pair: str
    direction: str
    quantity_usd: float
    executable_price_a: float
    executable_price_b: float
    combined_vwap: float
    gross_settlement_value: float = 1.0
    gross_edge_bps: float
    venue_fee_bps: float
    slippage_bps: float
    latency_penalty_bps: float
    hedge_cost_bps: float
    total_cost_bps: float
    net_edge_bps: float
    capital_required_usd: float
    residual_exposure_usd: float
    final_verdict: str


class LatencyStressResult(BaseModel):
    """Stress evaluation under variable execution latency (Section 4)."""
    latency_ms: float
    leg_a_latency_ms: float
    leg_b_latency_ms: float
    hedge_latency_ms: float
    max_price_movement_bps: float
    residual_exposure_usd: float
    net_executable_edge_bps: float
    is_edge_positive: bool
    verdict: str


class DepthStressResult(BaseModel):
    """Stress evaluation under diminished order book depth (Section 5)."""
    depth_factor: float
    available_depth_a_usd: float
    available_depth_b_usd: float
    executable_quantity_usd: float
    residual_unhedged_qty_usd: float
    vwap_a: float
    vwap_b: float
    net_edge_bps: float
    capital_utilization: float
    is_fully_hedged: bool
    is_edge_positive: bool


class FeeStressResult(BaseModel):
    """Stress evaluation under exchange fee increases (Section 6)."""
    fee_multiplier: float
    fee_a_bps: float
    fee_b_bps: float
    combined_fee_bps: float
    net_edge_bps: float
    is_edge_positive: bool


class SlippageStressResult(BaseModel):
    """Stress evaluation under adverse execution slippage (Section 7)."""
    slippage_stress_bps: float
    recalculated_vwap_a: float
    recalculated_vwap_b: float
    recalculated_combined_vwap: float
    total_slippage_bps: float
    net_edge_bps: float
    is_edge_positive: bool


class QuoteStalenessResult(BaseModel):
    """Replay evaluation under quote staleness (Section 8)."""
    quote_age_ms: float
    classification: str              # "EXECUTABLE_DISCREPANCY" or "STALE_QUOTE_ARTIFACT"
    net_edge_bps: float
    is_stale: bool


class AsynchronousLegResult(BaseModel):
    """Stress evaluation under asynchronous leg execution and fill asymmetries (Section 9)."""
    case_name: str
    leg_a_fill_pct: float
    leg_b_fill_pct: float
    filled_quantity_usd: float
    unhedged_quantity_usd: float
    residual_directional_exposure_usd: float
    hedge_cost_usd: float
    worst_case_loss_usd: float
    deterministic_settlement_value_usd: float
    net_pnl_usd: float
    net_edge_bps: float


class PriceMovementResult(BaseModel):
    """Evaluation of price movement between leg executions (Section 10)."""
    movement_type: str               # "adverse" or "favorable"
    movement_amount: float
    movement_unit: str                # "tick" or "bps"
    effective_leg_b_price: float
    net_edge_bps: float
    edge_destroyed: bool


class CapitalStressResult(BaseModel):
    """Evaluation under reduced capital availability (Section 11)."""
    capital_factor: float
    available_capital_a: float
    available_capital_b: float
    max_common_executable_qty_usd: float
    capital_utilization: float
    simultaneous_opportunities_count: int
    capital_trapped_usd: float
    residual_exposure_usd: float


class CorrelatedStressResult(BaseModel):
    """Multi-dimensional correlated stress scenario evaluation (Section 12)."""
    scenario_name: str               # STRESS_1 through STRESS_5
    parameters: Dict[str, Any]
    executable_quantity_usd: float
    unhedged_quantity_usd: float
    net_edge_bps: float
    net_pnl_usd: float
    worst_case_loss_usd: float
    is_viable: bool


class EdgeSurvivalBound(BaseModel):
    """Identifies the maximum adverse stress under which net edge remains >= 0 (Section 13)."""
    max_latency_tolerated_ms: float
    max_fee_tolerated_bps: float
    max_slippage_tolerated_bps: float
    min_depth_required_usd: float
    max_hedge_delay_tolerated_ms: float
    max_adverse_price_move_tolerated_bps: float
    bounds_summary: str


class AdversarialAuditSummary(BaseModel):
    """Complete adversarial execution stress audit record."""
    audit_id: str
    candidate_id: str
    mapping_id: str
    config_hash: str
    calculation_timestamp: datetime
    baseline: BaselineExecutionResult
    latency_stress: List[LatencyStressResult]
    depth_stress: List[DepthStressResult]
    fee_stress: List[FeeStressResult]
    slippage_stress: List[SlippageStressResult]
    quote_staleness: List[QuoteStalenessResult]
    asynchronous_legs: List[AsynchronousLegResult]
    price_movements: List[PriceMovementResult]
    capital_stress: List[CapitalStressResult]
    correlated_stress: List[CorrelatedStressResult]
    edge_survival: EdgeSurvivalBound
    all_stress_passed: bool
    rejection_reasons: List[str]


# ==============================================================================
# 3. ADVERSARIAL EXECUTION ENGINE
# ==============================================================================

class CrossVenueAdversarialEngine:
    """Evaluates cross-venue arbitrage candidates against progressive execution stress."""

    def __init__(self, config: Optional[AdversarialConfig] = None):
        self.config = config or AdversarialConfig()
        self.config_hash = self.config.compute_config_hash()
        self.l2_model = ExecutablePriceModel()

    def run_full_adversarial_audit(
        self,
        candidate: CrossVenueArbitrageOpportunity,
        quote_poly: SyncQuote,
        quote_kalshi: SyncQuote,
        mapping: ContractMappingResult,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> AdversarialAuditSummary:
        """Executes the complete adversarial stress grid against a candidate."""
        now = evaluation_timestamp or datetime.now(timezone.utc)
        
        # 1. Anti-Lookahead check (Section 16)
        self._verify_no_lookahead(quote_poly, quote_kalshi, now)

        # 2. Baseline
        baseline = self.evaluate_baseline(candidate)

        # 3. Latency Stress
        latency_results = self.evaluate_latency_stress(candidate)

        # 4. Depth Stress
        depth_results = self.evaluate_depth_stress(candidate, quote_poly, quote_kalshi)

        # 5. Fee Stress
        fee_results = self.evaluate_fee_stress(candidate)

        # 6. Slippage Stress
        slippage_results = self.evaluate_slippage_stress(candidate)

        # 7. Quote Staleness
        staleness_results = self.evaluate_quote_staleness(candidate)

        # 8. Asynchronous Legs
        async_results = self.evaluate_asynchronous_legs(candidate)

        # 9. Price Movement
        move_results = self.evaluate_price_movement(candidate)

        # 10. Capital Stress
        cap_results = self.evaluate_capital_stress(candidate)

        # 11. Correlated Stress
        corr_results = self.evaluate_correlated_stress(candidate, quote_poly, quote_kalshi)

        # 12. Edge Survival Bounds
        survival_bound = self.calculate_edge_survival_bound(candidate, quote_poly, quote_kalshi)

        # Assess overall adversarial robustness
        rejection_reasons = []
        if baseline.net_edge_bps <= 0:
            rejection_reasons.append("Baseline net edge is non-positive.")
        if not any(r.is_viable for r in corr_results):
            rejection_reasons.append("Zero correlated stress scenarios remained viable.")
        if survival_bound.max_adverse_price_move_tolerated_bps <= 0:
            rejection_reasons.append("Zero adverse price movement tolerated before edge collapses.")

        audit_id = f"adv_audit_{candidate.opportunity_id}_{int(now.timestamp())}"
        return AdversarialAuditSummary(
            audit_id=audit_id,
            candidate_id=candidate.opportunity_id,
            mapping_id=candidate.mapping_id,
            config_hash=self.config_hash,
            calculation_timestamp=now,
            baseline=baseline,
            latency_stress=latency_results,
            depth_stress=depth_results,
            fee_stress=fee_results,
            slippage_stress=slippage_results,
            quote_staleness=staleness_results,
            asynchronous_legs=async_results,
            price_movements=move_results,
            capital_stress=cap_results,
            correlated_stress=corr_results,
            edge_survival=survival_bound,
            all_stress_passed=len(rejection_reasons) == 0,
            rejection_reasons=rejection_reasons,
        )

    def _verify_no_lookahead(
        self,
        quote_a: SyncQuote,
        quote_b: SyncQuote,
        eval_ts: datetime
    ) -> None:
        """Enforces that no observation timestamp occurs after the evaluation timestamp (Section 16)."""
        eval_utc = eval_ts if eval_ts.tzinfo else eval_ts.replace(tzinfo=timezone.utc)
        for q in (quote_a, quote_b):
            rec_ts = q.local_receive_timestamp
            if rec_ts:
                r_utc = rec_ts if rec_ts.tzinfo else rec_ts.replace(tzinfo=timezone.utc)
                if r_utc > eval_utc:
                    raise ValueError(f"LOOKAHEAD VIOLATION: Quote timestamp {r_utc} > evaluation time {eval_utc}.")
            if q.exchange_timestamp:
                e_utc = q.exchange_timestamp if q.exchange_timestamp.tzinfo else q.exchange_timestamp.replace(tzinfo=timezone.utc)
                if e_utc > eval_utc:
                    raise ValueError(f"LOOKAHEAD VIOLATION: Exchange timestamp {e_utc} > evaluation time {eval_utc}.")

    def evaluate_baseline(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> BaselineExecutionResult:
        """Records unmodified baseline execution parameters (Section 3)."""
        la = candidate.leg_a
        lb = candidate.leg_b
        return BaselineExecutionResult(
            candidate_id=candidate.opportunity_id,
            mapping_id=candidate.mapping_id,
            venue_pair=f"{la.venue}_{la.outcome}/{lb.venue}_{lb.outcome}",
            direction="BUY_PAIRED",
            quantity_usd=la.order_size_usd,
            executable_price_a=la.vwap_price,
            executable_price_b=lb.vwap_price,
            combined_vwap=la.vwap_price + lb.vwap_price,
            gross_settlement_value=candidate.settlement_gross_value,
            gross_edge_bps=candidate.gross_edge_bps,
            venue_fee_bps=candidate.cost_breakdown.venue_fee_bps,
            slippage_bps=candidate.cost_breakdown.execution_slippage_bps,
            latency_penalty_bps=candidate.cost_breakdown.latency_penalty_bps,
            hedge_cost_bps=candidate.cost_breakdown.hedge_cost_bps,
            total_cost_bps=candidate.cost_breakdown.total_cost_bps,
            net_edge_bps=candidate.net_deterministic_edge_bps,
            capital_required_usd=candidate.capital_result.required_capital_a + candidate.capital_result.required_capital_b,
            residual_exposure_usd=candidate.leg_risk_result.residual_exposure_usd,
            final_verdict=candidate.final_verdict.value,
        )

    def evaluate_latency_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[LatencyStressResult]:
        """Calculates net edge under progressive execution latency (Section 4)."""
        results = []
        base_edge_bps = candidate.gross_edge_bps - (
            candidate.cost_breakdown.venue_fee_bps +
            candidate.cost_breakdown.execution_slippage_bps +
            candidate.cost_breakdown.hedge_cost_bps
        )

        for lat_ms in self.config.latency_grid_ms:
            # Latency penalty models adverse drift during hedge window:
            # drift_bps = volatility_rate * sqrt(latency_seconds)
            lat_sec = lat_ms / 1000.0
            price_move_bps = self.config.volatility_rate_bps_per_sqrt_sec * math.sqrt(lat_sec)
            
            # Linear latency penalty component + stochastic move
            dynamic_lat_penalty_bps = (lat_ms / 100.0) * 4.0 + price_move_bps
            stressed_net_edge_bps = base_edge_bps - dynamic_lat_penalty_bps

            is_positive = stressed_net_edge_bps > 0.0
            verdict = "PASS" if is_positive and lat_ms <= 250.0 else "FAIL"

            results.append(LatencyStressResult(
                latency_ms=lat_ms,
                leg_a_latency_ms=lat_ms / 2.0,
                leg_b_latency_ms=lat_ms / 2.0,
                hedge_latency_ms=lat_ms,
                max_price_movement_bps=round(price_move_bps, 2),
                residual_exposure_usd=candidate.leg_risk_result.residual_exposure_usd,
                net_executable_edge_bps=round(stressed_net_edge_bps, 2),
                is_edge_positive=is_positive,
                verdict=verdict,
            ))
        return results

    def evaluate_depth_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity,
        quote_poly: SyncQuote,
        quote_kalshi: SyncQuote,
    ) -> List[DepthStressResult]:
        """Evaluates execution against depleted order book depth (Section 5)."""
        results = []
        target_size = candidate.leg_a.order_size_usd

        for factor in self.config.depth_factors:
            stressed_depth_a = candidate.leg_a.available_depth_usd * factor
            stressed_depth_b = candidate.leg_b.available_depth_usd * factor
            
            # Executable size cannot exceed available stressed depth
            exec_qty = min(target_size, stressed_depth_a, stressed_depth_b)
            residual_unhedged = max(0.0, target_size - exec_qty)

            # Recalculate VWAP with reduced depth factor
            # As depth dries up, slippage increases quadratically with concentration
            slippage_impact = ((1.0 / factor) - 1.0) * 10.0  # bps
            vwap_a = candidate.leg_a.vwap_price * (1.0 + slippage_impact / 20000.0)
            vwap_b = candidate.leg_b.vwap_price * (1.0 + slippage_impact / 20000.0)
            combined_vwap = vwap_a + vwap_b

            gross_edge_bps = (1.0 - combined_vwap) * 10000.0
            net_edge_bps = gross_edge_bps - candidate.cost_breakdown.total_cost_bps

            cap_utilization = (exec_qty / target_size) if target_size > 0 else 0.0
            is_hedged = residual_unhedged == 0.0
            is_positive = (net_edge_bps > 0.0) and is_hedged

            results.append(DepthStressResult(
                depth_factor=factor,
                available_depth_a_usd=round(stressed_depth_a, 2),
                available_depth_b_usd=round(stressed_depth_b, 2),
                executable_quantity_usd=round(exec_qty, 2),
                residual_unhedged_qty_usd=round(residual_unhedged, 2),
                vwap_a=round(vwap_a, 4),
                vwap_b=round(vwap_b, 4),
                net_edge_bps=round(net_edge_bps, 2),
                capital_utilization=round(cap_utilization, 4),
                is_fully_hedged=is_hedged,
                is_edge_positive=is_positive,
            ))
        return results

    def evaluate_fee_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[FeeStressResult]:
        """Evaluates impact of venue fee surges (Section 6)."""
        results = []
        base_gross_edge_bps = candidate.gross_edge_bps
        non_fee_costs_bps = (
            candidate.cost_breakdown.execution_slippage_bps +
            candidate.cost_breakdown.latency_penalty_bps +
            candidate.cost_breakdown.hedge_cost_bps
        )

        for mult in self.config.fee_multipliers:
            fee_a_stressed = candidate.leg_a.fee_bps * mult
            fee_b_stressed = candidate.leg_b.fee_bps * mult
            combined_fee_bps = (fee_a_stressed + fee_b_stressed) / 2.0

            total_cost_bps = combined_fee_bps + non_fee_costs_bps
            net_edge_bps = base_gross_edge_bps - total_cost_bps

            results.append(FeeStressResult(
                fee_multiplier=mult,
                fee_a_bps=round(fee_a_stressed, 2),
                fee_b_bps=round(fee_b_stressed, 2),
                combined_fee_bps=round(combined_fee_bps, 2),
                net_edge_bps=round(net_edge_bps, 2),
                is_edge_positive=net_edge_bps > 0.0,
            ))
        return results

    def evaluate_slippage_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[SlippageStressResult]:
        """Recalculates executable prices under elevated slippage (Section 7)."""
        results = []
        for slip_stress in self.config.slippage_stresses_bps:
            # Recalculate price: each leg suffers slip_stress / 2 in price deterioration
            price_impact_ratio = (slip_stress / 10000.0) / 2.0
            recalc_vwap_a = candidate.leg_a.vwap_price * (1.0 + price_impact_ratio)
            recalc_vwap_b = candidate.leg_b.vwap_price * (1.0 + price_impact_ratio)
            recalc_combined_vwap = recalc_vwap_a + recalc_vwap_b

            gross_edge_bps = (1.0 - recalc_combined_vwap) * 10000.0
            total_slippage_bps = candidate.cost_breakdown.execution_slippage_bps + slip_stress
            
            # Non-slippage costs
            other_costs_bps = (
                candidate.cost_breakdown.venue_fee_bps +
                candidate.cost_breakdown.latency_penalty_bps +
                candidate.cost_breakdown.hedge_cost_bps
            )
            net_edge_bps = gross_edge_bps - other_costs_bps

            results.append(SlippageStressResult(
                slippage_stress_bps=slip_stress,
                recalculated_vwap_a=round(recalc_vwap_a, 4),
                recalculated_vwap_b=round(recalc_vwap_b, 4),
                recalculated_combined_vwap=round(recalc_combined_vwap, 4),
                total_slippage_bps=round(total_slippage_bps, 2),
                net_edge_bps=round(net_edge_bps, 2),
                is_edge_positive=net_edge_bps > 0.0,
            ))
        return results

    def evaluate_quote_staleness(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[QuoteStalenessResult]:
        """Tests whether opportunity survives progressive quote aging (Section 8)."""
        results = []
        for age_ms in self.config.quote_ages_ms:
            # Stale quote artifact if quote is older than 250ms threshold
            is_stale = age_ms > 250.0
            
            # Decay of apparent edge due to stale quotation adverse selection
            decay_penalty_bps = (age_ms / 100.0) * 8.0
            decayed_edge_bps = candidate.net_deterministic_edge_bps - decay_penalty_bps

            classification = "EXECUTABLE_DISCREPANCY" if not is_stale and decayed_edge_bps > 0 else "STALE_QUOTE_ARTIFACT"

            results.append(QuoteStalenessResult(
                quote_age_ms=age_ms,
                classification=classification,
                net_edge_bps=round(decayed_edge_bps, 2),
                is_stale=is_stale,
            ))
        return results

    def evaluate_asynchronous_legs(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[AsynchronousLegResult]:
        """Tests the 6 asynchronous execution and partial fill scenarios (Section 9)."""
        target_qty = candidate.leg_a.order_size_usd
        price_a = candidate.leg_a.vwap_price
        price_b = candidate.leg_b.vwap_price

        cases = [
            ("CASE_A_LEG_A_FIRST_B_DELAYED", 1.0, 1.0, 0.02),      # Delay causes 200 bps slip on leg B
            ("CASE_B_LEG_B_FIRST_A_DELAYED", 1.0, 1.0, 0.02),      # Delay causes 200 bps slip on leg A
            ("CASE_C_LEG_A_FULL_B_PARTIAL", 1.0, 0.50, 0.0),       # Leg A 100%, Leg B 50%
            ("CASE_D_LEG_A_PARTIAL_B_FULL", 0.50, 1.0, 0.0),       # Leg A 50%, Leg B 100%
            ("CASE_E_LEG_A_FULL_B_FAILED", 1.0, 0.0, 0.0),         # Leg A 100%, Leg B 0%
            ("CASE_F_BOTH_LEGS_PARTIAL", 0.60, 0.40, 0.0),         # Leg A 60%, Leg B 40%
        ]

        results = []
        for name, fill_a_pct, fill_b_pct, delay_slip in cases:
            qty_a = target_qty * fill_a_pct
            qty_b = target_qty * fill_b_pct

            common_hedged_qty = min(qty_a, qty_b)
            unhedged_qty = abs(qty_a - qty_b)

            # Directional exposure
            residual_exposure = unhedged_qty

            # Execution cost
            actual_price_a = price_a * (1.0 + (delay_slip if "LEG_B_FIRST" in name else 0.0))
            actual_price_b = price_b * (1.0 + (delay_slip if "LEG_A_FIRST" in name else 0.0))

            cost_paid = (qty_a * actual_price_a) + (qty_b * actual_price_b)
            
            # Deterministic settlement value:
            # Common paired contracts settle for 1.00 each
            # Unhedged leg has payoff = 1.00 (if won) or 0.00 (if lost).
            # Worst-case deterministic payoff assumes unhedged position expires worthless (0.00).
            settlement_val = common_hedged_qty * 1.0
            
            # Hedge cost to emergency-liquidate unhedged leg at 10% penalty
            emergency_hedge_cost = unhedged_qty * 0.10

            worst_case_loss = (cost_paid - settlement_val) + emergency_hedge_cost
            net_pnl = settlement_val - cost_paid - emergency_hedge_cost
            net_edge_bps = (net_pnl / target_qty) * 10000.0 if target_qty > 0 else -10000.0

            results.append(AsynchronousLegResult(
                case_name=name,
                leg_a_fill_pct=fill_a_pct,
                leg_b_fill_pct=fill_b_pct,
                filled_quantity_usd=round(qty_a + qty_b, 2),
                unhedged_quantity_usd=round(unhedged_qty, 2),
                residual_directional_exposure_usd=round(residual_exposure, 2),
                hedge_cost_usd=round(emergency_hedge_cost, 2),
                worst_case_loss_usd=round(worst_case_loss, 2),
                deterministic_settlement_value_usd=round(settlement_val, 2),
                net_pnl_usd=round(net_pnl, 2),
                net_edge_bps=round(net_edge_bps, 2),
            ))
        return results

    def evaluate_price_movement(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[PriceMovementResult]:
        """Tests sensitivity to adverse and favorable price moves between legs (Section 10)."""
        results = []
        base_edge_bps = candidate.net_deterministic_edge_bps
        base_leg_b_price = candidate.leg_b.vwap_price

        # 1. Tick movements (1, 2, 5, 10 ticks = 0.01 to 0.10)
        for ticks in self.config.adverse_movements_ticks:
            move_dollars = ticks * self.config.tick_size_usd
            move_bps = (move_dollars / 1.0) * 10000.0

            # Adverse move: Leg B price increases by move_dollars
            adverse_price_b = base_leg_b_price + move_dollars
            adverse_net_edge_bps = base_edge_bps - move_bps
            results.append(PriceMovementResult(
                movement_type="adverse",
                movement_amount=float(ticks),
                movement_unit="tick",
                effective_leg_b_price=round(adverse_price_b, 4),
                net_edge_bps=round(adverse_net_edge_bps, 2),
                edge_destroyed=adverse_net_edge_bps <= 0.0,
            ))

            # Favorable move (recorded for descriptive symmetry, NOT to justify trade)
            fav_price_b = max(0.01, base_leg_b_price - move_dollars)
            fav_net_edge_bps = base_edge_bps + move_bps
            results.append(PriceMovementResult(
                movement_type="favorable",
                movement_amount=float(ticks),
                movement_unit="tick",
                effective_leg_b_price=round(fav_price_b, 4),
                net_edge_bps=round(fav_net_edge_bps, 2),
                edge_destroyed=False,
            ))

        # 2. Basis points movements (25, 50, 100 bps)
        for bps in self.config.adverse_movements_bps:
            move_dollars = (bps / 10000.0)
            adverse_price_b = base_leg_b_price + move_dollars
            adverse_net_edge_bps = base_edge_bps - bps
            results.append(PriceMovementResult(
                movement_type="adverse",
                movement_amount=bps,
                movement_unit="bps",
                effective_leg_b_price=round(adverse_price_b, 4),
                net_edge_bps=round(adverse_net_edge_bps, 2),
                edge_destroyed=adverse_net_edge_bps <= 0.0,
            ))

        return results

    def evaluate_capital_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity
    ) -> List[CapitalStressResult]:
        """Calculates capacity limits under reduced venue capital (Section 11)."""
        results = []
        target_size = candidate.leg_a.order_size_usd
        base_cap_a = candidate.capital_result.capital_a
        base_cap_b = candidate.capital_result.capital_b

        for factor in self.config.capital_factors:
            cap_a = base_cap_a * factor
            cap_b = base_cap_b * factor
            
            max_common_size = min(
                candidate.leg_a.available_depth_usd,
                candidate.leg_b.available_depth_usd,
                cap_a,
                cap_b,
            )
            cap_utilization = (target_size / min(cap_a, cap_b)) if min(cap_a, cap_b) > 0 else 1.0
            simul_opps = int(min(cap_a, cap_b) / target_size) if target_size > 0 else 0
            
            # Capital trapped for binary holding duration
            capital_trapped = max_common_size * 2.0
            residual_exposure = max(0.0, target_size - max_common_size)

            results.append(CapitalStressResult(
                capital_factor=factor,
                available_capital_a=round(cap_a, 2),
                available_capital_b=round(cap_b, 2),
                max_common_executable_qty_usd=round(max_common_size, 2),
                capital_utilization=round(cap_utilization, 4),
                simultaneous_opportunities_count=simul_opps,
                capital_trapped_usd=round(capital_trapped, 2),
                residual_exposure_usd=round(residual_exposure, 2),
            ))
        return results

    def evaluate_correlated_stress(
        self,
        candidate: CrossVenueArbitrageOpportunity,
        quote_poly: SyncQuote,
        quote_kalshi: SyncQuote,
    ) -> List[CorrelatedStressResult]:
        """Tests the 5 fixed multi-dimensional correlated stress scenarios (Section 12)."""
        target_size = candidate.leg_a.order_size_usd
        results = []

        # STRESS_1: +100% fees (2.0x), +50% slippage (1.5x), +50% depth reduction (0.5x depth)
        p1 = {"fee_mult": 2.0, "slippage_mult": 1.5, "depth_factor": 0.5}
        exec_qty_1 = min(target_size, candidate.leg_a.available_depth_usd * 0.5, candidate.leg_b.available_depth_usd * 0.5)
        fee_bps_1 = candidate.cost_breakdown.venue_fee_bps * 2.0
        slip_bps_1 = candidate.cost_breakdown.execution_slippage_bps * 1.5
        costs_1 = fee_bps_1 + slip_bps_1 + candidate.cost_breakdown.latency_penalty_bps + candidate.cost_breakdown.hedge_cost_bps
        net_edge_1 = candidate.gross_edge_bps - costs_1
        net_pnl_1 = (net_edge_1 / 10000.0) * exec_qty_1
        results.append(CorrelatedStressResult(
            scenario_name="STRESS_1",
            parameters=p1,
            executable_quantity_usd=round(exec_qty_1, 2),
            unhedged_quantity_usd=round(target_size - exec_qty_1, 2),
            net_edge_bps=round(net_edge_1, 2),
            net_pnl_usd=round(net_pnl_1, 2),
            worst_case_loss_usd=round(max(0.0, -net_pnl_1), 2),
            is_viable=net_edge_1 > 0.0 and (target_size - exec_qty_1 == 0.0),
        ))

        # STRESS_2: 500 ms latency, +25 bps adverse movement, +50% depth reduction
        p2 = {"latency_ms": 500.0, "adverse_move_bps": 25.0, "depth_factor": 0.5}
        exec_qty_2 = min(target_size, candidate.leg_a.available_depth_usd * 0.5, candidate.leg_b.available_depth_usd * 0.5)
        lat_penalty_2 = (500.0 / 100.0) * 4.0
        costs_2 = candidate.cost_breakdown.venue_fee_bps + candidate.cost_breakdown.execution_slippage_bps + lat_penalty_2 + 25.0
        net_edge_2 = candidate.gross_edge_bps - costs_2
        net_pnl_2 = (net_edge_2 / 10000.0) * exec_qty_2
        results.append(CorrelatedStressResult(
            scenario_name="STRESS_2",
            parameters=p2,
            executable_quantity_usd=round(exec_qty_2, 2),
            unhedged_quantity_usd=round(target_size - exec_qty_2, 2),
            net_edge_bps=round(net_edge_2, 2),
            net_pnl_usd=round(net_pnl_2, 2),
            worst_case_loss_usd=round(max(0.0, -net_pnl_2), 2),
            is_viable=net_edge_2 > 0.0 and (target_size - exec_qty_2 == 0.0),
        ))

        # STRESS_3: 1 s latency (1000ms), +100% fee (2.0x), 25% depth (0.25x depth)
        p3 = {"latency_ms": 1000.0, "fee_mult": 2.0, "depth_factor": 0.25}
        exec_qty_3 = min(target_size, candidate.leg_a.available_depth_usd * 0.25, candidate.leg_b.available_depth_usd * 0.25)
        lat_penalty_3 = (1000.0 / 100.0) * 4.0
        fee_bps_3 = candidate.cost_breakdown.venue_fee_bps * 2.0
        costs_3 = fee_bps_3 + candidate.cost_breakdown.execution_slippage_bps + lat_penalty_3 + candidate.cost_breakdown.hedge_cost_bps
        net_edge_3 = candidate.gross_edge_bps - costs_3
        net_pnl_3 = (net_edge_3 / 10000.0) * exec_qty_3
        results.append(CorrelatedStressResult(
            scenario_name="STRESS_3",
            parameters=p3,
            executable_quantity_usd=round(exec_qty_3, 2),
            unhedged_quantity_usd=round(target_size - exec_qty_3, 2),
            net_edge_bps=round(net_edge_3, 2),
            net_pnl_usd=round(net_pnl_3, 2),
            worst_case_loss_usd=round(max(0.0, -net_pnl_3), 2),
            is_viable=net_edge_3 > 0.0 and (target_size - exec_qty_3 == 0.0),
        ))

        # STRESS_4: partial fill (50%), +500 ms hedge delay, +10 tick adverse movement ($0.10 = 1000 bps)
        p4 = {"fill_ratio": 0.50, "hedge_delay_ms": 500.0, "adverse_move_ticks": 10}
        filled_qty_4 = target_size * 0.50
        unhedged_qty_4 = target_size * 0.50
        hedge_cost_4 = unhedged_qty_4 * 0.10
        adverse_cost_4 = unhedged_qty_4 * 0.10
        net_pnl_4 = - (hedge_cost_4 + adverse_cost_4)
        results.append(CorrelatedStressResult(
            scenario_name="STRESS_4",
            parameters=p4,
            executable_quantity_usd=round(filled_qty_4, 2),
            unhedged_quantity_usd=round(unhedged_qty_4, 2),
            net_edge_bps=-2000.0,
            net_pnl_usd=round(net_pnl_4, 2),
            worst_case_loss_usd=round(abs(net_pnl_4), 2),
            is_viable=False,
        ))

        # STRESS_5: second-leg failure (0% fill on leg B), +50% adverse movement allowance
        p5 = {"leg_b_fill": 0.0, "adverse_move_pct": 0.50}
        unhedged_qty_5 = target_size
        worst_loss_5 = target_size * 0.50
        results.append(CorrelatedStressResult(
            scenario_name="STRESS_5",
            parameters=p5,
            executable_quantity_usd=0.0,
            unhedged_quantity_usd=round(unhedged_qty_5, 2),
            net_edge_bps=-5000.0,
            net_pnl_usd=round(-worst_loss_5, 2),
            worst_case_loss_usd=round(worst_loss_5, 2),
            is_viable=False,
        ))

        return results

    def calculate_edge_survival_bound(
        self,
        candidate: CrossVenueArbitrageOpportunity,
        quote_poly: SyncQuote,
        quote_kalshi: SyncQuote,
    ) -> EdgeSurvivalBound:
        """Determines the exact threshold at which net edge drops to zero (Section 13)."""
        base_net_edge_bps = candidate.net_deterministic_edge_bps
        target_size = candidate.leg_a.order_size_usd

        # 1. Max fee tolerated: edge + baseline fee
        max_fee = max(0.0, base_net_edge_bps + candidate.cost_breakdown.venue_fee_bps)

        # 2. Max slippage tolerated: edge + baseline slippage
        max_slip = max(0.0, base_net_edge_bps + candidate.cost_breakdown.execution_slippage_bps)

        # 3. Max latency tolerated: latency where (lat / 100) * 4.0 == base_net_edge_bps
        max_lat_ms = max(0.0, (base_net_edge_bps / 4.0) * 100.0)

        # 4. Max hedge delay tolerated
        max_hedge_delay_tolerated_ms = max_lat_ms / 2.0

        # 5. Max adverse price move tolerated: exactly base_net_edge_bps in basis points
        max_adverse_move_bps = max(0.0, base_net_edge_bps)

        # 6. Minimum depth required: minimum depth to execute target size without excessive slippage
        min_depth = target_size

        summary = (
            f"Edge Survival: Latency<={max_lat_ms:.0f}ms, "
            f"Fee<={max_fee:.1f}bps, "
            f"Slippage<={max_slip:.1f}bps, "
            f"AdverseMove<={max_adverse_move_bps:.1f}bps"
        )

        return EdgeSurvivalBound(
            max_latency_tolerated_ms=round(max_lat_ms, 1),
            max_fee_tolerated_bps=round(max_fee, 1),
            max_slippage_tolerated_bps=round(max_slip, 1),
            min_depth_required_usd=round(min_depth, 2),
            max_hedge_delay_tolerated_ms=round(max_hedge_delay_tolerated_ms, 1),
            max_adverse_price_move_tolerated_bps=round(max_adverse_move_bps, 1),
            bounds_summary=summary,
        )
