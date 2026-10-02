"""Post-Fill Adverse Selection and Mark-to-Market Analysis for Phase 10A.8.

Responsibilities:
1. Measure post-fill price evolution across standard millisecond/second horizons:
   100ms, 250ms, 500ms, 1s, 2s, 5s, 10s, 30s, 60s.
2. Calculate both midpoint drift and true executable exit price by walking opposite-side L2 depth.
3. Compute adverse selection bps and mark-to-market P&L.
4. Flag depth exhaustion during liquidation.
"""

from datetime import datetime, timedelta
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from src.phase10a8.schema import (
    QuoteSide,
    PassiveQuote,
    FillResult,
    AdverseSelectionRecord,
    STANDARD_HORIZONS_MS,
)
from src.phase10a8.book_features import BookFeatureExtractor


class AdverseSelectionCalculator:
    """Calculates executable post-fill adverse selection across standard horizons."""

    @classmethod
    def evaluate_post_fill_trajectory(
        cls,
        quote: PassiveQuote,
        fill: FillResult,
        subsequent_snapshots: List[Dict[str, Any]],
        horizons_ms: Optional[List[int]] = None,
    ) -> List[AdverseSelectionRecord]:
        """Measures adverse selection across multiple horizons following fill timestamp."""
        if not fill.fill_timestamp or fill.fill_size_usd <= 0:
            return []

        horizons = horizons_ms or STANDARD_HORIZONS_MS
        fill_t = fill.fill_timestamp
        fill_px = fill.fill_price
        fill_size = fill.fill_size_usd
        shares = fill.fill_shares
        side = quote.side

        # Sort snapshots chronologically
        valid_snaps = [
            s for s in subsequent_snapshots
            if s["market_id"] == quote.market_id
            and s["token_id"] == quote.token_id
            and s["timestamp"] >= fill_t
        ]
        valid_snaps = sorted(valid_snaps, key=lambda x: x["timestamp"])

        if not valid_snaps:
            return []

        records: List[AdverseSelectionRecord] = []

        for h_ms in horizons:
            target_t = fill_t + timedelta(milliseconds=h_ms)
            
            # Find closest snapshot at or after target_t
            matching_snap = None
            for s in valid_snaps:
                if s["timestamp"] >= target_t:
                    matching_snap = s
                    break
            
            # Fallback to closest available snapshot
            if not matching_snap and valid_snaps:
                matching_snap = valid_snaps[-1]

            if not matching_snap:
                continue

            # Extract future book
            bids = BookFeatureExtractor.parse_ladder(matching_snap.get("bids"))
            asks = BookFeatureExtractor.parse_ladder(matching_snap.get("asks"))
            bids = sorted(bids, key=lambda x: x["price"], reverse=True)
            asks = sorted(asks, key=lambda x: x["price"], reverse=False)

            best_bid_fut = bids[0]["price"] if bids else 0.0
            best_ask_fut = asks[0]["price"] if asks else 1.0
            mid_fut = round((best_bid_fut + best_ask_fut) / 2.0, 6)
            mid_change_bps = round(((mid_fut - quote.midpoint) / quote.midpoint) * 10000.0, 2)

            # Executable Exit Price:
            # BUY fill -> Must SELL into bids
            # SELL fill -> Must BUY into asks
            depth_exhausted = False
            if side == QuoteSide.BUY:
                exit_vwap, depth_exhausted = cls._walk_ladder_exit(bids, fill_size, is_buy=False)
                # Adverse selection: fill_price - executable_exit_price
                adv_sel_bps = round(((fill_px - exit_vwap) / fill_px) * 10000.0, 2)
                mtm_pnl_usd = round(shares * (exit_vwap - fill_px), 4)
            else:  # QuoteSide.SELL
                exit_vwap, depth_exhausted = cls._walk_ladder_exit(asks, fill_size, is_buy=True)
                # Adverse selection: executable_exit_price - fill_price
                adv_sel_bps = round(((exit_vwap - fill_px) / fill_px) * 10000.0, 2)
                mtm_pnl_usd = round(shares * (fill_px - exit_vwap), 4)

            rid = hashlib.sha256(
                f"{fill.fill_id}_{h_ms}_{matching_snap['snapshot_id']}".encode()
            ).hexdigest()[:24]

            records.append(
                AdverseSelectionRecord(
                    record_id=rid,
                    fill_id=fill.fill_id,
                    quote_id=quote.quote_id,
                    horizon_ms=h_ms,
                    post_fill_timestamp=matching_snap["timestamp"],
                    midpoint_entry=quote.midpoint,
                    midpoint_future=mid_fut,
                    midpoint_change_bps=mid_change_bps,
                    executable_exit_vwap=round(exit_vwap, 4),
                    adverse_selection_bps=adv_sel_bps,
                    mark_to_market_pnl_usd=mtm_pnl_usd,
                    exit_depth_exhausted=depth_exhausted,
                )
            )

        return records

    @staticmethod
    def _walk_ladder_exit(
        ladder: List[Dict[str, float]],
        target_size_usd: float,
        is_buy: bool,
    ) -> Tuple[float, bool]:
        """Walks ladder to determine executable exit VWAP."""
        if not ladder or target_size_usd <= 0:
            return 0.50, True

        filled_usd = 0.0
        filled_shares = 0.0
        depth_exhausted = False

        for level in ladder:
            p = level["price"]
            s = level["size"]
            u = level["size_usd"]
            needed_usd = target_size_usd - filled_usd

            if u <= needed_usd:
                filled_usd += u
                filled_shares += s
            else:
                fraction = needed_usd / u
                filled_usd += needed_usd
                filled_shares += s * fraction
                break

        if filled_usd < target_size_usd * 0.99:
            depth_exhausted = True
            # Extrapolate beyond book with penalty
            if is_buy:
                p_last = ladder[-1]["price"] if ladder else 1.0
                unfilled_usd = target_size_usd - filled_usd
                penalty_px = min(0.99, p_last * 1.05)
                filled_shares += unfilled_usd / penalty_px
                filled_usd = target_size_usd
            else:
                p_last = ladder[-1]["price"] if ladder else 0.0
                unfilled_usd = target_size_usd - filled_usd
                penalty_px = max(0.01, p_last * 0.95)
                filled_shares += unfilled_usd / penalty_px
                filled_usd = target_size_usd

        vwap = filled_usd / filled_shares if filled_shares > 0 else 0.50
        return vwap, depth_exhausted
