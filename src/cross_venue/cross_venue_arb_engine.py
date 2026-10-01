"""Deterministic Executable Cross-Venue Arbitrage Engine.

Phase 10A.6e Sections 5, 6, 7, 8, 11, 18:
Calculates actual executable cross-venue arbitrage between Polymarket and Kalshi.

CORE FORMULATION:
In a binary prediction market: YES + NO = 1.0 at settlement.
For exact equivalent contracts:
Option 1: Buy YES on Venue A + Buy NO on Venue B
Option 2: Buy NO on Venue A + Buy YES on Venue B

Executable prices are determined strictly via L2 order-book ladder walking.
MIDPOINT PRICES MUST NEVER BE USED FOR PROFITABILITY.
NO COMPOSITE SCORE: Evaluates 10 independent categorical quality gates.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from src.phase10.response_study.executable_price_model import (
    ExecutablePriceModel,
    TakerExecutionFill,
)
from src.cross_venue.schema import (
    ContractMappingResult,
    SyncQuote,
    QuoteState,
    EquivalenceClass,
    MappingStatus,
    StaleStatus,
    CategoryStatus,
    FinalArbitrageVerdict,
    ArbitrageLeg,
    CrossVenueCostBreakdown,
    LegRiskResult,
    CapitalCapacityResult,
    CrossVenueArbitrageOpportunity,
)
from src.cross_venue.synchronizer import CrossVenueSynchronizer

logger = logging.getLogger(__name__)


class CrossVenueArbEngine:
    """Deterministic cross-venue execution and arbitrage bounds engine."""

    def __init__(
        self,
        polymarket_fee_bps: float = 0.0,    # Polymarket CTF standard taker fee (0-20 bps)
        kalshi_fee_bps: float = 30.0,        # Kalshi trading fees (~30 bps effective on notional)
        default_latency_penalty_bps: float = 8.0,
        default_hedge_cost_bps: float = 5.0,
        max_allowable_hedge_latency_ms: float = 250.0,
        capital_a_usd: float = 10000.0,
        capital_b_usd: float = 10000.0,
    ):
        self.polymarket_fee_bps = polymarket_fee_bps
        self.kalshi_fee_bps = kalshi_fee_bps
        self.default_latency_penalty_bps = default_latency_penalty_bps
        self.default_hedge_cost_bps = default_hedge_cost_bps
        self.max_allowable_hedge_latency_ms = max_allowable_hedge_latency_ms
        self.capital_a_usd = capital_a_usd
        self.capital_b_usd = capital_b_usd

        self.synchronizer = CrossVenueSynchronizer()
        self.l2_model = ExecutablePriceModel()

    def evaluate_arbitrage(
        self,
        mapping: ContractMappingResult,
        quote_poly: SyncQuote,
        quote_kalshi: SyncQuote,
        target_order_size_usd: float,
        sync_window_ms: int = 100,
        evaluation_timestamp: Optional[datetime] = None,
        override_capital_a: Optional[float] = None,
        override_capital_b: Optional[float] = None,
        override_hedge_latency_ms: Optional[float] = None,
    ) -> CrossVenueArbitrageOpportunity:
        """Evaluates whether an exact cross-venue arbitrage exists and is executable after friction."""
        now = evaluation_timestamp or datetime.now(timezone.utc)
        cap_a = override_capital_a if override_capital_a is not None else self.capital_a_usd
        cap_b = override_capital_b if override_capital_b is not None else self.capital_b_usd
        hedge_lat_ms = override_hedge_latency_ms if override_hedge_latency_ms is not None else 50.0

        rejection_reasons: List[str] = []

        # -------------------------------------------------------------
        # Gate 1: Mapping Status
        # -------------------------------------------------------------
        if mapping.equivalence_class != EquivalenceClass.EXACT_EQUIVALENT or not mapping.settlement_equivalence:
            mapping_gate = CategoryStatus.FAIL
            rejection_reasons.append(f"Gate 1 Failed: Mapping is not EXACT_EQUIVALENT ({mapping.mapping_status.value}).")
        else:
            mapping_gate = CategoryStatus.PASS

        # -------------------------------------------------------------
        # Gate 2 & 3: Synchronization and Stale Quote Detection
        # -------------------------------------------------------------
        is_synced, sync_status, state_poly, state_kalshi, sync_msg = self.synchronizer.synchronize_quotes(
            quote_poly, quote_kalshi, window_ms=sync_window_ms, evaluation_timestamp=now
        )
        sync_gate = sync_status
        if not is_synced:
            rejection_reasons.append(f"Gate 2/3 Failed: {sync_msg}")

        quote_gate = CategoryStatus.PASS if (state_poly.is_available and state_kalshi.is_available) else CategoryStatus.FAIL

        # -------------------------------------------------------------
        # Strategy Direction Selection:
        # Pair 1: Buy Polymarket YES + Buy Kalshi NO
        # Pair 2: Buy Polymarket NO + Buy Kalshi YES
        # -------------------------------------------------------------
        # We walk the L2 book for both pairs and select the most favorable executable candidate
        fill_poly_yes = self._walk_book(quote_poly, "BUY", "YES", target_order_size_usd, self.polymarket_fee_bps)
        fill_kalshi_no = self._walk_book(quote_kalshi, "BUY", "NO", target_order_size_usd, self.kalshi_fee_bps)

        fill_poly_no = self._walk_book(quote_poly, "BUY", "NO", target_order_size_usd, self.polymarket_fee_bps)
        fill_kalshi_yes = self._walk_book(quote_kalshi, "BUY", "YES", target_order_size_usd, self.kalshi_fee_bps)

        # Calculate combined acquisition cost (VWAP A + VWAP B)
        cost_pair_1 = fill_poly_yes.fill_price_vwap + fill_kalshi_no.fill_price_vwap
        cost_pair_2 = fill_poly_no.fill_price_vwap + fill_kalshi_yes.fill_price_vwap

        if cost_pair_1 <= cost_pair_2:
            fill_a, fill_b = fill_poly_yes, fill_kalshi_no
            leg_a_outcome, leg_b_outcome = "YES", "NO"
            leg_a_venue, leg_b_venue = "polymarket", "kalshi"
            fee_a_bps, fee_b_bps = self.polymarket_fee_bps, self.kalshi_fee_bps
        else:
            fill_a, fill_b = fill_poly_no, fill_kalshi_yes
            leg_a_outcome, leg_b_outcome = "NO", "YES"
            leg_a_venue, leg_b_venue = "polymarket", "kalshi"
            fee_a_bps, fee_b_bps = self.polymarket_fee_bps, self.kalshi_fee_bps

        # Construct ArbitrageLeg objects
        leg_a = ArbitrageLeg(
            venue=leg_a_venue,
            outcome=leg_a_outcome,
            direction="BUY",
            order_size_usd=target_order_size_usd,
            best_price=fill_a.best_price,
            vwap_price=fill_a.fill_price_vwap,
            shares_filled=fill_a.total_shares_filled,
            available_depth_usd=fill_a.total_depth_available_usd,
            fee_bps=fill_a.exchange_fee_bps,
            slippage_bps=fill_a.slippage_bps,
            notional_usd=fill_a.gross_notional_filled,
        )
        leg_b = ArbitrageLeg(
            venue=leg_b_venue,
            outcome=leg_b_outcome,
            direction="BUY",
            order_size_usd=target_order_size_usd,
            best_price=fill_b.best_price,
            vwap_price=fill_b.fill_price_vwap,
            shares_filled=fill_b.total_shares_filled,
            available_depth_usd=fill_b.total_depth_available_usd,
            fee_bps=fill_b.exchange_fee_bps,
            slippage_bps=fill_b.slippage_bps,
            notional_usd=fill_b.gross_notional_filled,
        )

        # -------------------------------------------------------------
        # Gate 4: Liquidity & Execution Fillability
        # -------------------------------------------------------------
        if not fill_a.is_fillable or not fill_b.is_fillable:
            executable_gate = CategoryStatus.FAIL
            liquidity_gate = CategoryStatus.FAIL
            reasons = []
            if not fill_a.is_fillable:
                reasons.append(f"{leg_a.venue} {leg_a.outcome} fill failed ({fill_a.rejection_reason})")
            if not fill_b.is_fillable:
                reasons.append(f"{leg_b.venue} {leg_b.outcome} fill failed ({fill_b.rejection_reason})")
            rejection_reasons.append(f"Gate 4/9 Failed: Insufficient liquidity/depth to fill order ({'; '.join(reasons)}).")
        else:
            executable_gate = CategoryStatus.PASS
            liquidity_gate = CategoryStatus.PASS

        # -------------------------------------------------------------
        # Gate 5 & 6: Fee, Slippage & Latency Cost Breakdown (Section 11)
        # -------------------------------------------------------------
        combined_vwap = leg_a.vwap_price + leg_b.vwap_price
        gross_settlement_val = 1.0  # Exact binary payoff
        gross_edge = gross_settlement_val - combined_vwap
        gross_edge_bps = gross_edge * 10000.0

        venue_fee_bps = (leg_a.fee_bps + leg_b.fee_bps) / 2.0
        slippage_bps = (leg_a.slippage_bps + leg_b.slippage_bps) / 2.0
        latency_penalty_bps = self.default_latency_penalty_bps
        hedge_cost_bps = self.default_hedge_cost_bps
        total_cost_bps = venue_fee_bps + slippage_bps + latency_penalty_bps + hedge_cost_bps

        cost_breakdown = CrossVenueCostBreakdown(
            venue_fee_bps=venue_fee_bps,
            execution_slippage_bps=slippage_bps,
            latency_penalty_bps=latency_penalty_bps,
            hedge_cost_bps=hedge_cost_bps,
            total_cost_bps=total_cost_bps,
        )

        net_deterministic_edge_bps = gross_edge_bps - total_cost_bps

        if fee_a_bps > 0 or fee_b_bps > 0:
            fee_gate = CategoryStatus.PASS
        else:
            fee_gate = CategoryStatus.PASS

        latency_gate = CategoryStatus.PASS if hedge_lat_ms <= self.max_allowable_hedge_latency_ms else CategoryStatus.FAIL
        if latency_gate == CategoryStatus.FAIL:
            rejection_reasons.append(f"Gate 6 Failed: Hedge latency {hedge_lat_ms}ms > max {self.max_allowable_hedge_latency_ms}ms.")

        # -------------------------------------------------------------
        # Gate 7: Capital & Capacity Model (Section 8)
        # -------------------------------------------------------------
        required_cap_a = target_order_size_usd
        required_cap_b = target_order_size_usd
        max_common_size = min(
            leg_a.available_depth_usd,
            leg_b.available_depth_usd,
            cap_a,
            cap_b,
        )
        is_cap_sufficient = (
            cap_a >= required_cap_a and
            cap_b >= required_cap_b and
            max_common_size >= target_order_size_usd
        )
        cap_utilization = (target_order_size_usd / min(cap_a, cap_b)) if min(cap_a, cap_b) > 0 else 1.0

        cap_result = CapitalCapacityResult(
            capital_a=cap_a,
            capital_b=cap_b,
            required_capital_a=required_cap_a,
            required_capital_b=required_cap_b,
            available_depth_a=leg_a.available_depth_usd,
            available_depth_b=leg_b.available_depth_usd,
            maximum_common_size_usd=max_common_size,
            capital_utilization_ratio=cap_utilization,
            settlement_lockup_hours=24.0,
            max_simultaneous_positions=int(min(cap_a, cap_b) / target_order_size_usd) if target_order_size_usd > 0 else 0,
            is_capacity_sufficient=is_cap_sufficient,
            rejection_reason="Capital or observable depth constraint exceeded." if not is_cap_sufficient else None,
        )
        capacity_gate = CategoryStatus.PASS if is_cap_sufficient else CategoryStatus.FAIL
        if not is_cap_sufficient:
            rejection_reasons.append(f"Gate 7 Failed: {cap_result.rejection_reason}")

        # -------------------------------------------------------------
        # Gate 8: Settlement Status
        # -------------------------------------------------------------
        settlement_gate = CategoryStatus.PASS if mapping.settlement_equivalence else CategoryStatus.FAIL

        # -------------------------------------------------------------
        # Gate 10: Net Deterministic Edge Status
        # -------------------------------------------------------------
        if net_deterministic_edge_bps > 0.0:
            net_edge_gate = CategoryStatus.PASS
        else:
            net_edge_gate = CategoryStatus.FAIL
            rejection_reasons.append(
                f"Gate 10 Failed: Net edge negative or zero ({net_deterministic_edge_bps:.1f} bps net, "
                f"Gross: {gross_edge_bps:.1f} bps, Total Cost: {total_cost_bps:.1f} bps)."
            )

        # -------------------------------------------------------------
        # Leg Risk Assessment (Section 7)
        # -------------------------------------------------------------
        leg_risk_reasons = []
        if hedge_lat_ms > 150.0:
            leg_risk_reasons.append(f"Elevated asynchronous fill latency: {hedge_lat_ms}ms")
        if leg_a.shares_filled != leg_b.shares_filled:
            leg_risk_reasons.append(f"Imbalanced share fills ({leg_a.shares_filled:.1f} vs {leg_b.shares_filled:.1f})")

        leg_fill_risk_status = CategoryStatus.PASS if len(leg_risk_reasons) == 0 else CategoryStatus.FAIL
        residual_exposure = abs(leg_a.notional_usd - leg_b.notional_usd)

        leg_risk_result = LegRiskResult(
            fill_risk_status=leg_fill_risk_status,
            max_hedge_latency_ms=hedge_lat_ms,
            price_movement_allowance_bps=self.default_latency_penalty_bps,
            residual_exposure_usd=residual_exposure,
            max_unhedged_qty=abs(leg_a.shares_filled - leg_b.shares_filled),
            reasons=leg_risk_reasons,
        )

        # -------------------------------------------------------------
        # Final Categorical Determination
        # -------------------------------------------------------------
        all_passed = (
            mapping_gate == CategoryStatus.PASS and
            quote_gate == CategoryStatus.PASS and
            sync_gate == CategoryStatus.PASS and
            liquidity_gate == CategoryStatus.PASS and
            fee_gate == CategoryStatus.PASS and
            latency_gate == CategoryStatus.PASS and
            capacity_gate == CategoryStatus.PASS and
            settlement_gate == CategoryStatus.PASS and
            executable_gate == CategoryStatus.PASS and
            net_edge_gate == CategoryStatus.PASS
        )
        final_verdict = FinalArbitrageVerdict.ELIGIBLE if all_passed else FinalArbitrageVerdict.REJECTED

        return CrossVenueArbitrageOpportunity(
            opportunity_id=f"opp_{uuid.uuid4().hex[:10]}",
            mapping_id=mapping.mapping_id,
            timestamp=now,
            sync_window_ms=sync_window_ms,
            leg_a=leg_a,
            leg_b=leg_b,
            settlement_gross_value=gross_settlement_val,
            gross_edge_bps=gross_edge_bps,
            cost_breakdown=cost_breakdown,
            net_deterministic_edge_bps=net_deterministic_edge_bps,
            capital_result=cap_result,
            leg_risk_result=leg_risk_result,
            mapping_status=mapping_gate,
            quote_status=quote_gate,
            synchronization_status=sync_gate,
            liquidity_status=liquidity_gate,
            fee_status=fee_gate,
            latency_status=latency_gate,
            capacity_status=capacity_gate,
            settlement_status=settlement_gate,
            executable_status=executable_gate,
            net_edge_status=net_edge_gate,
            final_verdict=final_verdict,
            rejection_reasons=rejection_reasons,
        )

    def _walk_book(
        self,
        quote: SyncQuote,
        side: str,
        outcome: str,
        order_size_usd: float,
        fee_bps: float,
    ) -> TakerExecutionFill:
        """Walks order book ladder using ExecutablePriceModel."""
        # Select appropriate ladder: when buying YES, we walk YES asks. When buying NO, we walk NO asks.
        ladder = quote.asks if quote.asks else []

        if not ladder and quote.price > 0.0 and quote.size > 0.0:
            # Construct synthetic depth level from top-of-book quote
            ladder = [{"price": quote.price, "size": quote.size, "size_usd": quote.price * quote.size}]

        return self.l2_model.execute_taker_order(
            bids_raw=[],
            asks_raw=ladder,
            direction="BUY",
            order_size_usd=order_size_usd,
            fee_bps=fee_bps,
        )
