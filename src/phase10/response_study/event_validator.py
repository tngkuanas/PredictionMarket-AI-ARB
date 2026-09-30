"""Deterministic Event Validation, Contract Mapping, and Clustering Engine for Phase 10A.6.

Integrates deterministic contract mapping, ambiguity gating, temporal boundary validation,
and event dependence/clustering without LLM interference in the execution path.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import List, Dict, Any, Optional, Tuple, Set

from src.phase10.events.schema import InformationEvent, EventDirection, SourceType
from src.phase10.events.contract_mapper import DeterministicContractMapper, MappingDecision
from src.phase10.response_study.schema import EventStudyQualityStatus

logger = logging.getLogger(__name__)


class EventValidatorAndMapper:
    """Validates real-world events, maps them to tradable contracts, and detects dependence clusters."""

    def __init__(self, cluster_window_seconds: float = 3600.0):
        self.cluster_window_seconds = cluster_window_seconds
        self.contract_mapper = DeterministicContractMapper()

    def validate_event_record(
        self,
        event: Dict[str, Any]
    ) -> Tuple[bool, EventStudyQualityStatus, Optional[str]]:
        """Ensures event possesses valid provenance, timestamping, and deterministic fields."""
        event_id = event.get("event_id")
        if not event_id:
            return False, EventStudyQualityStatus.INVALID_TIMESTAMP, "Missing event_id"

        pub_ts = event.get("publication_timestamp") or event.get("event_timestamp")
        if not pub_ts:
            return False, EventStudyQualityStatus.INVALID_TIMESTAMP, "Missing event publication timestamp"

        if isinstance(pub_ts, str):
            try:
                pub_ts = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
            except Exception:
                return False, EventStudyQualityStatus.INVALID_TIMESTAMP, f"Unparseable publication timestamp: {pub_ts}"

        pub_utc = pub_ts if pub_ts.tzinfo else pub_ts.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if pub_utc > now_utc:
            return False, EventStudyQualityStatus.INVALID_TIMESTAMP, f"Future publication timestamp: {pub_utc} > {now_utc}"

        source = event.get("source")
        source_url = event.get("source_url")
        if not source or not source_url:
            return False, EventStudyQualityStatus.OTHER_INVALID, "Event missing source or source_url provenance"

        # Direction check: must be deterministically specified
        direction = event.get("direction") or event.get("expected_direction")
        if not direction or str(direction).upper() in ("UNCERTAIN", "AMBIGUOUS", "UNKNOWN"):
            return False, EventStudyQualityStatus.AMBIGUOUS_MAPPING, "Event direction is ambiguous or uncertain"

        return True, EventStudyQualityStatus.VALID, None

    def map_event_to_market(
        self,
        event: Dict[str, Any],
        market_universe: List[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[str], Optional[str], EventStudyQualityStatus, Optional[str]]:
        """Deterministically maps event to target market & token, deriving trading direction.

        Returns: (market_id, token_id, trade_direction, quality_status, reason)
        """
        # First validate event fields
        is_valid, status, reason = self.validate_event_record(event)
        if not is_valid:
            return None, None, None, status, reason

        # Check explicit mapped tokens first if provided
        if event.get("mapped_market_id") and event.get("mapped_token_id"):
            dir_str = str(event.get("direction") or event.get("expected_direction")).upper()
            trade_dir = "BUY" if dir_str in ("BUY", "INCREASE", "LONG", "YES") else "SELL"
            if event.get("is_inverted", False):
                trade_dir = "SELL" if trade_dir == "BUY" else "BUY"
            return event["mapped_market_id"], event["mapped_token_id"], trade_dir, EventStudyQualityStatus.VALID, None

        # Deterministic match against monitored market universe
        affected_entity = str(event.get("affected_entity") or event.get("title", "")).lower()
        event_title = str(event.get("title") or event.get("description", "")).lower()

        matched_entry = None
        for entry in market_universe:
            mkt_title = str(entry.get("title", "")).lower()
            mkt_outcome = str(entry.get("outcome", "")).lower()

            # Exact keyword or entity overlap
            if affected_entity and (affected_entity in mkt_title or affected_entity in mkt_outcome):
                matched_entry = entry
                break
            # Title overlap
            if event_title and any(word in mkt_title for word in event_title.split() if len(word) > 4):
                matched_entry = entry
                break

        if not matched_entry:
            return None, None, None, EventStudyQualityStatus.AMBIGUOUS_MAPPING, "No deterministic market match found in active universe"

        market_id = matched_entry["market_id"]
        token_id = matched_entry["token_id"]

        dir_str = str(event.get("direction") or event.get("expected_direction")).upper()
        trade_dir = "BUY" if dir_str in ("BUY", "INCREASE", "LONG", "YES") else "SELL"
        if event.get("is_inverted", False):
            trade_dir = "SELL" if trade_dir == "BUY" else "BUY"

        return market_id, token_id, trade_dir, EventStudyQualityStatus.VALID, None

    def cluster_events_and_detect_overlap(
        self,
        events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Assigns cluster IDs and flags overlapping or duplicate events for the same contract."""
        sorted_events = sorted(
            events,
            key=lambda e: (e.get("mapped_market_id") or "", e.get("publication_timestamp") or datetime.min)
        )

        seen_keys: Set[Tuple[str, datetime]] = set()
        clustered = []

        for i, ev in enumerate(sorted_events):
            mkt_id = ev.get("mapped_market_id", "unknown_mkt")
            ts = ev.get("publication_timestamp") or ev.get("event_timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

            # 1. Duplicate event detection
            dup_key = (mkt_id, ts_utc)
            is_duplicate = dup_key in seen_keys
            seen_keys.add(dup_key)

            # 2. Overlap detection with preceding events on same contract
            is_overlapping = False
            cluster_id = ev.get("event_cluster_id") or f"cluster_{mkt_id}_{ts_utc.strftime('%Y%m%d%H')}"

            for prev in clustered:
                if prev.get("mapped_market_id") == mkt_id:
                    prev_ts = prev.get("publication_timestamp")
                    if abs((ts_utc - prev_ts).total_seconds()) <= self.cluster_window_seconds:
                        is_overlapping = True
                        cluster_id = prev.get("event_cluster_id", cluster_id)
                        break

            enriched = dict(ev)
            enriched["event_cluster_id"] = cluster_id
            enriched["publication_timestamp"] = ts_utc
            if is_duplicate:
                enriched["dependence_status"] = EventStudyQualityStatus.DUPLICATE_EVENT
            elif is_overlapping:
                enriched["dependence_status"] = EventStudyQualityStatus.OVERLAPPING_EVENT
            else:
                enriched["dependence_status"] = EventStudyQualityStatus.VALID

            clustered.append(enriched)

        return clustered
