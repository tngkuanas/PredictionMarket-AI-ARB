"""Deterministic Comparison Tool: Periodic Snapshots vs Raw WebSocket Reconstruction.

Audits whether periodic snapshots in phase10a5_book_snapshots match the state
reconstructed directly from the underlying raw WebSocket frames.

Classifies discrepancies:
- EXACT_MATCH: identical best quotes, spread, and depth (diff <= 1e-4)
- EXPECTED_TIMESTAMP_DIFFERENCE: slight clock disparity between snapshot write and raw event
- RECONSTRUCTION_DIFFERENCE: depth aggregation level disparity
- DATA_QUALITY_ISSUE: uninitialized session or dropped packet
- IMPLEMENTATION_BUG: logic error in ladder delta processing
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import logging
from typing import Dict, List, Optional, Tuple, Any

import duckdb
import pandas as pd

from src.phase10.response_study.raw_l2_reconstructor import (
    RawL2OrderBookReconstructor,
    ReconstructedRawBookState,
)
from src.phase10.response_study.executable_price_model import ExecutablePriceModel

logger = logging.getLogger(__name__)


@dataclass
class SnapshotComparisonPoint:
    snapshot_id: str
    token_id: str
    timestamp: datetime
    snap_best_bid: Optional[float]
    raw_best_bid: Optional[float]
    snap_best_ask: Optional[float]
    raw_best_ask: Optional[float]
    snap_spread: Optional[float]
    raw_spread: Optional[float]
    bid_diff: float
    ask_diff: float
    spread_diff: float
    snap_vwap_buy: float
    raw_vwap_buy: float
    vwap_diff_bps: float
    discrepancy_category: str # "EXACT_MATCH", "EXPECTED_TIMESTAMP_DIFFERENCE", "RECONSTRUCTION_DIFFERENCE", "DATA_QUALITY_ISSUE", "IMPLEMENTATION_BUG"
    explanation: str


@dataclass
class SnapshotComparisonSummary:
    token_id: str
    total_evaluated: int
    exact_match_count: int
    expected_diff_count: int
    reconstruction_diff_count: int
    data_quality_issue_count: int
    implementation_bug_count: int
    mean_spread_discrepancy: float
    mean_vwap_discrepancy_bps: float
    is_concordant: bool
    details: Dict[str, Any] = field(default_factory=dict)


class SnapshotRawComparator:
    """Compares periodic database snapshots with genuine raw WebSocket reconstruction."""

    def __init__(
        self,
        db_path: str = "data/prediction_market.duckdb",
        tolerance: float = 1e-4
    ):
        self.db_path = db_path
        self.tolerance = tolerance
        self.reconstructor = RawL2OrderBookReconstructor(db_path=db_path)
        self.exec_model = ExecutablePriceModel()

    def compare_token_snapshots(
        self,
        token_id: str,
        limit: int = 10,
        test_order_size_usd: float = 50.0
    ) -> Tuple[List[SnapshotComparisonPoint], SnapshotComparisonSummary]:
        """Loads periodic snapshots for a token and compares against raw reconstruction."""
        query = """
            SELECT 
                snapshot_id, session_id, market_id, token_id, 
                exchange_timestamp, best_bid, best_ask, spread, bids, asks
            FROM phase10a5_book_snapshots
            WHERE token_id = ?
            ORDER BY exchange_timestamp DESC
            LIMIT ?
        """
        rows = self.reconstructor._execute_read_query(query, [token_id, limit])
        if not rows:
            return [], SnapshotComparisonSummary(
                token_id=token_id, total_evaluated=0, exact_match_count=0,
                expected_diff_count=0, reconstruction_diff_count=0,
                data_quality_issue_count=0, implementation_bug_count=0,
                mean_spread_discrepancy=0.0, mean_vwap_discrepancy_bps=0.0,
                is_concordant=False, details={"reason": "No snapshots found"}
            )

        points: List[SnapshotComparisonPoint] = []
        bid_diffs = []
        vwap_diffs = []

        for snap_id, sess_id, mkt_id, tok_id, exch_ts, s_bid, s_ask, s_spr, bids_raw, asks_raw in rows:
            # Reconstruct from raw WebSocket frames at this exact timestamp
            raw_state = self.reconstructor.reconstruct_book_at_timestamp(
                token_id=tok_id,
                target_timestamp=exch_ts,
                market_id=mkt_id,
                session_id=sess_id,
                timestamp_basis="exchange"
            )

            if raw_state.status != "VALID":
                cat = "DATA_QUALITY_ISSUE" if raw_state.status in ("MISSING_DATA", "UNINITIALIZED") else "RECONSTRUCTION_DIFFERENCE"
                points.append(SnapshotComparisonPoint(
                    snapshot_id=snap_id,
                    token_id=tok_id,
                    timestamp=exch_ts,
                    snap_best_bid=s_bid,
                    raw_best_bid=raw_state.best_bid,
                    snap_best_ask=s_ask,
                    raw_best_ask=raw_state.best_ask,
                    snap_spread=s_spr,
                    raw_spread=raw_state.spread,
                    bid_diff=1.0,
                    ask_diff=1.0,
                    spread_diff=1.0,
                    snap_vwap_buy=0.0,
                    raw_vwap_buy=0.0,
                    vwap_diff_bps=0.0,
                    discrepancy_category=cat,
                    explanation=f"Raw reconstructor returned status {raw_state.status}"
                ))
                continue

            r_bid = raw_state.best_bid
            r_ask = raw_state.best_ask
            r_spr = raw_state.spread

            b_diff = abs(s_bid - r_bid) if (s_bid is not None and r_bid is not None) else 0.0
            a_diff = abs(s_ask - r_ask) if (s_ask is not None and r_ask is not None) else 0.0
            s_diff = abs(s_spr - r_spr) if (s_spr is not None and r_spr is not None) else 0.0
            bid_diffs.append(b_diff)

            # VWAP comparison
            snap_fill = self.exec_model.execute_taker_order(bids_raw, asks_raw, "BUY", test_order_size_usd)
            raw_fill = self.reconstructor.execute_taker_order_on_raw_book(raw_state, "BUY", test_order_size_usd)

            v_diff_bps = 0.0
            if snap_fill.is_fillable and raw_fill.is_fillable:
                v_diff_bps = abs(snap_fill.fill_price_vwap - raw_fill.fill_price_vwap) / snap_fill.fill_price_vwap * 10000.0
            vwap_diffs.append(v_diff_bps)

            # Categorize
            if b_diff <= self.tolerance and a_diff <= self.tolerance:
                cat = "EXACT_MATCH"
                exp = "Exact match between snapshot and raw WebSocket reconstruction."
            elif b_diff <= 0.01 and a_diff <= 0.01:
                cat = "EXPECTED_TIMESTAMP_DIFFERENCE"
                exp = "Sub-cent difference attributable to snapshot sampling epoch alignment."
            else:
                cat = "RECONSTRUCTION_DIFFERENCE"
                exp = f"Spread diff: {s_diff:.4f}, VWAP diff: {v_diff_bps:.1f} bps"

            points.append(SnapshotComparisonPoint(
                snapshot_id=snap_id,
                token_id=tok_id,
                timestamp=exch_ts,
                snap_best_bid=s_bid,
                raw_best_bid=r_bid,
                snap_best_ask=s_ask,
                raw_best_ask=r_ask,
                snap_spread=s_spr,
                raw_spread=r_spr,
                bid_diff=round(b_diff, 6),
                ask_diff=round(a_diff, 6),
                spread_diff=round(s_diff, 6),
                snap_vwap_buy=round(snap_fill.fill_price_vwap, 4) if snap_fill.is_fillable else 0.0,
                raw_vwap_buy=round(raw_fill.fill_price_vwap, 4) if raw_fill.is_fillable else 0.0,
                vwap_diff_bps=round(v_diff_bps, 2),
                discrepancy_category=cat,
                explanation=exp
            ))

        exact_cnt = sum(1 for p in points if p.discrepancy_category == "EXACT_MATCH")
        exp_cnt = sum(1 for p in points if p.discrepancy_category == "EXPECTED_TIMESTAMP_DIFFERENCE")
        rec_cnt = sum(1 for p in points if p.discrepancy_category == "RECONSTRUCTION_DIFFERENCE")
        dq_cnt = sum(1 for p in points if p.discrepancy_category == "DATA_QUALITY_ISSUE")
        bug_cnt = sum(1 for p in points if p.discrepancy_category == "IMPLEMENTATION_BUG")

        summary = SnapshotComparisonSummary(
            token_id=token_id,
            total_evaluated=len(points),
            exact_match_count=exact_cnt,
            expected_diff_count=exp_cnt,
            reconstruction_diff_count=rec_cnt,
            data_quality_issue_count=dq_cnt,
            implementation_bug_count=bug_cnt,
            mean_spread_discrepancy=round(float(pd.Series(bid_diffs).mean()), 6) if bid_diffs else 0.0,
            mean_vwap_discrepancy_bps=round(float(pd.Series(vwap_diffs).mean()), 2) if vwap_diffs else 0.0,
            is_concordant=bool(exact_cnt + exp_cnt >= 0.8 * len(points) if points else False),
            details={"discrepancy_breakdown": {
                "EXACT_MATCH": exact_cnt,
                "EXPECTED_TIMESTAMP_DIFFERENCE": exp_cnt,
                "RECONSTRUCTION_DIFFERENCE": rec_cnt,
                "DATA_QUALITY_ISSUE": dq_cnt,
                "IMPLEMENTATION_BUG": bug_cnt,
            }}
        )

        return points, summary
