"""Trade Structures and Executable Threshold Evaluator for Phase 10A.11-C.

Formalizes K-outcome mutually exclusive prediction market mechanics:
p_1 + p_2 + ... + p_K = 1

Evaluates:
- Structure A: Buy all outcomes (complete-set arbitrage: sum(ask_i) + costs < 1)
- Structure B: Sell all outcomes (shorting feasibility check on Polymarket CLOB)
- Structure C: Buy lagging outcome / sell leading outcome (statistical convergence)
- Structure D: Partial multi-leg basket (residual exposure quantified)

Calculates the exact required executable overhang threshold vs observed distribution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from src.phase10a11c import TradeStructure


@dataclass
class OutcomeBookState:
    token_id: str
    outcome_label: str
    best_bid: float
    best_ask: float
    midpoint: float
    depth_bid_usd: float
    depth_ask_usd: float
    spread_bps: float
    timestamp: Optional[Any] = None

    @property
    def bid_ask_spread(self) -> float:
        return max(0.0, self.best_ask - self.best_bid)


@dataclass
class MarketMultiOutcomeState:
    market_id: str
    outcomes: List[OutcomeBookState]
    timestamp: Any

    @property
    def k_outcomes(self) -> int:
        return len(self.outcomes)

    @property
    def sum_midpoints(self) -> float:
        return sum(o.midpoint for o in self.outcomes)

    @property
    def sum_best_asks(self) -> float:
        return sum(o.best_ask for o in self.outcomes)

    @property
    def sum_best_bids(self) -> float:
        return sum(o.best_bid for o in self.outcomes)

    @property
    def total_spread_bps(self) -> float:
        return sum(o.spread_bps for o in self.outcomes)

    @property
    def midpoint_overhang_bps(self) -> float:
        return (self.sum_midpoints - 1.0) * 10000.0

    @property
    def executable_overhang_bps(self) -> float:
        # If sum_best_asks < 1.0, positive executable buy overhang exists
        # Otherwise, buying all asks costs > 1.0, representing an immediate negative payoff
        return (1.0 - self.sum_best_asks) * 10000.0


@dataclass
class TradeStructureEvaluation:
    structure: TradeStructure
    is_feasible_on_venue: bool
    requires_shorting: bool
    entry_cost_usd: float
    settlement_payoff_usd: float
    gross_pnl_bps: float
    fee_bps: float
    slippage_bps: float
    net_pnl_bps: float
    residual_delta: float
    is_profitable: bool
    diagnostic_rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure": self.structure.value,
            "is_feasible_on_venue": self.is_feasible_on_venue,
            "requires_shorting": self.requires_shorting,
            "entry_cost_usd": round(self.entry_cost_usd, 4),
            "settlement_payoff_usd": round(self.settlement_payoff_usd, 4),
            "gross_pnl_bps": round(self.gross_pnl_bps, 2),
            "fee_bps": round(self.fee_bps, 2),
            "slippage_bps": round(self.slippage_bps, 2),
            "net_pnl_bps": round(self.net_pnl_bps, 2),
            "residual_delta": round(self.residual_delta, 4),
            "is_profitable": self.is_profitable,
            "diagnostic_rationale": self.diagnostic_rationale,
        }


@dataclass
class ExecutableThresholdDistribution:
    median_midpoint_overhang_bps: float
    pct_75_midpoint_overhang_bps: float
    pct_90_midpoint_overhang_bps: float
    pct_95_midpoint_overhang_bps: float
    max_midpoint_overhang_bps: float
    
    median_executable_overhang_bps: float
    pct_75_executable_overhang_bps: float
    pct_90_executable_overhang_bps: float
    pct_95_executable_overhang_bps: float
    max_executable_overhang_bps: float

    median_total_execution_cost_bps: float
    pct_95_total_execution_cost_bps: float
    required_profitable_overhang_bps: float
    pct_opportunities_exceeding_cost: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "median_midpoint_overhang_bps": round(self.median_midpoint_overhang_bps, 2),
            "pct_75_midpoint_overhang_bps": round(self.pct_75_midpoint_overhang_bps, 2),
            "pct_90_midpoint_overhang_bps": round(self.pct_90_midpoint_overhang_bps, 2),
            "pct_95_midpoint_overhang_bps": round(self.pct_95_midpoint_overhang_bps, 2),
            "max_midpoint_overhang_bps": round(self.max_midpoint_overhang_bps, 2),
            "median_executable_overhang_bps": round(self.median_executable_overhang_bps, 2),
            "pct_75_executable_overhang_bps": round(self.pct_75_executable_overhang_bps, 2),
            "pct_90_executable_overhang_bps": round(self.pct_90_executable_overhang_bps, 2),
            "pct_95_executable_overhang_bps": round(self.pct_95_executable_overhang_bps, 2),
            "max_executable_overhang_bps": round(self.max_executable_overhang_bps, 2),
            "median_total_execution_cost_bps": round(self.median_total_execution_cost_bps, 2),
            "pct_95_total_execution_cost_bps": round(self.pct_95_total_execution_cost_bps, 2),
            "required_profitable_overhang_bps": round(self.required_profitable_overhang_bps, 2),
            "pct_opportunities_exceeding_cost": round(self.pct_opportunities_exceeding_cost, 2),
        }


class TradeStructureEvaluator:
    """Evaluates the four candidate trade structures on multi-outcome state."""

    BASE_FEE_BPS_PER_LEG = 5.0    # 5 bps per leg taker fee
    DEFAULT_SLIPPAGE_BPS = 5.0     # 5 bps top level slippage

    def evaluate_structure_a_buy_all(self, state: MarketMultiOutcomeState, order_size_usd: float = 10.0) -> TradeStructureEvaluation:
        """Structure A: Buy all K outcomes at best asks.
        
        Arbitrage condition: sum(ask_i) + total_costs < 1.00
        At settlement, exactly one outcome pays 1.00; total payoff = 1.00.
        """
        sum_asks = state.sum_best_asks
        k = state.k_outcomes
        total_fee = k * self.BASE_FEE_BPS_PER_LEG
        total_slippage = k * self.DEFAULT_SLIPPAGE_BPS
        total_cost_bps = total_fee + total_slippage

        # Gross PnL in bps relative to entry cost
        gross_pnl_bps = ((1.0 - sum_asks) / sum_asks) * 10000.0 if sum_asks > 0 else 0.0
        net_pnl_bps = gross_pnl_bps - total_cost_bps

        is_profitable = net_pnl_bps > 0.0
        rationale = (
            f"Buy all {k} outcomes at sum(ask)={sum_asks:.4f}. Payoff=1.00. "
            f"Gross: {gross_pnl_bps:.1f} bps, Costs: {total_cost_bps:.1f} bps, Net: {net_pnl_bps:.1f} bps. "
            f"{'Profitable complete set' if is_profitable else 'Negative return: sum(asks) exceeds 1.00 + costs'}."
        )

        return TradeStructureEvaluation(
            structure=TradeStructure.STRUCTURE_A_BUY_ALL,
            is_feasible_on_venue=True,
            requires_shorting=False,
            entry_cost_usd=sum_asks * (order_size_usd / k),
            settlement_payoff_usd=1.00 * (order_size_usd / k),
            gross_pnl_bps=gross_pnl_bps,
            fee_bps=total_fee,
            slippage_bps=total_slippage,
            net_pnl_bps=net_pnl_bps,
            residual_delta=0.0,  # Perfectly delta-neutral
            is_profitable=is_profitable,
            diagnostic_rationale=rationale,
        )

    def evaluate_structure_b_short_all(self, state: MarketMultiOutcomeState, order_size_usd: float = 10.0) -> TradeStructureEvaluation:
        """Structure B: Sell/short all outcomes at best bids.
        
        CRITICAL VENUE CHECK: Polymarket CLOB operates on ERC-1155 tokens.
        Naked shorting is NOT supported. To sell tokens, a trader must already own them
        or mint a complete set by locking 1.00 USDC collateral.
        Minting complete sets costs 1.00 USDC. Selling both at sum(bid) < 1.00 guarantees
        an immediate loss of (1.00 - sum(bid)) + fees.
        """
        sum_bids = state.sum_best_bids
        k = state.k_outcomes
        total_fee = k * self.BASE_FEE_BPS_PER_LEG

        # Mint set for 1.00, sell for sum_bids
        gross_pnl_bps = (sum_bids - 1.0) * 10000.0
        net_pnl_bps = gross_pnl_bps - total_fee

        rationale = (
            f"Polymarket CLOB does NOT support naked shorting. Minting complete set requires 1.00 USDC. "
            f"Selling at sum(bid)={sum_bids:.4f} incurs an immediate loss of {gross_pnl_bps:.1f} bps gross "
            f"and {net_pnl_bps:.1f} bps net. Venue structural constraint prevents unhedged shorting."
        )

        return TradeStructureEvaluation(
            structure=TradeStructure.STRUCTURE_B_SHORT_ALL,
            is_feasible_on_venue=False,  # Naked shorting is prohibited
            requires_shorting=True,
            entry_cost_usd=1.00 * (order_size_usd / k),
            settlement_payoff_usd=sum_bids * (order_size_usd / k),
            gross_pnl_bps=gross_pnl_bps,
            fee_bps=total_fee,
            slippage_bps=k * self.DEFAULT_SLIPPAGE_BPS,
            net_pnl_bps=net_pnl_bps,
            residual_delta=0.0,
            is_profitable=False,
            diagnostic_rationale=rationale,
        )

    def evaluate_structure_c_lag_lead(self, state: MarketMultiOutcomeState, order_size_usd: float = 10.0) -> TradeStructureEvaluation:
        """Structure C: Statistical convergence (buy lagging outcome at ask, sell leading at bid).
        
        Requires shorting leading outcome or holding inventory.
        Evaluates convergence edge vs crossing spread on both legs.
        """
        if state.k_outcomes < 2:
            return TradeStructureEvaluation(
                structure=TradeStructure.STRUCTURE_C_LAG_LEAD,
                is_feasible_on_venue=False,
                requires_shorting=True,
                entry_cost_usd=0.0,
                settlement_payoff_usd=0.0,
                gross_pnl_bps=0.0,
                fee_bps=0.0,
                slippage_bps=0.0,
                net_pnl_bps=0.0,
                residual_delta=0.0,
                is_profitable=False,
                diagnostic_rationale="Insufficient outcomes for lead-lag pair",
            )

        # Identify leader and lagger
        o1, o2 = state.outcomes[0], state.outcomes[1]
        midpoint_overhang = abs(state.sum_midpoints - 1.0) * 10000.0

        # Crossing spread on lagger (buy at ask) and leader (sell at bid)
        # Combined spread penalty
        spread_penalty_bps = (o1.spread_bps + o2.spread_bps) * 0.5
        total_fee = 2 * self.BASE_FEE_BPS_PER_LEG
        total_slippage = 2 * self.DEFAULT_SLIPPAGE_BPS
        
        # Expected convergence recovers half of the midpoint overhang
        expected_convergence_bps = midpoint_overhang * 0.5
        net_pnl_bps = expected_convergence_bps - spread_penalty_bps - total_fee - total_slippage

        is_profitable = net_pnl_bps > 0.0
        rationale = (
            f"Statistical convergence: expected recovery {expected_convergence_bps:.1f} bps vs "
            f"spread penalty {spread_penalty_bps:.1f} bps and costs {total_fee + total_slippage:.1f} bps. "
            f"Net: {net_pnl_bps:.1f} bps. {'Profitable convergence' if is_profitable else 'Spread swallows statistical edge'}."
        )

        return TradeStructureEvaluation(
            structure=TradeStructure.STRUCTURE_C_LAG_LEAD,
            is_feasible_on_venue=False,  # Requires shorting leader, which requires inventory/minting
            requires_shorting=True,
            entry_cost_usd=order_size_usd,
            settlement_payoff_usd=order_size_usd * (1.0 + net_pnl_bps / 10000.0),
            gross_pnl_bps=expected_convergence_bps - spread_penalty_bps,
            fee_bps=total_fee,
            slippage_bps=total_slippage,
            net_pnl_bps=net_pnl_bps,
            residual_delta=0.0,
            is_profitable=is_profitable,
            diagnostic_rationale=rationale,
        )

    def evaluate_structure_d_partial_basket(
        self, state: MarketMultiOutcomeState, order_size_usd: float = 10.0
    ) -> TradeStructureEvaluation:
        """Structure D: Partial basket (buy lagging outcome only, without shorting leader).
        
        Carries full directional market risk on the lagging outcome.
        NOT an arbitrage: residual delta = 1.0.
        """
        if not state.outcomes:
            return TradeStructureEvaluation(
                structure=TradeStructure.STRUCTURE_D_PARTIAL_BASKET,
                is_feasible_on_venue=False,
                requires_shorting=False,
                entry_cost_usd=0.0,
                settlement_payoff_usd=0.0,
                gross_pnl_bps=0.0,
                fee_bps=0.0,
                slippage_bps=0.0,
                net_pnl_bps=0.0,
                residual_delta=1.0,
                is_profitable=False,
                diagnostic_rationale="No outcomes available",
            )

        # Buy single lagger at ask
        lagger = min(state.outcomes, key=lambda o: o.midpoint)
        spread_penalty = lagger.spread_bps
        expected_drift = abs(state.sum_midpoints - 1.0) * 5000.0  # expected reversion 50 bps
        total_fee = self.BASE_FEE_BPS_PER_LEG
        total_slippage = self.DEFAULT_SLIPPAGE_BPS

        net_pnl_bps = expected_drift - spread_penalty - total_fee - total_slippage
        is_profitable = net_pnl_bps > 0.0

        rationale = (
            f"Partial unhedged long on lagger {lagger.outcome_label}. "
            f"Residual directional delta = 1.00. Expected drift {expected_drift:.1f} bps vs "
            f"spread {spread_penalty:.1f} bps. Net: {net_pnl_bps:.1f} bps. High directional volatility."
        )

        return TradeStructureEvaluation(
            structure=TradeStructure.STRUCTURE_D_PARTIAL_BASKET,
            is_feasible_on_venue=True,
            requires_shorting=False,
            entry_cost_usd=order_size_usd,
            settlement_payoff_usd=order_size_usd * (1.0 + net_pnl_bps / 10000.0),
            gross_pnl_bps=expected_drift - spread_penalty,
            fee_bps=total_fee,
            slippage_bps=total_slippage,
            net_pnl_bps=net_pnl_bps,
            residual_delta=1.0,
            is_profitable=is_profitable,
            diagnostic_rationale=rationale,
        )

    def compute_executable_threshold_distribution(
        self, states: List[MarketMultiOutcomeState]
    ) -> ExecutableThresholdDistribution:
        """Computes empirical distribution of midpoint overhang, executable overhang, and execution costs."""
        if not states:
            return ExecutableThresholdDistribution(
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            )

        mid_overhangs = [abs(s.midpoint_overhang_bps) for s in states]
        exec_overhangs = [s.executable_overhang_bps for s in states]
        
        # Total execution cost = combined spread + taker fees (20 bps) + slippage (10 bps) + latency/leg-risk (30 bps)
        total_costs = [s.total_spread_bps + 20.0 + 10.0 + 30.0 for s in states]

        req_overhang = float(np.median(total_costs))
        exceeding = sum(1 for eo, tc in zip(exec_overhangs, total_costs) if eo > tc)
        pct_exceeding = (exceeding / len(states)) * 100.0 if states else 0.0

        return ExecutableThresholdDistribution(
            median_midpoint_overhang_bps=float(np.median(mid_overhangs)),
            pct_75_midpoint_overhang_bps=float(np.percentile(mid_overhangs, 75)),
            pct_90_midpoint_overhang_bps=float(np.percentile(mid_overhangs, 90)),
            pct_95_midpoint_overhang_bps=float(np.percentile(mid_overhangs, 95)),
            max_midpoint_overhang_bps=float(np.max(mid_overhangs)),
            median_executable_overhang_bps=float(np.median(exec_overhangs)),
            pct_75_executable_overhang_bps=float(np.percentile(exec_overhangs, 75)),
            pct_90_executable_overhang_bps=float(np.percentile(exec_overhangs, 90)),
            pct_95_executable_overhang_bps=float(np.percentile(exec_overhangs, 95)),
            max_executable_overhang_bps=float(np.max(exec_overhangs)),
            median_total_execution_cost_bps=float(np.median(total_costs)),
            pct_95_total_execution_cost_bps=float(np.percentile(total_costs, 95)),
            required_profitable_overhang_bps=req_overhang,
            pct_opportunities_exceeding_cost=pct_exceeding,
        )
