"""Source Validation and Anti-Lookahead Engine for Phase 10A.10.

Enforces:
1. Strict timestamp chronology:
   `source_event_timestamp <= source_observation_timestamp <= market_observation_timestamp <= execution_timestamp`
2. Anti-lookahead rejection:
   Rejects future information, retroactive revisions, or timestamps after the trade.
3. Content hashing and immutable provenance verification.
4. Timezone normalization to UTC.
"""

from datetime import datetime, timezone
import hashlib
from typing import Dict, Any, Tuple, Optional

from src.phase10a10.schema import SourceRecord, SourceTier
from src.phase10a10.source_registry import SourceRegistry


class SourceValidationError(ValueError):
    """Raised when source chronology or integrity validation fails."""
    pass


class SourceValidator:
    """Rigorous validator ensuring zero lookahead and immutable source provenance."""

    @staticmethod
    def compute_content_hash(raw_payload: str) -> str:
        """Computes deterministic SHA-256 hash of raw source payload."""
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    @classmethod
    def validate_chronology(
        cls,
        source_event_ts: datetime,
        source_obs_ts: datetime,
        market_obs_ts: datetime,
        execution_ts: datetime,
    ) -> Tuple[bool, Optional[str]]:
        """Validates that timestamps obey strict monotonic chronology.
        
        Rule: source_event_ts <= source_obs_ts <= market_obs_ts <= execution_ts
        """
        # Ensure timezone-aware UTC comparison
        def to_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        t_event = to_utc(source_event_ts)
        t_src_obs = to_utc(source_obs_ts)
        t_mkt_obs = to_utc(market_obs_ts)
        t_exec = to_utc(execution_ts)

        if t_event > t_src_obs:
            return False, f"Chronology violation: source_event_ts ({t_event}) > source_obs_ts ({t_src_obs})"

        if t_src_obs > t_mkt_obs:
            return False, f"Lookahead violation: source_obs_ts ({t_src_obs}) > market_obs_ts ({t_mkt_obs})"

        if t_mkt_obs > t_exec:
            return False, f"Causality violation: market_obs_ts ({t_mkt_obs}) > execution_ts ({t_exec})"

        return True, None

    @classmethod
    def validate_source_record(cls, record: SourceRecord) -> Tuple[bool, Optional[str]]:
        """Validates source eligibility and payload integrity."""
        # Check source tier
        if not SourceRegistry.is_eligible_for_primary_research(record.source_tier):
            return False, f"Source tier {record.source_tier} is prohibited for primary research"

        # Check content hash
        computed_hash = cls.compute_content_hash(record.raw_payload)
        if computed_hash != record.content_hash:
            return False, f"Content hash mismatch: expected {record.content_hash}, got {computed_hash}"

        # Chronology of retrieval vs publication
        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        if to_utc(record.source_timestamp) > to_utc(record.retrieval_timestamp):
            return False, "Publication timestamp is strictly after retrieval timestamp"

        return True, None

    @classmethod
    def check_revision_vintage(
        cls,
        release_vintage_ts: datetime,
        target_observation_ts: datetime
    ) -> bool:
        """Verifies that an authoritative figure was available at the observation time,
        preventing lookahead via retroactive data revisions (e.g. BLS / BEA revisions).
        """
        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        return to_utc(release_vintage_ts) <= to_utc(target_observation_ts)
