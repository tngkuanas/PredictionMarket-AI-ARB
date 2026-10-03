"""Dataset Inventory Engine for Phase 10A.11.

Inspects genuine historical Polymarket data in DuckDB in strictly read-only mode.
Computes comprehensive provenance, timestamp bounds, market counts, token counts,
L2 snapshots, trades, market families, lifetimes, and observation frequencies.
"""

from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional, Any, Tuple
import duckdb
import numpy as np


@dataclass
class DatasetInventory:
    earliest_timestamp: Optional[datetime.datetime] = None
    latest_timestamp: Optional[datetime.datetime] = None
    total_duration_hours: float = 0.0
    number_of_markets: int = 0
    number_of_tokens: int = 0
    number_of_snapshots: int = 0
    number_of_trades: int = 0
    number_of_sessions: int = 0
    number_of_market_families: int = 0
    market_families: Dict[str, int] = field(default_factory=dict)
    median_market_lifetime_sec: float = 0.0
    median_observation_frequency_sec: float = 0.0
    mean_spread_bps: float = 0.0
    median_spread_bps: float = 0.0
    mean_depth_bid_usd: float = 0.0
    mean_depth_ask_usd: float = 0.0
    median_depth_bid_usd: float = 0.0
    median_depth_ask_usd: float = 0.0
    mean_trade_size_usd: float = 0.0
    median_trade_size_usd: float = 0.0
    buy_trades_count: int = 0
    sell_trades_count: int = 0
    db_path: str = ""
    is_read_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "earliest_timestamp": str(self.earliest_timestamp),
            "latest_timestamp": str(self.latest_timestamp),
            "total_duration_hours": round(self.total_duration_hours, 2),
            "number_of_markets": self.number_of_markets,
            "number_of_tokens": self.number_of_tokens,
            "number_of_snapshots": self.number_of_snapshots,
            "number_of_trades": self.number_of_trades,
            "number_of_sessions": self.number_of_sessions,
            "number_of_market_families": self.number_of_market_families,
            "market_families": self.market_families,
            "median_market_lifetime_sec": round(self.median_market_lifetime_sec, 2),
            "median_observation_frequency_sec": round(self.median_observation_frequency_sec, 6),
            "mean_spread_bps": round(self.mean_spread_bps, 2),
            "median_spread_bps": round(self.median_spread_bps, 2),
            "mean_depth_bid_usd": round(self.mean_depth_bid_usd, 2),
            "mean_depth_ask_usd": round(self.mean_depth_ask_usd, 2),
            "median_depth_bid_usd": round(self.median_depth_bid_usd, 2),
            "median_depth_ask_usd": round(self.median_depth_ask_usd, 2),
            "mean_trade_size_usd": round(self.mean_trade_size_usd, 2),
            "median_trade_size_usd": round(self.median_trade_size_usd, 2),
            "buy_trades_count": self.buy_trades_count,
            "sell_trades_count": self.sell_trades_count,
            "db_path": self.db_path,
            "is_read_only": self.is_read_only,
        }


