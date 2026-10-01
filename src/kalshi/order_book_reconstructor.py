"""Deterministic Kalshi L2 Order-Book Reconstruction Engine.

Maintains and reconstructs full L2 order books from Kalshi WebSocket messages,
processing initial snapshots, incremental level updates (delta_fp), level deletions,
computing complementary executable sides (YES/NO parity), and detecting structural
anomalies (crossed books, locked books, sequence gaps, impossible prices).
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Dict, List, Optional, Tuple, Any

from src.kalshi.schema import (
    KalshiRawMessageRecord,
    KalshiBookUpdateRecord,
    KalshiReconstructedBookSnapshot,
    KalshiDataQualityStatus,
)

logger = logging.getLogger(__name__)


class KalshiOrderBookReconstructor:
    """Deterministic order-book reconstructor adhering to Kalshi v2 WebSocket semantics."""

    def __init__(self, depth_limit: int = 10, stale_threshold_seconds: float = 30.0):
        self.depth_limit = depth_limit
        self.stale_threshold_seconds = stale_threshold_seconds
        # market_ticker -> {
        #   "yes_bids": {price: qty},
        #   "no_bids": {price: qty},
        #   "yes_asks": {price: qty},
        #   "no_asks": {price: qty},
        #   "seq": int,
        #   "last_update_ts": datetime,
        #   "initialized": bool,
        #   "session_id": str
        # }
        self._books: Dict[str, Dict[str, Any]] = {}
        self.reconstructed_snapshots: List[KalshiReconstructedBookSnapshot] = []
        self.book_updates: List[KalshiBookUpdateRecord] = []

    def clear_buffers(self) -> None:
        """Clears memory buffers after persistence to DuckDB."""
        self.reconstructed_snapshots.clear()
        self.book_updates.clear()

    def mark_disconnected(self) -> None:
        """Marks all internal market books as uninitialized to prevent stale delta application."""
        for mkt in self._books:
            self._books[mkt]["initialized"] = False
        logger.info("KalshiReconstructor: Marked all market order books uninitialized pending fresh snapshots.")

    def process_raw_record(
        self,
        raw_rec: KalshiRawMessageRecord
    ) -> Tuple[List[KalshiBookUpdateRecord], Optional[KalshiReconstructedBookSnapshot]]:
        """Processes a raw Kalshi message frame, mutates book state, and outputs snapshot."""
        try:
            payload = json.loads(raw_rec.raw_payload)
        except Exception as e:
            logger.warning(f"Failed to decode raw message JSON: {e}")
            return [], None

        msg_type = raw_rec.message_type
        if msg_type == "orderbook_snapshot":
            return self._handle_snapshot(payload, raw_rec)
        elif msg_type == "orderbook_delta":
            return self._handle_delta(payload, raw_rec)
        else:
            return [], None

    def _extract_market_id(self, payload: Dict[str, Any], raw_rec: KalshiRawMessageRecord) -> str:
        msg = payload.get("msg", {}) if isinstance(payload.get("msg"), dict) else payload
        mkt = (
            msg.get("market_ticker") or
            msg.get("ticker") or
            raw_rec.market_id or
            payload.get("market_ticker") or
            payload.get("ticker")
        )
        return str(mkt or "").strip()

    def _parse_price_qty(self, item: Any) -> Tuple[Optional[float], Optional[float]]:
        """Parses price and quantity from various Kalshi payload formats (cents, dollars, string, list)."""
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                p_raw, q_raw = item[0], item[1]
                p = float(p_raw)
                # Convert cents (1-99) to dollars (0.01-0.99) if > 1.0
                if p > 1.0:
                    p = p / 100.0
                q = float(q_raw)
                return round(p, 4), round(q, 4)
            elif isinstance(item, dict):
                p_raw = item.get("price_dollars") or item.get("price")
                q_raw = item.get("delta_fp") or item.get("quantity") or item.get("size")
                if p_raw is not None and q_raw is not None:
                    p = float(p_raw)
                    if p > 1.0:
                        p = p / 100.0
                    q = float(q_raw)
                    return round(p, 4), round(q, 4)
        except (ValueError, TypeError):
            pass
        return None, None

    def _handle_snapshot(
        self,
        payload: Dict[str, Any],
        raw_rec: KalshiRawMessageRecord
    ) -> Tuple[List[KalshiBookUpdateRecord], Optional[KalshiReconstructedBookSnapshot]]:
        market_id = self._extract_market_id(payload, raw_rec)
        if not market_id:
            return [], None

        msg = payload.get("msg", {}) if isinstance(payload.get("msg"), dict) else payload
        seq = payload.get("seq") or msg.get("seq")
        if seq is not None:
            try:
                seq = int(seq)
            except (ValueError, TypeError):
                seq = None

        yes_bids: Dict[float, float] = {}
        no_bids: Dict[float, float] = {}
        yes_asks: Dict[float, float] = {}
        no_asks: Dict[float, float] = {}

        # 1. Parse YES levels
        yes_items = msg.get("yes_dollars_fp") or msg.get("yes") or []
        for it in yes_items:
            p, q = self._parse_price_qty(it)
            if p is not None and q is not None and p > 0 and q > 0:
                yes_bids[p] = q

        # 2. Parse NO levels
        no_items = msg.get("no_dollars_fp") or msg.get("no") or []
        for it in no_items:
            p, q = self._parse_price_qty(it)
            if p is not None and q is not None and p > 0 and q > 0:
                no_bids[p] = q

        # 3. Explicit asks if present
        for it in msg.get("yes_asks", []):
            p, q = self._parse_price_qty(it)
            if p is not None and q is not None and p > 0 and q > 0:
                yes_asks[p] = q

        for it in msg.get("no_asks", []):
            p, q = self._parse_price_qty(it)
            if p is not None and q is not None and p > 0 and q > 0:
                no_asks[p] = q

        # Store in book state
        self._books[market_id] = {
            "yes_bids": yes_bids,
            "no_bids": no_bids,
            "yes_asks": yes_asks,
            "no_asks": no_asks,
            "seq": seq or 1,
            "last_update_ts": raw_rec.receive_timestamp,
            "initialized": True,
            "session_id": raw_rec.session_id,
        }

        # Build snapshot record
        snap = self._compile_snapshot(market_id, raw_rec, seq)
        if snap:
            self.reconstructed_snapshots.append(snap)
        return [], snap

    def _handle_delta(
        self,
        payload: Dict[str, Any],
        raw_rec: KalshiRawMessageRecord
    ) -> Tuple[List[KalshiBookUpdateRecord], Optional[KalshiReconstructedBookSnapshot]]:
        market_id = self._extract_market_id(payload, raw_rec)
        if not market_id:
            return [], None

        msg = payload.get("msg", {}) if isinstance(payload.get("msg"), dict) else payload
        seq = payload.get("seq") or msg.get("seq")
        if seq is not None:
            try:
                seq = int(seq)
            except (ValueError, TypeError):
                seq = None

        # Check if book is initialized
        book = self._books.get(market_id)
        if not book or not book.get("initialized"):
            # Update before snapshot anomaly
            snap = self._build_anomaly_snapshot(
                market_id, raw_rec, seq,
                KalshiDataQualityStatus.UPDATE_BEFORE_SNAPSHOT,
                "Delta update received before initial book snapshot."
            )
            self.reconstructed_snapshots.append(snap)
            return [], snap

        # Check session contamination
        if book.get("session_id") != raw_rec.session_id:
            snap = self._build_anomaly_snapshot(
                market_id, raw_rec, seq,
                KalshiDataQualityStatus.SESSION_CONTAMINATION,
                f"Delta session ({raw_rec.session_id}) does not match initialized session ({book.get('session_id')})."
            )
            self.reconstructed_snapshots.append(snap)
            return [], snap

        # Check sequence gaps and duplicate updates
        last_seq = book.get("seq")
        if seq is not None and last_seq is not None:
            if seq == last_seq:
                snap = self._build_anomaly_snapshot(
                    market_id, raw_rec, seq,
                    KalshiDataQualityStatus.DUPLICATE_UPDATE,
                    f"Duplicate sequence number {seq} received."
                )
                self.reconstructed_snapshots.append(snap)
                return [], snap
            elif seq < last_seq:
                snap = self._build_anomaly_snapshot(
                    market_id, raw_rec, seq,
                    KalshiDataQualityStatus.OUT_OF_ORDER,
                    f"Out of order sequence {seq} received after {last_seq}."
                )
                self.reconstructed_snapshots.append(snap)
                return [], snap
            elif seq > last_seq + 1:
                # Sequence gap detected
                logger.warning(f"Sequence gap on Kalshi {market_id}: {last_seq} -> {seq}")
                book["initialized"] = False  # Mark uninitialized until fresh snapshot
                snap = self._build_anomaly_snapshot(
                    market_id, raw_rec, seq,
                    KalshiDataQualityStatus.INVALID_SEQUENCE,
                    f"Sequence gap detected: expected {last_seq + 1}, got {seq}."
                )
                self.reconstructed_snapshots.append(snap)
                return [], snap

        # Extract delta fields
        side = str(msg.get("side", "yes")).lower()
        price_raw = msg.get("price_dollars") if "price_dollars" in msg else msg.get("price")
        delta_qty_raw = msg.get("delta_fp") if "delta_fp" in msg else msg.get("delta")

        if price_raw is None or delta_qty_raw is None:
            snap = self._build_anomaly_snapshot(
                market_id, raw_rec, seq,
                KalshiDataQualityStatus.MALFORMED,
                "Delta update missing price or delta quantity fields."
            )
            self.reconstructed_snapshots.append(snap)
            return [], snap

        try:
            price = float(price_raw)
            if price > 1.0:
                price = price / 100.0
            price = round(price, 4)
            delta_qty = float(delta_qty_raw)
        except (ValueError, TypeError) as e:
            snap = self._build_anomaly_snapshot(
                market_id, raw_rec, seq,
                KalshiDataQualityStatus.MALFORMED,
                f"Failed to parse numerical delta fields: {e}"
            )
            self.reconstructed_snapshots.append(snap)
            return [], snap

        # Price bounds validation
        if price <= 0.0 or price >= 1.0:
            snap = self._build_anomaly_snapshot(
                market_id, raw_rec, seq,
                KalshiDataQualityStatus.IMPOSSIBLE_PRICE,
                f"Impossible price {price} outside valid prediction bounds (0.01, 0.99)."
            )
            self.reconstructed_snapshots.append(snap)
            return [], snap

        target_side_map = book["yes_bids"] if side == "yes" else book["no_bids"]
        old_qty = target_side_map.get(price, 0.0)
        new_qty = max(0.0, round(old_qty + delta_qty, 4))

        if old_qty == 0.0 and new_qty > 0.0:
            action = "add"
        elif new_qty == 0.0:
            action = "delete"
        else:
            action = "modify"

        if new_qty <= 0.0:
            target_side_map.pop(price, None)
        else:
            target_side_map[price] = new_qty

        if seq is not None:
            book["seq"] = seq
        book["last_update_ts"] = raw_rec.receive_timestamp

        upd = KalshiBookUpdateRecord(
            update_id=f"upd_{market_id}_{seq or int(datetime.now().timestamp())}_{price}",
            session_id=raw_rec.session_id,
            market_id=market_id,
            receive_timestamp=raw_rec.receive_timestamp,
            exchange_timestamp=raw_rec.exchange_timestamp,
            side=side,
            action=action,
            price=price,
            delta_quantity=delta_qty,
            remaining_quantity=new_qty,
            sequence=seq,
            raw_message_id=raw_rec.raw_message_id
        )
        self.book_updates.append(upd)

        snap = self._compile_snapshot(market_id, raw_rec, seq)
        if snap:
            self.reconstructed_snapshots.append(snap)
        return [upd], snap

    def _compile_snapshot(
        self,
        market_id: str,
        raw_rec: KalshiRawMessageRecord,
        seq: Optional[int]
    ) -> Optional[KalshiReconstructedBookSnapshot]:
        book = self._books.get(market_id)
        if not book:
            return None

        # Sorted YES bids (highest first)
        yes_bids_sorted = sorted(book["yes_bids"].items(), key=lambda x: x[0], reverse=True)[:self.depth_limit]
        # Sorted NO bids (highest first)
        no_bids_sorted = sorted(book["no_bids"].items(), key=lambda x: x[0], reverse=True)[:self.depth_limit]

        # Explicit or Derived YES asks:
        # A NO bid at price P_no implies a YES ask at (1.0 - P_no)
        # Lowest ask is (1.0 - highest NO bid)
        if book["yes_asks"]:
            yes_asks_sorted = sorted(book["yes_asks"].items(), key=lambda x: x[0])[:self.depth_limit]
        else:
            # Deterministic transformation from NO bids
            yes_asks_sorted = sorted(
                [(round(1.0 - p, 4), q) for p, q in book["no_bids"].items()],
                key=lambda x: x[0]
            )[:self.depth_limit]

        # Explicit or Derived NO asks:
        if book["no_asks"]:
            no_asks_sorted = sorted(book["no_asks"].items(), key=lambda x: x[0])[:self.depth_limit]
        else:
            # Deterministic transformation from YES bids
            no_asks_sorted = sorted(
                [(round(1.0 - p, 4), q) for p, q in book["yes_bids"].items()],
                key=lambda x: x[0]
            )[:self.depth_limit]

        best_yes_bid = yes_bids_sorted[0][0] if yes_bids_sorted else None
        best_yes_ask = yes_asks_sorted[0][0] if yes_asks_sorted else None
        best_no_bid = no_bids_sorted[0][0] if no_bids_sorted else None
        best_no_ask = no_asks_sorted[0][0] if no_asks_sorted else None

        yes_bid_depth = sum(q for _, q in yes_bids_sorted)
        yes_ask_depth = sum(q for _, q in yes_asks_sorted)
        top_n_depth = yes_bid_depth + yes_ask_depth

        total_depth = yes_bid_depth + yes_ask_depth
        imbalance = round((yes_bid_depth - yes_ask_depth) / total_depth, 4) if total_depth > 0 else 0.0

        spread = round(best_yes_ask - best_yes_bid, 4) if (best_yes_bid is not None and best_yes_ask is not None) else None

        # Data quality classification
        quality_status = KalshiDataQualityStatus.VALID
        quality_reason = None

        if best_yes_bid is None or best_yes_ask is None:
            quality_status = KalshiDataQualityStatus.MISSING_DATA
            quality_reason = "One-sided order book (missing bids or asks)."
        elif best_yes_bid > best_yes_ask:
            quality_status = KalshiDataQualityStatus.CROSSED_BOOK
            quality_reason = f"Crossed book: best_yes_bid ({best_yes_bid}) > best_yes_ask ({best_yes_ask})."
        elif best_yes_bid == best_yes_ask:
            quality_status = KalshiDataQualityStatus.LOCKED_BOOK
            quality_reason = f"Locked book: best_yes_bid ({best_yes_bid}) == best_yes_ask ({best_yes_ask})."

        # Check staleness
        elapsed_sec = (raw_rec.receive_timestamp - book["last_update_ts"]).total_seconds()
        if elapsed_sec > self.stale_threshold_seconds:
            quality_status = KalshiDataQualityStatus.STALE
            quality_reason = f"Book state stale: {elapsed_sec:.1f}s elapsed > {self.stale_threshold_seconds}s threshold."

        # Compute deterministic book hash
        raw_repr = f"{best_yes_bid}|{best_yes_ask}|{yes_bid_depth}|{yes_ask_depth}|{seq}"
        book_hash = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()

        return KalshiReconstructedBookSnapshot(
            snapshot_id=f"kalshi_snap_{market_id}_{int(raw_rec.receive_timestamp.timestamp() * 1000)}",
            session_id=raw_rec.session_id,
            market_id=market_id,
            receive_timestamp=raw_rec.receive_timestamp,
            exchange_timestamp=raw_rec.exchange_timestamp,
            sequence=seq,
            yes_bids=[{"price": p, "quantity": q} for p, q in yes_bids_sorted],
            yes_asks=[{"price": p, "quantity": q} for p, q in yes_asks_sorted],
            no_bids=[{"price": p, "quantity": q} for p, q in no_bids_sorted],
            no_asks=[{"price": p, "quantity": q} for p, q in no_asks_sorted],
            best_yes_bid=best_yes_bid,
            best_yes_ask=best_yes_ask,
            best_no_bid=best_no_bid,
            best_no_ask=best_no_ask,
            yes_spread=spread,
            yes_bid_depth=yes_bid_depth,
            yes_ask_depth=yes_ask_depth,
            top_n_depth=top_n_depth,
            book_imbalance=imbalance,
            quality_status=quality_status,
            quality_reason=quality_reason,
            raw_message_id=raw_rec.raw_message_id,
            book_hash=book_hash
        )

    def _build_anomaly_snapshot(
        self,
        market_id: str,
        raw_rec: KalshiRawMessageRecord,
        seq: Optional[int],
        status: KalshiDataQualityStatus,
        reason: str
    ) -> KalshiReconstructedBookSnapshot:
        return KalshiReconstructedBookSnapshot(
            snapshot_id=f"kalshi_snap_anomaly_{market_id}_{int(raw_rec.receive_timestamp.timestamp() * 1000)}",
            session_id=raw_rec.session_id,
            market_id=market_id,
            receive_timestamp=raw_rec.receive_timestamp,
            exchange_timestamp=raw_rec.exchange_timestamp,
            sequence=seq,
            yes_bids=[],
            yes_asks=[],
            no_bids=[],
            no_asks=[],
            best_yes_bid=None,
            best_yes_ask=None,
            best_no_bid=None,
            best_no_ask=None,
            yes_spread=None,
            yes_bid_depth=0.0,
            yes_ask_depth=0.0,
            top_n_depth=0.0,
            book_imbalance=0.0,
            quality_status=status,
            quality_reason=reason,
            raw_message_id=raw_rec.raw_message_id,
            book_hash=hashlib.sha256(f"anomaly_{status}_{reason}".encode("utf-8")).hexdigest()
        )
