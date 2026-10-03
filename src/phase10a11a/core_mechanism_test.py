"""Core Mechanism Testing Engine for Phase 10A.11-A.

Directly tests the post-sweep mean reversion hypothesis across BUY and SELL sweeps
at horizons 1s, 5s, 10s, 15s, 30s, 45s, and 60s, evaluating both midpoint and
executable markouts.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any
import numpy as np
from src.phase10a11a.event_reconstruction import EventAuditRow


@dataclass
class HorizonMarkoutResult:
    horizon_sec: int
    sample_count: int
    mean_midpoint_markout_bps: float
    median_midpoint_markout_bps: float
    mean_executable_markout_bps: float
    median_executable_markout_bps: float
    buy_sweeps_exec_markout_bps: float
    sell_sweeps_exec_markout_bps: float
    fraction_positive_exec: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_sec": self.horizon_sec,
            "sample_count": self.sample_count,
            "mean_midpoint_markout_bps": round(self.mean_midpoint_markout_bps, 2),
            "median_midpoint_markout_bps": round(self.median_midpoint_markout_bps, 2),
            "mean_executable_markout_bps": round(self.mean_executable_markout_bps, 2),
            "median_executable_markout_bps": round(self.median_executable_markout_bps, 2),
            "buy_sweeps_exec_markout_bps": round(self.buy_sweeps_exec_markout_bps, 2),
            "sell_sweeps_exec_markout_bps": round(self.sell_sweeps_exec_markout_bps, 2),
            "fraction_positive_exec": round(self.fraction_positive_exec, 4),
        }


class CoreMechanismTestEngine:
    """Evaluates the post-sweep markout curve across multiple horizons."""

    HORIZONS = [1, 5, 10, 15, 30, 45, 60]

    def evaluate_markouts(self, events: List[EventAuditRow]) -> Dict[int, HorizonMarkoutResult]:
        """Calculates midpoint and executable markouts across all horizons."""
        results: Dict[int, HorizonMarkoutResult] = {}

        for h in self.HORIZONS:
            attr_name = f"markout_{h}s"
            valid_events = [e for e in events if getattr(e, attr_name, -999.0) > -5000.0]
            if not valid_events:
                continue

            exec_vals = [getattr(e, attr_name) for e in valid_events]
            # Approximate midpoint markout from executable markout + spread cross allowance
            mid_vals = [e.mid_markout_30s if h == 30 else (getattr(e, attr_name) + e.spread_immediately_after_sweep * 0.5) for e in valid_events]

            buy_events = [e for e in valid_events if e.sweep_direction == "BUY"]
            sell_events = [e for e in valid_events if e.sweep_direction == "SELL"]

            buy_exec = [getattr(e, attr_name) for e in buy_events]
            sell_exec = [getattr(e, attr_name) for e in sell_events]

            pos_count = sum(1 for v in exec_vals if v > 0.0)

            results[h] = HorizonMarkoutResult(
                horizon_sec=h,
                sample_count=len(valid_events),
                mean_midpoint_markout_bps=float(np.mean(mid_vals)) if mid_vals else 0.0,
                median_midpoint_markout_bps=float(np.median(mid_vals)) if mid_vals else 0.0,
                mean_executable_markout_bps=float(np.mean(exec_vals)),
                median_executable_markout_bps=float(np.median(exec_vals)),
                buy_sweeps_exec_markout_bps=float(np.mean(buy_exec)) if buy_exec else 0.0,
                sell_sweeps_exec_markout_bps=float(np.mean(sell_exec)) if sell_exec else 0.0,
                fraction_positive_exec=(pos_count / len(valid_events)) if valid_events else 0.0,
            )

        return results
