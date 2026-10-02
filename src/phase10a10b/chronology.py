"""Chronology and Discovery/OOS Splitting Engine for Phase 10A.10-B.

Enforces:
- Strict monotonic chronological sorting by source timestamp.
- Mechanical Discovery/OOS boundary calculation (60% discovery, 40% OOS).
- Complete isolation preventing events from crossing between discovery and OOS.
- Reporting of discovery and OOS date spans and event counts.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from src.phase10a10b.universe import ExpandedEventRecord


class ChronologyManager:
    """Manages event ordering and deterministic chronological partitioning."""

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def apply_chronological_split(
        cls,
        events: List[ExpandedEventRecord],
        discovery_pct: float = 0.60
    ) -> Tuple[List[ExpandedEventRecord], List[ExpandedEventRecord], Dict[str, Any]]:
        """Sorts events chronologically and assigns discovery/OOS flags."""
        if not events:
            return [], [], {"discovery_count": 0, "oos_count": 0}

        sorted_events = sorted(events, key=lambda e: cls.to_utc(e.source_timestamp))
        n_total = len(sorted_events)
        n_disc = int(n_total * discovery_pct)

        discovery_events: List[ExpandedEventRecord] = []
        oos_events: List[ExpandedEventRecord] = []

        for i, ev in enumerate(sorted_events):
            if i < n_disc:
                ev.is_out_of_sample = False
                discovery_events.append(ev)
            else:
                ev.is_out_of_sample = True
                oos_events.append(ev)

        summary = {
            "total_events": n_total,
            "discovery_count": len(discovery_events),
            "oos_count": len(oos_events),
            "discovery_start": cls.to_utc(discovery_events[0].source_timestamp) if discovery_events else None,
            "discovery_end": cls.to_utc(discovery_events[-1].source_timestamp) if discovery_events else None,
            "oos_start": cls.to_utc(oos_events[0].source_timestamp) if oos_events else None,
            "oos_end": cls.to_utc(oos_events[-1].source_timestamp) if oos_events else None,
        }

        return discovery_events, oos_events, summary
