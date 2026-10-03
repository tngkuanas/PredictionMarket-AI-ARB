"""Atomic Routing and Leg-Risk Simulator for Phase 10A.11-C.

Implements:
- Multi-leg execution simulator across discrete latencies (0ms to 10s)
- All K! leg-order permutation simulations (worst-leg vs average-leg slippage)
- 8 partial-fill and failure scenarios
- Size/capacity tiers ($1 to $1,000)
- Latency boundary and half-life decay estimation
"""

from dataclasses import dataclass, field
import itertools
import math
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from src.phase10a11c import RoutingMode, FailureScenario
from src.phase10a11c.trade_structures import MarketMultiOutcomeState, OutcomeBookState


@dataclass
class LatencyProfileResult:
    latency_label: str
    latency_ms: float
    all_legs_fill_prob: float
    one_leg_fail_prob: float
    residual_exposure_delta: float
    expected_hedge_cost_bps: float
    gross_ev_bps: float
    fees_bps: float
    slippage_bps: float
    net_ev_bps: float
    is_profitable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latency_label": self.latency_label,
            "latency_ms": self.latency_ms,
            "all_legs_fill_prob": round(self.all_legs_fill_prob, 4),
            "one_leg_fail_prob": round(self.one_leg_fail_prob, 4),
            "residual_exposure_delta": round(self.residual_exposure_delta, 4),
            "expected_hedge_cost_bps": round(self.expected_hedge_cost_bps, 2),
            "gross_ev_bps": round(self.gross_ev_bps, 2),
            "fees_bps": round(self.fees_bps, 2),
            "slippage_bps": round(self.slippage_bps, 2),
            "net_ev_bps": round(self.net_ev_bps, 2),
            "is_profitable": self.is_profitable,
        }


@dataclass
class LegOrderPermutationResult:
    sequence: Tuple[str, ...]
    worst_leg_slippage_bps: float
    avg_leg_slippage_bps: float
    residual_exposure: float
    completion_probability: float
    expected_hedge_loss_bps: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": list(self.sequence),
            "worst_leg_slippage_bps": round(self.worst_leg_slippage_bps, 2),
            "avg_leg_slippage_bps": round(self.avg_leg_slippage_bps, 2),
            "residual_exposure": round(self.residual_exposure, 4),
            "completion_probability": round(self.completion_probability, 4),
            "expected_hedge_loss_bps": round(self.expected_hedge_loss_bps, 2),
        }


@dataclass
class PartialFillScenarioResult:
    scenario: FailureScenario
    description: str
    fill_fraction: float
    residual_directional_exposure: float
    realized_slippage_bps: float
    liquidation_penalty_bps: float
    final_portfolio_pnl_bps: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "description": self.description,
            "fill_fraction": round(self.fill_fraction, 2),
            "residual_directional_exposure": round(self.residual_directional_exposure, 2),
            "realized_slippage_bps": round(self.realized_slippage_bps, 2),
            "liquidation_penalty_bps": round(self.liquidation_penalty_bps, 2),
            "final_portfolio_pnl_bps": round(self.final_portfolio_pnl_bps, 2),
        }


@dataclass
class CapacityEvaluationResult:
    size_usd: float
    all_leg_fill_prob: float
    executable_basket_vwap: float
    fees_bps: float
    slippage_bps: float
    residual_exposure: float
    net_ev_bps: float
    expected_pnl_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "size_usd": self.size_usd,
            "all_leg_fill_prob": round(self.all_leg_fill_prob, 4),
            "executable_basket_vwap": round(self.executable_basket_vwap, 4),
            "fees_bps": round(self.fees_bps, 2),
            "slippage_bps": round(self.slippage_bps, 2),
            "residual_exposure": round(self.residual_exposure, 4),
            "net_ev_bps": round(self.net_ev_bps, 2),
            "expected_pnl_usd": round(self.expected_pnl_usd, 4),
        }


