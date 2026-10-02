"""Event Independence and Multi-Scale Clustering Engine for Phase 10A.10-B.

Enforces:
- Distinguishing raw candidate observations from unique underlying events.
- Tracking source event IDs, event families, dates, 5-minute clusters, and 1-minute clusters.
- Identification of duplicate events and co-dependent market observations.
- Aggregation of independence statistics to prevent degree-of-freedom inflation.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Set, Tuple

from src.phase10a10b.universe import ExpandedEventRecord, EventIndependenceRecord, RejectionCategory


class EventIndependenceTracker:
    """Calculates multi-scale clustering and guarantees event independence."""

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def assign_clusters(
        cls,
        events: List[ExpandedEventRecord],
        window_5m_sec: float = 300.0,
        window_1m_sec: float = 60.0
    ) -> List[EventIndependenceRecord]:
        """Assigns 5-minute and 1-minute time clusters to events."""
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: cls.to_utc(e.source_timestamp))
        records: List[EventIndependenceRecord] = []

        seen_sources: Set[str] = set()

        curr_5m_id = 0
        curr_1m_id = 0
        last_ts_5m = cls.to_utc(sorted_events[0].source_timestamp).timestamp()
        last_ts_1m = cls.to_utc(sorted_events[0].source_timestamp).timestamp()

        for ev in sorted_events:
            ts_sec = cls.to_utc(ev.source_timestamp).timestamp()

            # 5-minute cluster assignment
            if ts_sec - last_ts_5m > window_5m_sec:
                curr_5m_id += 1
                last_ts_5m = ts_sec

            # 1-minute cluster assignment
            if ts_sec - last_ts_1m > window_1m_sec:
                curr_1m_id += 1
                last_ts_1m = ts_sec

            cluster_5m_name = f"c5m_{ev.category.value}_{curr_5m_id}"
            cluster_1m_name = f"c1m_{ev.category.value}_{curr_1m_id}"

            ev.cluster_5m_id = cluster_5m_name
            ev.cluster_1m_id = cluster_1m_name

            # Check if source event is unique or duplicate
            is_independent = (ev.source_event_id not in seen_sources)
            seen_sources.add(ev.source_event_id)

            records.append(EventIndependenceRecord(
                event_id=ev.event_id,
                market_id=ev.market_id,
                source_event_id=ev.source_event_id,
                event_family=ev.event_family,
                event_date=cls.to_utc(ev.source_timestamp).strftime("%Y-%m-%d"),
                cluster_5m=cluster_5m_name,
                cluster_1m=cluster_1m_name,
                is_independent_event=is_independent
            ))

        return records

    @classmethod
    def compute_independence_metrics(
        cls,
        events: List[ExpandedEventRecord],
        candidate_count: int
    ) -> Dict[str, int]:
        """Calculates exact uniqueness counts across all dimensions."""
        return {
            "raw_candidate_observations": candidate_count,
            "unique_events": len(set(e.event_id for e in events)),
            "unique_source_events": len(set(e.source_event_id for e in events)),
            "unique_markets": len(set(e.market_id for e in events)),
            "unique_5m_clusters": len(set(e.cluster_5m_id for e in events)),
            "unique_1m_clusters": len(set(e.cluster_1m_id for e in events)),
            "unique_event_families": len(set(e.event_family for e in events)),
        }
