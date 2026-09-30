"""Phase 9 Pre-Live Shadow Execution Pipeline.
Bridge between historical research and real-time execution:
Records signal -> timestamp -> intended quote -> actual book -> hypothetical queue -> hypothetical fill -> cancellation -> 1m/5m/15m markouts -> hypothetical P&L.
Zero real capital deployed.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
import duckdb
import pandas as pd

from src.phase9.config import Phase9Config


@dataclass
class ShadowQuoteRecord:
    record_id: str
    signal_timestamp: datetime
    market_a_id: str
    market_b_id: str
    predicted_delta_15m_pp: float
    best_bid_b: float
    best_ask_b: float
    intended_quote_price: float
    quote_distance_d: int
    hypothetical_queue_ahead: float
    is_hypothetically_filled: bool
    fill_timestamp: Optional[datetime]
    is_cancelled: bool
    cancellation_reason: Optional[str]
    markout_1m_pp: float
    markout_5m_pp: float
    markout_15m_pp: float
    hypothetical_pnl_usd: float
    recorded_at: datetime


class PreLiveShadowPipeline:
    def __init__(self, config: Phase9Config, db_path: str = "data/prediction_market.duckdb"):
        self.config = config
        self.db_path = db_path
        self._init_db_schema()

    def _init_db_schema(self) -> None:
        """Create phase9 shadow recording table in DuckDB."""
        with duckdb.connect(self.db_path) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS phase9_shadow_records (
                record_id VARCHAR PRIMARY KEY,
                signal_timestamp TIMESTAMP,
                market_a_id VARCHAR,
                market_b_id VARCHAR,
                predicted_delta_15m_pp DOUBLE,
                best_bid_b DOUBLE,
                best_ask_b DOUBLE,
                intended_quote_price DOUBLE,
                quote_distance_d INTEGER,
                hypothetical_queue_ahead DOUBLE,
                is_hypothetically_filled BOOLEAN,
                fill_timestamp TIMESTAMP,
                is_cancelled BOOLEAN,
                cancellation_reason VARCHAR,
                markout_1m_pp DOUBLE,
                markout_5m_pp DOUBLE,
                markout_15m_pp DOUBLE,
                hypothetical_pnl_usd DOUBLE,
                recorded_at TIMESTAMP
            );
            """)

    def record_shadow_event(
        self,
        signal_timestamp: datetime,
        market_a_id: str,
        market_b_id: str,
        predicted_delta_15m_pp: float,
        best_bid_b: float,
        best_ask_b: float,
        quote_distance_d: int = 1,
        initial_queue_ahead: float = 2500.0,
        is_filled: bool = False,
        fill_timestamp: Optional[datetime] = None,
        is_cancelled: bool = False,
        cancel_reason: Optional[str] = None,
        m1: float = 0.0,
        m5: float = 0.0,
        m15: float = 0.0,
        pnl_usd: float = 0.0
    ) -> ShadowQuoteRecord:
        """Record an immutable shadow quote event into DuckDB."""
        side_buy = (predicted_delta_15m_pp >= 0)
        tick = self.config.tick_size
        intended_price = round(best_bid_b - (quote_distance_d * tick), 4) if side_buy else round(best_ask_b + (quote_distance_d * tick), 4)

        rec_id = f"sh9_{signal_timestamp.strftime('%Y%m%d%H%M%S')}_{market_b_id}"
        rec = ShadowQuoteRecord(
            record_id=rec_id,
            signal_timestamp=signal_timestamp,
            market_a_id=market_a_id,
            market_b_id=market_b_id,
            predicted_delta_15m_pp=predicted_delta_15m_pp,
            best_bid_b=best_bid_b,
            best_ask_b=best_ask_b,
            intended_quote_price=intended_price,
            quote_distance_d=quote_distance_d,
            hypothetical_queue_ahead=initial_queue_ahead,
            is_hypothetically_filled=is_filled,
            fill_timestamp=fill_timestamp,
            is_cancelled=is_cancelled,
            cancellation_reason=cancel_reason,
            markout_1m_pp=m1,
            markout_5m_pp=m5,
            markout_15m_pp=m15,
            hypothetical_pnl_usd=pnl_usd,
            recorded_at=datetime.utcnow()
        )

        with duckdb.connect(self.db_path) as con:
            con.execute("""
            INSERT OR REPLACE INTO phase9_shadow_records VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """, [
                rec.record_id,
                rec.signal_timestamp,
                rec.market_a_id,
                rec.market_b_id,
                rec.predicted_delta_15m_pp,
                rec.best_bid_b,
                rec.best_ask_b,
                rec.intended_quote_price,
                rec.quote_distance_d,
                rec.hypothetical_queue_ahead,
                rec.is_hypothetically_filled,
                rec.fill_timestamp,
                rec.is_cancelled,
                rec.cancellation_reason,
                rec.markout_1m_pp,
                rec.markout_5m_pp,
                rec.markout_15m_pp,
                rec.hypothetical_pnl_usd,
                rec.recorded_at
            ])

        return rec

    def get_shadow_performance_summary(self) -> Dict[str, Any]:
        """Fetch cumulative performance metrics from recorded shadow trading."""
        with duckdb.connect(self.db_path) as con:
            df = con.execute("SELECT * FROM phase9_shadow_records").fetchdf()

        if df.empty:
            return {
                "total_records": 0,
                "fill_rate_pct": 0.0,
                "cumulative_pnl_usd": 0.0,
                "mean_markout_15m_pp": 0.0
            }

        n_tot = len(df)
        filled = df[df["is_hypothetically_filled"]]
        n_f = len(filled)
        fill_rate = float(n_f / n_tot) * 100.0 if n_tot > 0 else 0.0
        tot_pnl = float(filled["hypothetical_pnl_usd"].sum()) if n_f > 0 else 0.0
        mean_m15 = float(filled["markout_15m_pp"].mean()) if n_f > 0 else 0.0

        return {
            "total_records": n_tot,
            "fill_rate_pct": fill_rate,
            "cumulative_pnl_usd": tot_pnl,
            "mean_markout_15m_pp": mean_m15
        }
