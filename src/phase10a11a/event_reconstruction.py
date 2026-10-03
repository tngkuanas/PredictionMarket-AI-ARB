"""Raw Event-Level Reconstruction Engine for Phase 10A.11-A.

Reconstructs the full 8-step causal event sequence directly from genuine L2 order book
snapshots and trade events in DuckDB in strictly read-only mode:
1. Pre-sweep book state
2. Aggressive trade / sweep
3. Depth depletion
4. Post-sweep book state
5. Signal timestamp (t_sig >= t_sweep)
6. Executable entry (t_exec >= t_sig)
7. Replenishment / recovery tracking
8. Exit / markout tracking (1s, 5s, 15s, 30s, 45s, 60s)
"""

from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional, Any, Tuple
import duckdb
import numpy as np


@dataclass
class EventAuditRow:
    event_id: str
    market_id: str
    token_id: str
    sweep_timestamp: datetime.datetime
    signal_timestamp: datetime.datetime
    execution_timestamp: datetime.datetime
    sweep_direction: str  # "BUY" or "SELL"
    sweep_notional: float  # size_usd
    levels_consumed: int
    pre_sweep_depth: float
    post_sweep_depth: float
    depth_depletion_pct: float
    replenishment_pct_30s: float
    spread_before_sweep: float  # bps
    spread_immediately_after_sweep: float  # bps
    executable_entry_vwap: float
    executable_exit_vwap_30s: float = 0.0
    markout_1s: float = 0.0  # executable bps
    markout_5s: float = 0.0
    markout_10s: float = 0.0
    markout_15s: float = 0.0
    markout_30s: float = 0.0
    markout_45s: float = 0.0
    markout_60s: float = 0.0
    mid_markout_30s: float = 0.0
    net_pnl_bps: float = 0.0
    episode_id: str = ""
    market_family: str = "General"
    is_valid_executable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "sweep_timestamp": str(self.sweep_timestamp),
            "signal_timestamp": str(self.signal_timestamp),
            "execution_timestamp": str(self.execution_timestamp),
            "sweep_direction": self.sweep_direction,
            "sweep_notional": round(self.sweep_notional, 2),
            "levels_consumed": self.levels_consumed,
            "pre_sweep_depth": round(self.pre_sweep_depth, 2),
            "post_sweep_depth": round(self.post_sweep_depth, 2),
            "depth_depletion_pct": round(self.depth_depletion_pct, 2),
            "replenishment_pct_30s": round(self.replenishment_pct_30s, 2),
            "spread_before_sweep": round(self.spread_before_sweep, 2),
            "spread_immediately_after_sweep": round(self.spread_immediately_after_sweep, 2),
            "executable_entry_vwap": round(self.executable_entry_vwap, 4),
            "executable_exit_vwap_30s": round(self.executable_exit_vwap_30s, 4),
            "markout_1s": round(self.markout_1s, 2),
            "markout_5s": round(self.markout_5s, 2),
            "markout_10s": round(self.markout_10s, 2),
            "markout_15s": round(self.markout_15s, 2),
            "markout_30s": round(self.markout_30s, 2),
            "markout_45s": round(self.markout_45s, 2),
            "markout_60s": round(self.markout_60s, 2),
            "mid_markout_30s": round(self.mid_markout_30s, 2),
            "net_pnl_bps": round(self.net_pnl_bps, 2),
            "episode_id": self.episode_id,
            "market_family": self.market_family,
            "is_valid_executable": self.is_valid_executable,
        }