class AtomicRoutingSimulator:
    """Simulates realistic multi-leg routing for M3."""

    LATENCY_SWEEP_MS = [
        ("0ms (Ideal Atomic)", 0.0),
        ("10ms", 10.0),
        ("25ms", 25.0),
        ("50ms", 50.0),
        ("100ms", 100.0),
        ("250ms", 250.0),
        ("500ms", 500.0),
        ("1s", 1000.0),
        ("2s", 2000.0),
        ("5s", 5000.0),
        ("10s", 10000.0),
    ]

    CAPACITY_TIERS_USD = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]

    def __init__(self, base_fee_bps: float = 10.0, half_life_sec: float = 1.85):
        self.base_fee_bps = base_fee_bps
        self.half_life_sec = half_life_sec

    def evaluate_latency_sweep(self, state: MarketMultiOutcomeState) -> Dict[str, LatencyProfileResult]:
        """Evaluates net EV across discrete latencies (0ms to 10s)."""
        results: Dict[str, LatencyProfileResult] = {}
        k = max(2, state.k_outcomes)

        # Baseline spread and fees
        comb_spread = state.total_spread_bps
        taker_fee = k * self.base_fee_bps

        for label, ms in self.LATENCY_SWEEP_MS:
            # Atomic (0ms): If venue had atomic bundle routing
            if ms == 0.0:
                fill_prob = 1.0
                fail_prob = 0.0
                slippage = 5.0 * k
                hedge_cost = 0.0
                res_exp = 0.0
            else:
                # Latency-dependent probability of quote expiration / preemption
                # Arrival rate lambda ~ 0.5 per sec
                time_s = ms / 1000.0
                leg_fill_prob = math.exp(-0.4 * time_s)
                fill_prob = leg_fill_prob ** k
                fail_prob = 1.0 - fill_prob
                slippage = (5.0 + 15.0 * (1.0 - math.exp(-time_s))) * k
                hedge_cost = fail_prob * (comb_spread * 0.5)  # liquidation cost of unhedged leg
                res_exp = fail_prob * (1.0 / k)

            # Theoretical gross edge from sum-to-one imbalance decaying with half-life 1.85s
            decay = math.exp(-math.log(2.0) * (ms / 1000.0) / self.half_life_sec)
            initial_overhang = abs(state.midpoint_overhang_bps)
            gross_edge = initial_overhang * decay

            # Executable returns must cross the combined spread of all legs!
            # Since sum_best_asks >= 1.0 (mean comb_spread ~ 1,000 bps), crossing spread incurs negative gross PnL
            spread_crossing_loss = comb_spread * 0.5
            executable_gross_ev = gross_edge - spread_crossing_loss

            net_ev = executable_gross_ev - taker_fee - slippage - hedge_cost
            is_prof = net_ev > 0.0

            results[label] = LatencyProfileResult(
                latency_label=label,
                latency_ms=ms,
                all_legs_fill_prob=fill_prob,
                one_leg_fail_prob=fail_prob,
                residual_exposure_delta=res_exp,
                expected_hedge_cost_bps=hedge_cost,
                gross_ev_bps=executable_gross_ev,
                fees_bps=taker_fee,
                slippage_bps=slippage,
                net_ev_bps=net_ev,
                is_profitable=is_prof,
            )

        return results

    def simulate_leg_order_permutations(
        self, state: MarketMultiOutcomeState, inter_leg_latency_ms: float = 50.0
    ) -> List[LegOrderPermutationResult]:
        """Simulates all K! leg execution sequences."""
        labels = [o.outcome_label for o in state.outcomes]
        permutations = list(itertools.permutations(labels))
        results: List[LegOrderPermutationResult] = []

        for seq in permutations:
            # Simulate sequential fill: each subsequent leg incurs adverse selection
            n = len(seq)
            slippages = []
            for idx in range(n):
                # Earlier legs experience less slippage than later legs
                # Latency accumulates: idx * inter_leg_latency_ms
                t_sec = (idx * inter_leg_latency_ms) / 1000.0
                leg_slip = 5.0 + (idx * 12.0) * (1.0 + t_sec)
                slippages.append(leg_slip)

            worst_slip = max(slippages)
            avg_slip = float(np.mean(slippages))

            # Completion probability drops as sequence progresses
            completion_prob = max(0.20, 1.0 - (0.08 * (n - 1)))
            residual_exp = (1.0 - completion_prob) * (1.0 / n)
            expected_hedge_loss = (1.0 - completion_prob) * (state.total_spread_bps * 0.5)

            results.append(
                LegOrderPermutationResult(
                    sequence=seq,
                    worst_leg_slippage_bps=worst_slip,
                    avg_leg_slippage_bps=avg_slip,
                    residual_exposure=residual_exp,
                    completion_probability=completion_prob,
                    expected_hedge_loss_bps=expected_hedge_loss,
                )
            )

        return results

    def simulate_partial_fill_scenarios(
        self, state: MarketMultiOutcomeState, base_spread_bps: float = 500.0
    ) -> List[PartialFillScenarioResult]:
        """Simulates 8 distinct execution failure scenarios."""
        scenarios = [
            (
                FailureScenario.FIRST_LEG_FILLS_SECOND_FAILS,
                "First leg filled at ask; second leg quote was canceled, leaving 100% unhedged directional exposure.",
                0.50, 0.50, 25.0, 250.0, -275.0,
            ),
            (
                FailureScenario.FIRST_TWO_FILL_FINAL_FAILS,
                "First 2 legs filled in 3-outcome basket; 3rd leg failed on insufficient liquidity.",
                0.67, 0.33, 30.0, 320.0, -350.0,
            ),
            (
                FailureScenario.PARTIAL_DEPTH_FILL,
                "Top level partially filled (40% of desired size); remaining quantity sat in queue and was canceled.",
                0.40, 0.20, 15.0, 100.0, -115.0,
            ),
            (
                FailureScenario.STALE_QUOTE,
                "Second leg targeted stale quote; matching engine rejected due to min tick or post-only flag.",
                0.50, 0.50, 10.0, 260.0, -270.0,
            ),
            (
                FailureScenario.QUOTE_WITHDRAWAL,
                "Market maker withdrew liquidity across all outcomes simultaneously during order dispatch.",
                0.00, 0.00, 0.0, 0.0, -10.0,  # missed opportunity cost + fee
            ),
            (
                FailureScenario.ADVERSE_PRICE_MOVE_BEFORE_FINAL_LEG,
                "Adverse toxic flow moved final leg price 3 ticks worse before fill was confirmed.",
                1.00, 0.00, 85.0, 0.0, -105.0,
            ),
            (
                FailureScenario.WEBSOCKET_LATENCY,
                "WebSocket message delayed by 650ms; book state was already stale upon arrival.",
                0.50, 0.50, 40.0, 280.0, -320.0,
            ),
            (
                FailureScenario.ORDER_REJECTION,
                "Matching engine returned ERR_ALLOWANCE / ERR_BALANCE during second leg execution.",
                0.50, 0.50, 5.0, 250.0, -255.0,
            ),
        ]

        results = []
        for scen, desc, fill_frac, delta, slip, liq, pnl in scenarios:
            # Scale by actual combined spread
            scaled_pnl = pnl * (state.total_spread_bps / max(100.0, base_spread_bps))
            results.append(
                PartialFillScenarioResult(
                    scenario=scen,
                    description=desc,
                    fill_fraction=fill_frac,
                    residual_directional_exposure=delta,
                    realized_slippage_bps=slip,
                    liquidation_penalty_bps=liq,
                    final_portfolio_pnl_bps=scaled_pnl,
                )
            )

        return results

    def evaluate_capacity_tiers(self, state: MarketMultiOutcomeState) -> List[CapacityEvaluationResult]:
        """Evaluates execution quality across size tiers ($1 to $1,000)."""
        k = max(2, state.k_outcomes)
        results = []

        # Available depth at top of book
        min_depth = min(o.depth_ask_usd for o in state.outcomes) if state.outcomes else 10.0

        for size in self.CAPACITY_TIERS_USD:
            # Fill probability decays rapidly when order size exceeds top-of-book depth
            if size <= min_depth:
                fill_prob = 0.95
                slippage = 5.0 * k
                levels_consumed = 1.0
            elif size <= min_depth * 3.0:
                fill_prob = 0.80
                slippage = 18.0 * k
                levels_consumed = 2.2
            elif size <= min_depth * 10.0:
                fill_prob = 0.55
                slippage = 45.0 * k
                levels_consumed = 4.0
            else:
                fill_prob = 0.25
                slippage = 120.0 * k
                levels_consumed = 7.5

            fee = k * self.base_fee_bps
            # Basket VWAP = sum(asks) + slippage
            basket_vwap = state.sum_best_asks * (1.0 + slippage / 10000.0)
            residual_exposure = (1.0 - fill_prob) * 0.5

            # Gross edge from overhang (-spread_crossing)
            gross_pnl_bps = -state.total_spread_bps * 0.5 + abs(state.midpoint_overhang_bps) * 0.5
            net_ev = gross_pnl_bps - fee - slippage - (1.0 - fill_prob) * 150.0
            expected_pnl_usd = size * (net_ev / 10000.0)

            results.append(
                CapacityEvaluationResult(
                    size_usd=size,
                    all_leg_fill_prob=fill_prob,
                    executable_basket_vwap=basket_vwap,
                    fees_bps=fee,
                    slippage_bps=slippage,
                    residual_exposure=residual_exposure,
                    net_ev_bps=net_ev,
                    expected_pnl_usd=expected_pnl_usd,
                )
            )

        return results

    def find_latency_boundary(self, sweep_results: Dict[str, LatencyProfileResult]) -> float:
        """Determines the maximum latency in ms at which positive net EV survives.
        
        Returns 0.0 if even 0ms ideal atomic has negative net EV.
        """
        for label, res in sweep_results.items():
            if res.is_profitable:
                return res.latency_ms
        return 0.0
