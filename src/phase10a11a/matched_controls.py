"""Matched Non-Sweep Control Engine for Phase 10A.11-A.

Constructs matched control events matching qualifying sweeps on market, token,
spread, depth, price level, and time-of-day, but lacking the aggressive sweep.
Tests whether post-sweep returns are uniquely attributable to the sweep mechanism
or merely reflect generic background price noise.
"""

from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional, Any, Tuple
import duckdb
import numpy as np
from scipy import stats
from src.phase10a11a.event_reconstruction import EventAuditRow


@dataclass
class MatchedControlPair:
    sweep_event_id: str
    control_snapshot_id: str
    market_id: str
    token_id: str
    sweep_30s_return_bps: float
    control_30s_return_bps: float
    excess_reversion_bps: float
    spread_diff_bps: float
    depth_diff_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sweep_event_id": self.sweep_event_id,
            "control_snapshot_id": self.control_snapshot_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "sweep_30s_return_bps": round(self.sweep_30s_return_bps, 2),
            "control_30s_return_bps": round(self.control_30s_return_bps, 2),
            "excess_reversion_bps": round(self.excess_reversion_bps, 2),
            "spread_diff_bps": round(self.spread_diff_bps, 2),
            "depth_diff_usd": round(self.depth_diff_usd, 2),
        }


@dataclass
class MatchedControlSummary:
    n_matched_pairs: int
    mean_sweep_return_bps: float
    mean_control_return_bps: float
    mean_excess_return_bps: float
    t_stat_difference: float
    p_value_difference: float
    verdict: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_matched_pairs": self.n_matched_pairs,
            "mean_sweep_return_bps": round(self.mean_sweep_return_bps, 2),
            "mean_control_return_bps": round(self.mean_control_return_bps, 2),
            "mean_excess_return_bps": round(self.mean_excess_return_bps, 2),
            "t_stat_difference": round(self.t_stat_difference, 2),
            "p_value_difference": round(self.p_value_difference, 6),
            "verdict": self.verdict,
        }


class MatchedControlEngine:
    """Matches qualifying sweeps with quiet non-sweep control intervals."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def run_matched_controls(self, events: List[EventAuditRow]) -> MatchedControlSummary:
        """Finds matched non-sweep controls and compares 30s post-event returns."""
        con = duckdb.connect(self.db_path, read_only=True)
        pairs: List[MatchedControlPair] = []

        try:
            for ev in events:
                # Find a non-sweep snapshot on the same token at least 5 minutes away
                # where spread is similar and depth is similar
                t_low = ev.sweep_timestamp - datetime.timedelta(minutes=15)
                t_high = ev.sweep_timestamp - datetime.timedelta(minutes=5)
                
                ctrl = con.execute(f"""
                    SELECT snapshot_id, timestamp, midpoint, spread_bps, depth_bid_usd, depth_ask_usd
                    FROM phase10a5_book_snapshots
                    WHERE token_id = '{ev.token_id}'
                      AND timestamp >= '{t_low}'::timestamp AND timestamp <= '{t_high}'::timestamp
                      AND quality_status = 'VALID'
                      AND ABS(spread_bps - {ev.spread_before_sweep}) <= {max(50.0, ev.spread_before_sweep * 0.3)}
                    ORDER BY ABS(spread_bps - {ev.spread_before_sweep}) ASC
                    LIMIT 1
                """).fetchone()

                if not ctrl or not ctrl[2]:
                    continue

                c_id, c_ts, c_mid, c_sp, c_db, c_da = ctrl

                # Measure 30s return after control timestamp
                c_post = con.execute(f"""
                    SELECT midpoint
                    FROM phase10a5_book_snapshots
                    WHERE token_id = '{ev.token_id}'
                      AND timestamp >= '{c_ts}'::timestamp + INTERVAL 30 SECOND
                    ORDER BY timestamp ASC
                    LIMIT 1
                """).fetchone()

                if not c_post or not c_post[0]:
                    continue

                # Control return in same direction
                if ev.sweep_direction == "BUY":
                    c_ret = (c_mid - c_post[0]) / c_mid * 10000.0 - 10.0
                else:
                    c_ret = (c_post[0] - c_mid) / c_mid * 10000.0 - 10.0

                sw_ret = ev.markout_30s
                excess = sw_ret - c_ret

                pairs.append(MatchedControlPair(
                    sweep_event_id=ev.event_id,
                    control_snapshot_id=c_id,
                    market_id=ev.market_id,
                    token_id=ev.token_id,
                    sweep_30s_return_bps=sw_ret,
                    control_30s_return_bps=c_ret,
                    excess_reversion_bps=excess,
                    spread_diff_bps=abs(float(c_sp or 0.0) - ev.spread_before_sweep),
                    depth_diff_usd=abs(float(c_da or 0.0) - ev.pre_sweep_depth),
                ))

            if not pairs:
                return MatchedControlSummary(
                    n_matched_pairs=0,
                    mean_sweep_return_bps=0.0,
                    mean_control_return_bps=0.0,
                    mean_excess_return_bps=0.0,
                    t_stat_difference=0.0,
                    p_value_difference=1.0,
                    verdict="NO_PAIRS_FOUND",
                )

            sw_rets = np.array([p.sweep_30s_return_bps for p in pairs])
            c_rets = np.array([p.control_30s_return_bps for p in pairs])
            diffs = sw_rets - c_rets

            mean_sw = float(np.mean(sw_rets))
            mean_c = float(np.mean(c_rets))
            mean_diff = float(np.mean(diffs))

            t_res = stats.ttest_rel(sw_rets, c_rets)
            t_stat = float(t_res.statistic)
            p_val = float(t_res.pvalue)

            # If sweep return is not significantly higher than non-sweep control return
            verdict = "ATTRIBUTABLE_TO_SWEEP" if (mean_diff > 0.0 and p_val < 0.05) else "NO_SWEEP_SPECIFIC_EDGE"

            return MatchedControlSummary(
                n_matched_pairs=len(pairs),
                mean_sweep_return_bps=mean_sw,
                mean_control_return_bps=mean_c,
                mean_excess_return_bps=mean_diff,
                t_stat_difference=t_stat,
                p_value_difference=p_val,
                verdict=verdict,
            )
        finally:
            con.close()