class EventReconstructionEngine:
    """Scans DuckDB to reconstruct raw event sequences and markouts."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def reconstruct_events(
        self,
        min_trade_size_usd: float = 360.0,
        max_timestamp: Optional[datetime.datetime] = None,
        base_fee_bps: float = 5.0,
        max_events: Optional[int] = None,
    ) -> List[EventAuditRow]:
        """Reconstructs event audit table directly from trades and book snapshots."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            ts_filter = f"AND receive_timestamp <= '{max_timestamp}'::timestamp" if max_timestamp else ""
            limit_clause = f"LIMIT {max_events}" if max_events else ""

            # Fetch candidate sweep trades
            query = f"""
                SELECT 
                    t.trade_id, t.market_id, t.token_id, t.receive_timestamp, 
                    t.price, t.size, t.size_usd, t.side,
                    COALESCE(u.category, 'General') as category
                FROM phase10a5_trades t
                LEFT JOIN phase10a5_market_universe u ON t.token_id = u.token_id
                WHERE t.size_usd >= {min_trade_size_usd}
                {ts_filter}
                ORDER BY t.receive_timestamp ASC
                {limit_clause}
            """
            sweeps = con.execute(query).fetchall()

            audit_rows: List[EventAuditRow] = []
            episode_tracker: Dict[str, datetime.datetime] = {}
            episode_counters: Dict[str, int] = {}

            horizons = [1, 5, 10, 15, 30, 45, 60]

            for row in sweeps:
                tid, mkt, tok, sw_ts, price, size, size_usd, side, cat = row
                side = (side or "BUY").upper()

                # 1. Episode clustering: group sweeps on same token within 60s into single episode
                last_ep_ts = episode_tracker.get(tok)
                if last_ep_ts is None or (sw_ts - last_ep_ts).total_seconds() > 60.0:
                    episode_counters[tok] = episode_counters.get(tok, 0) + 1
                    episode_tracker[tok] = sw_ts
                ep_id = f"ep_{tok[:8]}_{episode_counters[tok]}"

                # 2. Pre-sweep snapshot (last valid snap <= sw_ts)
                pre_snap = con.execute(f"""
                    SELECT timestamp, midpoint, spread_bps, depth_bid_usd, depth_ask_usd, best_bid, best_ask
                    FROM phase10a5_book_snapshots
                    WHERE token_id = '{tok}' AND timestamp <= '{sw_ts}'::timestamp
                    ORDER BY timestamp DESC
                    LIMIT 1
                """).fetchone()

                if not pre_snap or not pre_snap[1] or not pre_snap[5] or not pre_snap[6]:
                    continue

                pre_ts, mid_pre, sp_pre, depth_bid_pre, depth_ask_pre, bid_pre, ask_pre = pre_snap
                pre_depth = depth_ask_pre if side == "BUY" else depth_bid_pre
                pre_depth = max(1.0, float(pre_depth or 1.0))

                # 3. Post-sweep entry snapshot (first valid snap >= sw_ts)
                post_snap = con.execute(f"""
                    SELECT timestamp, midpoint, spread_bps, depth_bid_usd, depth_ask_usd, best_bid, best_ask
                    FROM phase10a5_book_snapshots
                    WHERE token_id = '{tok}' AND timestamp >= '{sw_ts}'::timestamp
                    ORDER BY timestamp ASC
                    LIMIT 1
                """).fetchone()

                if not post_snap or not post_snap[1] or not post_snap[5] or not post_snap[6]:
                    continue

                post_ts, mid_post, sp_post, depth_bid_post, depth_ask_post, bid_post, ask_post = post_snap
                post_depth = depth_ask_post if side == "BUY" else depth_bid_post
                post_depth = float(post_depth or 0.0)

                # Depth depletion %
                depletion_pct = max(0.0, min(100.0, (pre_depth - post_depth) / pre_depth * 100.0))
                levels_consumed = max(1, int(size_usd / max(1.0, pre_depth * 0.5)))

                # Strict causal timestamps: sweep_ts <= signal_ts <= exec_ts
                sig_ts = max(sw_ts, post_ts)
                exec_ts = sig_ts + datetime.timedelta(milliseconds=100)  # 100ms realistic execution latency

                # Executable entry price (counter-trend):
                # BUY sweep pushed price up -> counter-trend sells at bid_post
                # SELL sweep pushed price down -> counter-trend buys at ask_post
                if side == "BUY":
                    entry_vwap = bid_post
                else:
                    entry_vwap = ask_post

                # Markouts across horizons
                horizon_markouts: Dict[int, float] = {}
                mid_markout_30s = 0.0
                replenishment_30s = 0.0
                exit_vwap_30s = entry_vwap

                for h in horizons:
                    h_snap = con.execute(f"""
                        SELECT midpoint, best_bid, best_ask, depth_bid_usd, depth_ask_usd
                        FROM phase10a5_book_snapshots
                        WHERE token_id = '{tok}' AND timestamp >= '{sw_ts}'::timestamp + INTERVAL {h} SECOND
                        ORDER BY timestamp ASC
                        LIMIT 1
                    """).fetchone()

                    if h_snap and h_snap[0] and h_snap[1] and h_snap[2]:
                        h_mid, h_bid, h_ask, h_db, h_da = h_snap
                        
                        # Executable exit:
                        # If entry was SELL (sold at bid), exit is BUY (buy at h_ask) -> PnL = (entry - h_ask) / entry
                        # If entry was BUY (bought at ask), exit is SELL (sell at h_bid) -> PnL = (h_bid - entry) / entry
                        if side == "BUY":
                            exec_pnl = (entry_vwap - h_ask) / entry_vwap * 10000.0 - (2.0 * base_fee_bps)
                            rev_mid = (mid_pre - h_mid) / mid_pre * 10000.0
                        else:
                            exec_pnl = (h_bid - entry_vwap) / entry_vwap * 10000.0 - (2.0 * base_fee_bps)
                            rev_mid = (h_mid - mid_pre) / mid_pre * 10000.0

                        horizon_markouts[h] = exec_pnl

                        if h == 30:
                            mid_markout_30s = rev_mid
                            exit_vwap_30s = h_ask if side == "BUY" else h_bid
                            h_depth = float(h_da if side == "BUY" else h_db)
                            replenished = max(0.0, h_depth - post_depth)
                            depleted = max(1.0, pre_depth - post_depth)
                            replenishment_30s = min(200.0, (replenished / depleted) * 100.0)
                    else:
                        horizon_markouts[h] = -999.0

                net_pnl = horizon_markouts.get(30, -999.0)

                audit_rows.append(EventAuditRow(
                    event_id=f"ev_{tid}",
                    market_id=mkt,
                    token_id=tok,
                    sweep_timestamp=sw_ts,
                    signal_timestamp=sig_ts,
                    execution_timestamp=exec_ts,
                    sweep_direction=side,
                    sweep_notional=size_usd,
                    levels_consumed=levels_consumed,
                    pre_sweep_depth=pre_depth,
                    post_sweep_depth=post_depth,
                    depth_depletion_pct=depletion_pct,
                    replenishment_pct_30s=replenishment_30s,
                    spread_before_sweep=float(sp_pre or 0.0),
                    spread_immediately_after_sweep=float(sp_post or 0.0),
                    executable_entry_vwap=entry_vwap,
                    executable_exit_vwap_30s=exit_vwap_30s,
                    markout_1s=horizon_markouts.get(1, 0.0),
                    markout_5s=horizon_markouts.get(5, 0.0),
                    markout_10s=horizon_markouts.get(10, 0.0),
                    markout_15s=horizon_markouts.get(15, 0.0),
                    markout_30s=horizon_markouts.get(30, 0.0),
                    markout_45s=horizon_markouts.get(45, 0.0),
                    markout_60s=horizon_markouts.get(60, 0.0),
                    mid_markout_30s=mid_markout_30s,
                    net_pnl_bps=net_pnl,
                    episode_id=ep_id,
                    market_family=cat,
                    is_valid_executable=True,
                ))

            return audit_rows
        finally:
            con.close()
