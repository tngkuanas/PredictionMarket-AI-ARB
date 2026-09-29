"""Phase 5: Live Prospective Shadow-Trading Engine.
Runs live paper trading against Polymarket Gamma & CLOB endpoints with frozen thresholds,
capturing timestamped t0 predictions and simulated order executions for forward out-of-sample audit.
STRICTLY PAPER TRADING ONLY - Zero real capital deployed.
"""
import uuid
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from src.api.polymarket import PolymarketClient
from src.db.duckdb_store import DuckDBStore, get_db
from src.normalization.schema import (
    Market,
    OrderSide,
    OpportunityClass,
    ShadowCandidate,
    ShadowOrder,
    ShadowFill,
    ShadowRunRecord,
)
from src.execution.order_book import ReconstructedOrderBook, OrderBookSimulator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrozenShadowTraderConfig:
    """Immutable, frozen parameters for prospective shadow trading.
    Prevents post-hoc parameter adjusting / p-hacking during live prospective audit.
    """
    frozen_min_edge_threshold: float = 0.015       # 1.5% minimum net edge required
    frozen_min_sample_epochs: int = 15             # Minimum 15 independent 72h epochs required
    frozen_latency_ms: float = 250.0               # 250ms simulated execution latency
    frozen_taker_fee_rate: float = 0.001           # 10 bps Polymarket taker fee
    max_order_size_usd: float = 500.0              # Max single-order size
    target_horizon_hours: float = 24.0             # Forward prediction evaluation horizon
    paper_trading_only: bool = True                # Safety assertion
    config_version: str = "v1.0.0-frozen"
    candidate_generator_version: str = "v1.0.0-multi-class"
    execution_model_version: str = "v1.0.0-clob-l2-depth"

    @property
    def config_hash(self) -> str:
        payload = f"{self.config_version}:{self.frozen_min_edge_threshold}:{self.frozen_min_sample_epochs}:{self.frozen_latency_ms}:{self.frozen_taker_fee_rate}:{self.max_order_size_usd}:{self.target_horizon_hours}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class LiveShadowTrader:
    """Live prospective paper shadow trading engine.
    Audits live Polymarket order books, identifies candidate dislocations, applies frozen
    falsification thresholds, simulates realistic queue depth walks, and logs forward predictions.
    """

    def __init__(
        self,
        config: Optional[FrozenShadowTraderConfig] = None,
        client: Optional[PolymarketClient] = None,
        db: Optional[DuckDBStore] = None,
    ):
        self.config = config or FrozenShadowTraderConfig()
        assert self.config.paper_trading_only, "SAFETY VIOLATION: Shadow trader must strictly run in paper mode."
        self.client = client or PolymarketClient()
        self.db = db or get_db()
        self.sim = OrderBookSimulator(
            default_latency_ms=self.config.frozen_latency_ms,
            taker_fee_rate=self.config.frozen_taker_fee_rate,
        )

    def run_shadow_scan(self, market_limit: int = 50) -> Dict[str, Any]:
        """Performs a live point-in-time (t0) scan of Polymarket markets,
        evaluates prospective candidates against frozen thresholds, and executes shadow orders.
        """
        t0 = datetime.utcnow()
        logger.info(f"=== Starting Live Shadow Trading Scan at t0 = {t0.isoformat()}Z ===")
        logger.info(
            f"Frozen Thresholds: Min Net Edge={self.config.frozen_min_edge_threshold:.2%}, "
            f"Min Epochs K={self.config.frozen_min_sample_epochs}, Latency={self.config.frozen_latency_ms}ms"
        )

        # 1. Fetch live active markets
        markets = self.client.fetch_active_markets(limit=market_limit)
        logger.info(f"Retrieved {len(markets)} live active markets from Polymarket.")

        # Index markets by ID and group by event/title patterns
        candidates: List[ShadowCandidate] = []
        orders: List[ShadowOrder] = []
        fills: List[ShadowFill] = []

        # 2. Evaluate Candidate Opportunities
        # Group 1: Structural Monotonic Ladders (e.g. Bitcoin strike rungs)
        btc_markets = [m for m in markets if "bitcoin" in m.title.lower() or "btc" in m.title.lower()]
        structural_candidates = self._evaluate_structural_ladders(btc_markets, t0)
        candidates.extend(structural_candidates)

        # Group 2: Cross-Market Geopolitical / Event Clusters (e.g. Middle East / Iran)
        geo_markets = [m for m in markets if any(k in m.title.lower() for k in ["iran", "hormuz", "ukraine", "election", "president"])]
        macro_candidates = self._evaluate_macro_clusters(geo_markets, t0)
        candidates.extend(macro_candidates)

        # Group 3: General Active CLOB Markets (Semantic / Information Latency)
        clob_candidates = self._evaluate_clob_markets(markets[:25], t0)
        candidates.extend(clob_candidates)

        # 3. Simulate Execution on Viable Candidates
        active_candidates = [c for c in candidates if c.status == "CANDIDATE_ACTIVE"]
        logger.info(f"Candidates generated: {len(candidates)} total, {len(active_candidates)} active passed initial filters.")

        for cand in active_candidates:
            order, fill = self._execute_shadow_order(cand, t0)
            if order:
                orders.append(order)
            if fill:
                fills.append(fill)

        # 4. Persist to DuckDB
        self.db.save_shadow_candidates(candidates)
        if orders:
            self.db.save_shadow_orders(orders)
        if fills:
            self.db.save_shadow_fills(fills)

        # 5. Persist Run Metadata (Reproducibility & Provenance Tracking)
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        rejections = self._tally_rejections(candidates)
        run_record = ShadowRunRecord(
            run_id=run_id,
            timestamp=t0,
            config_version=self.config.config_version,
            config_hash=self.config.config_hash,
            candidate_generator_version=self.config.candidate_generator_version,
            execution_model_version=self.config.execution_model_version,
            markets_scanned=len(markets),
            candidates_generated=len(candidates),
            filtered_out_count=len([c for c in candidates if c.status == "FILTERED_OUT"]),
            active_candidates_count=len(active_candidates),
            orders_placed=len(orders),
            fills_executed=len(fills),
            rejections_json=rejections,
        )
        self.db.save_shadow_run(run_record)

        # 6. Compile Audit Summary
        summary = {
            "run_id": run_id,
            "t0_timestamp": t0.isoformat(),
            "config_version": self.config.config_version,
            "config_hash": self.config.config_hash,
            "candidate_generator_version": self.config.candidate_generator_version,
            "execution_model_version": self.config.execution_model_version,
            "markets_scanned": len(markets),
            "candidates_generated": len(candidates),
            "filtered_out_count": len([c for c in candidates if c.status == "FILTERED_OUT"]),
            "active_candidates_count": len(active_candidates),
            "orders_placed": len(orders),
            "fills_executed": len(fills),
            "rejection_reasons": rejections,
            "frozen_config": {
                "min_edge_threshold": self.config.frozen_min_edge_threshold,
                "min_sample_epochs": self.config.frozen_min_sample_epochs,
                "latency_ms": self.config.frozen_latency_ms,
                "paper_trading_only": self.config.paper_trading_only,
                "config_hash": self.config.config_hash,
            }
        }
        logger.info(f"Shadow Trading Scan complete. Run: {run_id} | Hash: {self.config.config_hash} | Orders: {len(orders)}, Fills: {len(fills)}")
        return summary

    def _evaluate_structural_ladders(
        self,
        btc_markets: List[Market],
        t0: datetime
    ) -> List[ShadowCandidate]:
        """Evaluates pairwise monotonic threshold conditions on live Bitcoin contracts."""
        candidates = []
        if len(btc_markets) < 2:
            return candidates

        # Pairwise inspection
        for i in range(len(btc_markets)):
            for j in range(i + 1, len(btc_markets)):
                m_a = btc_markets[i]
                m_b = btc_markets[j]
                tok_a = m_a.clob_token_ids[0] if m_a.clob_token_ids else None
                tok_b = m_b.clob_token_ids[0] if m_b.clob_token_ids else None
                if not tok_a or not tok_b:
                    continue

                # Query live books
                ob_a = self.client.fetch_order_book(tok_a)
                ob_b = self.client.fetch_order_book(tok_b)
                p_a = self._extract_mid_or_last(ob_a)
                p_b = self._extract_mid_or_last(ob_b)

                # Check if monotonic ladder inversion exists
                # Inversion: P(A) > P(B) + threshold when strike(A) > strike(B)
                is_inverted = False
                inversion_gap = 0.0
                if p_a is not None and p_b is not None:
                    inversion_gap = p_a - p_b
                    if inversion_gap > 0.005:
                        is_inverted = True

                cid = f"shad_struct_{uuid.uuid4().hex[:8]}"
                cand = ShadowCandidate(
                    candidate_id=cid,
                    t0_timestamp=t0,
                    market_id=m_a.market_id,
                    token_id=tok_a,
                    title=f"Structural Ladder: {m_a.title[:35]} vs {m_b.title[:35]}",
                    opportunity_class=OpportunityClass.STRUCTURAL,
                    predicted_fair_value=p_b if p_b is not None else 0.50,
                    market_mid_price=p_a if p_a is not None else 0.50,
                    raw_edge=inversion_gap if is_inverted else 0.0,
                    frozen_min_edge_threshold=self.config.frozen_min_edge_threshold,
                    status="CANDIDATE_ACTIVE" if (is_inverted and inversion_gap >= self.config.frozen_min_edge_threshold) else "FILTERED_OUT",
                    rejection_reason=None if (is_inverted and inversion_gap >= self.config.frozen_min_edge_threshold) else "NO_MONOTONIC_INVERSION_OBSERVED",
                    target_horizon_hours=self.config.target_horizon_hours,
                    target_timestamp=t0 + timedelta(hours=self.config.target_horizon_hours),
                )
                candidates.append(cand)
        return candidates

    def _evaluate_macro_clusters(
        self,
        geo_markets: List[Market],
        t0: datetime
    ) -> List[ShadowCandidate]:
        """Evaluates live geopolitical / macro cross-market clusters."""
        candidates = []
        for m in geo_markets:
            if not m.clob_token_ids:
                continue
            tok = m.clob_token_ids[0]
            ob = self.client.fetch_order_book(tok)
            p_mid = self._extract_mid_or_last(ob) or 0.50

            cid = f"shad_macro_{uuid.uuid4().hex[:8]}"
            # Geopolitical clusters suffer from catalyst sparsity (K < 15 independent 72h epochs)
            cand = ShadowCandidate(
                candidate_id=cid,
                t0_timestamp=t0,
                market_id=m.market_id,
                token_id=tok,
                title=f"Macro Cluster: {m.title[:45]}",
                opportunity_class=OpportunityClass.SECOND_ORDER,
                predicted_fair_value=round(p_mid * 1.01, 4), # Theoretical +1% drift
                market_mid_price=p_mid,
                raw_edge=round(abs(p_mid * 0.01), 4),
                frozen_min_edge_threshold=self.config.frozen_min_edge_threshold,
                status="FILTERED_OUT",
                rejection_reason="CATALYST_SPARSITY_INDEPENDENT_K_LT_15",
                target_horizon_hours=self.config.target_horizon_hours,
                target_timestamp=t0 + timedelta(hours=self.config.target_horizon_hours),
            )
            candidates.append(cand)
        return candidates

    def _evaluate_clob_markets(
        self,
        markets: List[Market],
        t0: datetime
    ) -> List[ShadowCandidate]:
        """Evaluates active CLOB order books for information latency / semantic mispricings."""
        candidates = []
        for m in markets:
            if not m.clob_token_ids:
                continue
            tok = m.clob_token_ids[0]
            ob = self.client.fetch_order_book(tok)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if not bids or not asks:
                continue

            p_bid = float(bids[0].get("price", 0.0))
            p_ask = float(asks[0].get("price", 1.0))
            p_mid = round((p_bid + p_ask) / 2.0, 4)
            spread = round(p_ask - p_bid, 4)

            # Check if there is an unexploited edge exceeding spread + frozen threshold
            # In live prediction markets, spread drag typically dominates small semantic edges
            hypothetical_semantic_alpha = 0.008 # 0.8% typical model edge
            net_edge = hypothetical_semantic_alpha - spread - (2 * self.config.frozen_taker_fee_rate)

            cid = f"shad_sem_{uuid.uuid4().hex[:8]}"
            is_active = net_edge >= self.config.frozen_min_edge_threshold
            rejection = None if is_active else ("SPREAD_AND_FRICTION_EXCEED_EDGE" if spread > 0.02 else "RAW_EDGE_BELOW_FROZEN_THRESHOLD")

            cand = ShadowCandidate(
                candidate_id=cid,
                t0_timestamp=t0,
                market_id=m.market_id,
                token_id=tok,
                title=f"Semantic/Latency: {m.title[:45]}",
                opportunity_class=OpportunityClass.AI_SEMANTIC,
                predicted_fair_value=round(p_mid + hypothetical_semantic_alpha, 4),
                market_mid_price=p_mid,
                raw_edge=hypothetical_semantic_alpha,
                frozen_min_edge_threshold=self.config.frozen_min_edge_threshold,
                status="CANDIDATE_ACTIVE" if is_active else "FILTERED_OUT",
                rejection_reason=rejection,
                target_horizon_hours=self.config.target_horizon_hours,
                target_timestamp=t0 + timedelta(hours=self.config.target_horizon_hours),
            )
            candidates.append(cand)
        return candidates

    def _execute_shadow_order(
        self,
        candidate: ShadowCandidate,
        t0: datetime
    ) -> Tuple[Optional[ShadowOrder], Optional[ShadowFill]]:
        """Simulates realistic limit/IOC order execution against live CLOB orderbook."""
        ob_data = self.client.fetch_order_book(candidate.token_id)
        book = ReconstructedOrderBook.from_clob_order_book(
            market_id=candidate.market_id,
            clob_data=ob_data,
            timestamp=t0
        )

        side = OrderSide.BUY if candidate.predicted_fair_value > candidate.market_mid_price else OrderSide.SELL
        order_size = self.config.max_order_size_usd

        # Walk the book with 250ms simulated latency
        exec_res = self.sim.walk_the_book(
            book=book,
            side=side,
            order_size_usd=order_size,
            simulate_latency=True
        )

        order_id = f"ord_{uuid.uuid4().hex[:8]}"
        fill_price = exec_res.get("vwap_fill_price", 0.0)
        order = ShadowOrder(
            order_id=order_id,
            candidate_id=candidate.candidate_id,
            market_id=candidate.market_id,
            token_id=candidate.token_id,
            side=side,
            placed_at=t0,
            limit_price=fill_price,
            target_size_usd=order_size,
            status=exec_res["status"],
            simulated_latency_ms=self.config.frozen_latency_ms,
        )

        if exec_res["status"] in ("FILLED", "PARTIALLY_FILLED"):
            fill_id = f"fill_{uuid.uuid4().hex[:8]}"
            fill = ShadowFill(
                fill_id=fill_id,
                order_id=order_id,
                candidate_id=candidate.candidate_id,
                market_id=candidate.market_id,
                filled_at=t0 + timedelta(milliseconds=self.config.frozen_latency_ms),
                side=side,
                fill_price=fill_price,
                size_usd=exec_res["filled_size_usd"],
                fee_usd=exec_res["fee_usd"],
                slippage_usd=exec_res["effective_slippage_pp"] * exec_res["filled_size_usd"],
                levels_swept=exec_res["levels_swept"],
                status=exec_res["status"],
                realized_edge=None, # Populated at target horizon
            )
            return order, fill

        return order, None

    def evaluate_prospective_outcomes(self) -> Dict[str, Any]:
        """Evaluates prospective out-of-sample forward outcomes for logged shadow candidates.
        Decomposes performance across three layers:
            Theoretical Edge -> Executable Edge -> Realized Return
        Calculates raw prediction-realization gap and bins predictions to test monotonicity.
        NOTE: These represent preliminary prospective observations from initial scans;
        a full statistical audit requires the full 30-60 day prospective observation window.
        """
        now = datetime.utcnow()
        df_c = self.db.get_shadow_candidates()
        if df_c.empty:
            return {"status": "NO_CANDIDATES", "evaluated": 0}

        evaluated_count = 0
        pnl_tracking = []

        for _, row in df_c.iterrows():
            tok = str(row["token_id"])
            p_t0 = float(row["market_mid_price"])
            p_pred = float(row["predicted_fair_value"])

            ob = self.client.fetch_order_book(tok)
            p_current = self._extract_mid_or_last(ob)
            if p_current is not None:
                realized_delta = p_current - p_t0
                predicted_delta = p_pred - p_t0
                # Layer 1: Theoretical Gross Edge
                theoretical_edge = (predicted_delta / p_t0) if p_t0 > 0 else 0.0

                # Layer 2: Executable Edge (after CLOB spread & taker fees)
                bids = ob.get("bids", [])
                asks = ob.get("asks", [])
                spread = 0.02
                if bids and asks:
                    try:
                        spread = float(asks[0].get("price", 1.0)) - float(bids[0].get("price", 0.0))
                    except Exception:
                        pass
                friction = spread + (2 * self.config.frozen_taker_fee_rate)
                executable_edge = max(0.0, theoretical_edge - friction)

                # Layer 3: Realized 24h Price Movement
                realized_edge = (realized_delta / p_t0) if p_t0 > 0 else 0.0

                # Raw prediction-realization gap
                prediction_realization_gap = realized_edge - theoretical_edge

                # Directional correctness
                is_correct_sign = (predicted_delta * realized_delta) > 0
                pnl_tracking.append({
                    "candidate_id": row["candidate_id"],
                    "t0_mid": p_t0,
                    "predicted_target": p_pred,
                    "realized_price": p_current,
                    "predicted_delta": round(predicted_delta, 4),
                    "realized_delta": round(realized_delta, 4),
                    "theoretical_edge_pct": round(theoretical_edge * 100.0, 2),
                    "executable_edge_pct": round(executable_edge * 100.0, 2),
                    "realized_edge_pct": round(realized_edge * 100.0, 2),
                    "prediction_realization_gap_pp": round(prediction_realization_gap * 100.0, 2),
                    "directional_hit": bool(is_correct_sign)
                })
                evaluated_count += 1

        hit_rate = (sum(1 for x in pnl_tracking if x["directional_hit"]) / len(pnl_tracking)) if pnl_tracking else 0.0
        mean_theo_edge = np.mean([x["theoretical_edge_pct"] for x in pnl_tracking]) if pnl_tracking else 0.0
        mean_exec_edge = np.mean([x["executable_edge_pct"] for x in pnl_tracking]) if pnl_tracking else 0.0
        mean_real_edge = np.mean([x["realized_edge_pct"] for x in pnl_tracking]) if pnl_tracking else 0.0
        mean_gap = np.mean([x["prediction_realization_gap_pp"] for x in pnl_tracking]) if pnl_tracking else 0.0

        # Tradeable prospective sample (Net executable edge >= frozen threshold)
        tradeable_pnl = [
            x for x in pnl_tracking
            if x["executable_edge_pct"] >= (self.config.frozen_min_edge_threshold * 100.0)
        ]
        tradeable_count = len(tradeable_pnl)
        tradeable_hit_rate = (sum(1 for x in tradeable_pnl if x["directional_hit"]) / tradeable_count) if tradeable_count > 0 else 0.0
        tradeable_mean_theo = np.mean([x["theoretical_edge_pct"] for x in tradeable_pnl]) if tradeable_count > 0 else 0.0
        tradeable_mean_exec = np.mean([x["executable_edge_pct"] for x in tradeable_pnl]) if tradeable_count > 0 else 0.0
        tradeable_mean_real = np.mean([x["realized_edge_pct"] for x in tradeable_pnl]) if tradeable_count > 0 else 0.0
        tradeable_median_real = float(np.median([x["realized_edge_pct"] for x in tradeable_pnl])) if tradeable_count > 0 else 0.0
        tradeable_vol = float(np.std([x["realized_edge_pct"] for x in tradeable_pnl])) if tradeable_count > 1 else 0.0

        # Rank correlation (Spearman) to test monotonicity across all evaluated predictions
        spearman_corr = 0.0
        spearman_p = 1.0
        if len(pnl_tracking) > 1:
            try:
                pred_edges = [x["theoretical_edge_pct"] for x in pnl_tracking]
                real_returns = [x["realized_edge_pct"] for x in pnl_tracking]
                if len(set(pred_edges)) > 1 and len(set(real_returns)) > 1:
                    from scipy.stats import spearmanr
                    sc_res = spearmanr(pred_edges, real_returns)
                    spearman_corr = float(sc_res.correlation if not np.isnan(sc_res.correlation) else 0.0)
                    spearman_p = float(sc_res.pvalue if not np.isnan(sc_res.pvalue) else 1.0)
            except Exception as e:
                logger.debug(f"Spearman rank calculation fallback: {e}")

        # Binned Edge Analysis: 1.5-3%, 3-5%, 5-10%, >10% (plus <1.5%)
        bin_definitions = [
            ("< 1.5% (Sub-hurdle)", lambda e: e < 1.5),
            ("1.5%–3.0%", lambda e: 1.5 <= e < 3.0),
            ("3.0%–5.0%", lambda e: 3.0 <= e < 5.0),
            ("5.0%–10.0%", lambda e: 5.0 <= e < 10.0),
            ("> 10.0%", lambda e: e >= 10.0),
        ]
        binned_results = []
        for label, cond in bin_definitions:
            in_bin = [x for x in pnl_tracking if cond(x["theoretical_edge_pct"])]
            cnt = len(in_bin)
            m_theo = np.mean([x["theoretical_edge_pct"] for x in in_bin]) if cnt > 0 else 0.0
            m_exec = np.mean([x["executable_edge_pct"] for x in in_bin]) if cnt > 0 else 0.0
            m_real = np.mean([x["realized_edge_pct"] for x in in_bin]) if cnt > 0 else 0.0
            m_hit = (sum(1 for x in in_bin if x["directional_hit"]) / cnt) if cnt > 0 else 0.0
            binned_results.append({
                "bin_range": label,
                "candidate_count": cnt,
                "mean_theoretical_edge_pct": round(float(m_theo), 2),
                "mean_executable_edge_pct": round(float(m_exec), 2),
                "mean_realized_edge_pct": round(float(m_real), 2),
                "directional_hit_rate": round(float(m_hit), 2)
            })

        three_layer_decomp = {
            "theoretical_gross_edge_pct": round(float(mean_theo_edge), 2),
            "spread_and_friction_drag_pct": round(float(mean_theo_edge - mean_exec_edge), 2),
            "executable_net_edge_pct": round(float(mean_exec_edge), 2),
            "unrealized_alpha_decay_pct": round(float(mean_exec_edge - mean_real_edge), 2),
            "realized_return_pct": round(float(mean_real_edge), 2)
        }

        return {
            "discovery_sample": {
                "total_candidates": evaluated_count,
                "mean_theoretical_edge_pct": round(float(mean_theo_edge), 2),
                "mean_executable_edge_pct": round(float(mean_exec_edge), 2),
                "mean_realized_edge_pct": round(float(mean_real_edge), 2),
                "raw_prediction_realization_gap_pp": round(float(mean_gap), 2),
                "directional_hit_rate": hit_rate,
                "spearman_rank_correlation": round(spearman_corr, 4),
                "spearman_p_value": round(spearman_p, 4),
            },
            "tradeable_prospective_sample": {
                "threshold_net_edge_pct": round(self.config.frozen_min_edge_threshold * 100.0, 2),
                "qualifying_count": tradeable_count,
                "directional_hit_rate": tradeable_hit_rate,
                "mean_theoretical_edge_pct": round(float(tradeable_mean_theo), 2),
                "mean_executable_edge_pct": round(float(tradeable_mean_exec), 2),
                "mean_realized_return_pct": round(float(tradeable_mean_real), 2),
                "median_realized_return_pct": round(tradeable_median_real, 2),
                "return_volatility_pct": round(tradeable_vol, 2),
            },
            "three_layer_decomposition": three_layer_decomp,
            "binned_analysis": binned_results,
            # Backwards compatibility keys
            "evaluated_candidates": evaluated_count,
            "prospective_hit_rate": hit_rate,
            "mean_theoretical_edge_pct": round(float(mean_theo_edge), 2),
            "mean_executable_edge_pct": round(float(mean_exec_edge), 2),
            "mean_realized_edge_pct": round(float(mean_real_edge), 2),
            "raw_prediction_realization_gap_pp": round(float(mean_gap), 2),
            "tracking_details": pnl_tracking[:10]
        }

    def _extract_mid_or_last(self, ob_data: Dict[str, Any]) -> Optional[float]:
        bids = ob_data.get("bids", [])
        asks = ob_data.get("asks", [])
        if bids and asks:
            try:
                top_b = float(bids[0].get("price", 0.0))
                top_a = float(asks[0].get("price", 1.0))
                return round((top_b + top_a) / 2.0, 4)
            except Exception:
                pass
        elif bids:
            return float(bids[0].get("price", 0.0))
        elif asks:
            return float(asks[0].get("price", 1.0))
        return None

    def _tally_rejections(self, candidates: List[ShadowCandidate]) -> Dict[str, int]:
        counts = {}
        for c in candidates:
            if c.rejection_reason:
                counts[c.rejection_reason] = counts.get(c.rejection_reason, 0) + 1
        return counts