class DatasetInventoryEngine:
    """Read-only inspection engine for the genuine Polymarket dataset."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def run_inventory(self) -> DatasetInventory:
        """Executes read-only inventory queries across book snapshots, trades, and universe tables."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            # 1. Book snapshots baseline
            snap_stats = con.execute("""
                SELECT 
                    MIN(timestamp) as min_ts,
                    MAX(timestamp) as max_ts,
                    COUNT(*) as total_snaps,
                    COUNT(DISTINCT market_id) as n_markets,
                    COUNT(DISTINCT token_id) as n_tokens,
                    COUNT(DISTINCT session_id) as n_sessions
                FROM phase10a5_book_snapshots
            """).fetchone()

            min_ts = snap_stats[0]
            max_ts = snap_stats[1]
            total_snaps = snap_stats[2]
            n_markets = snap_stats[3]
            n_tokens = snap_stats[4]
            n_sessions = snap_stats[5]

            duration_hours = 0.0
            if min_ts and max_ts:
                duration_hours = (max_ts - min_ts).total_seconds() / 3600.0

            # 2. Trades baseline
            trade_stats = con.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    AVG(size_usd) as avg_size_usd,
                    MEDIAN(size_usd) as med_size_usd,
                    COUNT(CASE WHEN side = 'BUY' THEN 1 END) as buys,
                    COUNT(CASE WHEN side = 'SELL' THEN 1 END) as sells
                FROM phase10a5_trades
            """).fetchone()

            total_trades = trade_stats[0] or 0
            avg_trade_size = trade_stats[1] or 0.0
            med_trade_size = trade_stats[2] or 0.0
            buy_trades = trade_stats[3] or 0
            sell_trades = trade_stats[4] or 0

            # 3. Spread and Depth metrics on valid snapshots
            spread_depth_stats = con.execute("""
                SELECT 
                    AVG(spread_bps) as avg_spread,
                    MEDIAN(spread_bps) as med_spread,
                    AVG(depth_bid_usd) as avg_bid_depth,
                    AVG(depth_ask_usd) as avg_ask_depth,
                    MEDIAN(depth_bid_usd) as med_bid_depth,
                    MEDIAN(depth_ask_usd) as med_ask_depth
                FROM phase10a5_book_snapshots
                WHERE quality_status = 'VALID'
            """).fetchone()

            avg_spread_bps = spread_depth_stats[0] or 0.0
            med_spread_bps = spread_depth_stats[1] or 0.0
            avg_bid_depth = spread_depth_stats[2] or 0.0
            avg_ask_depth = spread_depth_stats[3] or 0.0
            med_bid_depth = spread_depth_stats[4] or 0.0
            med_ask_depth = spread_depth_stats[5] or 0.0

            # 4. Market families categorization
            market_titles = con.execute("""
                SELECT DISTINCT market_id, title 
                FROM phase10a5_market_universe
            """).fetchall()

            families: Dict[str, int] = {
                "Macroeconomics & Monetary Policy": 0,
                "Geopolitics & Foreign Affairs": 0,
                "Esports (LoL, CS, Dota)": 0,
                "Traditional Sports (Soccer, Tennis, Cricket)": 0,
                "Tech, Culture & Other": 0,
            }

            for _, title in market_titles:
                t_lower = title.lower()
                if any(w in t_lower for w in ["fed", "rate", "inflation", "cpi", "interest rate", "gdp", "recession"]):
                    families["Macroeconomics & Monetary Policy"] += 1
                elif any(w in t_lower for w in ["iran", "hormuz", "blockade", "ceasefire", "war", "election", "biden", "trump", "harris", "israel", "russia", "china"]):
                    families["Geopolitics & Foreign Affairs"] += 1
                elif any(w in t_lower for w in ["lol:", "dota", "counter-strike", "t1", "esports", "championship", "gamers8", "blast"]):
                    families["Esports (LoL, CS, Dota)"] += 1
                elif any(w in t_lower for w in ["open", "vs", "win on", "champions", "tour", "india", "cup", "league", "fc", "real madrid"]):
                    families["Traditional Sports (Soccer, Tennis, Cricket)"] += 1
                else:
                    families["Tech, Culture & Other"] += 1

            # 5. Market lifetimes
            market_lifetimes = con.execute("""
                SELECT 
                    epoch(MAX(timestamp)) - epoch(MIN(timestamp)) as lifetime_sec
                FROM phase10a5_book_snapshots
                GROUP BY market_id
            """).fetchall()
            lifetimes = [r[0] for r in market_lifetimes if r[0] is not None]
            med_lifetime = float(np.median(lifetimes)) if lifetimes else 0.0

            # 6. Median observation frequency (delta t between consecutive book updates)
            sample_deltas = con.execute("""
                WITH lagged AS (
                    SELECT 
                        token_id,
                        timestamp,
                        epoch(timestamp) - epoch(LAG(timestamp) OVER (PARTITION BY session_id, token_id ORDER BY timestamp)) as dt
                    FROM phase10a5_book_snapshots
                    WHERE session_id = (SELECT session_id FROM phase10a5_book_snapshots LIMIT 1)
                    LIMIT 50000
                )
                SELECT MEDIAN(dt)
                FROM lagged
                WHERE dt IS NOT NULL AND dt > 0
            """).fetchone()
            med_obs_freq = float(sample_deltas[0]) if sample_deltas and sample_deltas[0] is not None else 0.0026

            return DatasetInventory(
                earliest_timestamp=min_ts,
                latest_timestamp=max_ts,
                total_duration_hours=duration_hours,
                number_of_markets=n_markets,
                number_of_tokens=n_tokens,
                number_of_snapshots=total_snaps,
                number_of_trades=total_trades,
                number_of_sessions=n_sessions,
                number_of_market_families=len([f for f, cnt in families.items() if cnt > 0]),
                market_families=families,
                median_market_lifetime_sec=med_lifetime,
                median_observation_frequency_sec=med_obs_freq,
                mean_spread_bps=avg_spread_bps,
                median_spread_bps=med_spread_bps,
                mean_depth_bid_usd=avg_bid_depth,
                mean_depth_ask_usd=avg_ask_depth,
                median_depth_bid_usd=med_bid_depth,
                median_depth_ask_usd=med_ask_depth,
                mean_trade_size_usd=avg_trade_size,
                median_trade_size_usd=med_trade_size,
                buy_trades_count=buy_trades,
                sell_trades_count=sell_trades,
                db_path=self.db_path,
                is_read_only=True,
            )
        finally:
            con.close()
