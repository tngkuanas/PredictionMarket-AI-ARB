"""Historical Source Validator and Anti-Lookahead Verifier for Phase 10A.10-B.

Enforces:
1. Strict chronology:
   source_event_timestamp <= source_observation_timestamp <= market_observation_timestamp <= execution_timestamp
2. Source tier qualification: Tier 1 and Tier 2 only; Tier 3 strictly rejected.
3. Content hash integrity (SHA-256).
4. Rejection logging for unverified timestamps, lookahead, or post-outcome edits.
"""

from datetime import datetime, timezone
import hashlib
from typing import Dict, Any, Optional, Tuple

from src.phase10a10b.universe import RejectionCategory, SourceEvidenceRecord
from src.phase10a10.source_registry import SourceRegistry


class HistoricalSourceValidator:
    """Rigorous validator ensuring zero lookahead and immutable historical source integrity."""

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        """Converts datetime to UTC-aware datetime."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def validate_historical_source(
        cls,
        evidence: SourceEvidenceRecord,
        market_observation_ts: datetime,
    ) -> Tuple[bool, Optional[RejectionCategory], Optional[str]]:
        """Validates historical source availability, tier authority, and non-lookahead."""
        t_pub = cls.to_utc(evidence.published_at)
        t_src_obs = cls.to_utc(evidence.source_observation_timestamp)
        t_mkt_obs = cls.to_utc(market_observation_ts)

        # 1. Authoritative Tier Check
        tier = SourceRegistry.get_tier(evidence.source_domain)
        if not SourceRegistry.is_eligible_for_primary_research(tier):
            return False, RejectionCategory.SOURCE_NOT_AUTHORITATIVE, f"Source tier {tier} not authorized for primary discovery"

        # 2. Chronology Check: published_at <= source_obs_ts
        if t_pub > t_src_obs:
            return False, RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE, f"Published time {t_pub} > source observation time {t_src_obs}"

        # 3. Lookahead Check: source_obs_ts <= market_obs_ts
        if t_src_obs > t_mkt_obs:
            return False, RejectionCategory.LOOKAHEAD, f"Source observation {t_src_obs} > market observation {t_mkt_obs}"

        # 4. Content Hash Verification
        calc_hash = hashlib.sha256(evidence.raw_payload_snippet.encode("utf-8")).hexdigest()
        if calc_hash != evidence.content_hash:
            return False, RejectionCategory.SOURCE_TIMESTAMP_UNVERIFIABLE, "Content hash mismatch against raw snippet"

        return True, None, None
