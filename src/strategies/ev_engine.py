"""Mispricing & Basis-Risk-Adjusted Net Expected Value (EV) Engine."""
import logging
from typing import Optional, Dict, Any

from src.normalization.schema import (
    CandidateRelationship,
    ResolutionRuleAnalysis,
    Signal,
    OrderSide,
    OpportunityClass,
)
from src.execution.fee_model import DynamicExecutionCostModel

logger = logging.getLogger(__name__)

class MispricingEVEngine:
    """Calculates Net Expected Value adjusted for basis risk, transaction costs, and oracle uncertainty."""

    def __init__(
        self,
        min_required_net_edge: float = 0.015, # 1.5% minimum net edge
        taker_fee_rate: float = 0.001,        # 0.1% Polymarket taker fee
        slippage_rate: float = 0.002,         # 0.2% slippage
        default_spread: float = 0.012,        # 1.2% typical spread
        divergence_loss_penalty_weight: float = 0.50, # Penalty weight for resolution divergence
        dynamic_cost_model: Optional[DynamicExecutionCostModel] = None
    ):
        self.min_edge = min_required_net_edge
        self.taker_fee = taker_fee_rate
        self.slippage = slippage_rate
        self.default_spread = default_spread
        self.divergence_weight = divergence_loss_penalty_weight
        self.cost_model = dynamic_cost_model or DynamicExecutionCostModel(
            default_taker_fee=taker_fee_rate,
            default_maker_fee=0.0,
            min_spread_cents=0.005
        )

    def calculate_net_ev(
        self,
        raw_edge: float,
        resolution_analysis: ResolutionRuleAnalysis,
        opportunity_class: OpportunityClass,
        market_spread: Optional[float] = None,
        price: Optional[float] = None,
        liquidity_usd: Optional[float] = None,
        order_size_usd: float = 1_000.0,
        is_maker: bool = False
    ) -> Dict[str, float]:
        """Compute net executable expected value after all frictions and basis risk penalties."""
        if price is not None and self.cost_model is not None:
            liq = liquidity_usd if liquidity_usd is not None and liquidity_usd > 0 else 50_000.0
            cost_info = self.cost_model.calculate_cost(
                price=price,
                order_size_usd=order_size_usd,
                liquidity_usd=liq,
                observed_spread=market_spread,
                is_maker=is_maker,
                platform="polymarket"
            )
            spread_cost = cost_info["spread_cost"]
            slippage_cost = cost_info["slippage_cost"]
            fee_cost = cost_info["fee_cost"]
            total_friction = cost_info["total_friction"]
        else:
            spread = market_spread if market_spread is not None else self.default_spread
            fee_cost = 2.0 * self.taker_fee
            slippage_cost = 2.0 * self.slippage
            spread_cost = spread
            total_friction = spread_cost + fee_cost + slippage_cost

        # Basis risk adjustment
        p_div = resolution_analysis.prob_divergence
        # If mathematically guaranteed (structural tautology), divergence risk is 0.
        if resolution_analysis.is_mathematically_guaranteed or opportunity_class == OpportunityClass.STRUCTURAL:
            basis_risk_discount = 0.0
            net_edge_before_friction = raw_edge
        else:
            # Expected loss from divergence: with probability p_div, the trade diverges causing basis loss
            basis_risk_discount = p_div * self.divergence_weight * raw_edge
            net_edge_before_friction = (raw_edge * (1.0 - p_div)) - basis_risk_discount

        net_expected_value = net_edge_before_friction - total_friction
        is_executable = (net_expected_value >= self.min_edge)

        return {
            "raw_edge": raw_edge,
            "p_divergence": p_div,
            "basis_risk_discount": basis_risk_discount,
            "spread_cost": spread_cost,
            "fee_cost": fee_cost,
            "slippage_cost": slippage_cost,
            "total_friction": total_friction,
            "net_expected_value": net_expected_value,
            "is_executable": is_executable
        }
