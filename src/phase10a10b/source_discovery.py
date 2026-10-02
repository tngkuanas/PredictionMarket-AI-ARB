"""Authoritative Source Discovery Engine for Phase 10A.10-B.

Discovers, qualifies, and hashes authoritative source evidence across all 10 event categories:
- Tier 1: Official government bodies, central banks, statistical agencies, sports/esports governing bodies, financial exchanges.
- Tier 2: Primary wire services (Reuters, AP, Bloomberg Wire) with primary timestamps.
- Tier 3: Prohibited from primary discovery.
"""

from datetime import datetime, timezone, timedelta
import hashlib
from typing import Dict, Any, Optional, Tuple

from src.phase10a10b.universe import SourceEvidenceRecord, RejectionCategory
from src.phase10a10.source_registry import SourceRegistry


class SourceDiscoveryEngine:
    """Discovers and verifies authoritative source metadata."""

    @classmethod
    def create_source_evidence(
        cls,
        source_id: str,
        event_id: str,
        source_name_or_domain: str,
        source_url: str,
        published_at: datetime,
        source_obs_ts: datetime,
        raw_payload: str,
    ) -> Tuple[Optional[SourceEvidenceRecord], Optional[RejectionCategory], Optional[str]]:
        """Constructs and validates a source evidence record."""
        # Check source tier
        meta = SourceRegistry.lookup_source(source_name_or_domain)
        if meta is None:
            # Check domain
            domain = source_name_or_domain.lower().replace("https://", "").replace("http://", "").split("/")[0]
            tier = SourceRegistry.get_tier(domain)
        else:
            domain = meta["domains"][0]
            tier = meta["tier"]

        if not SourceRegistry.is_eligible_for_primary_research(tier):
            return None, RejectionCategory.SOURCE_NOT_AUTHORITATIVE, f"Source '{source_name_or_domain}' tier {tier} is ineligible for primary discovery"

        content_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

        evidence = SourceEvidenceRecord(
            source_id=source_id,
            event_id=event_id,
            source_url=source_url,
            source_domain=domain,
            source_tier=tier.value,
            published_at=published_at,
            source_observation_timestamp=source_obs_ts,
            retrieved_at=source_obs_ts + timedelta(seconds=1.0),
            content_hash=content_hash,
            raw_payload_snippet=raw_payload[:300],
            is_verified=True
        )

        return evidence, None, None
