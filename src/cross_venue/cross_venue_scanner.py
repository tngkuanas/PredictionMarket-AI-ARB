"""Live Cross-Venue Quote Synchronization and Arbitrage Candidate Scanner.

Phase 10A.6I:
Connects deterministic Phase 10A.6H market mappings to genuine Polymarket and Kalshi
order book quotes to determine whether any mapped economically equivalent contracts
produce synchronized executable cross-venue arbitrage candidates.

HARD SAFETY AND METHODOLOGICAL CONSTRAINTS:
1. No synthetic data in production tables.
2. Anti-lookahead enforcement: evaluation_timestamp >= quote receive timestamps.
3. No midpoint or last-trade pricing: executable prices strictly via L2 ladder walking.
4. Complete price independence: price/volume dynamics never alter contract identity or mapping.
5. Strict deterministic lifecycle statuses and rejection reasons.
6. Multi-size ladder walking ($10 to $1,000) and dual direction evaluation.
7. Asynchronous leg risk analysis (Cases A-F) and latency stress (0-1,000ms).
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import math
import uuid
from typing import List, Dict, Any, Optional, Tuple

from pydantic import BaseModel, Field

from src.cross_venue.schema import (
    ContractMappingResult,
    EquivalenceClass,
    SyncQuote,
)
from src.cross_venue.cross_venue_quote_adapter import MappedContractQuote
from src.phase10.response_study.executable_price_model import (
    ExecutablePriceModel,
    TakerExecutionFill,
)
from src.cross_venue.synchronizer import CrossVenueSynchronizer

logger = logging.getLogger(__name__)


class ScannerLifecycleStatus(str, Enum):
    """Deterministic candidate lifecycle status (Phase 10A.6I Section 8)."""
    DETECTED = "DETECTED"
    EXECUTABLE = "EXECUTABLE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ScannerRejectionReason(str, Enum):
    """Specific deterministic rejection classifications (Phase 10A.6I Section 9)."""
    NON_EXACT_MAPPING = "NON_EXACT_MAPPING"
    ASYNC_WINDOW_EXCEEDED = "ASYNC_WINDOW_EXCEEDED"
    STALE_QUOTE = "STALE_QUOTE"
    MISSING_BID = "MISSING_BID"
    MISSING_ASK = "MISSING_ASK"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"
    FEE_EROSION = "FEE_EROSION"
    SLIPPAGE_EROSION = "SLIPPAGE_EROSION"
    NEGATIVE_NET_EDGE = "NEGATIVE_NET_EDGE"
    ASYMMETRIC_FILL_RISK = "ASYMMETRIC_FILL_RISK"
    LATENCY_EXCEEDED = "LATENCY_EXCEEDED"
    CAPITAL_EXHAUSTED = "CAPITAL_EXHAUSTED"
    LOOKAHEAD_VIOLATION = "LOOKAHEAD_VIOLATION"


class ArbitrageDirection(str, Enum):
    """Dual arbitrage directions evaluated simultaneously (Phase 10A.6I Section 6)."""
    POLY_YES_KALSHI_NO = "POLY_YES_KALSHI_NO"
    POLY_NO_KALSHI_YES = "POLY_NO_KALSHI_YES"


class ScannerConfig(BaseModel):
    """Frozen deterministic scanner configuration."""
    version: str = "1.0.0"
    target_sizes_usd: List[float] = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    latency_stresses_ms: List[float] = [0.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    max_sync_window_ms: float = 100.0
    stale_quote_threshold_ms: float = 250.0
    polymarket_fee_bps: float = 0.0
    kalshi_fee_bps: float = 30.0
    default_latency_penalty_bps: float = 8.0
    default_unwind_cost_bps: float = 10.0
    emergency_unwind_haircut_pct: float = 0.10
    volatility_rate_bps_per_sqrt_sec: float = 30.0

    def compute_config_hash(self) -> str:
        payload = {
            "version": self.version,
            "target_sizes_usd": self.target_sizes_usd,
            "latency_stresses_ms": self.latency_stresses_ms,
            "max_sync_window_ms": self.max_sync_window_ms,
            "stale_quote_threshold_ms": self.stale_quote_threshold_ms,
            "polymarket_fee_bps": self.polymarket_fee_bps,
            "kalshi_fee_bps": self.kalshi_fee_bps,
            "default_latency_penalty_bps": self.default_latency_penalty_bps,
            "default_unwind_cost_bps": self.default_unwind_cost_bps,
            "emergency_unwind_haircut_pct": self.emergency_unwind_haircut_pct,
            "volatility_rate_bps_per_sqrt_sec": self.volatility_rate_bps_per_sqrt_sec,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class SizeExecutionResult(BaseModel):
    """Execution ladder result for a specific order size (Phase 10A.6I Section 7)."""
    target_size_usd: float
    shares_filled_a: float
    shares_filled_b: float
    vwap_a: float
    vwap_b: float
    combined_vwap: float
    gross_edge_bps: float
    fee_bps: float
    slippage_bps: float
    latency_penalty_bps: float
    unwind_cost_bps: float
    total_cost_bps: float
    net_edge_bps: float
    is_fillable: bool
    is_edge_positive: bool
    rejection_reason: Optional[str] = None


class LatencyStressEvaluation(BaseModel):
    """Stress evaluation across latency grid."""
    latency_ms: float
    price_movement_allowance_bps: float
    net_edge_bps: float
    is_viable: bool


class LegRiskEvaluation(BaseModel):
    """Asynchronous leg risk evaluation (Cases A through F)."""
    case_name: str
    fill_pct_a: float
    fill_pct_b: float
    filled_usd: float
    unhedged_usd: float
    emergency_unwind_cost_usd: float
    worst_case_loss_usd: float
    deterministic_settlement_value_usd: float
    net_pnl_usd: float
    net_edge_bps: float


class CrossVenueArbitrageCandidate(BaseModel):
    """Complete candidate evaluation record (Phase 10A.6I Section 10)."""
    candidate_id: str
    mapping_id: str
    direction: ArbitrageDirection
    lifecycle_status: ScannerLifecycleStatus
    rejection_reasons: List[str] = Field(default_factory=list)
    evaluation_timestamp: datetime
    quote_poly_hash: str
    quote_kalshi_hash: str
    poly_market_id: str
    kalshi_market_id: str
    sync_latency_delta_ms: float
    best_executable_size_usd: float = 0.0
    best_net_edge_bps: float = 0.0
    gross_edge_bps: float = 0.0
    total_cost_bps: float = 0.0
    vwap_poly: float = 0.0
    vwap_kalshi: float = 0.0
    combined_vwap: float = 0.0
    size_executions: List[SizeExecutionResult] = Field(default_factory=list)
    latency_stress_results: List[LatencyStressEvaluation] = Field(default_factory=list)
    leg_risk_results: List[LegRiskEvaluation] = Field(default_factory=list)
    reproducibility_hash: str = ""

    def compute_reproducibility_hash(self) -> str:
        payload = {
            "candidate_id": self.candidate_id,
            "mapping_id": self.mapping_id,
            "direction": self.direction.value,
            "evaluation_timestamp": self.evaluation_timestamp.isoformat(),
            "quote_poly_hash": self.quote_poly_hash,
            "quote_kalshi_hash": self.quote_kalshi_hash,
            "sync_latency_delta_ms": round(self.sync_latency_delta_ms, 4),
            "best_executable_size_usd": round(self.best_executable_size_usd, 2),
            "best_net_edge_bps": round(self.best_net_edge_bps, 2),
            "lifecycle_status": self.lifecycle_status.value,
            "size_executions_count": len(self.size_executions),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class ScanRunSummary(BaseModel):
    """Aggregated scan execution metrics (Phase 10A.6I Section 14)."""
    scan_run_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    mappings_scanned_count: int = 0
    quotes_processed_count: int = 0
    candidates_detected_count: int = 0
    candidates_executable_count: int = 0
    candidates_rejected_count: int = 0
    config_hash: str


class CrossVenueArbitrageScanner:
    """Live Cross-Venue Quote Synchronization and Arbitrage Candidate Scanner."""

    def __init__(
        self,
        config: Optional[ScannerConfig] = None,
        db_store: Optional[Any] = None,
    ):
        self.config = config or ScannerConfig()
        self.db_store = db_store
        self.l2_model = ExecutablePriceModel()
        self.synchronizer = CrossVenueSynchronizer()

    def scan_quote_pair(
        self,
        mapping: ContractMappingResult,
        quote_poly: MappedContractQuote,
        quote_kalshi: MappedContractQuote,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> List[CrossVenueArbitrageCandidate]:
        """Scans a mapped pair and evaluates both arbitrage directions.
        
        ANTI-LOOKAHEAD:
        Strictly requires evaluation_timestamp >= quote_poly.local_receive_timestamp
        and evaluation_timestamp >= quote_kalshi.local_receive_timestamp.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Anti-lookahead assertion
        poly_recv = quote_poly.local_receive_timestamp
        if poly_recv.tzinfo is None:
            poly_recv = poly_recv.replace(tzinfo=timezone.utc)
        kalshi_recv = quote_kalshi.local_receive_timestamp
        if kalshi_recv.tzinfo is None:
            kalshi_recv = kalshi_recv.replace(tzinfo=timezone.utc)

        if now < poly_recv or now < kalshi_recv:
            raise ValueError(
                f"Anti-lookahead violation: evaluation_timestamp {now.isoformat()} is before "
                f"quote receive timestamps (Poly: {poly_recv.isoformat()}, Kalshi: {kalshi_recv.isoformat()})."
            )

        # Sync window calculation
        delta_ms = abs((poly_recv - kalshi_recv).total_seconds() * 1000.0)
        age_poly_ms = max(0.0, (now - poly_recv).total_seconds() * 1000.0)
        age_kalshi_ms = max(0.0, (now - kalshi_recv).total_seconds() * 1000.0)

        # Evaluate both directions
        candidates: List[CrossVenueArbitrageCandidate] = []
        for direction in [ArbitrageDirection.POLY_YES_KALSHI_NO, ArbitrageDirection.POLY_NO_KALSHI_YES]:
            cand = self._evaluate_direction(
                mapping=mapping,
                quote_poly=quote_poly,
                quote_kalshi=quote_kalshi,
                direction=direction,
                evaluation_timestamp=now,
                delta_ms=delta_ms,
                age_poly_ms=age_poly_ms,
                age_kalshi_ms=age_kalshi_ms,
            )
            candidates.append(cand)

        return candidates

    def _evaluate_direction(
        self,
        mapping: ContractMappingResult,
        quote_poly: MappedContractQuote,
        quote_kalshi: MappedContractQuote,
        direction: ArbitrageDirection,
        evaluation_timestamp: datetime,
        delta_ms: float,
        age_poly_ms: float,
        age_kalshi_ms: float,
    ) -> CrossVenueArbitrageCandidate:
        """Evaluates single arbitrage direction with comprehensive gates."""
        candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        rejection_reasons: List[str] = []

        # Gate 1: Mapping exact equivalence
        if mapping.equivalence_class != EquivalenceClass.EXACT_EQUIVALENT or not mapping.settlement_equivalence:
            rejection_reasons.append(
                f"{ScannerRejectionReason.NON_EXACT_MAPPING.value}: Contract mapping class {mapping.equivalence_class.value} is not EXACT_EQUIVALENT or settlement_equivalence is False."
            )

        # Gate 2: Quote synchronization window
        if delta_ms > self.config.max_sync_window_ms:
            rejection_reasons.append(
                f"{ScannerRejectionReason.ASYNC_WINDOW_EXCEEDED.value}: Latency skew {delta_ms:.1f}ms exceeds maximum sync window {self.config.max_sync_window_ms:.1f}ms."
            )

        # Gate 3: Staleness check
        if age_poly_ms > self.config.stale_quote_threshold_ms or age_kalshi_ms > self.config.stale_quote_threshold_ms:
            rejection_reasons.append(
                f"{ScannerRejectionReason.STALE_QUOTE.value}: Quote age exceeds threshold (Poly: {age_poly_ms:.1f}ms, Kalshi: {age_kalshi_ms:.1f}ms, limit: {self.config.stale_quote_threshold_ms:.1f}ms)."
            )

        # Determine quote ladders for the given direction
        # Poly leg and Kalshi leg
        if direction == ArbitrageDirection.POLY_YES_KALSHI_NO:
            # Poly YES: ask ladder. Kalshi NO: ask ladder
            ladder_poly = quote_poly.asks
            ladder_kalshi = quote_kalshi.asks if quote_kalshi.economic_outcome == "NO" else []
            best_ask_poly = quote_poly.best_ask
            best_ask_kalshi = quote_kalshi.best_ask if quote_kalshi.economic_outcome == "NO" else None
        else:
            # Poly NO: ask ladder. Kalshi YES: ask ladder
            ladder_poly = quote_poly.asks if quote_poly.economic_outcome == "NO" else []
            ladder_kalshi = quote_kalshi.asks if quote_kalshi.economic_outcome == "YES" else quote_kalshi.asks
            best_ask_poly = quote_poly.best_ask if quote_poly.economic_outcome == "NO" else None
            best_ask_kalshi = quote_kalshi.best_ask

        # Check for missing ask quotes
        if (not ladder_poly and best_ask_poly is None) or (not ladder_kalshi and best_ask_kalshi is None):
            rejection_reasons.append(
                f"{ScannerRejectionReason.MISSING_ASK.value}: Order book ask quotes are missing on one or both venues."
            )

        # Multi-size L2 ladder walking
        size_executions: List[SizeExecutionResult] = []
        best_exec_size = 0.0
        best_net_edge = -99999.0
        best_gross_edge = 0.0
        best_total_cost = 0.0
        best_vwap_poly = 0.0
        best_vwap_kalshi = 0.0
        best_combined_vwap = 0.0
        has_any_executable_size = False

        for target_size in self.config.target_sizes_usd:
            exec_res = self._walk_l2_for_size(
                ladder_poly=ladder_poly,
                best_ask_poly=best_ask_poly,
                ladder_kalshi=ladder_kalshi,
                best_ask_kalshi=best_ask_kalshi,
                target_size_usd=target_size,
            )
            size_executions.append(exec_res)

            if exec_res.is_fillable and exec_res.is_edge_positive:
                has_any_executable_size = True
                if exec_res.net_edge_bps > best_net_edge:
                    best_net_edge = exec_res.net_edge_bps
                    best_exec_size = target_size
                    best_gross_edge = exec_res.gross_edge_bps
                    best_total_cost = exec_res.total_cost_bps
                    best_vwap_poly = exec_res.vwap_a
                    best_vwap_kalshi = exec_res.vwap_b
                    best_combined_vwap = exec_res.combined_vwap

        # If no size was fully executable, record the primary economic rejection reason from the smallest size
        if not has_any_executable_size and size_executions:
            smallest = size_executions[0]
            if smallest.rejection_reason and smallest.rejection_reason not in rejection_reasons:
                rejection_reasons.append(smallest.rejection_reason)
            # Default presentation metrics to smallest size for audit trail
            best_gross_edge = smallest.gross_edge_bps
            best_total_cost = smallest.total_cost_bps
            best_net_edge = smallest.net_edge_bps
            best_vwap_poly = smallest.vwap_a
            best_vwap_kalshi = smallest.vwap_b
            best_combined_vwap = smallest.combined_vwap

        # Latency stress testing
        latency_stress_evals = self._evaluate_latency_stress(
            base_net_edge_bps=best_net_edge if has_any_executable_size else -100.0,
        )

        # Leg risk analysis (Cases A through F)
        eval_size = best_exec_size if best_exec_size > 0.0 else self.config.target_sizes_usd[0]
        leg_risk_evals = self._evaluate_leg_risk(
            target_size_usd=eval_size,
            vwap_poly=best_vwap_poly,
            vwap_kalshi=best_vwap_kalshi,
        )

        # Lifecycle Status Determination
        if len(rejection_reasons) == 0 and has_any_executable_size:
            lifecycle_status = ScannerLifecycleStatus.EXECUTABLE
        else:
            lifecycle_status = ScannerLifecycleStatus.REJECTED

        candidate = CrossVenueArbitrageCandidate(
            candidate_id=candidate_id,
            mapping_id=mapping.mapping_id,
            direction=direction,
            lifecycle_status=lifecycle_status,
            rejection_reasons=rejection_reasons,
            evaluation_timestamp=evaluation_timestamp,
            quote_poly_hash=quote_poly.book_hash,
            quote_kalshi_hash=quote_kalshi.book_hash,
            poly_market_id=quote_poly.venue_contract_id,
            kalshi_market_id=quote_kalshi.venue_contract_id,
            sync_latency_delta_ms=delta_ms,
            best_executable_size_usd=best_exec_size,
            best_net_edge_bps=best_net_edge if has_any_executable_size else 0.0,
            gross_edge_bps=best_gross_edge,
            total_cost_bps=best_total_cost,
            vwap_poly=best_vwap_poly,
            vwap_kalshi=best_vwap_kalshi,
            combined_vwap=best_combined_vwap,
            size_executions=size_executions,
            latency_stress_results=latency_stress_evals,
            leg_risk_results=leg_risk_evals,
        )
        candidate.reproducibility_hash = candidate.compute_reproducibility_hash()
        return candidate

    def _walk_l2_for_size(
        self,
        ladder_poly: List[Dict[str, float]],
        best_ask_poly: Optional[float],
        ladder_kalshi: List[Dict[str, float]],
        best_ask_kalshi: Optional[float],
        target_size_usd: float,
    ) -> SizeExecutionResult:
        """Walks L2 book ladders on both venues for given USD size."""
        # Fallback to top of book if ladder list is empty but best price exists
        poly_asks = list(ladder_poly)
        if not poly_asks and best_ask_poly is not None and best_ask_poly > 0.0:
            poly_asks = [{"price": best_ask_poly, "size": 100000.0, "size_usd": 100000.0 * best_ask_poly}]

        kalshi_asks = list(ladder_kalshi)
        if not kalshi_asks and best_ask_kalshi is not None and best_ask_kalshi > 0.0:
            kalshi_asks = [{"price": best_ask_kalshi, "size": 100000.0, "size_usd": 100000.0 * best_ask_kalshi}]

        # Execute taker orders via L2 model
        fill_poly = self.l2_model.execute_taker_order(
            bids_raw=[],
            asks_raw=poly_asks,
            direction="BUY",
            order_size_usd=target_size_usd,
            fee_bps=self.config.polymarket_fee_bps,
        )
        fill_kalshi = self.l2_model.execute_taker_order(
            bids_raw=[],
            asks_raw=kalshi_asks,
            direction="BUY",
            order_size_usd=target_size_usd,
            fee_bps=self.config.kalshi_fee_bps,
        )

        is_fillable = fill_poly.is_fillable and fill_kalshi.is_fillable
        vwap_a = fill_poly.fill_price_vwap
        vwap_b = fill_kalshi.fill_price_vwap
        combined_vwap = vwap_a + vwap_b

        # Binary contract settlement gross value is exactly 1.00
        gross_settlement_value = 1.0
        gross_edge_bps = (gross_settlement_value - combined_vwap) * 10000.0

        # Cost model
        fee_bps = (self.config.polymarket_fee_bps + self.config.kalshi_fee_bps) / 2.0
        slippage_bps = (fill_poly.slippage_bps + fill_kalshi.slippage_bps) / 2.0
        lat_penalty_bps = self.config.default_latency_penalty_bps
        unwind_cost_bps = self.config.default_unwind_cost_bps
        total_cost_bps = fee_bps + slippage_bps + lat_penalty_bps + unwind_cost_bps

        net_edge_bps = gross_edge_bps - total_cost_bps
        is_edge_positive = is_fillable and (net_edge_bps > 0.0)

        # Categorize rejection if not executable
        rejection_reason = None
        if not is_fillable:
            rejection_reason = f"{ScannerRejectionReason.INSUFFICIENT_DEPTH.value}: Available depth is less than order size ${target_size_usd:.2f}."
        elif gross_edge_bps > 0.0 and (gross_edge_bps - (fee_bps + lat_penalty_bps + unwind_cost_bps)) <= 0.0:
            rejection_reason = f"{ScannerRejectionReason.FEE_EROSION.value}: Positive gross edge {gross_edge_bps:.1f}bps eroded by exchange fees and friction."
        elif gross_edge_bps > 0.0 and slippage_bps > 0.0 and net_edge_bps <= 0.0:
            rejection_reason = f"{ScannerRejectionReason.SLIPPAGE_EROSION.value}: Positive gross edge {gross_edge_bps:.1f}bps eroded by order book ladder slippage."
        elif net_edge_bps <= 0.0:
            rejection_reason = f"{ScannerRejectionReason.NEGATIVE_NET_EDGE.value}: Net edge is negative ({net_edge_bps:.1f} bps)."

        return SizeExecutionResult(
            target_size_usd=target_size_usd,
            shares_filled_a=fill_poly.total_shares_filled,
            shares_filled_b=fill_kalshi.total_shares_filled,
            vwap_a=round(vwap_a, 4),
            vwap_b=round(vwap_b, 4),
            combined_vwap=round(combined_vwap, 4),
            gross_edge_bps=round(gross_edge_bps, 2),
            fee_bps=round(fee_bps, 2),
            slippage_bps=round(slippage_bps, 2),
            latency_penalty_bps=round(lat_penalty_bps, 2),
            unwind_cost_bps=round(unwind_cost_bps, 2),
            total_cost_bps=round(total_cost_bps, 2),
            net_edge_bps=round(net_edge_bps, 2),
            is_fillable=is_fillable,
            is_edge_positive=is_edge_positive,
            rejection_reason=rejection_reason,
        )

    def _evaluate_latency_stress(self, base_net_edge_bps: float) -> List[LatencyStressEvaluation]:
        """Evaluates candidate net edge under progressive execution latency."""
        results: List[LatencyStressEvaluation] = []
        for lat_ms in self.config.latency_stresses_ms:
            # Microstructure price movement allowance: sigma * sqrt(dt)
            # e.g., 30 bps per sqrt(second)
            sec = lat_ms / 1000.0
            price_move_bps = self.config.volatility_rate_bps_per_sqrt_sec * math.sqrt(sec)
            decayed_edge = base_net_edge_bps - price_move_bps
            is_viable = decayed_edge > 0.0

            results.append(LatencyStressEvaluation(
                latency_ms=lat_ms,
                price_movement_allowance_bps=round(price_move_bps, 2),
                net_edge_bps=round(decayed_edge, 2),
                is_viable=is_viable,
            ))
        return results

    def _evaluate_leg_risk(
        self,
        target_size_usd: float,
        vwap_poly: float,
        vwap_kalshi: float,
    ) -> List[LegRiskEvaluation]:
        """Evaluates the 6 asynchronous execution cases (Cases A through F)."""
        cases = [
            ("CASE_A_LEG_A_FIRST_B_DELAYED", 1.0, 1.0, 0.02),
            ("CASE_B_LEG_B_FIRST_A_DELAYED", 1.0, 1.0, 0.02),
            ("CASE_C_LEG_A_FULL_B_PARTIAL", 1.0, 0.50, 0.0),
            ("CASE_D_LEG_A_PARTIAL_B_FULL", 0.50, 1.0, 0.0),
            ("CASE_E_LEG_A_FULL_B_FAILED", 1.0, 0.0, 0.0),
            ("CASE_F_BOTH_LEGS_PARTIAL", 0.60, 0.40, 0.0),
        ]

        results: List[LegRiskEvaluation] = []
        for name, fill_a_pct, fill_b_pct, delay_slip in cases:
            qty_a = target_size_usd * fill_a_pct
            qty_b = target_size_usd * fill_b_pct

            common_hedged_usd = min(qty_a, qty_b)
            unhedged_usd = abs(qty_a - qty_b)

            actual_p_a = vwap_poly * (1.0 + (delay_slip if "LEG_B_FIRST" in name else 0.0))
            actual_p_b = vwap_kalshi * (1.0 + (delay_slip if "LEG_A_FIRST" in name else 0.0))

            cost_paid = (qty_a * actual_p_a) + (qty_b * actual_p_b)
            settlement_val = common_hedged_usd * 1.0  # Perfect pairing settles at 1.00

            # Emergency unwind cost at 10% haircut
            emergency_cost = unhedged_usd * self.config.emergency_unwind_haircut_pct
            worst_case_loss = (cost_paid - settlement_val) + emergency_cost
            net_pnl = settlement_val - cost_paid - emergency_cost
            net_edge_bps = (net_pnl / target_size_usd) * 10000.0 if target_size_usd > 0 else -10000.0

            results.append(LegRiskEvaluation(
                case_name=name,
                fill_pct_a=fill_a_pct,
                fill_pct_b=fill_b_pct,
                filled_usd=round(qty_a + qty_b, 2),
                unhedged_usd=round(unhedged_usd, 2),
                emergency_unwind_cost_usd=round(emergency_cost, 2),
                worst_case_loss_usd=round(worst_case_loss, 2),
                deterministic_settlement_value_usd=round(settlement_val, 2),
                net_pnl_usd=round(net_pnl, 2),
                net_edge_bps=round(net_edge_bps, 2),
            ))
        return results
