"""Live Cross-Venue Quote Adapters for Polymarket and Kalshi.

Phase 10A.6I Sections 2 & 3:
Provides a clean adapter layer converting genuine reconstructed L2 order book states
from Polymarket (Phase 10A.5) and Kalshi (Phase 10A.6F) into a common, venue-neutral
MappedContractQuote representation.

CRITICAL RULES:
1. Retains full raw provenance and cryptographic book hashes.
2. NEVER fabricates maker/taker info, prices, or order book depth.
3. Completely decoupled from mapping and settlement equivalence decisions.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

from src.cross_venue.schema import SyncQuote

logger = logging.getLogger(__name__)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class MappedContractQuote(BaseModel):
    """Venue-neutral quote representation with full provenance (Phase 10A.6I Section 3)."""
    mapping_id: str
    venue: str                                               # "polymarket" or "kalshi"
    venue_contract_id: str
    token_id: Optional[str] = None
    economic_outcome: str                                    # "YES" or "NO"
    local_receive_timestamp: datetime
    exchange_timestamp: Optional[datetime] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    bids: List[Dict[str, float]] = Field(default_factory=list)  # [{"price": p, "size": q}]
    asks: List[Dict[str, float]] = Field(default_factory=list)
    book_hash: str
    source_session_id: str
    source_message_id: str
    source_hash: str
    stale: bool = False

    def to_sync_quote(self, side: str = "ask") -> SyncQuote:
        """Converts into Phase 10A.6E SyncQuote for synchronizer and execution engine."""
        price = self.best_ask if side == "ask" else self.best_bid
        size = self.ask_depth if side == "ask" else self.bid_depth
        return SyncQuote(
            venue=self.venue,
            market_id=self.venue_contract_id,
            contract_id=self.token_id or self.venue_contract_id,
            side=side,
            outcome=self.economic_outcome,
            price=price if price is not None else (1.0 if side == "ask" else 0.0),
            size=size,
            bids=self.bids,
            asks=self.asks,
            venue_timestamp=self.exchange_timestamp,
            exchange_timestamp=self.exchange_timestamp,
            local_receive_timestamp=self.local_receive_timestamp,
            sequence_frame_id=self.source_message_id,
        )


class PolymarketQuoteAdapter:
    """Adapts Polymarket reconstructed L2 order book states into MappedContractQuotes."""

    @classmethod
    def from_reconstructed_snapshot(
        cls,
        mapping_id: str,
        snapshot: Any,
        economic_outcome: str = "YES"
    ) -> MappedContractQuote:
        """Adapts a Phase 10A.5 ReconstructedBookSnapshot into MappedContractQuote."""
        receive_ts = _ensure_utc(snapshot.timestamp)
        exchange_ts = _ensure_utc(snapshot.exchange_timestamp)

        # Standardize bids and asks ladders
        bids = [{"price": float(b.get("price", 0.0)), "size": float(b.get("size", 0.0))} for b in snapshot.bids if float(b.get("price", 0.0)) > 0.0]
        asks = [{"price": float(a.get("price", 0.0)), "size": float(a.get("size", 0.0))} for a in snapshot.asks if float(a.get("price", 0.0)) > 0.0]

        # Calculate depths
        bid_depth = sum(b["size"] for b in bids)
        ask_depth = sum(a["size"] for a in asks)

        # Book hash
        ladder_json = json.dumps({"bids": bids, "asks": asks}, sort_keys=True)
        book_hash = hashlib.sha256(ladder_json.encode("utf-8")).hexdigest()

        return MappedContractQuote(
            mapping_id=mapping_id,
            venue="polymarket",
            venue_contract_id=snapshot.market_id,
            token_id=snapshot.token_id,
            economic_outcome=economic_outcome,
            local_receive_timestamp=receive_ts,
            exchange_timestamp=exchange_ts,
            best_bid=snapshot.best_bid if snapshot.best_bid > 0.0 else (bids[0]["price"] if bids else None),
            best_ask=snapshot.best_ask if snapshot.best_ask < 1.0 else (asks[0]["price"] if asks else None),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            bids=bids,
            asks=asks,
            book_hash=book_hash,
            source_session_id=snapshot.session_id,
            source_message_id=snapshot.snapshot_id,
            source_hash=book_hash[:16],
            stale=False,
        )

    @classmethod
    def from_l2_dict(
        cls,
        mapping_id: str,
        market_id: str,
        token_id: str,
        bids: List[Dict[str, float]],
        asks: List[Dict[str, float]],
        receive_timestamp: datetime,
        exchange_timestamp: Optional[datetime] = None,
        session_id: str = "sess_manual",
        message_id: str = "msg_manual",
        economic_outcome: str = "YES",
    ) -> MappedContractQuote:
        """Adapts raw L2 dictionaries into MappedContractQuote."""
        clean_bids = [{"price": float(b["price"]), "size": float(b["size"])} for b in bids if float(b.get("price", 0.0)) > 0.0]
        clean_asks = [{"price": float(a["price"]), "size": float(a["size"])} for a in asks if float(a.get("price", 0.0)) > 0.0]

        clean_bids.sort(key=lambda x: x["price"], reverse=True)
        clean_asks.sort(key=lambda x: x["price"], reverse=False)

        best_b = clean_bids[0]["price"] if clean_bids else None
        best_a = clean_asks[0]["price"] if clean_asks else None
        b_depth = sum(b["size"] for b in clean_bids)
        a_depth = sum(a["size"] for a in clean_asks)

        ladder_json = json.dumps({"bids": clean_bids, "asks": clean_asks}, sort_keys=True)
        book_hash = hashlib.sha256(ladder_json.encode("utf-8")).hexdigest()

        return MappedContractQuote(
            mapping_id=mapping_id,
            venue="polymarket",
            venue_contract_id=market_id,
            token_id=token_id,
            economic_outcome=economic_outcome,
            local_receive_timestamp=_ensure_utc(receive_timestamp),
            exchange_timestamp=_ensure_utc(exchange_timestamp),
            best_bid=best_b,
            best_ask=best_a,
            bid_depth=b_depth,
            ask_depth=a_depth,
            bids=clean_bids,
            asks=clean_asks,
            book_hash=book_hash,
            source_session_id=session_id,
            source_message_id=message_id,
            source_hash=book_hash[:16],
            stale=False,
        )


class KalshiQuoteAdapter:
    """Adapts Kalshi reconstructed L2 order book states into MappedContractQuotes."""

    @classmethod
    def from_reconstructed_snapshot(
        cls,
        mapping_id: str,
        snapshot: Any,
        economic_outcome: str = "YES"
    ) -> MappedContractQuote:
        """Adapts a Phase 10A.6F KalshiReconstructedBookSnapshot into MappedContractQuote."""
        receive_ts = _ensure_utc(snapshot.receive_timestamp)
        exchange_ts = _ensure_utc(snapshot.exchange_timestamp)

        # Select ladder based on outcome
        if economic_outcome == "NO" and hasattr(snapshot, "no_bids") and snapshot.no_bids:
            bids = [{"price": float(b["price"]), "size": float(b["quantity"])} for b in snapshot.no_bids]
            asks = [{"price": float(a["price"]), "size": float(a["quantity"])} for a in snapshot.no_asks]
            best_b = snapshot.best_no_bid
            best_a = snapshot.best_no_ask
        else:
            bids = [{"price": float(b["price"]), "size": float(b["quantity"])} for b in snapshot.yes_bids]
            asks = [{"price": float(a["price"]), "size": float(a["quantity"])} for a in snapshot.yes_asks]
            best_b = snapshot.best_yes_bid
            best_a = snapshot.best_yes_ask

        bid_depth = sum(b["size"] for b in bids)
        ask_depth = sum(a["size"] for a in asks)

        return MappedContractQuote(
            mapping_id=mapping_id,
            venue="kalshi",
            venue_contract_id=snapshot.market_id,
            token_id=snapshot.market_id,
            economic_outcome=economic_outcome,
            local_receive_timestamp=receive_ts,
            exchange_timestamp=exchange_ts,
            best_bid=best_b,
            best_ask=best_a,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            bids=bids,
            asks=asks,
            book_hash=snapshot.book_hash,
            source_session_id=snapshot.session_id,
            source_message_id=snapshot.raw_message_id or snapshot.snapshot_id,
            source_hash=snapshot.book_hash[:16],
            stale=False,
        )

    @classmethod
    def from_l2_dict(
        cls,
        mapping_id: str,
        ticker: str,
        bids: List[Dict[str, float]],
        asks: List[Dict[str, float]],
        receive_timestamp: datetime,
        exchange_timestamp: Optional[datetime] = None,
        session_id: str = "sess_kalshi_manual",
        message_id: str = "msg_kalshi_manual",
        economic_outcome: str = "YES",
    ) -> MappedContractQuote:
        """Adapts raw Kalshi L2 dictionaries into MappedContractQuote."""
        clean_bids = [{"price": float(b["price"]), "size": float(b.get("size") or b.get("quantity", 0.0))} for b in bids if float(b.get("price", 0.0)) > 0.0]
        clean_asks = [{"price": float(a["price"]), "size": float(a.get("size") or a.get("quantity", 0.0))} for a in asks if float(a.get("price", 0.0)) > 0.0]

        clean_bids.sort(key=lambda x: x["price"], reverse=True)
        clean_asks.sort(key=lambda x: x["price"], reverse=False)

        best_b = clean_bids[0]["price"] if clean_bids else None
        best_a = clean_asks[0]["price"] if clean_asks else None
        b_depth = sum(b["size"] for b in clean_bids)
        a_depth = sum(a["size"] for a in clean_asks)

        ladder_json = json.dumps({"bids": clean_bids, "asks": clean_asks}, sort_keys=True)
        book_hash = hashlib.sha256(ladder_json.encode("utf-8")).hexdigest()

        return MappedContractQuote(
            mapping_id=mapping_id,
            venue="kalshi",
            venue_contract_id=ticker,
            token_id=ticker,
            economic_outcome=economic_outcome,
            local_receive_timestamp=_ensure_utc(receive_timestamp),
            exchange_timestamp=_ensure_utc(exchange_timestamp),
            best_bid=best_b,
            best_ask=best_a,
            bid_depth=b_depth,
            ask_depth=a_depth,
            bids=clean_bids,
            asks=clean_asks,
            book_hash=book_hash,
            source_session_id=session_id,
            source_message_id=message_id,
            source_hash=book_hash[:16],
            stale=False,
        )
