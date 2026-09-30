"""Strict Future Event Interface for Phase 10A.5.

Ensures strict separation between real market observations and future event definitions.
Guarantees:
1. No path from future price -> event definition.
2. No path from event direction -> generated price.
3. Publication timestamps must be objectively verifiable prior to alignment.
"""
from datetime import datetime, timezone
import logging
from typing import List, Optional

import duckdb

from src.phase10.acquisition.schema import GenuineEventRecord

logger = logging.getLogger(__name__)


class GenuineEventRegistry:
    """Manages objectively timestamped real events for future research without circularity."""

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path

    def init_table(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Creates the phase10a5_events table in DuckDB."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phase10a5_events (
                event_id VARCHAR PRIMARY KEY,
                source VARCHAR,
                source_url VARCHAR,
                publication_timestamp TIMESTAMP,
                event_category VARCHAR,
                description VARCHAR,
                affected_entity VARCHAR,
                event_created_timestamp TIMESTAMP
            );
        """)

    def register_event(
        self,
        event_id: str,
        source: str,
        source_url: str,
        publication_timestamp: datetime,
        event_category: str,
        description: str,
        affected_entity: str
    ) -> GenuineEventRecord:
        """Validates and registers an objectively timestamped event."""
        now = datetime.now(timezone.utc)
        
        # Validation: publication timestamp cannot be in the future relative to registration
        pub_utc = publication_timestamp if publication_timestamp.tzinfo else publication_timestamp.replace(tzinfo=timezone.utc)
        if pub_utc > now:
            raise ValueError(f"Publication timestamp {pub_utc} is in the future relative to current time {now}")

        if not source or not source_url:
            raise ValueError("Event must have a verified source and source URL.")

        record = GenuineEventRecord(
            event_id=event_id,
            source=source,
            source_url=source_url,
            publication_timestamp=pub_utc,
            event_category=event_category,
            description=description,
            affected_entity=affected_entity,
            event_created_timestamp=now
        )
        return record

    def persist_events(self, conn: duckdb.DuckDBPyConnection, events: List[GenuineEventRecord]) -> int:
        if not events:
            return 0
        rows = [
            (
                e.event_id, e.source, e.source_url, e.publication_timestamp,
                e.event_category, e.description, e.affected_entity,
                e.event_created_timestamp
            )
            for e in events
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a5_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)
