"""Persistent High-Frequency Market Data Recorder for Prediction Markets.

Captures L2 order-book snapshots, delta updates, and trade tapes with sub-millisecond
local receive timestamps and raw message preservation.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import duckdb
import numpy as np

from src.phase10.high_frequency.schema import (
    BookSnapshot,
    BookUpdate,
    HighFrequencyTrade,
    L2PriceLevel,
    OrderSideEnum,
)

logger = logging.getLogger(__name__)


class HighFrequencyRecorder:
    """Manages high-frequency order-book and trade ingestion for Polymarket/prediction markets."""

    def __init__(
        self,
        raw_storage_dir: str = "data/raw_hf_messages",
        db_path: str = "data/prediction_market.duckdb"
    ):
        self.raw_dir = Path(raw_storage_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._seen_snapshots = set()
        self._seen_updates = set()
        self._seen_trades = set()

    def init_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initializes high-frequency recording DuckDB tables."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phase10a4_book_snapshots (
                snapshot_id VARCHAR PRIMARY KEY,
                market_id VARCHAR,
                token_id VARCHAR,
                venue VARCHAR,
                timestamp_exchange TIMESTAMP,
                timestamp_local_receive TIMESTAMP,
                best_bid DOUBLE,
                best_ask DOUBLE,
                midpoint DOUBLE,
                spread DOUBLE,
                spread_bps DOUBLE,
                bids_l2 JSON,
                asks_l2 JSON,
                total_bid_depth_usd DOUBLE,
                total_ask_depth_usd DOUBLE,
                update_sequence BIGINT,
                raw_message_ref VARCHAR
            );

            CREATE TABLE IF NOT EXISTS phase10a4_book_updates (
                update_id VARCHAR PRIMARY KEY,
                market_id VARCHAR,
                token_id VARCHAR,
                venue VARCHAR,
                timestamp_exchange TIMESTAMP,
                timestamp_local_receive TIMESTAMP,
                side VARCHAR,
                price DOUBLE,
                size DOUBLE,
                delta_type VARCHAR,
                update_sequence BIGINT
            );

            CREATE TABLE IF NOT EXISTS phase10a4_trades (
                trade_id VARCHAR PRIMARY KEY,
                market_id VARCHAR,
                token_id VARCHAR,
                venue VARCHAR,
                timestamp_exchange TIMESTAMP,
                timestamp_local_receive TIMESTAMP,
                price DOUBLE,
                size_shares DOUBLE,
                size_usd DOUBLE,
                side VARCHAR,
                transaction_hash VARCHAR
            );
        """)

    def save_raw_message(self, message_type: str, token_id: str, raw_payload: Dict[str, Any]) -> str:
        """Saves raw exchange message to disk for auditability and returns relative file path."""
        dt_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        digest = hashlib.sha256(json.dumps(raw_payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
        filename = f"{message_type}_{token_id}_{dt_str}_{digest}.json"
        dest_dir = self.raw_dir / message_type / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(raw_payload, f, indent=2, default=str)
        return str(file_path.relative_to(self.raw_dir.parent))

    def parse_book_snapshot(
        self,
        market_id: str,
        token_id: str,
        clob_book: Dict[str, Any],
        local_receive_ts: datetime,
        exchange_ts: Optional[datetime] = None,
        sequence: int = 0,
        venue: str = "polymarket"
    ) -> Optional[BookSnapshot]:
        """Parses L2 order book payload into structured BookSnapshot."""
        if not isinstance(clob_book, dict):
            logger.warning("Malformed CLOB book: expected dictionary.")
            return None

        # Parse bids
        bids: List[L2PriceLevel] = []
        for b in clob_book.get("bids", []):
            try:
                p = float(b.get("price", 0.0))
                s = float(b.get("size", 0.0))
                if p > 0 and s > 0:
                    bids.append(L2PriceLevel(price=round(p, 4), size_shares=s, size_usd=round(p * s, 2)))
            except (ValueError, TypeError, KeyError):
                continue
        bids.sort(key=lambda x: x.price, reverse=True)

        # Parse asks
        asks: List[L2PriceLevel] = []
        for a in clob_book.get("asks", []):
            try:
                p = float(a.get("price", 0.0))
                s = float(a.get("size", 0.0))
                if p > 0 and s > 0:
                    asks.append(L2PriceLevel(price=round(p, 4), size_shares=s, size_usd=round(p * s, 2)))
            except (ValueError, TypeError, KeyError):
                continue
        asks.sort(key=lambda x: x.price, reverse=False)

        if not bids or not asks:
            # Incomplete book / no two-sided liquidity
            return None

        best_bid = bids[0].price
        best_ask = asks[0].price
        midpoint = round((best_bid + best_ask) / 2.0, 4)
        spread = round(max(0.0, best_ask - best_bid), 4)
        spread_bps = round((spread / midpoint) * 10000.0, 2) if midpoint > 0 else 0.0

        total_bid_depth = sum(lvl.size_usd for lvl in bids)
        total_ask_depth = sum(lvl.size_usd for lvl in asks)

        # Save raw message reference
        raw_ref = self.save_raw_message("book_snapshot", token_id, clob_book)
        
        # Unique deterministic snapshot ID
        time_ms = int(local_receive_ts.timestamp() * 1000)
        snap_id = f"snap_{token_id}_{time_ms}_{sequence}"

        if snap_id in self._seen_snapshots:
            return None # Deduplicate
        self._seen_snapshots.add(snap_id)

        return BookSnapshot(
            snapshot_id=snap_id,
            market_id=market_id,
            token_id=token_id,
            venue=venue,
            timestamp_exchange=exchange_ts,
            timestamp_local_receive=local_receive_ts,
            best_bid=best_bid,
            best_ask=best_ask,
            midpoint=midpoint,
            spread=spread,
            spread_bps=spread_bps,
            bids_l2=bids,
            asks_l2=asks,
            total_bid_depth_usd=total_bid_depth,
            total_ask_depth_usd=total_ask_depth,
            update_sequence=sequence,
            raw_message_ref=raw_ref
        )

    def parse_trade(
        self,
        market_id: str,
        token_id: str,
        trade_data: Dict[str, Any],
        local_receive_ts: datetime,
        venue: str = "polymarket"
    ) -> Optional[HighFrequencyTrade]:
        """Parses individual executed trade payload."""
        if not isinstance(trade_data, dict):
            return None

        try:
            price = float(trade_data.get("price", 0.0))
            size = float(trade_data.get("size", 0.0))
            if price <= 0 or size <= 0:
                return None
            side_str = str(trade_data.get("side", "BUY")).upper()
            side = OrderSideEnum.BUY if side_str == "BUY" else OrderSideEnum.SELL

            # Timestamp parsing
            raw_ts = trade_data.get("timestamp")
            exchange_ts = None
            if raw_ts is not None:
                if isinstance(raw_ts, (int, float)):
                    # Check if ms or sec
                    ts_val = float(raw_ts) / 1000.0 if raw_ts > 1e11 else float(raw_ts)
                    exchange_ts = datetime.fromtimestamp(ts_val, tz=timezone.utc).replace(tzinfo=None)
                elif isinstance(raw_ts, str):
                    try:
                        exchange_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pass

            tx_hash = trade_data.get("transactionHash") or trade_data.get("hash")
            trade_id = str(trade_data.get("id") or f"tr_{token_id}_{int(local_receive_ts.timestamp()*1000)}_{price}_{size}")

            if trade_id in self._seen_trades:
                return None
            self._seen_trades.add(trade_id)

            return HighFrequencyTrade(
                trade_id=trade_id,
                market_id=market_id,
                token_id=token_id,
                venue=venue,
                timestamp_exchange=exchange_ts,
                timestamp_local_receive=local_receive_ts,
                price=price,
                size_shares=size,
                size_usd=round(price * size, 2),
                side=side,
                transaction_hash=tx_hash
            )
        except Exception as e:
            logger.warning(f"Error parsing trade: {e}")
            return None

    def persist_snapshots(self, conn: duckdb.DuckDBPyConnection, snapshots: List[BookSnapshot]) -> int:
        """Batch inserts BookSnapshots into DuckDB."""
        if not snapshots:
            return 0
        rows = []
        for s in snapshots:
            bids_json = json.dumps([b.to_dict() for b in s.bids_l2])
            asks_json = json.dumps([a.to_dict() for a in s.asks_l2])
            rows.append((
                s.snapshot_id, s.market_id, s.token_id, s.venue,
                s.timestamp_exchange, s.timestamp_local_receive,
                s.best_bid, s.best_ask, s.midpoint, s.spread, s.spread_bps,
                bids_json, asks_json, s.total_bid_depth_usd, s.total_ask_depth_usd,
                s.update_sequence, s.raw_message_ref
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a4_book_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    def persist_trades(self, conn: duckdb.DuckDBPyConnection, trades: List[HighFrequencyTrade]) -> int:
        """Batch inserts HighFrequencyTrades into DuckDB."""
        if not trades:
            return 0
        rows = []
        for t in trades:
            rows.append((
                t.trade_id, t.market_id, t.token_id, t.venue,
                t.timestamp_exchange, t.timestamp_local_receive,
                t.price, t.size_shares, t.size_usd, t.side.value, t.transaction_hash
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a4_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)
