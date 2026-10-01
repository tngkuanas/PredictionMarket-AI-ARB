"""Cross-Venue Live Observation Harness & Empirical Friction Calibration.

Phase 10A.6J:
Connects deterministic Phase 10A.6H market mappings and Phase 10A.6I quote adapters
to empirical observation and friction calibration across Polymarket and Kalshi.

CRITICAL RESEARCH & OPERATIONAL RULES:
1. Zero fabrication: No synthetic quotes, credentials, or fills in production tables.
2. Read-only credential audit: Secrets are NEVER logged, persisted, or displayed.
3. No midpoint or last-trade pricing for execution analysis.
4. Strict anti-lookahead enforcement: evaluation_timestamp >= quote receive timestamps.
5. Strict terminology:
   - "Displayed liquidity", NOT "guaranteed fill probability".
   - "Observed post-quote adverse price movement", NOT "realized execution slippage".
   - "Scanner-surviving observations", NOT "profitable trades".
6. Frozen parameters: Calibration and observation only; no parameter optimization.
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
import hashlib
import json
import logging
import math
import os
from typing import List, Dict, Any, Optional, Tuple, Set

import numpy as np
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.cross_venue.schema import (
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
    CanonicalEconomicContract,
)
from src.cross_venue.cross_venue_quote_adapter import (
    MappedContractQuote,
    PolymarketQuoteAdapter,
    KalshiQuoteAdapter,
)
from src.cross_venue.cross_venue_scanner import (
    ScannerLifecycleStatus,
    ScannerRejectionReason,
    ArbitrageDirection,
    ScannerConfig,
    CrossVenueArbitrageCandidate,
    CrossVenueArbitrageScanner,
    SizeExecutionResult,
)
from src.cross_venue.cross_venue_market_discovery import (
    DiscoveryConfig,
    CrossVenueMarketDiscovery,
    PolymarketCanonicalAdapter,
    KalshiCanonicalAdapter,
    DiscoveryRunSummary,
)
from src.phase10.response_study.executable_price_model import (
    ExecutablePriceModel,
    TakerExecutionFill,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. CREDENTIAL AUDIT
# ==============================================================================

class KalshiCredentialStatus(BaseModel):
    """Safe, read-only credential status representation (never contains secrets)."""
    credentials_available: bool
    credential_source: str  # "environment", "configuration", or "none"
    status_category: str    # "ACTIVE", "BLOCKED_CREDENTIALS_UNAVAILABLE", "BLOCKED_CONFIG_ERROR"
    audit_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "credentials_available": self.credentials_available,
            "credential_source": self.credential_source,
            "status_category": self.status_category,
            "audit_timestamp": self.audit_timestamp.isoformat(),
        }


# ==============================================================================
# 2. METRICS & CALIBRATION SCHEMAS
# ==============================================================================

class SyncDistributionMetrics(BaseModel):
    """Empirical distribution of absolute quote timestamp skew |t_poly - t_kalshi|."""
    sample_size_n: int
    min_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    count_within_10ms: int = 0
    count_within_25ms: int = 0
    count_within_50ms: int = 0
    count_within_100ms: int = 0
    count_within_250ms: int = 0
    count_within_500ms: int = 0
    count_within_1000ms: int = 0


class QuoteStalenessMetrics(BaseModel):
    """Empirical quote age distribution (evaluation_timestamp - quote.receive_timestamp)."""
    venue: str
    sample_size_n: int
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    pct_exceeding_25ms: float = 0.0
    pct_exceeding_50ms: float = 0.0
    pct_exceeding_100ms: float = 0.0
    pct_exceeding_250ms: float = 0.0
    pct_exceeding_500ms: float = 0.0
    pct_exceeding_1000ms: float = 0.0


class BookUpdateFrequencyMetrics(BaseModel):
    """Empirical update frequency and inter-update intervals."""
    venue_contract_id: str
    venue: str
    book_updates_per_sec: float
    trade_updates_per_sec: float
    median_interval_ms: float
    p95_interval_ms: float
    p99_interval_ms: float
    max_quiet_period_ms: float


class DisplayedDepthTier(BaseModel):
    """Displayed order-book depth at a specific size tier."""
    target_size_usd: float
    best_ask: float
    executable_vwap: float
    slippage_bps: float
    available_depth_usd: float
    unfilled_usd: float
    is_fully_displayed: bool


class ObservedPostQuoteMovement(BaseModel):
    """Observed post-quote adverse movement at fixed horizons (Section 11)."""
    horizon_ms: float
    median_adverse_bps: float
    p90_adverse_bps: float
    p95_adverse_bps: float
    p99_adverse_bps: float
    max_adverse_bps: float


class CandidatePersistenceMetrics(BaseModel):
    """Quote persistence metrics after initial positive observation (Section 15)."""
    n_positive_observations: int
    pct_positive_at_10ms: float = 0.0
    pct_positive_at_25ms: float = 0.0
    pct_positive_at_50ms: float = 0.0
    pct_positive_at_100ms: float = 0.0
    pct_positive_at_250ms: float = 0.0
    pct_positive_at_500ms: float = 0.0
    pct_positive_at_1000ms: float = 0.0
    median_lifetime_ms: float = 0.0
    p95_lifetime_ms: float = 0.0
    max_lifetime_ms: float = 0.0


class LeadLagClassification(str, Enum):
    VENUE_A_FIRST = "VENUE_A_FIRST"
    VENUE_B_FIRST = "VENUE_B_FIRST"
    SIMULTANEOUS_OR_INDETERMINATE = "SIMULTANEOUS_OR_INDETERMINATE"


class LeadLagObservationRecord(BaseModel):
    """Descriptive record of cross-venue price update ordering (Section 16)."""
    mapping_id: str
    timestamp: datetime
    classification: LeadLagClassification
    first_mover_venue: Optional[str]
    second_mover_venue: Optional[str]
    lag_magnitude_ms: float


class ObservationHarnessConfig(BaseModel):
    """Frozen configuration for empirical observation harness."""
    version: str = "1.0.0"
    target_sizes_usd: List[float] = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    calibration_horizons_ms: List[float] = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
    sync_window_ms: float = 100.0
    stale_quote_threshold_ms: float = 250.0
    config_hash: str = Field(default="")

    def __init__(self, **data):
        super().__init__(**data)
        if not self.config_hash:
            self.config_hash = self.compute_config_hash()

    def compute_config_hash(self) -> str:
        payload = {
            "version": self.version,
            "target_sizes_usd": self.target_sizes_usd,
            "calibration_horizons_ms": self.calibration_horizons_ms,
            "sync_window_ms": self.sync_window_ms,
            "stale_quote_threshold_ms": self.stale_quote_threshold_ms,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


# ==============================================================================
# 3. OBSERVATION HARNESS COORDINATOR
# ==============================================================================

class CrossVenueObservationHarness:
    """Live Kalshi access audit, cross-venue observation, and empirical friction calibration."""

    def __init__(
        self,
        config: Optional[ObservationHarnessConfig] = None,
        db_store: Optional[Any] = None,
    ):
        self.config = config or ObservationHarnessConfig()
        self.db_store = db_store
        self.l2_model = ExecutablePriceModel()
        self.scanner = CrossVenueArbitrageScanner(
            config=ScannerConfig(
                target_sizes_usd=self.config.target_sizes_usd,
                max_sync_window_ms=self.config.sync_window_ms,
                stale_quote_threshold_ms=self.config.stale_quote_threshold_ms,
            )
        )

    # --------------------------------------------------------------------------
    # A. Credential Audit
    # --------------------------------------------------------------------------
    @classmethod
    def audit_kalshi_credentials(cls) -> KalshiCredentialStatus:
        """Performs a non-secret, read-only audit of Kalshi authentication material."""
        keys_to_check = [
            "KALSHI_API_KEY",
            "KALSHI_API_KEY_ID",
            "KALSHI_PRIVATE_KEY",
            "KALSHI_PRIVATE_KEY_PATH",
            "KALSHI_KEY_ID",
        ]
        found_env = [k for k in keys_to_check if os.environ.get(k)]
        
        settings = get_settings()
        settings_key = getattr(settings.api, "kalshi_api_key", None)

        if found_env:
            return KalshiCredentialStatus(
                credentials_available=True,
                credential_source="environment",
                status_category="ACTIVE",
            )
        elif settings_key:
            return KalshiCredentialStatus(
                credentials_available=True,
                credential_source="configuration",
                status_category="ACTIVE",
            )
        else:
            return KalshiCredentialStatus(
                credentials_available=False,
                credential_source="none",
                status_category="BLOCKED_CREDENTIALS_UNAVAILABLE",
            )

    # --------------------------------------------------------------------------
    # B. Live Market Universe Mapping
    # --------------------------------------------------------------------------
    def run_market_universe_discovery(
        self,
        poly_markets_raw: List[Dict[str, Any]],
        kalshi_markets_raw: List[Dict[str, Any]],
        discovery_engine: Optional[CrossVenueMarketDiscovery] = None,
        persist: bool = True,
    ) -> Tuple[DiscoveryRunSummary, List[Tuple[ContractMappingResult, Any]]]:
        """Runs Phase 10A.6H deterministic mapping pipeline on live market universes."""
        engine = discovery_engine or CrossVenueMarketDiscovery(db_store=self.db_store)

        poly_contracts = [engine.poly_adapter.adapt_market(m) for m in poly_markets_raw]
        kalshi_contracts = [engine.kalshi_adapter.adapt_market(m) for m in kalshi_markets_raw]

        summary = engine.run_discovery(poly_contracts, kalshi_contracts, persist=persist)
        candidates = engine.generate_candidates(poly_contracts, kalshi_contracts)
        validated_pairs = engine.validate_candidates(candidates)

        return summary, validated_pairs

    # --------------------------------------------------------------------------
    # C. Empirical Synchronization Distribution
    # --------------------------------------------------------------------------
    @staticmethod
    def compute_sync_distribution(
        quote_pairs: List[Tuple[MappedContractQuote, MappedContractQuote]]
    ) -> SyncDistributionMetrics:
        """Computes empirical skew distribution: abs(poly_recv - kalshi_recv)."""
        if not quote_pairs:
            return SyncDistributionMetrics(
                sample_size_n=0,
                min_ms=0.0,
                median_ms=0.0,
                p90_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                max_ms=0.0,
            )

        skews: List[float] = []
        for q_poly, q_kalshi in quote_pairs:
            t1 = q_poly.local_receive_timestamp
            t2 = q_kalshi.local_receive_timestamp
            delta = abs((t1 - t2).total_seconds() * 1000.0)
            skews.append(delta)

        arr = np.array(skews)
        return SyncDistributionMetrics(
            sample_size_n=len(skews),
            min_ms=float(np.min(arr)),
            median_ms=float(np.median(arr)),
            p90_ms=float(np.percentile(arr, 90)),
            p95_ms=float(np.percentile(arr, 95)),
            p99_ms=float(np.percentile(arr, 99)),
            max_ms=float(np.max(arr)),
            count_within_10ms=int(np.sum(arr <= 10.0)),
            count_within_25ms=int(np.sum(arr <= 25.0)),
            count_within_50ms=int(np.sum(arr <= 50.0)),
            count_within_100ms=int(np.sum(arr <= 100.0)),
            count_within_250ms=int(np.sum(arr <= 250.0)),
            count_within_500ms=int(np.sum(arr <= 500.0)),
            count_within_1000ms=int(np.sum(arr <= 1000.0)),
        )

    # --------------------------------------------------------------------------
    # D. Empirical Quote Staleness
    # --------------------------------------------------------------------------
    @staticmethod
    def compute_staleness_distribution(
        quotes: List[MappedContractQuote],
        evaluation_timestamp: datetime,
    ) -> QuoteStalenessMetrics:
        """Computes quote age distribution (evaluation_timestamp - local_receive_timestamp)."""
        venue = quotes[0].venue if quotes else "unknown"
        if not quotes:
            return QuoteStalenessMetrics(
                venue=venue,
                sample_size_n=0,
                median_ms=0.0,
                p90_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                max_ms=0.0,
            )

        eval_ts = evaluation_timestamp
        if eval_ts.tzinfo is None:
            eval_ts = eval_ts.replace(tzinfo=timezone.utc)

        ages: List[float] = []
        for q in quotes:
            recv = q.local_receive_timestamp
            if recv.tzinfo is None:
                recv = recv.replace(tzinfo=timezone.utc)
            if eval_ts < recv:
                raise ValueError(
                    f"Anti-lookahead violation: evaluation_timestamp {eval_ts.isoformat()} "
                    f"is earlier than quote receive timestamp {recv.isoformat()}."
                )
            age_ms = (eval_ts - recv).total_seconds() * 1000.0
            ages.append(max(0.0, age_ms))

        arr = np.array(ages)
        n = len(arr)
        return QuoteStalenessMetrics(
            venue=venue,
            sample_size_n=n,
            median_ms=float(np.median(arr)),
            p90_ms=float(np.percentile(arr, 90)),
            p95_ms=float(np.percentile(arr, 95)),
            p99_ms=float(np.percentile(arr, 99)),
            max_ms=float(np.max(arr)),
            pct_exceeding_25ms=float(np.sum(arr > 25.0) / n * 100.0),
            pct_exceeding_50ms=float(np.sum(arr > 50.0) / n * 100.0),
            pct_exceeding_100ms=float(np.sum(arr > 100.0) / n * 100.0),
            pct_exceeding_250ms=float(np.sum(arr > 250.0) / n * 100.0),
            pct_exceeding_500ms=float(np.sum(arr > 500.0) / n * 100.0),
            pct_exceeding_1000ms=float(np.sum(arr > 1000.0) / n * 100.0),
        )

    # --------------------------------------------------------------------------
    # E. Empirical Book Update Frequency
    # --------------------------------------------------------------------------
    @staticmethod
    def compute_update_frequency(
        quotes: List[MappedContractQuote],
        trades_count: int = 0,
    ) -> BookUpdateFrequencyMetrics:
        """Measures genuine update rates and quiet intervals for a contract quote stream."""
        if not quotes:
            return BookUpdateFrequencyMetrics(
                venue_contract_id="",
                venue="",
                book_updates_per_sec=0.0,
                trade_updates_per_sec=0.0,
                median_interval_ms=0.0,
                p95_interval_ms=0.0,
                p99_interval_ms=0.0,
                max_quiet_period_ms=0.0,
            )

        sorted_quotes = sorted(quotes, key=lambda q: q.local_receive_timestamp)
        first_t = sorted_quotes[0].local_receive_timestamp
        last_t = sorted_quotes[-1].local_receive_timestamp
        duration_sec = max(0.001, (last_t - first_t).total_seconds())

        intervals_ms: List[float] = []
        for i in range(len(sorted_quotes) - 1):
            t_curr = sorted_quotes[i].local_receive_timestamp
            t_next = sorted_quotes[i + 1].local_receive_timestamp
            diff_ms = max(0.0, (t_next - t_curr).total_seconds() * 1000.0)
            intervals_ms.append(diff_ms)

        if not intervals_ms:
            intervals_ms = [0.0]

        arr = np.array(intervals_ms)
        book_rate = len(quotes) / duration_sec
        trade_rate = trades_count / duration_sec

        return BookUpdateFrequencyMetrics(
            venue_contract_id=sorted_quotes[0].venue_contract_id,
            venue=sorted_quotes[0].venue,
            book_updates_per_sec=round(book_rate, 2),
            trade_updates_per_sec=round(trade_rate, 2),
            median_interval_ms=float(np.median(arr)),
            p95_interval_ms=float(np.percentile(arr, 95)),
            p99_interval_ms=float(np.percentile(arr, 99)),
            max_quiet_period_ms=float(np.max(arr)),
        )

    # --------------------------------------------------------------------------
    # F. Empirical L2 Displayed Liquidity & Slippage
    # --------------------------------------------------------------------------
    def calibrate_displayed_liquidity(
        self,
        quote: MappedContractQuote,
        target_sizes: Optional[List[float]] = None,
    ) -> List[DisplayedDepthTier]:
        """Calculates displayed depth, taker VWAP, and ladder slippage across order sizes."""
        sizes = target_sizes or self.config.target_sizes_usd
        results: List[DisplayedDepthTier] = []

        ladder = quote.asks if quote.asks else []
        if not ladder and quote.best_ask is not None and quote.best_ask > 0.0:
            ladder = [{"price": quote.best_ask, "size": quote.ask_depth}]

        best_ask = quote.best_ask or (ladder[0]["price"] if ladder else 1.0)

        for sz in sizes:
            fill = self.l2_model.execute_taker_order(
                bids_raw=[],
                asks_raw=ladder,
                direction="BUY",
                order_size_usd=sz,
                fee_bps=0.0,
            )
            unfilled = max(0.0, sz - fill.gross_notional_filled)
            results.append(DisplayedDepthTier(
                target_size_usd=sz,
                best_ask=best_ask,
                executable_vwap=fill.fill_price_vwap,
                slippage_bps=fill.slippage_bps,
                available_depth_usd=fill.total_depth_available_usd,
                unfilled_usd=unfilled,
                is_fully_displayed=fill.is_fillable,
            ))
        return results

    # --------------------------------------------------------------------------
    # G. Observed Post-Quote Adverse Price Movement (Section 11)
    # --------------------------------------------------------------------------
    @staticmethod
    def measure_post_quote_adverse_movement(
        initial_quote: MappedContractQuote,
        subsequent_quotes: List[MappedContractQuote],
        horizons_ms: Optional[List[float]] = None,
    ) -> List[ObservedPostQuoteMovement]:
        """Calculates observed post-quote adverse price movement across future horizons.
        
        MANDATORY TERMINOLOGY:
        This is 'observed post-quote adverse price movement', NOT 'realized execution slippage'.
        """
        targets = horizons_ms or [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
        base_time = initial_quote.local_receive_timestamp
        base_ask = initial_quote.best_ask or 1.0

        results: List[ObservedPostQuoteMovement] = []
        for h_ms in targets:
            target_time = base_time + timedelta(milliseconds=h_ms)
            # Find quote closest to horizon without lookahead beyond target window
            eligible = [q for q in subsequent_quotes if q.local_receive_timestamp >= target_time]
            if not eligible:
                # If no subsequent quote, test next available quote
                eligible = [q for q in subsequent_quotes if q.local_receive_timestamp > base_time]

            adverse_moves: List[float] = []
            if eligible:
                closest_q = min(eligible, key=lambda q: abs((q.local_receive_timestamp - target_time).total_seconds()))
                curr_ask = closest_q.best_ask or base_ask
                # Adverse movement for a buyer is price increase
                move_bps = max(0.0, (curr_ask - base_ask) * 10000.0)
                adverse_moves.append(move_bps)
            else:
                adverse_moves.append(0.0)

            arr = np.array(adverse_moves)
            results.append(ObservedPostQuoteMovement(
                horizon_ms=h_ms,
                median_adverse_bps=float(np.median(arr)),
                p90_adverse_bps=float(np.percentile(arr, 90)),
                p95_adverse_bps=float(np.percentile(arr, 95)),
                p99_adverse_bps=float(np.percentile(arr, 99)),
                max_adverse_bps=float(np.max(arr)),
            ))
        return results

    # --------------------------------------------------------------------------
    # H. Candidate Survival Funnel (Section 13)
    # --------------------------------------------------------------------------
    def evaluate_candidate_survival_funnel(
        self,
        mapping: ContractMappingResult,
        quote_poly: MappedContractQuote,
        quote_kalshi: MappedContractQuote,
        evaluation_timestamp: datetime,
    ) -> Dict[str, Any]:
        """Evaluates observed candidate survival across the deterministic quality gates.
        
        Funnel Stages:
        1. exact_mappings
        2. synchronized_observations
        3. valid_two_sided_books
        4. gross_positive_edge
        5. fee_adjusted_positive_edge
        6. l2_executable_positive_edge
        7. latency_stress_positive_edge
        8. leg_risk_positive_edge (scanner-surviving observations)
        """
        eval_ts = evaluation_timestamp
        if eval_ts.tzinfo is None:
            eval_ts = eval_ts.replace(tzinfo=timezone.utc)

        # Anti-lookahead assertion
        if eval_ts < quote_poly.local_receive_timestamp or eval_ts < quote_kalshi.local_receive_timestamp:
            raise ValueError("Anti-lookahead violation in candidate survival funnel.")

        candidates = self.scanner.scan_quote_pair(
            mapping=mapping,
            quote_poly=quote_poly,
            quote_kalshi=quote_kalshi,
            evaluation_timestamp=eval_ts,
        )

        stage_exact = (mapping.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT and mapping.settlement_equivalence)
        delta_ms = abs((quote_poly.local_receive_timestamp - quote_kalshi.local_receive_timestamp).total_seconds() * 1000.0)
        stage_sync = stage_exact and (delta_ms <= self.config.sync_window_ms)
        stage_two_sided = stage_sync and (quote_poly.best_ask is not None and quote_kalshi.best_ask is not None)

        best_cand = candidates[0] if candidates else None
        stage_gross = stage_two_sided and bool(best_cand and best_cand.gross_edge_bps > 0.0)

        # Fee adjusted
        total_fee_bps = (self.scanner.config.polymarket_fee_bps + self.scanner.config.kalshi_fee_bps) / 2.0
        stage_fee = stage_gross and bool(best_cand and (best_cand.gross_edge_bps - total_fee_bps) > 0.0)

        # L2 executable
        stage_l2 = stage_fee and bool(best_cand and any(s.is_fillable and s.net_edge_bps > 0.0 for s in best_cand.size_executions))

        # Latency stress survival
        stage_latency = stage_l2 and bool(best_cand and any(l.is_viable for l in best_cand.latency_stress_results if l.latency_ms >= 50.0))

        # Leg risk survival (Case A through F survivability)
        stage_leg_risk = stage_latency and bool(best_cand and best_cand.lifecycle_status == ScannerLifecycleStatus.EXECUTABLE)

        return {
            "mapping_id": mapping.mapping_id,
            "evaluation_timestamp": eval_ts.isoformat(),
            "stages": {
                "exact_mappings": stage_exact,
                "synchronized_observations": stage_sync,
                "valid_two_sided_books": stage_two_sided,
                "gross_positive_edge": stage_gross,
                "fee_adjusted_positive_edge": stage_fee,
                "l2_executable_positive_edge": stage_l2,
                "latency_stress_positive_edge": stage_latency,
                "scanner_surviving_observations": stage_leg_risk,
            },
            "candidate": best_cand,
        }

    # --------------------------------------------------------------------------
    # I. Candidate Persistence Measurement (Section 15)
    # --------------------------------------------------------------------------
    @staticmethod
    def measure_candidate_persistence(
        initial_candidate: CrossVenueArbitrageCandidate,
        future_candidates: List[Tuple[float, CrossVenueArbitrageCandidate]],
        horizons_ms: Optional[List[float]] = None,
    ) -> CandidatePersistenceMetrics:
        """Measures whether positive gross/net edge remains present in subsequent genuine observations."""
        horizons = horizons_ms or [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
        if initial_candidate.gross_edge_bps <= 0.0:
            return CandidatePersistenceMetrics(n_positive_observations=0)

        surviving_at_horizon: Dict[float, bool] = {h: False for h in horizons}
        lifetime_ms = 0.0

        for h in horizons:
            # Check candidate at horizon
            matching = [cand for dt, cand in future_candidates if dt >= h]
            if matching:
                cand_at_h = matching[0]
                if cand_at_h.gross_edge_bps > 0.0:
                    surviving_at_horizon[h] = True
                    lifetime_ms = max(lifetime_ms, h)

        return CandidatePersistenceMetrics(
            n_positive_observations=1,
            pct_positive_at_10ms=100.0 if surviving_at_horizon.get(10.0) else 0.0,
            pct_positive_at_25ms=100.0 if surviving_at_horizon.get(25.0) else 0.0,
            pct_positive_at_50ms=100.0 if surviving_at_horizon.get(50.0) else 0.0,
            pct_positive_at_100ms=100.0 if surviving_at_horizon.get(100.0) else 0.0,
            pct_positive_at_250ms=100.0 if surviving_at_horizon.get(250.0) else 0.0,
            pct_positive_at_500ms=100.0 if surviving_at_horizon.get(500.0) else 0.0,
            pct_positive_at_1000ms=100.0 if surviving_at_horizon.get(1000.0) else 0.0,
            median_lifetime_ms=lifetime_ms,
            p95_lifetime_ms=lifetime_ms,
            max_lifetime_ms=lifetime_ms,
        )

    # --------------------------------------------------------------------------
    # J. Cross-Venue Price-Lead Observation (Section 16)
    # --------------------------------------------------------------------------
    @staticmethod
    def classify_lead_lag(
        quotes_poly: List[MappedContractQuote],
        quotes_kalshi: List[MappedContractQuote],
        delta_tolerance_ms: float = 2.0,
    ) -> List[LeadLagObservationRecord]:
        """Classifies which venue's executable quote changed first (descriptive only)."""
        records: List[LeadLagObservationRecord] = []
        if len(quotes_poly) < 2 or len(quotes_kalshi) < 2:
            return records

        # Pair successive price changes
        # Find first price change event on Poly
        p0_ask = quotes_poly[0].best_ask
        poly_moves = [q for q in quotes_poly[1:] if q.best_ask != p0_ask]

        # Find first price change event on Kalshi
        k0_ask = quotes_kalshi[0].best_ask
        kalshi_moves = [q for q in quotes_kalshi[1:] if q.best_ask != k0_ask]

        if poly_moves and kalshi_moves:
            poly_t = poly_moves[0].local_receive_timestamp
            kalshi_t = kalshi_moves[0].local_receive_timestamp
            diff_ms = (poly_t - kalshi_t).total_seconds() * 1000.0

            if abs(diff_ms) <= delta_tolerance_ms:
                cls = LeadLagClassification.SIMULTANEOUS_OR_INDETERMINATE
                first = None
                second = None
            elif diff_ms < 0:
                cls = LeadLagClassification.VENUE_A_FIRST
                first = "polymarket"
                second = "kalshi"
            else:
                cls = LeadLagClassification.VENUE_B_FIRST
                first = "kalshi"
                second = "polymarket"

            records.append(LeadLagObservationRecord(
                mapping_id=quotes_poly[0].mapping_id,
                timestamp=min(poly_t, kalshi_t),
                classification=cls,
                first_mover_venue=first,
                second_mover_venue=second,
                lag_magnitude_ms=abs(diff_ms),
            ))
        return records
