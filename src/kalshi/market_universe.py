"""Kalshi Market Universe Collector and Cross-Venue Candidate Interface.

Collects objective market universe metadata from Kalshi APIs and maps candidate markets
into Phase 10A.6E canonical economic contract representations for deterministic equivalence
validation.
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional

from src.kalshi.schema import KalshiMarketUniverseRecord
from src.cross_venue.schema import CanonicalEconomicContract

logger = logging.getLogger(__name__)


class KalshiMarketUniverseManager:
    """Manages Kalshi market discovery, metadata hashing, and canonical contract generation."""

    def __init__(self, min_liquidity: float = 0.0, min_volume: float = 0.0):
        self.min_liquidity = min_liquidity
        self.min_volume = min_volume

    def parse_market_item(
        self,
        item: Dict[str, Any],
        session_id: str
    ) -> KalshiMarketUniverseRecord:
        """Parses a raw market metadata JSON object from Kalshi REST/WebSocket feeds."""
        ticker = str(item.get("ticker", "")).strip()
        title = str(item.get("title") or item.get("subtitle", "")).strip()
        status = str(item.get("status", "open")).lower()

        open_time = self._parse_dt(item.get("open_time"))
        close_time = self._parse_dt(item.get("close_time"))
        expiration_time = self._parse_dt(item.get("expiration_time") or item.get("settlement_timer_started_at"))

        settlement_source = str(
            item.get("settlement_source") or
            item.get("source") or
            item.get("rules_primary") or
            "Official Release"
        )
        resolution_rules = str(
            item.get("rules_primary") or
            item.get("resolution_rules") or
            item.get("description") or
            title
        )

        strike_type = item.get("strike_type")
        floor_strike = float(item["floor_strike"]) if item.get("floor_strike") is not None else None
        cap_strike = float(item["cap_strike"]) if item.get("cap_strike") is not None else None

        tick_size = float(item.get("tick_size") or 0.01)
        volume = float(item.get("volume", 0.0) or 0.0)
        open_interest = float(item.get("open_interest", 0.0) or 0.0)
        liquidity = float(item.get("liquidity", 0.0) or open_interest)

        # Canonical deterministic hash of raw metadata
        raw_str = json.dumps(item, sort_keys=True, default=str)
        meta_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        return KalshiMarketUniverseRecord(
            entry_id=f"kalshi_univ_{ticker}_{int(now.timestamp())}",
            session_id=session_id,
            market_id=ticker,
            title=title,
            status=status,
            open_time=open_time,
            close_time=close_time,
            expiration_time=expiration_time,
            settlement_source=settlement_source,
            resolution_rules=resolution_rules,
            strike_type=strike_type,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            tick_size=tick_size,
            volume=volume,
            open_interest=open_interest,
            liquidity=liquidity,
            raw_metadata_hash=meta_hash,
            retrieval_timestamp=now
        )

    def _parse_dt(self, val: Any) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val / 1000.0 if val > 1e11 else val, tz=timezone.utc)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    def get_kalshi_candidate_markets(
        self,
        records: List[KalshiMarketUniverseRecord]
    ) -> List[CanonicalEconomicContract]:
        """Translates Kalshi universe records into candidate CanonicalEconomicContracts.

        NOTE: This does NOT automatically approve equivalence. It maps fields objectively
        so Phase 10A.6E's SettlementNormalizer can run rigorous deterministic checks.
        """
        candidates: List[CanonicalEconomicContract] = []

        for rec in records:
            # Extract economic variables from title / rules
            event_name = rec.title
            geo_scope = "US"  # Kalshi is a US-regulated CFTC exchange; default to US unless international ticker
            if "ECB" in rec.market_id or "Eurozone" in rec.title:
                geo_scope = "EUR"
            elif "BOE" in rec.market_id or "UK" in rec.title:
                geo_scope = "UK"

            obs_var = rec.title
            threshold = rec.floor_strike if rec.floor_strike is not None else rec.cap_strike
            ineq_dir = None

            # Infer inequality direction from title or strike_type if present
            if rec.strike_type == "greater":
                ineq_dir = ">="
            elif rec.strike_type == "less":
                ineq_dir = "<="
            elif "above" in rec.title.lower() or "greater" in rec.title.lower() or ">" in rec.title:
                ineq_dir = ">="
            elif "below" in rec.title.lower() or "less" in rec.title.lower() or "<" in rec.title:
                ineq_dir = "<="

            temporal_scope = rec.close_time.strftime("%Y-%m-%d") if rec.close_time else "open"

            contract = CanonicalEconomicContract(
                venue="kalshi",
                venue_contract_id=rec.market_id,
                underlying_event=event_name,
                geographic_scope=geo_scope,
                observation_variable=obs_var,
                temporal_scope=temporal_scope,
                resolution_timestamp=rec.close_time or rec.expiration_time,
                threshold=threshold,
                inequality_direction=ineq_dir,
                source_of_resolution=rec.settlement_source,
                currency="USD",
                tick_size=rec.tick_size,
                contract_multiplier=1.0,
                resolution_rules=rec.resolution_rules,
                invalidation_rules="",
                raw_metadata_hash=rec.raw_metadata_hash
            )
            candidates.append(contract)

        return candidates
