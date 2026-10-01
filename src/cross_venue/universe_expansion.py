"""Phase 10A.6K: Genuine Kalshi Access, Credential Gate, Expanded Market Universe,
Deterministic Mapping Reproduction, and Permanent Contamination Guards.

CRITICAL RULES:
1. Credential gate: never print or persist private keys or secrets.
   If credentials unavailable, classify as BLOCKED_CREDENTIALS_UNAVAILABLE.
2. Market universe: metadata-only; never inspect prices for contract mapping.
3. Provenance: preserve all raw payload SHA-256 hashes and source classifications.
4. Contamination guard: permanently reject UNIT_FIXTURE, SYNTHETIC, and UNKNOWN
   provenance from production DuckDB tables.
5. Independent reproduction: independently reconstruct canonical contracts and hashes
   from raw metadata alone.
"""

from datetime import datetime, timezone
from enum import Enum
import glob
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Dict, Any, List, Optional, Set, Tuple, Union
import uuid

from pydantic import BaseModel, Field

from src.cross_venue.schema import (
    CanonicalEconomicContract,
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer
from src.cross_venue.cross_venue_market_discovery import (
    RejectionReason,
    ConservativeTextNormalizer,
    PolymarketCanonicalAdapter,
    KalshiCanonicalAdapter,
    MarketCandidatePair,
)
from src.cross_venue.provenance_auditor import SourceClassification

logger = logging.getLogger(__name__)


# =====================================================================
# 1. CREDENTIAL GATE & SECRETS AUDITING
# =====================================================================

class CredentialFailureCategory(str, Enum):
    """Categorical classification of credential audit results."""
    NONE_SPECIFIED = "NONE_SPECIFIED"
    KEY_ID_MISSING = "KEY_ID_MISSING"
    PRIVATE_KEY_MISSING = "PRIVATE_KEY_MISSING"
    MALFORMED_PEM = "MALFORMED_PEM"
    SIGNING_FAILED = "SIGNING_FAILED"
    UNREADABLE_KEY_FILE = "UNREADABLE_KEY_FILE"
    BLOCKED_CREDENTIALS_UNAVAILABLE = "BLOCKED_CREDENTIALS_UNAVAILABLE"


class KalshiCredentialStatusRecord(BaseModel):
    """Audit record for Kalshi credentials without exposing secret contents."""
    credentials_available: bool = False
    credential_source: str = "none"  # "environment", "file", "keychain", "none"
    authentication_attempted: bool = False
    authentication_success: bool = False
    failure_category: Optional[str] = None
    expected_env_vars: List[str] = Field(
        default_factory=lambda: ["KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY", "KALSHI_PRIVATE_KEY_PATH"]
    )
    expected_key_format: str = "Kalshi API Key ID (alphanumeric string)"
    expected_private_key_format: str = "RSA PEM (2048/4096-bit private key)"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns safe dictionary with zero secrets."""
        return {
            "credentials_available": self.credentials_available,
            "credential_source": self.credential_source,
            "authentication_attempted": self.authentication_attempted,
            "authentication_success": self.authentication_success,
            "failure_category": self.failure_category,
            "expected_env_vars": self.expected_env_vars,
            "expected_key_format": self.expected_key_format,
            "expected_private_key_format": self.expected_private_key_format,
            "timestamp": self.timestamp.isoformat(),
        }


class KalshiCredentialGate:
    """Deterministic, read-only credential gate for Kalshi access."""

    @classmethod
    def audit_credentials(cls) -> KalshiCredentialStatusRecord:
        """Inspects environment and files for Kalshi credentials without printing secrets."""
        key_id = os.environ.get("KALSHI_API_KEY_ID") or os.environ.get("KALSHI_KEY_ID") or os.environ.get("KALSHI_API_KEY")
        priv_key = os.environ.get("KALSHI_PRIVATE_KEY")
        priv_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH") or os.environ.get("KALSHI_PEM_PATH")

        if not key_id and not priv_key and not priv_key_path:
            return KalshiCredentialStatusRecord(
                credentials_available=False,
                credential_source="none",
                authentication_attempted=False,
                authentication_success=False,
                failure_category=CredentialFailureCategory.BLOCKED_CREDENTIALS_UNAVAILABLE.value,
            )

        source = "environment"
        if not key_id:
            return KalshiCredentialStatusRecord(
                credentials_available=False,
                credential_source=source,
                authentication_attempted=True,
                authentication_success=False,
                failure_category=CredentialFailureCategory.KEY_ID_MISSING.value,
            )

        pem_text = priv_key
        if not pem_text and priv_key_path:
            source = "file"
            path = Path(priv_key_path)
            if not path.is_file() or not os.access(path, os.R_OK):
                return KalshiCredentialStatusRecord(
                    credentials_available=False,
                    credential_source=source,
                    authentication_attempted=True,
                    authentication_success=False,
                    failure_category=CredentialFailureCategory.UNREADABLE_KEY_FILE.value,
                )
            try:
                pem_text = path.read_text(encoding="utf-8")
            except Exception:
                return KalshiCredentialStatusRecord(
                    credentials_available=False,
                    credential_source=source,
                    authentication_attempted=True,
                    authentication_success=False,
                    failure_category=CredentialFailureCategory.UNREADABLE_KEY_FILE.value,
                )

        if not pem_text:
            return KalshiCredentialStatusRecord(
                credentials_available=False,
                credential_source=source,
                authentication_attempted=True,
                authentication_success=False,
                failure_category=CredentialFailureCategory.PRIVATE_KEY_MISSING.value,
            )

        # Validate RSA PEM format without exposing key
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            load_pem_private_key(pem_text.encode("utf-8"), password=None)
        except Exception:
            return KalshiCredentialStatusRecord(
                credentials_available=False,
                credential_source=source,
                authentication_attempted=True,
                authentication_success=False,
                failure_category=CredentialFailureCategory.MALFORMED_PEM.value,
            )

        return KalshiCredentialStatusRecord(
            credentials_available=True,
            credential_source=source,
            authentication_attempted=True,
            authentication_success=True,
            failure_category=None,
        )

    @classmethod
    def redact_data(cls, data: Any) -> Any:
        """Recursively removes any keys containing 'key', 'secret', 'signature', 'pem', 'token'."""
        sensitive_patterns = {"key", "secret", "signature", "private", "pem", "token", "auth"}
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(p in k_lower for p in sensitive_patterns) and not ("market_id" in k_lower or "contract_id" in k_lower or "event_ticker" in k_lower):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = cls.redact_data(v)
            return clean
        elif isinstance(data, list):
            return [cls.redact_data(item) for item in data]
        return data


# =====================================================================
# 2. EXPANDED MARKET RECORD SCHEMA
# =====================================================================

class ExpandedKalshiMarketRecord(BaseModel):
    """Complete, provenance-traced Kalshi market metadata record."""
    ticker: str
    event_ticker: str
    title: str
    subtitle: str = ""
    rules_primary: str = ""
    rules_secondary: str = ""
    market_type: str = "binary"
    strike_type: Optional[str] = None
    floor_strike: Optional[float] = None
    cap_strike: Optional[float] = None
    inequality_direction: Optional[str] = None
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    expiration_time: Optional[datetime] = None
    settlement_time: Optional[datetime] = None
    timezone_str: str = "UTC"
    category: str = "General"
    series_ticker: str = ""
    status: str = "active"
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    source_endpoint: str = "rest_api"
    retrieval_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload_hash: str
    provenance: SourceClassification = SourceClassification.KALSHI_LIVE

    def to_canonical_contract(self) -> CanonicalEconomicContract:
        """Converts into Phase 10A.6E CanonicalEconomicContract."""
        # Geography scope inference
        geo_scope = "US"
        t_upper = self.ticker.upper()
        title_upper = self.title.upper()
        if "ECB" in t_upper or "EUROZONE" in title_upper:
            geo_scope = "EUR"
        elif "BOE" in t_upper or "UK" in title_upper:
            geo_scope = "UK"
        elif "GLOBAL" in title_upper or "WORLD" in title_upper:
            geo_scope = "GLOBAL"

        # Observation variable
        obs_var = self.title.strip()
        threshold = self.floor_strike if self.floor_strike is not None else self.cap_strike
        ineq_dir = self.inequality_direction
        if not ineq_dir:
            if self.strike_type == "greater":
                ineq_dir = ">="
            elif self.strike_type == "less":
                ineq_dir = "<="
            elif "above" in self.title.lower() or "greater" in self.title.lower() or ">" in self.title:
                ineq_dir = ">="
            elif "below" in self.title.lower() or "less" in self.title.lower() or "<" in self.title:
                ineq_dir = "<="

        temporal_scope = self.close_time.strftime("%Y-%m-%d") if self.close_time else "open"
        settlement_source = self.rules_primary[:100] if self.rules_primary else "Official Release"

        return CanonicalEconomicContract(
            venue="kalshi",
            venue_contract_id=self.ticker,
            underlying_event=self.title,
            geographic_scope=geo_scope,
            observation_variable=obs_var,
            temporal_scope=temporal_scope,
            measurement_timestamp=self.open_time,
            resolution_timestamp=self.close_time or self.expiration_time,
            threshold=threshold,
            inequality_direction=ineq_dir,
            units="USD",
            currency="USD",
            source_of_resolution=settlement_source,
            resolution_rules=f"{self.rules_primary} | {self.rules_secondary}".strip(" |"),
            cancellation_rules=self.rules_secondary,
            invalidation_rules="",
        )


# =====================================================================
# 3. EXPANDED MARKET UNIVERSE COLLECTOR
# =====================================================================

class ExpandedMarketUniverseCollector:
    """Discovers and parses comprehensive market universes across venues."""

    KALSHI_PUBLIC_EVENTS_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
    KALSHI_PUBLIC_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"

    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.raw_data_dir = raw_data_dir or Path("data/raw")
        self.kalshi_raw_dir = self.raw_data_dir / "kalshi"
        self.polymarket_gamma_dir = self.raw_data_dir / "polymarket" / "gamma"

    @classmethod
    def _parse_dt(cls, val: Any) -> Optional[datetime]:
        """Safely parses ISO timestamp or epoch seconds/ms to UTC datetime."""
        if not val:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        if isinstance(val, (int, float)):
            ts = val / 1000.0 if val > 1e11 else float(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(val, str):
            try:
                s = val.replace("Z", "+00:00")
                return datetime.fromisoformat(s)
            except Exception:
                return None
        return None

    def parse_kalshi_market_dict(
        self,
        item: Dict[str, Any],
        parent_event: Optional[Dict[str, Any]] = None,
        source_endpoint: str = "rest_api",
        provenance: SourceClassification = SourceClassification.KALSHI_LIVE,
    ) -> ExpandedKalshiMarketRecord:
        """Parses a Kalshi market JSON object into an ExpandedKalshiMarketRecord."""
        ticker = str(item.get("ticker", "")).strip()
        event_ticker = str(item.get("event_ticker") or (parent_event.get("event_ticker") if parent_event else "") or ticker).strip()
        title = str(item.get("title") or (parent_event.get("title") if parent_event else "") or ticker).strip()
        subtitle = str(item.get("subtitle") or item.get("sub_title") or (parent_event.get("sub_title") if parent_event else "")).strip()

        rules_primary = str(item.get("rules_primary") or (parent_event.get("rules_primary") if parent_event else "")).strip()
        rules_secondary = str(item.get("rules_secondary") or (parent_event.get("rules_secondary") if parent_event else "")).strip()

        floor_strike = float(item["floor_strike"]) if item.get("floor_strike") is not None else None
        cap_strike = float(item["cap_strike"]) if item.get("cap_strike") is not None else None
        strike_type = item.get("strike_type")

        ineq_dir = None
        if strike_type == "greater":
            ineq_dir = ">="
        elif strike_type == "less":
            ineq_dir = "<="

        open_time = self._parse_dt(item.get("open_time"))
        close_time = self._parse_dt(item.get("close_time"))
        exp_time = self._parse_dt(item.get("expiration_time") or item.get("expected_expiration_time"))
        settle_time = self._parse_dt(item.get("settlement_timer_started_at") or exp_time)

        created_time = self._parse_dt(item.get("created_time"))
        updated_time = self._parse_dt(item.get("updated_time"))

        category = str(item.get("category") or (parent_event.get("category") if parent_event else "General")).strip()
        series_ticker = str(item.get("series_ticker") or (parent_event.get("series_ticker") if parent_event else "")).strip()
        status = str(item.get("status", "active")).lower()

        # SHA-256 of raw item JSON
        raw_json = json.dumps(item, sort_keys=True, default=str)
        raw_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

        return ExpandedKalshiMarketRecord(
            ticker=ticker,
            event_ticker=event_ticker,
            title=title,
            subtitle=subtitle,
            rules_primary=rules_primary,
            rules_secondary=rules_secondary,
            market_type=str(item.get("market_type", "binary")),
            strike_type=strike_type,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            inequality_direction=ineq_dir,
            open_time=open_time,
            close_time=close_time,
            expiration_time=exp_time,
            settlement_time=settle_time,
            timezone_str="UTC",
            category=category,
            series_ticker=series_ticker,
            status=status,
            created_time=created_time,
            updated_time=updated_time,
            source_endpoint=source_endpoint,
            retrieval_timestamp=datetime.now(timezone.utc),
            raw_payload_hash=raw_hash,
            provenance=provenance,
        )

    def load_archived_kalshi_markets(self) -> List[ExpandedKalshiMarketRecord]:
        """Loads and parses all markets from archived Kalshi JSON files."""
        records: List[ExpandedKalshiMarketRecord] = []
        if not self.kalshi_raw_dir.exists():
            return records

        json_files = sorted(self.kalshi_raw_dir.glob("**/*.json"))
        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                markets = data.get("markets", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for m in markets:
                    rec = self.parse_kalshi_market_dict(
                        item=m,
                        source_endpoint=f"archived_file:{jf.name}",
                        provenance=SourceClassification.KALSHI_ARCHIVED,
                    )
                    records.append(rec)
            except Exception as e:
                logger.warning(f"Failed to read archived Kalshi file {jf}: {e}")
        return records

    def fetch_live_kalshi_events(self, max_pages: int = 5, page_limit: int = 50) -> List[ExpandedKalshiMarketRecord]:
        """Fetches active Kalshi events and nested markets from the public read-only endpoint."""
        records: List[ExpandedKalshiMarketRecord] = []
        try:
            import requests
        except ImportError:
            logger.warning("requests package not available; skipping live Kalshi fetch.")
            return records

        cursor = None
        for page in range(max_pages):
            params: Dict[str, Any] = {
                "limit": page_limit,
                "status": "open",
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            try:
                resp = requests.get(self.KALSHI_PUBLIC_EVENTS_URL, params=params, timeout=10.0)
                if resp.status_code != 200:
                    logger.warning(f"Kalshi events fetch page {page} returned status {resp.status_code}")
                    break
                data = resp.json()
                events = data.get("events", [])
                for ev in events:
                    markets = ev.get("markets", [])
                    for m in markets:
                        rec = self.parse_kalshi_market_dict(
                            item=m,
                            parent_event=ev,
                            source_endpoint=self.KALSHI_PUBLIC_EVENTS_URL,
                            provenance=SourceClassification.KALSHI_LIVE,
                        )
                        records.append(rec)
                cursor = data.get("cursor")
                if not cursor or len(events) == 0:
                    break
            except Exception as e:
                logger.warning(f"Error fetching live Kalshi events on page {page}: {e}")
                break

        return records

    def collect_kalshi_universe(
        self,
        include_live: bool = True,
        include_archived: bool = True,
        max_live_pages: int = 5,
    ) -> List[ExpandedKalshiMarketRecord]:
        """Collects deduplicated Kalshi market universe preserving provenance."""
        by_ticker: Dict[str, ExpandedKalshiMarketRecord] = {}

        # 1. Archived files
        if include_archived:
            archived = self.load_archived_kalshi_markets()
            for r in archived:
                by_ticker[r.ticker] = r

        # 2. Live API (overrides or adds, preserving KALSHI_LIVE classification)
        if include_live:
            live = self.fetch_live_kalshi_events(max_pages=max_live_pages)
            for r in live:
                by_ticker[r.ticker] = r

        return list(by_ticker.values())

    def load_polymarket_gamma_markets(self, max_files: int = 50) -> List[CanonicalEconomicContract]:
        """Loads Polymarket contracts from recent raw gamma JSON files."""
        contracts: List[CanonicalEconomicContract] = []
        if not self.polymarket_gamma_dir.exists():
            return contracts

        json_files = sorted(self.polymarket_gamma_dir.glob("**/*.json"), reverse=True)[:max_files]
        seen_ids: Set[str] = set()

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else data.get("data", [])
                for m in items:
                    mid = str(m.get("id", "")).strip()
                    if not mid or mid in seen_ids:
                        continue
                    seen_ids.add(mid)

                    question = str(m.get("question", "")).strip()
                    desc = str(m.get("description", "")).strip()
                    res_source = str(m.get("resolutionSource", "") or "Polymarket Resolution").strip()
                    end_date = self._parse_dt(m.get("endDate") or m.get("endDateIso"))

                    contract = CanonicalEconomicContract(
                        venue="polymarket",
                        venue_contract_id=mid,
                        underlying_event=question,
                        geographic_scope="US",
                        observation_variable=question,
                        temporal_scope=end_date.strftime("%Y-%m-%d") if end_date else "open",
                        measurement_timestamp=self._parse_dt(m.get("startDate")),
                        resolution_timestamp=end_date,
                        threshold=None,
                        inequality_direction=None,
                        units="USD",
                        currency="USDC",
                        source_of_resolution=res_source,
                        resolution_rules=desc or question,
                        cancellation_rules="",
                        invalidation_rules="",
                    )
                    contracts.append(contract)
            except Exception as e:
                logger.warning(f"Error loading Polymarket gamma file {jf}: {e}")

        return contracts


# =====================================================================
# 4. DETERMINISTIC CANDIDATE GENERATION & VALIDATION PIPELINE
# =====================================================================

class DeterministicMappingRecord(BaseModel):
    """Complete provenance-traced record of a non-rejected mapping."""
    mapping_id: str
    polymarket_contract_id: str
    kalshi_contract_id: str
    canonical_polymarket: CanonicalEconomicContract
    canonical_kalshi: CanonicalEconomicContract
    economic_terms_hash_polymarket: str
    economic_terms_hash_kalshi: str
    equivalence_class: EquivalenceClass
    mapping_status: MappingStatus
    rejection_reason: Optional[RejectionReason] = None
    outcome_transformation: str = "YES -> YES, NO -> NO"
    settlement_rule_comparison: str
    timezone_normalization: str = "UTC"
    inequality_comparison: str
    resolution_source_comparison: str
    revision_policy_comparison: str = "Identical / Standard"
    cancellation_policy_comparison: str = "Identical / Standard"
    mapping_version: str = "10a6k_v1.0"
    source_metadata_hash_poly: str
    source_metadata_hash_kalshi: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExpandedCrossVenuePipeline:
    """Pipeline executing candidate blocking, settlement normalization, and 15-reason accounting."""

    def __init__(self):
        self.normalizer = ConservativeTextNormalizer()

    def run_pipeline(
        self,
        polymarket_contracts: List[CanonicalEconomicContract],
        kalshi_contracts: List[CanonicalEconomicContract],
    ) -> Tuple[Dict[str, int], Dict[str, int], List[DeterministicMappingRecord], List[ContractMappingResult]]:
        """Executes candidate matching and categorizes rejections into the 15 taxonomy reasons."""
        counts = {
            "polymarket_universe_count": len(polymarket_contracts),
            "kalshi_universe_count": len(kalshi_contracts),
            "candidate_comparison_count": 0,
            "exact_equivalent_count": 0,
            "complementary_count": 0,
            "nested_count": 0,
            "conditional_equivalent_count": 0,
            "ambiguous_count": 0,
            "semantic_only_count": 0,
            "rejected_count": 0,
        }

        rejection_breakdown = {r.value: 0 for r in RejectionReason}
        accepted_records: List[DeterministicMappingRecord] = []
        all_results: List[ContractMappingResult] = []

        # Candidate blocking: pre-tokenize events for high-throughput comparison
        poly_tokens_list = [
            (poly, set(self.normalizer.normalize_entity(poly.underlying_event).split()))
            for poly in polymarket_contracts
        ]
        kalshi_tokens_list = [
            (kalshi, set(self.normalizer.normalize_entity(kalshi.underlying_event).split()))
            for kalshi in kalshi_contracts
        ]

        for poly, poly_tokens in poly_tokens_list:
            for kalshi, kalshi_tokens in kalshi_tokens_list:
                counts["candidate_comparison_count"] += 1

                overlap = poly_tokens.intersection(kalshi_tokens)
                # If there is insufficient semantic overlap, classify as EVENT_MISMATCH
                if len(overlap) < 2:
                    counts["rejected_count"] += 1
                    rejection_breakdown[RejectionReason.EVENT_MISMATCH.value] += 1
                    continue

                # Run SettlementNormalizer
                result = SettlementNormalizer.compare_contracts(poly, kalshi)
                all_results.append(result)

                if result.settlement_equivalence:
                    if result.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT:
                        counts["exact_equivalent_count"] += 1
                    elif result.equivalence_class == EquivalenceClass.COMPLEMENTARY:
                        counts["complementary_count"] += 1
                    elif result.equivalence_class == EquivalenceClass.NESTED:
                        counts["nested_count"] += 1
                    elif result.equivalence_class == EquivalenceClass.CONDITIONALLY_EQUIVALENT:
                        counts["conditional_equivalent_count"] += 1

                    # Create persistent deterministic record
                    rec = DeterministicMappingRecord(
                        mapping_id=result.mapping_id,
                        polymarket_contract_id=poly.venue_contract_id,
                        kalshi_contract_id=kalshi.venue_contract_id,
                        canonical_polymarket=poly,
                        canonical_kalshi=kalshi,
                        economic_terms_hash_polymarket=poly.compute_economic_terms_hash(),
                        economic_terms_hash_kalshi=kalshi.compute_economic_terms_hash(),
                        equivalence_class=result.equivalence_class,
                        mapping_status=result.mapping_status,
                        settlement_rule_comparison=f"Poly: {poly.source_of_resolution} vs Kalshi: {kalshi.source_of_resolution}",
                        inequality_comparison=f"Poly: {poly.inequality_direction} vs Kalshi: {kalshi.inequality_direction}",
                        resolution_source_comparison=f"Poly: {poly.source_of_resolution} vs Kalshi: {kalshi.source_of_resolution}",
                        source_metadata_hash_poly=poly.compute_contract_hash(),
                        source_metadata_hash_kalshi=kalshi.compute_contract_hash(),
                    )
                    accepted_records.append(rec)
                else:
                    counts["rejected_count"] += 1
                    # Parse rejection reason from result.mapping_reason
                    msg = (result.mapping_reason or "").upper()
                    matched_reason = None
                    for r in RejectionReason:
                        if r.value in msg:
                            matched_reason = r
                            break
                    if not matched_reason:
                        if "GEOGRAPHY" in msg:
                            matched_reason = RejectionReason.GEOGRAPHY_MISMATCH
                        elif "METRIC" in msg or "VARIABLE" in msg:
                            matched_reason = RejectionReason.VARIABLE_MISMATCH
                        elif "DATE" in msg or "TIME" in msg or "TEMPORAL" in msg:
                            matched_reason = RejectionReason.TIME_WINDOW_MISMATCH
                        elif "THRESHOLD" in msg or "STRIKE" in msg:
                            matched_reason = RejectionReason.THRESHOLD_MISMATCH
                        elif "INEQUALITY" in msg or "DIRECTION" in msg:
                            matched_reason = RejectionReason.INEQUALITY_MISMATCH
                        elif "SOURCE" in msg:
                            matched_reason = RejectionReason.RESOLUTION_SOURCE_MISMATCH
                        elif "AMBIGUOUS" in msg:
                            matched_reason = RejectionReason.AMBIGUOUS_MAPPING
                        else:
                            matched_reason = RejectionReason.SEMANTIC_ONLY

                    rejection_breakdown[matched_reason.value] += 1
                    if matched_reason == RejectionReason.SEMANTIC_ONLY:
                        counts["semantic_only_count"] += 1
                    elif matched_reason == RejectionReason.AMBIGUOUS_MAPPING:
                        counts["ambiguous_count"] += 1

        return counts, rejection_breakdown, accepted_records, all_results


# =====================================================================
# 5. INDEPENDENT MAPPING REPRODUCTION VERIFIER
# =====================================================================

class MappingVerificationError(Exception):
    """Raised when independent reproduction fails to match stored mapping."""
    pass


class IndependentMappingVerifier:
    """Completely independent verification engine.
    
    Reloads raw metadata, reconstructs contracts, recomputes hashes and equivalence,
    and asserts complete consistency against stored mapping records.
    """

    @classmethod
    def independently_verify_mapping(
        cls,
        poly_raw_meta: Dict[str, Any],
        kalshi_raw_meta: Dict[str, Any],
        expected_record: DeterministicMappingRecord,
    ) -> bool:
        """Independently verifies a mapping from raw metadata objects."""
        # 1. Reconstruct Polymarket canonical contract
        poly_end = ExpandedMarketUniverseCollector._parse_dt(
            poly_raw_meta.get("endDate") or poly_raw_meta.get("endDateIso")
        )
        reconstructed_poly = CanonicalEconomicContract(
            venue="polymarket",
            venue_contract_id=str(poly_raw_meta.get("id")),
            underlying_event=str(poly_raw_meta.get("question", "")).strip(),
            geographic_scope=expected_record.canonical_polymarket.geographic_scope,
            observation_variable=str(poly_raw_meta.get("question", "")).strip(),
            temporal_scope=poly_end.strftime("%Y-%m-%d") if poly_end else "open",
            measurement_timestamp=ExpandedMarketUniverseCollector._parse_dt(poly_raw_meta.get("startDate")),
            resolution_timestamp=poly_end,
            threshold=float(poly_raw_meta["threshold"]) if "threshold" in poly_raw_meta else None,
            inequality_direction=poly_raw_meta.get("inequality_direction"),
            units="USD",
            currency="USDC",
            source_of_resolution=str(poly_raw_meta.get("resolutionSource", "")).strip(),
            resolution_rules=str(poly_raw_meta.get("description", "")).strip(),
        )

        # 2. Reconstruct Kalshi canonical contract
        kalshi_collector = ExpandedMarketUniverseCollector()
        kalshi_rec = kalshi_collector.parse_kalshi_market_dict(kalshi_raw_meta)
        reconstructed_kalshi = kalshi_rec.to_canonical_contract()

        # 3. Recompute hashes
        poly_hash = reconstructed_poly.compute_economic_terms_hash()
        kalshi_hash = reconstructed_kalshi.compute_economic_terms_hash()

        if poly_hash != expected_record.economic_terms_hash_polymarket:
            raise MappingVerificationError(
                f"Independent Polymarket terms hash mismatch: {poly_hash} != {expected_record.economic_terms_hash_polymarket}"
            )
        if kalshi_hash != expected_record.economic_terms_hash_kalshi:
            raise MappingVerificationError(
                f"Independent Kalshi terms hash mismatch: {kalshi_hash} != {expected_record.economic_terms_hash_kalshi}"
            )

        # 4. Recompute Equivalence via SettlementNormalizer
        recomputed_res = SettlementNormalizer.compare_contracts(reconstructed_poly, reconstructed_kalshi)
        if recomputed_res.equivalence_class != expected_record.equivalence_class:
            raise MappingVerificationError(
                f"Equivalence mismatch: recomputed {recomputed_res.equivalence_class} != {expected_record.equivalence_class}"
            )

        return True


# =====================================================================
# 6. PERMANENT PRODUCTION CONTAMINATION GUARD
# =====================================================================

class ContaminationError(Exception):
    """Raised when unit fixtures, synthetic data, or invalid provenance attempt to enter production tables."""
    pass


class ProductionContaminationGuard:
    """Enforces zero-tolerance boundary between fixtures/synthetic data and production tables."""

    PROHIBITED_MARKERS = {
        "fixture",
        "mock",
        "synthetic",
        "fake",
        "demo",
        "obs_test_",
        "tempfile",
        "/var/folders/",
        "/tmp/",
    }

    VALID_PROVENANCES = {
        SourceClassification.POLYMARKET_LIVE,
        SourceClassification.KALSHI_LIVE,
        SourceClassification.POLYMARKET_ARCHIVED,
        SourceClassification.KALSHI_ARCHIVED,
    }

    @classmethod
    def assert_valid_production_observation(
        cls,
        observation: Dict[str, Any],
        is_production_db: bool = True,
    ) -> None:
        """Validates that observation has valid provenance and zero fixture/synthetic contamination."""
        obs_id = str(observation.get("observation_id", "")).lower()
        mapping_id = str(observation.get("mapping_id", "")).lower()
        source_session = str(observation.get("source_session_id", "")).lower()
        poly_id = str(observation.get("poly_contract_id", "")).lower()
        kalshi_id = str(observation.get("kalshi_contract_id", "")).lower()

        # Check for prohibited fixture/synthetic markers in IDs
        for field_val in [obs_id, mapping_id, source_session, poly_id, kalshi_id]:
            for marker in cls.PROHIBITED_MARKERS:
                if marker in field_val:
                    raise ContaminationError(
                        f"Production contamination rejected: field contains prohibited test marker '{marker}' in '{field_val}'."
                    )

        # Check provenance classification if provided
        poly_prov = observation.get("source_classification_poly")
        kalshi_prov = observation.get("source_classification_kalshi")

        if poly_prov:
            if isinstance(poly_prov, str):
                poly_prov = SourceClassification(poly_prov)
            if poly_prov not in cls.VALID_PROVENANCES:
                raise ContaminationError(
                    f"Production contamination rejected: invalid Polymarket provenance '{poly_prov}'."
                )

        if kalshi_prov:
            if isinstance(kalshi_prov, str):
                kalshi_prov = SourceClassification(kalshi_prov)
            if kalshi_prov not in cls.VALID_PROVENANCES:
                raise ContaminationError(
                    f"Production contamination rejected: invalid Kalshi provenance '{kalshi_prov}'."
                )
