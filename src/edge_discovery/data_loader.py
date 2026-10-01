"""Data Loading and Chronological Partitioning for Phase 10A.7 Edge Discovery.

Responsibilities:
1. Concurrency-safe access to production DuckDB without blocking PID 53380.
2. Chronological split: Stage 1 Discovery (first 60%) vs Stage 3 Out-of-Sample (last 40%).
3. Rigorous data hygiene:
   - Filter quality_status = 'VALID'.
   - Filter out crossing books, zero bids, zero asks.
   - Enforce strictly monotonically ordered timestamps.
4. Extract paired contracts for Branch E logical mispricing checks.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple, Union

import duckdb

logger = logging.getLogger(__name__)


class EdgeDiscoveryDataLoader:
    """Extracts, cleans, and partitions market data for edge research."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def _execute_query(self, query: str, params: Optional[List[Any]] = None) -> List[Tuple[Any, ...]]:
        """Executes a read query with retry and fallback to tempfile copy if locked."""
        params = params or []
        # Attempt 1: direct read-only connection
        for attempt in range(3):
            try:
                with duckdb.connect(self.db_path, read_only=True) as con:
                    return con.execute(query, params).fetchall()
            except Exception as e:
                time.sleep(0.3 * (2 ** attempt))

        # Attempt 2: temporary snapshot copy to prevent colliding with PID 53380
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".duckdb")
        os.close(tmp_fd)
        try:
            shutil.copyfile(self.db_path, tmp_path)
            with duckdb.connect(tmp_path, read_only=True) as con:
                return con.execute(query, params).fetchall()
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def get_dataset_timeline(self) -> Tuple[datetime, datetime, datetime]:
        """Calculates dataset bounds and 60/40 chronological split cutoff."""
        res = self._execute_query("""
            SELECT min(timestamp), max(timestamp)
            FROM phase10a5_book_snapshots
            WHERE quality_status = 'VALID'
        """)
        t_start, t_end = res[0]
        if not t_start or not t_end:
            # Fallback if empty
            now = datetime.now(timezone.utc)
            return now - timedelta(hours=24), now, now - timedelta(hours=10)

        total_sec = (t_end - t_start).total_seconds()
        split_sec = total_sec * 0.60
        t_split = t_start + timedelta(seconds=split_sec)
        return t_start, t_end, t_split

    def get_active_markets(self, min_snapshots: int = 500, min_trades: int = 20) -> List[Dict[str, Any]]:
        """Finds markets with sufficient snapshot and trade history."""
        query = """
            SELECT
                s.market_id,
                count(DISTINCT s.token_id) as n_tokens,
                count(*) as n_snaps,
                coalesce(t.n_trades, 0) as n_trades,
                coalesce(t.total_volume, 0.0) as total_volume
            FROM phase10a5_book_snapshots s
            LEFT JOIN (
                SELECT market_id, count(*) as n_trades, sum(size_usd) as total_volume
                FROM phase10a5_trades
                GROUP BY market_id
            ) t ON s.market_id = t.market_id
            WHERE s.quality_status = 'VALID'
            GROUP BY s.market_id, t.n_trades, t.total_volume
            HAVING count(*) >= ? AND coalesce(t.n_trades, 0) >= ?
            ORDER BY coalesce(t.total_volume, 0.0) DESC
        """
        rows = self._execute_query(query, [min_snapshots, min_trades])
        markets = []
        for r in rows:
            markets.append({
                "market_id": r[0],
                "n_tokens": r[1],
                "n_snapshots": r[2],
                "n_trades": r[3],
                "total_volume_usd": r[4],
            })
        return markets

    def load_snapshots(
        self,
        market_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        token_id: Optional[str] = None,
        limit: int = 50000,
        filter_clause: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Loads clean, valid L2 book snapshots for a given market."""
        conditions = ["quality_status = 'VALID'", "best_bid > 0", "best_ask > 0", "best_ask >= best_bid"]
        params: List[Any] = []

        if market_id:
            conditions.append("market_id = ?")
            params.append(market_id)
        if token_id:
            conditions.append("token_id = ?")
            params.append(token_id)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp < ?")
            params.append(end_time)
        if filter_clause:
            conditions.append(f"({filter_clause})")

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                snapshot_id,
                session_id,
                market_id,
                token_id,
                timestamp,
                exchange_timestamp,
                best_bid,
                best_ask,
                midpoint,
                spread_bps,
                depth_bid_usd,
                depth_ask_usd,
                book_imbalance,
                bids,
                asks
            FROM phase10a5_book_snapshots
            WHERE {where_clause}
            ORDER BY timestamp ASC
            LIMIT ?
        """
        params.append(limit)
        rows = self._execute_query(query, params)

        snapshots = []
        for r in rows:
            snapshots.append({
                "snapshot_id": r[0],
                "session_id": r[1],
                "market_id": r[2],
                "token_id": r[3],
                "timestamp": r[4],
                "exchange_timestamp": r[5],
                "best_bid": r[6],
                "best_ask": r[7],
                "midpoint": r[8],
                "spread_bps": r[9],
                "depth_bid_usd": r[10],
                "depth_ask_usd": r[11],
                "book_imbalance": r[12],
                "bids": r[13],
                "asks": r[14],
            })
        return snapshots

    def load_trades(
        self,
        market_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Loads executed trades for a market."""
        conditions = ["price > 0", "size > 0"]
        params: List[Any] = []

        if market_id:
            conditions.append("market_id = ?")
            params.append(market_id)
        if start_time:
            conditions.append("receive_timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("receive_timestamp < ?")
            params.append(end_time)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                trade_id,
                session_id,
                market_id,
                token_id,
                receive_timestamp,
                exchange_timestamp,
                price,
                size,
                size_usd,
                side,
                fee_rate_bps,
                transaction_hash
            FROM phase10a5_trades
            WHERE {where_clause}
            ORDER BY receive_timestamp ASC
            LIMIT ?
        """
        params.append(limit)
        rows = self._execute_query(query, params)

        trades = []
        for r in rows:
            trades.append({
                "trade_id": r[0],
                "session_id": r[1],
                "market_id": r[2],
                "token_id": r[3],
                "receive_timestamp": r[4],
                "exchange_timestamp": r[5],
                "price": r[6],
                "size": r[7],
                "size_usd": r[8],
                "side": r[9],
                "fee_rate_bps": r[10],
                "transaction_hash": r[11],
            })
        return trades

    def load_binary_token_pairs(self, market_id: str) -> Optional[Tuple[str, str]]:
        """Identifies the two complementary token IDs for a binary market."""
        query = """
            SELECT DISTINCT token_id
            FROM phase10a5_book_snapshots
            WHERE market_id = ? AND quality_status = 'VALID'
            LIMIT 2
        """
        rows = self._execute_query(query, [market_id])
        if len(rows) == 2:
            return rows[0][0], rows[1][0]
        return None
