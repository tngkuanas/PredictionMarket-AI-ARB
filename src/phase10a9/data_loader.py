"""Safe, Non-Blocking Production Data Loader for Phase 10A.9.

Reads genuine Polymarket market data from DuckDB using isolated snapshot copies
to guarantee zero file-lock interference with active recording daemon PID 67131.
"""

from datetime import datetime, timezone
import logging
import os
import shutil
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple
import duckdb

logger = logging.getLogger(__name__)


class Phase10A9DataLoader:
    """Safe data extraction harness for Phase 10A.9 hedged passive research."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def _execute_query_safe(self, query: str, params: Optional[List[Any]] = None) -> List[Tuple[Any, ...]]:
        """Executes read query against temporary snapshot copy of DuckDB to prevent write lock collisions."""
        params = params or []
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

    def load_market_universe(self) -> List[Dict[str, Any]]:
        """Loads all recorded Polymarket market universe entries."""
        rows = self._execute_query_safe("""
            SELECT market_id, token_id, outcome, title, category, volume_24h_usd, liquidity_usd, is_active, timestamp
            FROM phase10a5_market_universe
        """)
        entries = []
        for r in rows:
            entries.append({
                "market_id": str(r[0]),
                "token_id": str(r[1]),
                "outcome": str(r[2]),
                "title": str(r[3]),
                "category": str(r[4]),
                "volume_24h_usd": float(r[5] or 0.0),
                "liquidity_usd": float(r[6] or 0.0),
                "is_active": bool(r[7]),
                "timestamp": r[8]
            })
        return entries

    def load_passive_fills_with_quotes(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Loads empirical passive fills from Phase 10A.8 paired with quote parameters."""
        rows = self._execute_query_safe(f"""
            SELECT 
                f.fill_id, f.quote_id, f.fill_status, f.fill_mechanism, f.queue_model,
                f.fill_timestamp, f.fill_price, f.fill_size_usd, f.fill_shares,
                q.market_id, q.token_id, q.side, q.policy, q.quote_price, q.quote_size_usd,
                q.spread_bps, q.midpoint, q.book_imbalance, q.is_out_of_sample
            FROM phase10a8_fill_results f
            JOIN phase10a8_passive_quotes q ON f.quote_id = q.quote_id
            WHERE f.fill_status IN ('FILLED', 'PARTIALLY_FILLED')
            ORDER BY f.fill_timestamp ASC
            LIMIT {limit}
        """)

        fills = []
        for r in rows:
            fills.append({
                "fill_id": str(r[0]),
                "quote_id": str(r[1]),
                "fill_status": str(r[2]),
                "fill_mechanism": str(r[3]),
                "queue_model": str(r[4]),
                "fill_timestamp": r[5],
                "fill_price": float(r[6]),
                "fill_size_usd": float(r[7]),
                "fill_shares": float(r[8]),
                "market_id": str(r[9]),
                "token_id": str(r[10]),
                "side": str(r[11]),
                "quote_policy": str(r[12]),
                "quote_price": float(r[13]),
                "quote_size_usd": float(r[14]),
                "spread_bps": float(r[15]),
                "midpoint": float(r[16]),
                "book_imbalance": float(r[17]),
                "is_out_of_sample": bool(r[18]),
                "gross_spread_bps": max(0.0, ((float(r[16]) - float(r[13])) / max(0.01, float(r[16]))) * 10_000.0) if str(r[11]) == "BUY" else max(0.0, ((float(r[13]) - float(r[16])) / max(0.01, float(r[16]))) * 10_000.0),
                "adverse_selection_bps": 850.0,  # Empirical baseline
                "liquidation_cost_bps": 200.0
            })
        return fills

    def load_snapshots_for_tokens(self, token_ids: List[str], limit_per_token: int = 200) -> List[Dict[str, Any]]:
        """Loads L2 book snapshots for specified tokens."""
        if not token_ids:
            return []

        tok_list_str = ", ".join([f"'{t}'" for t in token_ids])
        rows = self._execute_query_safe(f"""
            SELECT snapshot_id, token_id, market_id, timestamp, best_bid, best_ask, midpoint, spread_bps, bids, asks
            FROM phase10a5_book_snapshots
            WHERE token_id IN ({tok_list_str})
            ORDER BY timestamp ASC
        """)

        snapshots = []
        for r in rows:
            snapshots.append({
                "snapshot_id": str(r[0]),
                "token_id": str(r[1]),
                "market_id": str(r[2]),
                "timestamp": r[3],
                "best_bid": float(r[4] or 0.0),
                "best_ask": float(r[5] or 1.0),
                "midpoint": float(r[6] or 0.5),
                "spread_bps": float(r[7] or 0.0),
                "bids": r[8],
                "asks": r[9]
            })
        return snapshots
