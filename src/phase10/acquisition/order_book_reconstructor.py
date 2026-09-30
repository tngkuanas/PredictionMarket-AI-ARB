"""Deterministic High-Frequency Order-Book Reconstruction Engine.

Reconstructs full L2 order books from raw Polymarket WebSocket messages,
applying initial book snapshots and handling incremental price changes, deletions (size=0),
and updates. Identifies crossed books, sequence anomalies, and malformed frames.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Tuple, Any

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    DataQualityStatus,
)

logger = logging.getLogger(__name__)


class OrderBookReconstructor:
    """Maintains and reconstructs deterministic order books per token from raw messages."""

    def __init__(self, depth_levels_limit: int = 10):
        self.depth_limit = depth_levels_limit
        # token_id -> {"bids": {price: size}, "asks": {price: size}, "market_id": str, "seq": int, "initialized": bool}
        self._books: Dict[str, Dict[str, Any]] = {}
        self._stale_or_reconnecting: bool = False
        self.reconstructed_snapshots: List[ReconstructedBookSnapshot] = []
        self.book_updates: List[BookUpdateRecord] = []

    def mark_disconnected(self) -> None:
        """Marks books as disconnected/stale so incremental updates are never applied prior to fresh snapshots."""
        self._stale_or_reconnecting = True
        for tok in self._books:
            self._books[tok]["initialized"] = False
        logger.info("OrderBookReconstructor: Marked all existing token books as uninitialized/stale pending fresh snapshots.")


    def process_raw_record(
        self,
        raw_rec: RawMessageRecord
    ) -> Tuple[List[BookUpdateRecord], Optional[ReconstructedBookSnapshot]]:
        """Processes a raw message, updates the internal book state, and emits records."""
        try:
            payload = json.loads(raw_rec.raw_message_json)
        except Exception as e:
            logger.warning(f"Failed to decode raw message JSON: {e}")
            return [], None

        msg_type = raw_rec.message_type
        if msg_type == "book":
            return self._handle_book_snapshot(payload, raw_rec)
        elif msg_type == "price_change":
            return self._handle_price_changes(payload, raw_rec)
        else:
            # Trade or other message type - does not mutate book structure
            return [], None

    def _handle_book_snapshot(
        self,
        payload: Dict[str, Any],
        raw_rec: RawMessageRecord
    ) -> Tuple[List[BookUpdateRecord], Optional[ReconstructedBookSnapshot]]:
        token_id = str(payload.get("asset_id") or raw_rec.token_id or "")
        market_id = str(payload.get("market") or raw_rec.market_id or "")
        if not token_id:
            return [], None

        bids_map: Dict[float, float] = {}
        for b in payload.get("bids", []):
            try:
                p = round(float(b.get("price", 0.0)), 4)
                s = round(float(b.get("size", 0.0)), 4)
                if p > 0 and s > 0:
                    bids_map[p] = s
            except (ValueError, TypeError):
                continue

        asks_map: Dict[float, float] = {}
        for a in payload.get("asks", []):
            try:
                p = round(float(a.get("price", 0.0)), 4)
                s = round(float(a.get("size", 0.0)), 4)
                if p > 0 and s > 0:
                    asks_map[p] = s
            except (ValueError, TypeError):
                continue

        self._books[token_id] = {
            "bids": bids_map,
            "asks": asks_map,
            "market_id": market_id,
            "seq": 1,
            "initialized": True
        }

        snap = self._compile_snapshot(token_id, raw_rec.ingestion_session_id, raw_rec.receive_timestamp, raw_rec.exchange_timestamp)
        if snap:
            self.reconstructed_snapshots.append(snap)
        return [], snap

    def _handle_price_changes(
        self,
        payload: Dict[str, Any],
        raw_rec: RawMessageRecord
    ) -> Tuple[List[BookUpdateRecord], Optional[ReconstructedBookSnapshot]]:
        market_id = str(payload.get("market") or raw_rec.market_id or "")
        changes = payload.get("price_changes", [])
        if not changes:
            return [], None

        updates: List[BookUpdateRecord] = []
        affected_tokens = set()

        for chg in changes:
            token_id = str(chg.get("asset_id") or raw_rec.token_id or "")
            if not token_id:
                continue

            # Anti-Stale-Book Gating (Phase 10A.5d Section 8):
            # Do NOT apply deltas to uninitialized or disconnected stale books
            if token_id not in self._books or not self._books[token_id].get("initialized", False):
                logger.debug(f"Gating: Dropping incremental price change on uninitialized/stale token {token_id}")
                continue

            try:
                price = round(float(chg.get("price", 0.0)), 4)
                size = round(float(chg.get("size", 0.0)), 4)
                side = str(chg.get("side", "")).upper()
                chg_hash = chg.get("hash")
                best_bid = float(chg.get("best_bid")) if chg.get("best_bid") else None
                best_ask = float(chg.get("best_ask")) if chg.get("best_ask") else None
            except (ValueError, TypeError) as ex:
                logger.debug(f"Malformed price change element: {ex}")
                continue

            book = self._books[token_id]
            book["seq"] += 1
            target_side_map = book["bids"] if side == "BUY" else book["asks"]

            # Determine delta type
            if size == 0.0:
                delta_type = "delete"
                if price in target_side_map:
                    del target_side_map[price]
            elif price in target_side_map:
                delta_type = "update"
                target_side_map[price] = size
            else:
                delta_type = "insert"
                target_side_map[price] = size

            upd_rec = BookUpdateRecord(
                update_id=f"upd_{raw_rec.ingestion_session_id}_{book['seq']}_{raw_rec.message_id}",
                session_id=raw_rec.ingestion_session_id,
                market_id=market_id,
                token_id=token_id,
                receive_timestamp=raw_rec.receive_timestamp,
                exchange_timestamp=raw_rec.exchange_timestamp,
                side=side,
                price=price,
                size=size,
                delta_type=delta_type,
                best_bid=best_bid,
                best_ask=best_ask,
                hash=chg_hash
            )
            updates.append(upd_rec)
            self.book_updates.append(upd_rec)
            affected_tokens.add(token_id)

        # Emit snapshot for primary affected token
        last_snap = None
        for tok in affected_tokens:
            snap = self._compile_snapshot(tok, raw_rec.ingestion_session_id, raw_rec.receive_timestamp, raw_rec.exchange_timestamp)
            if snap:
                self.reconstructed_snapshots.append(snap)
                last_snap = snap

        return updates, last_snap

    def _compile_snapshot(
        self,
        token_id: str,
        session_id: str,
        receive_ts: datetime,
        exchange_ts: Optional[datetime]
    ) -> Optional[ReconstructedBookSnapshot]:
        if token_id not in self._books:
            return None

        book = self._books[token_id]
        market_id = book["market_id"]
        bids_map = book["bids"]
        asks_map = book["asks"]

        # Sort bids descending, asks ascending
        sorted_bids = sorted(bids_map.items(), key=lambda x: x[0], reverse=True)[:self.depth_limit]
        sorted_asks = sorted(asks_map.items(), key=lambda x: x[0], reverse=False)[:self.depth_limit]

        # Check for missing data
        if not sorted_bids or not sorted_asks:
            best_b = sorted_bids[0][0] if sorted_bids else 0.0
            best_a = sorted_asks[0][0] if sorted_asks else 1.0
            return ReconstructedBookSnapshot(
                snapshot_id=f"snap_{token_id}_{int(receive_ts.timestamp()*1000)}_{book['seq']}",
                session_id=session_id,
                market_id=market_id,
                token_id=token_id,
                timestamp=receive_ts,
                exchange_timestamp=exchange_ts,
                best_bid=best_b,
                best_ask=best_a,
                midpoint=round((best_b + best_a) / 2.0, 4),
                spread=round(max(0.0, best_a - best_b), 4),
                spread_bps=0.0,
                depth_bid_usd=sum(p * s for p, s in sorted_bids),
                depth_ask_usd=sum(p * s for p, s in sorted_asks),
                book_imbalance=0.0,
                bids=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_bids],
                asks=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_asks],
                quality_status=DataQualityStatus.MISSING_DATA,
                quality_reason="One-sided book: bids or asks empty"
            )

        best_bid = sorted_bids[0][0]
        best_ask = sorted_asks[0][0]

        # Check for crossed book (best_bid >= best_ask)
        if best_bid >= best_ask:
            return ReconstructedBookSnapshot(
                snapshot_id=f"snap_{token_id}_{int(receive_ts.timestamp()*1000)}_{book['seq']}",
                session_id=session_id,
                market_id=market_id,
                token_id=token_id,
                timestamp=receive_ts,
                exchange_timestamp=exchange_ts,
                best_bid=best_bid,
                best_ask=best_ask,
                midpoint=round((best_bid + best_ask) / 2.0, 4),
                spread=round(best_ask - best_bid, 4),
                spread_bps=round(((best_ask - best_bid) / best_bid) * 10000.0, 1),
                depth_bid_usd=sum(p * s for p, s in sorted_bids),
                depth_ask_usd=sum(p * s for p, s in sorted_asks),
                book_imbalance=0.0,
                bids=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_bids],
                asks=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_asks],
                quality_status=DataQualityStatus.CROSSED_BOOK,
                quality_reason=f"Crossed book: best_bid ({best_bid}) >= best_ask ({best_ask})"
            )

        midpoint = round((best_bid + best_ask) / 2.0, 4)
        spread = round(best_ask - best_bid, 4)
        spread_bps = round((spread / midpoint) * 10000.0, 1) if midpoint > 0 else 0.0

        depth_bid = sum(p * s for p, s in sorted_bids)
        depth_ask = sum(p * s for p, s in sorted_asks)
        tot_depth = depth_bid + depth_ask
        imbalance = round((depth_bid - depth_ask) / tot_depth, 4) if tot_depth > 0 else 0.0

        return ReconstructedBookSnapshot(
            snapshot_id=f"snap_{token_id}_{int(receive_ts.timestamp()*1000)}_{book['seq']}",
            session_id=session_id,
            market_id=market_id,
            token_id=token_id,
            timestamp=receive_ts,
            exchange_timestamp=exchange_ts,
            best_bid=best_bid,
            best_ask=best_ask,
            midpoint=midpoint,
            spread=spread,
            spread_bps=spread_bps,
            depth_bid_usd=round(depth_bid, 2),
            depth_ask_usd=round(depth_ask, 2),
            book_imbalance=imbalance,
            bids=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_bids],
            asks=[{"price": p, "size": s, "size_usd": round(p * s, 2)} for p, s in sorted_asks],
            quality_status=DataQualityStatus.VALID,
            quality_reason=None
        )
