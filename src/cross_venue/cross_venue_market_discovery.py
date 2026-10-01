"""Deterministic Market Pair Discovery & Equivalence Validation Pipeline.

Phase 10A.6H:
Builds the deterministic discovery pipeline that maps Polymarket and Kalshi market universes
into canonical economic contracts, generates candidates via deterministic blocking, and passes
them through SettlementNormalizer for definitive classification.

CRITICAL RULES:
1. Mapping is strictly INDEPENDENT OF PRICE, SPREAD, LIQUIDITY, VOLUME, OR P&L.
2. AI may propose hypotheses, but deterministic validation remains authoritative.
3. Every synonym dictionary and configuration is versioned and SHA-256 hashed.
4. Retains full provenance and temporal versioning for every mapping.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Set

from pydantic import BaseModel, Field

from src.cross_venue.schema import (
    CanonicalEconomicContract,
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
)
from src.cross_venue.settlement_normalizer import SettlementNormalizer

logger = logging.getLogger(__name__)


# =====================================================================
# 1. TAXONOMIES & ENUMS
# =====================================================================

class RejectionReason(str, Enum):
    """Explicit machine-readable rejection reasons (Phase 10A.6H Section 9)."""
    EVENT_MISMATCH = "EVENT_MISMATCH"
    VARIABLE_MISMATCH = "VARIABLE_MISMATCH"
    THRESHOLD_MISMATCH = "THRESHOLD_MISMATCH"
    INEQUALITY_MISMATCH = "INEQUALITY_MISMATCH"
    TIME_WINDOW_MISMATCH = "TIME_WINDOW_MISMATCH"
    TIMEZONE_MISMATCH = "TIMEZONE_MISMATCH"
    GEOGRAPHY_MISMATCH = "GEOGRAPHY_MISMATCH"
    RESOLUTION_SOURCE_MISMATCH = "RESOLUTION_SOURCE_MISMATCH"
    REVISION_POLICY_MISMATCH = "REVISION_POLICY_MISMATCH"
    CANCELLATION_POLICY_MISMATCH = "CANCELLATION_POLICY_MISMATCH"
    OUTCOME_MAPPING_MISMATCH = "OUTCOME_MAPPING_MISMATCH"
    MISSING_REQUIRED_METADATA = "MISSING_REQUIRED_METADATA"
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    DUPLICATE_CONTRACT = "DUPLICATE_CONTRACT"


class CandidateFilterStatus(str, Enum):
    """Status of candidate generation before settlement validation."""
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ContractCardinality(str, Enum):
    """Mapping cardinality structure between venues."""
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"
    DUPLICATE = "DUPLICATE"


class ContractStatus(str, Enum):
    """Operational temporal status of a mapping version."""
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


# =====================================================================
# 2. CONFIGURATION & VERSIONED SYNONYM DICTIONARY
# =====================================================================

DEFAULT_SYNONYMS: Dict[str, str] = {
    # Monetary / Macro Entities
    "fed": "federal reserve",
    "the fed": "federal reserve",
    "federal reserve": "federal reserve",
    "fomc": "federal reserve",
    "bls": "bureau of labor statistics",
    "bureau of labor statistics": "bureau of labor statistics",
    "cpi": "consumer price index",
    "consumer price index": "consumer price index",
    "core cpi": "core consumer price index",
    "nfp": "nonfarm payrolls",
    "nonfarm payrolls": "nonfarm payrolls",
    "gdp": "gross domestic product",
    "gross domestic product": "gross domestic product",
    # Crypto / Assets
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
}

DEFAULT_GEO_ALIASES: Dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "us": "US",
    "global": "GLOBAL",
    "worldwide": "GLOBAL",
    "world": "GLOBAL",
    "united kingdom": "UK",
    "uk": "UK",
    "eurozone": "EUR",
    "eu": "EUR",
}

DEFAULT_UNIT_ALIASES: Dict[str, str] = {
    "usd": "USD",
    "dollars": "USD",
    "$": "USD",
    "percent": "PERCENT",
    "%": "PERCENT",
    "pct": "PERCENT",
    "bps": "BPS",
    "basis points": "BPS",
}


class DiscoveryConfig(BaseModel):
    """Immutable, versioned configuration for deterministic market discovery."""
    version: str = "1.0.0"
    synonym_dict_version: str = "1.0.0"
    synonyms: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SYNONYMS))
    geo_aliases: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_GEO_ALIASES))
    unit_aliases: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_UNIT_ALIASES))
    max_time_divergence_hours: float = 1.0
    config_hash: str = Field(default="")

    def __init__(self, **data):
        super().__init__(**data)
        if not self.config_hash:
            self.config_hash = self.compute_config_hash()

    def compute_config_hash(self) -> str:
        """Deterministic SHA-256 hash of entire discovery configuration."""
        payload = {
            "version": self.version,
            "synonym_dict_version": self.synonym_dict_version,
            "synonyms": dict(sorted(self.synonyms.items())),
            "geo_aliases": dict(sorted(self.geo_aliases.items())),
            "unit_aliases": dict(sorted(self.unit_aliases.items())),
            "max_time_divergence_hours": self.max_time_divergence_hours,
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def compute_synonym_dict_hash(self) -> str:
        """Deterministic SHA-256 hash of the synonym dictionary alone."""
        payload = {
            "synonym_dict_version": self.synonym_dict_version,
            "synonyms": dict(sorted(self.synonyms.items())),
            "geo_aliases": dict(sorted(self.geo_aliases.items())),
            "unit_aliases": dict(sorted(self.unit_aliases.items())),
        }
        raw_json = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


# =====================================================================
# 3. CONSERVATIVE TEXT NORMALIZER
# =====================================================================

class ConservativeTextNormalizer:
    """Deterministic, conservative text normalizer with zero LLM/embedding dependency."""

    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DiscoveryConfig()

    def normalize_text(self, text: str) -> str:
        """Standardizes case and collapses punctuation / whitespace."""
        if not text:
            return ""
        # Lowercase
        t = text.lower().strip()
        # Remove non-alphanumeric except common math/date symbols
        t = re.sub(r"[^\w\s\.\-\%\$\>\<\=\/]", " ", t)
        # Collapse whitespace
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def normalize_entity(self, text: str) -> str:
        """Maps entity/concept terms using the versioned synonym dictionary."""
        norm = self.normalize_text(text)
        for term, canonical in self.config.synonyms.items():
            pattern = r"\b" + re.escape(term) + r"\b"
            norm = re.sub(pattern, canonical, norm)
        return norm

    def normalize_geography(self, geo_raw: str) -> str:
        """Standardizes geographic jurisdiction code."""
        g = self.normalize_text(geo_raw)
        for alias, canon in self.config.geo_aliases.items():
            if alias == g or alias in g.split():
                return canon
        return geo_raw.strip().upper() if geo_raw else "GLOBAL"

    def normalize_unit(self, unit_raw: str) -> str:
        """Standardizes measurement unit."""
        u = self.normalize_text(unit_raw)
        for alias, canon in self.config.unit_aliases.items():
            if alias == u or alias in u.split():
                return canon
        return unit_raw.strip().upper() if unit_raw else "USD"

    def extract_threshold_and_direction(self, text: str) -> Tuple[Optional[float], Optional[str]]:
        """Deterministically extracts numeric threshold and inequality direction if present."""
        norm = self.normalize_text(text)
        
        # Check directions
        direction = None
        if ">=" in norm or "at least" in norm or "or higher" in norm or "or more" in norm:
            direction = ">="
        elif "<=" in norm or "at most" in norm or "or lower" in norm or "or less" in norm:
            direction = "<="
        elif ">" in norm or "above" in norm or "greater than" in norm or "higher than" in norm:
            direction = ">"
        elif "<" in norm or "below" in norm or "under" in norm or "less than" in norm or "lower than" in norm:
            direction = "<"
        elif "==" in norm or "equal to" in norm or "exactly" in norm:
            direction = "=="

        # Match number
        match = re.search(r"[-+]?\d*\.?\d+", norm)
        threshold = float(match.group(0)) if match else None

        return threshold, direction


# =====================================================================
# 4. CANONICAL ADAPTERS (POLYMARKET & KALSHI)
# =====================================================================

def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return _ensure_utc(val)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val / 1000.0 if val > 1e11 else val, tz=timezone.utc)
    if isinstance(val, str):
        try:
            return _ensure_utc(datetime.fromisoformat(val.replace("Z", "+00:00")))
        except Exception:
            return None
    return None


class PolymarketCanonicalAdapter:
    """Deterministic adapter converting Polymarket market metadata into CanonicalEconomicContract."""

    def __init__(self, normalizer: Optional[ConservativeTextNormalizer] = None):
        self.normalizer = normalizer or ConservativeTextNormalizer()

    def adapt_market(
        self,
        raw: Dict[str, Any],
        token_index: int = 0,
        metadata_version: str = "1.0"
    ) -> CanonicalEconomicContract:
        """Converts raw Polymarket metadata dictionary into CanonicalEconomicContract."""
        market_id = str(raw.get("id") or raw.get("market_id") or "").strip()
        condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip()
        
        # Token IDs
        clob_tokens = raw.get("clobTokenIds") or raw.get("clob_token_ids") or []
        if isinstance(clob_tokens, str):
            try:
                clob_tokens = json.loads(clob_tokens)
            except Exception:
                clob_tokens = [clob_tokens]
        token_id = clob_tokens[token_index] if clob_tokens and len(clob_tokens) > token_index else market_id

        # Question / Title
        title = str(raw.get("question") or raw.get("title") or "").strip()
        desc = str(raw.get("description") or "").strip()
        
        # Event ID & resolution source
        events = raw.get("events") or []
        event_obj = events[0] if isinstance(events, list) and events else {}
        resolution_source = str(
            raw.get("resolutionSource") or
            raw.get("resolution_source") or
            event_obj.get("resolutionSource") or
            ""
        ).strip()
        
        # Open / Close / Resolution Timestamps
        open_time = _parse_iso_dt(raw.get("startDate") or raw.get("open_time") or raw.get("createdAt"))
        close_time = _parse_iso_dt(raw.get("endDate") or raw.get("close_time"))
        res_time = _parse_iso_dt(raw.get("endDate") or raw.get("resolution_time") or close_time)

        # Geographic scope
        geo_scope = self.normalizer.normalize_geography(raw.get("geographic_scope") or "GLOBAL")
        if "us" in title.lower().split() or "u.s." in title.lower() or "federal" in title.lower():
            geo_scope = "US"

        # Observation variable
        obs_var = self.normalizer.normalize_entity(title)
        
        # Threshold & direction
        thresh, ineq = self.normalizer.extract_threshold_and_direction(title)
        if raw.get("threshold") is not None:
            try:
                thresh = float(raw["threshold"])
            except Exception:
                pass
        if raw.get("inequality_direction"):
            ineq = str(raw["inequality_direction"]).strip()

        temporal_scope = close_time.strftime("%Y-%m-%d") if close_time else "open"

        # Resolution & cancellation rules
        rules = desc or title
        cancellation_rules = str(raw.get("cancellation_rules") or "")
        invalidation_rules = str(raw.get("invalidation_rules") or "")
        if "cancelled" in desc.lower() or "postponed" in desc.lower() or "void" in desc.lower():
            cancellation_rules = desc

        # Raw metadata hash for provenance
        raw_clean = {k: v for k, v in raw.items() if not str(k).lower().startswith("price") and k not in ("outcomePrices", "volume", "liquidity")}
        raw_hash = hashlib.sha256(json.dumps(raw_clean, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        return CanonicalEconomicContract(
            venue="polymarket",
            venue_contract_id=f"{market_id}_{token_id}" if market_id != token_id else market_id,
            underlying_event=title,
            observation_variable=obs_var,
            geographic_scope=geo_scope,
            temporal_scope=temporal_scope,
            measurement_timestamp=None,
            resolution_timestamp=res_time,
            threshold=thresh,
            inequality_direction=ineq,
            strike_value=str(thresh) if thresh is not None else None,
            units=self.normalizer.normalize_unit(raw.get("units") or "USD"),
            currency="USDC",
            source_of_resolution=resolution_source or "Official Determination",
            resolution_rules=rules,
            cancellation_rules=cancellation_rules,
            invalidation_rules=invalidation_rules,
        )


class KalshiCanonicalAdapter:
    """Deterministic adapter converting Kalshi market metadata into CanonicalEconomicContract."""

    def __init__(self, normalizer: Optional[ConservativeTextNormalizer] = None):
        self.normalizer = normalizer or ConservativeTextNormalizer()

    def adapt_market(
        self,
        raw: Dict[str, Any],
        metadata_version: str = "1.0"
    ) -> CanonicalEconomicContract:
        """Converts raw Kalshi metadata dictionary into CanonicalEconomicContract."""
        ticker = str(raw.get("ticker") or raw.get("market_id") or "").strip()
        title = str(raw.get("title") or raw.get("subtitle") or "").strip()
        
        open_time = _parse_iso_dt(raw.get("open_time"))
        close_time = _parse_iso_dt(raw.get("close_time"))
        exp_time = _parse_iso_dt(raw.get("expiration_time") or raw.get("latest_expiration_time") or close_time)

        settlement_source = str(
            raw.get("settlement_source") or
            raw.get("rules_primary") or
            raw.get("source") or
            "Official Release"
        ).strip()
        
        rules = str(
            raw.get("rules_primary") or
            raw.get("resolution_rules") or
            raw.get("description") or
            title
        ).strip()

        # Thresholds
        floor_strike = float(raw["floor_strike"]) if raw.get("floor_strike") is not None else None
        cap_strike = float(raw["cap_strike"]) if raw.get("cap_strike") is not None else None
        thresh = floor_strike if floor_strike is not None else cap_strike

        # Inequality direction
        strike_type = str(raw.get("strike_type", "")).lower()
        ineq = None
        if strike_type == "greater":
            ineq = ">="
        elif strike_type == "less":
            ineq = "<="
        else:
            thresh_extracted, ineq_extracted = self.normalizer.extract_threshold_and_direction(title)
            if thresh is None:
                thresh = thresh_extracted
            ineq = ineq_extracted

        # Geography
        geo = "US"  # Kalshi default CFTC
        if "ECB" in ticker or "Eurozone" in title:
            geo = "EUR"
        elif "BOE" in ticker or "UK" in title:
            geo = "UK"
        elif raw.get("geography"):
            geo = self.normalizer.normalize_geography(raw["geography"])

        obs_var = self.normalizer.normalize_entity(title)
        temporal_scope = close_time.strftime("%Y-%m-%d") if close_time else "open"

        cancellation_rules = str(raw.get("cancellation_rules") or raw.get("rules_secondary") or "")
        invalidation_rules = str(raw.get("invalidation_rules") or "")

        raw_clean = {k: v for k, v in raw.items() if not str(k).lower().startswith("price") and k not in ("yes_bid_dollars", "yes_ask_dollars", "volume_fp", "liquidity_dollars")}
        raw_hash = hashlib.sha256(json.dumps(raw_clean, sort_keys=True, default=str).encode("utf-8")).hexdigest()

        return CanonicalEconomicContract(
            venue="kalshi",
            venue_contract_id=ticker,
            underlying_event=title,
            observation_variable=obs_var,
            geographic_scope=geo,
            temporal_scope=temporal_scope,
            measurement_timestamp=None,
            resolution_timestamp=exp_time,
            threshold=thresh,
            inequality_direction=ineq,
            strike_value=str(thresh) if thresh is not None else None,
            units=self.normalizer.normalize_unit(raw.get("units") or "USD"),
            currency="USD",
            source_of_resolution=settlement_source,
            resolution_rules=rules,
            cancellation_rules=cancellation_rules,
            invalidation_rules=invalidation_rules,
        )


# =====================================================================
# 5. CANDIDATE PAIR & PROVENANCE MODELS
# =====================================================================

class MarketCandidatePair(BaseModel):
    """Candidate pair generated through deterministic blocking and filtering."""
    candidate_id: str
    polymarket_id: str
    kalshi_id: str
    polymarket_contract: CanonicalEconomicContract
    kalshi_contract: CanonicalEconomicContract
    blocking_key: str
    filter_status: CandidateFilterStatus
    filter_rejection_reason: Optional[RejectionReason] = None
    rejection_detail: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MappingProvenance(BaseModel):
    """Deterministic provenance record for reproduction (Phase 10A.6H Section 10)."""
    mapping_id: str
    polymarket_market_id: str
    polymarket_token_id: str
    kalshi_market_id: str
    kalshi_contract_id: str
    canonical_contract_id: str
    normalization_version: str
    synonym_dict_hash: str
    poly_metadata_hash: str
    kalshi_metadata_hash: str
    equivalence_class: EquivalenceClass
    validation_reason: str
    validation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config_hash: str


class MappingVersionRecord(BaseModel):
    """Temporal validity and metadata version tracker (Phase 10A.6H Section 12)."""
    version_id: str
    mapping_id: str
    version_index: int = 1
    metadata_version: str = "1.0"
    mapping_start: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mapping_end: Optional[datetime] = None
    contract_status: ContractStatus = ContractStatus.ACTIVE
    invalidation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =====================================================================
# 6. MAPPING RELATIONSHIP GRAPH
# =====================================================================

class CrossVenueMappingGraph:
    """Represents the relationship graph: Polymarket <-> Canonical <-> Kalshi."""

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []

    def add_mapping(
        self,
        poly_id: str,
        kalshi_id: str,
        canonical_id: str,
        mapping_result: ContractMappingResult,
        provenance: MappingProvenance,
    ) -> None:
        """Adds nodes and linking edges into the relationship graph."""
        self.nodes[poly_id] = {"venue": "polymarket", "id": poly_id}
        self.nodes[kalshi_id] = {"venue": "kalshi", "id": kalshi_id}
        self.nodes[canonical_id] = {"venue": "canonical", "id": canonical_id}

        self.edges.append({
            "mapping_id": mapping_result.mapping_id,
            "polymarket_id": poly_id,
            "canonical_id": canonical_id,
            "kalshi_id": kalshi_id,
            "equivalence_class": mapping_result.equivalence_class,
            "settlement_equivalence": mapping_result.settlement_equivalence,
            "mapping_reason": mapping_result.mapping_reason,
            "provenance": provenance,
        })

    def get_exact_equivalent_edges(self) -> List[Dict[str, Any]]:
        return [e for e in self.edges if e["equivalence_class"] == EquivalenceClass.EXACT_EQUIVALENT]

    def get_complementary_edges(self) -> List[Dict[str, Any]]:
        return [e for e in self.edges if e["equivalence_class"] == EquivalenceClass.COMPLEMENTARY]

    def get_nested_edges(self) -> List[Dict[str, Any]]:
        return [e for e in self.edges if e["equivalence_class"] == EquivalenceClass.NESTED]

    def get_ambiguous_edges(self) -> List[Dict[str, Any]]:
        return [e for e in self.edges if e["equivalence_class"] in (EquivalenceClass.SEMANTIC_ONLY, EquivalenceClass.NON_EQUIVALENT)]

    def detect_duplicates(self, venue: str) -> List[Tuple[str, str, str]]:
        """Detects contracts on the same venue with identical canonical contract hashes."""
        seen: Dict[str, str] = {}
        duplicates: List[Tuple[str, str, str]] = []
        for node_id, data in self.nodes.items():
            if data.get("venue") == venue and "canonical_hash" in data:
                h = data["canonical_hash"]
                if h in seen:
                    duplicates.append((seen[h], node_id, h))
                else:
                    seen[h] = node_id
        return duplicates

    def get_cardinality(self) -> Dict[str, ContractCardinality]:
        """Calculates cardinality for each mapping."""
        poly_counts: Dict[str, int] = {}
        kalshi_counts: Dict[str, int] = {}
        for e in self.edges:
            p = e["polymarket_id"]
            k = e["kalshi_id"]
            poly_counts[p] = poly_counts.get(p, 0) + 1
            kalshi_counts[k] = kalshi_counts.get(k, 0) + 1

        cardinality_map: Dict[str, ContractCardinality] = {}
        for e in self.edges:
            m_id = e["mapping_id"]
            p = e["polymarket_id"]
            k = e["kalshi_id"]
            p_cnt = poly_counts[p]
            k_cnt = kalshi_counts[k]
            if p_cnt == 1 and k_cnt == 1:
                cardinality_map[m_id] = ContractCardinality.ONE_TO_ONE
            elif p_cnt > 1 and k_cnt == 1:
                cardinality_map[m_id] = ContractCardinality.ONE_TO_MANY
            elif p_cnt == 1 and k_cnt > 1:
                cardinality_map[m_id] = ContractCardinality.MANY_TO_ONE
            else:
                cardinality_map[m_id] = ContractCardinality.MANY_TO_MANY
        return cardinality_map


# =====================================================================
# 7. RUN SUMMARY
# =====================================================================

class DiscoveryRunSummary(BaseModel):
    """Execution summary of the deterministic market discovery funnel."""
    polymarket_universe_size: int
    kalshi_universe_size: int
    candidate_pairs_generated: int
    candidate_pairs_accepted: int
    candidate_pairs_rejected: int
    filter_rejections_by_reason: Dict[str, int]
    validation_count: int
    exact_equivalent_count: int
    complementary_count: int
    nested_count: int
    ambiguous_count: int
    rejected_count: int
    settlement_rejections_by_reason: Dict[str, int]
    config_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =====================================================================
# 8. DISCOVERY ENGINE COORDINATOR
# =====================================================================

class CrossVenueMarketDiscovery:
    """Deterministic discovery and equivalence validation coordinator."""

    def __init__(
        self,
        config: Optional[DiscoveryConfig] = None,
        db_store: Optional[Any] = None,
    ):
        self.config = config or DiscoveryConfig()
        self.normalizer = ConservativeTextNormalizer(self.config)
        self.poly_adapter = PolymarketCanonicalAdapter(self.normalizer)
        self.kalshi_adapter = KalshiCanonicalAdapter(self.normalizer)
        self.graph = CrossVenueMappingGraph()
        self.db_store = db_store
        self.version_tracker: Dict[str, MappingVersionRecord] = {}

    def generate_blocking_key(self, contract: CanonicalEconomicContract) -> str:
        """Deterministic blocking key for efficient candidate search."""
        geo = self.normalizer.normalize_geography(contract.geographic_scope)
        # Extract first 3 significant keywords of observation variable
        var_norm = self.normalizer.normalize_entity(contract.observation_variable)
        tokens = [t for t in var_norm.split() if len(t) > 2 and t not in ("the", "will", "and", "for")]
        keyword = "-".join(tokens[:2]) if tokens else "general"
        # Date bucket: YYYY-MM
        date_bucket = contract.temporal_scope[:7] if len(contract.temporal_scope) >= 7 else "any"
        return f"{geo}::{keyword}::{date_bucket}"

    def generate_candidates(
        self,
        poly_contracts: List[CanonicalEconomicContract],
        kalshi_contracts: List[CanonicalEconomicContract],
    ) -> List[MarketCandidatePair]:
        """Generates candidate pairs using deterministic blocking and strict metadata filters.
        
        PRICE INDEPENDENCE: Never accepts, reads, or checks prices or order books.
        """
        # 1. Build Index for Kalshi
        buckets: Dict[str, List[CanonicalEconomicContract]] = {}
        for k in kalshi_contracts:
            b_key = self.generate_blocking_key(k)
            buckets.setdefault(b_key, []).append(k)

        candidates: List[MarketCandidatePair] = []

        # 2. Evaluate Polymarket against buckets
        for p in poly_contracts:
            p_key = self.generate_blocking_key(p)
            matched_kalshi = buckets.get(p_key, [])
            
            # If no bucket match, evaluate candidate with filter rejection for visibility
            if not matched_kalshi:
                # Pair with first available Kalshi if any exists to record explicit rejection
                for k in kalshi_contracts[:1]:
                    cand_id = f"cand_{p.venue_contract_id}_{k.venue_contract_id}"
                    reason, detail = self._apply_candidate_filters(p, k)
                    candidates.append(MarketCandidatePair(
                        candidate_id=cand_id,
                        polymarket_id=p.venue_contract_id,
                        kalshi_id=k.venue_contract_id,
                        polymarket_contract=p,
                        kalshi_contract=k,
                        blocking_key=p_key,
                        filter_status=CandidateFilterStatus.REJECTED,
                        filter_rejection_reason=reason,
                        rejection_detail=detail,
                    ))
                continue

            for k in matched_kalshi:
                cand_id = f"cand_{p.venue_contract_id}_{k.venue_contract_id}"
                reason, detail = self._apply_candidate_filters(p, k)
                if reason is None:
                    candidates.append(MarketCandidatePair(
                        candidate_id=cand_id,
                        polymarket_id=p.venue_contract_id,
                        kalshi_id=k.venue_contract_id,
                        polymarket_contract=p,
                        kalshi_contract=k,
                        blocking_key=p_key,
                        filter_status=CandidateFilterStatus.ACCEPTED,
                        filter_rejection_reason=None,
                        rejection_detail=None,
                    ))
                else:
                    candidates.append(MarketCandidatePair(
                        candidate_id=cand_id,
                        polymarket_id=p.venue_contract_id,
                        kalshi_id=k.venue_contract_id,
                        polymarket_contract=p,
                        kalshi_contract=k,
                        blocking_key=p_key,
                        filter_status=CandidateFilterStatus.REJECTED,
                        filter_rejection_reason=reason,
                        rejection_detail=detail,
                    ))

        return candidates

    def _apply_candidate_filters(
        self,
        poly: CanonicalEconomicContract,
        kalshi: CanonicalEconomicContract
    ) -> Tuple[Optional[RejectionReason], Optional[str]]:
        """Filters candidate pairs based purely on deterministic metadata compatibility."""
        # 1. Basic Metadata Presence
        if not poly.underlying_event or not kalshi.underlying_event or not poly.observation_variable or not kalshi.observation_variable:
            return RejectionReason.MISSING_REQUIRED_METADATA, "Missing underlying event or observation variable"

        # 2. Geographic Compatibility
        poly_geo = self.normalizer.normalize_geography(poly.geographic_scope)
        kalshi_geo = self.normalizer.normalize_geography(kalshi.geographic_scope)
        if poly_geo != kalshi_geo:
            return RejectionReason.GEOGRAPHY_MISMATCH, f"Geography {poly_geo} != {kalshi_geo}"

        # 3. Observation Variable / Metric Compatibility
        p_var = self.normalizer.normalize_entity(poly.observation_variable)
        k_var = self.normalizer.normalize_entity(kalshi.observation_variable)
        if p_var != k_var and not (p_var in k_var or k_var in p_var):
            return RejectionReason.VARIABLE_MISMATCH, f"Metrics diverge: '{p_var}' vs '{k_var}'"

        # 4. Temporal Scope Overlap
        if poly.temporal_scope.strip().lower() != kalshi.temporal_scope.strip().lower():
            return RejectionReason.TIME_WINDOW_MISMATCH, f"Temporal scopes differ: '{poly.temporal_scope}' vs '{kalshi.temporal_scope}'"

        # 5. Timestamp divergence
        if poly.resolution_timestamp and kalshi.resolution_timestamp:
            p_ts = _ensure_utc(poly.resolution_timestamp)
            k_ts = _ensure_utc(kalshi.resolution_timestamp)
            diff_h = abs((p_ts - k_ts).total_seconds()) / 3600.0
            if diff_h > self.config.max_time_divergence_hours:
                if poly.resolution_timestamp.tzinfo != kalshi.resolution_timestamp.tzinfo and (
                    poly.resolution_timestamp.tzinfo is not None and kalshi.resolution_timestamp.tzinfo is not None
                ):
                    return RejectionReason.TIMEZONE_MISMATCH, f"Timezone divergence: {diff_h:.1f} hours"
                return RejectionReason.TIME_WINDOW_MISMATCH, f"Resolution timestamp divergence: {diff_h:.1f} hours"

        # 6. Resolution Source Compatibility
        p_src = SettlementNormalizer.normalize_source(poly.source_of_resolution)
        k_src = SettlementNormalizer.normalize_source(kalshi.source_of_resolution)
        if p_src != k_src and "official" not in p_src and "official" not in k_src:
            return RejectionReason.RESOLUTION_SOURCE_MISMATCH, f"Resolution sources diverge: '{p_src}' vs '{k_src}'"

        # 7. Threshold gross mismatch (if present and orders of magnitude apart without nesting)
        if poly.threshold is not None and kalshi.threshold is not None:
            if poly.threshold != kalshi.threshold:
                # If opposite directions on differing thresholds, incompatible
                if poly.inequality_direction != kalshi.inequality_direction:
                    return RejectionReason.THRESHOLD_MISMATCH, f"Opposite directions on differing thresholds ({poly.threshold} vs {kalshi.threshold})"

        return None, None

    def validate_candidates(
        self,
        candidates: List[MarketCandidatePair]
    ) -> List[Tuple[ContractMappingResult, MappingProvenance]]:
        """Validates all accepted candidates via SettlementNormalizer.compare_contracts."""
        results: List[Tuple[ContractMappingResult, MappingProvenance]] = []
        syn_hash = self.config.compute_synonym_dict_hash()

        for cand in candidates:
            if cand.filter_status != CandidateFilterStatus.ACCEPTED:
                continue

            mapping = SettlementNormalizer.compare_contracts(cand.polymarket_contract, cand.kalshi_contract)
            poly_hash = cand.polymarket_contract.compute_contract_hash()
            kalshi_hash = cand.kalshi_contract.compute_contract_hash()

            provenance = MappingProvenance(
                mapping_id=mapping.mapping_id,
                polymarket_market_id=cand.polymarket_id,
                polymarket_token_id=f"token_{cand.polymarket_id}",
                kalshi_market_id=cand.kalshi_id,
                kalshi_contract_id=cand.kalshi_id,
                canonical_contract_id=mapping.canonical_contract_id,
                normalization_version=self.config.version,
                synonym_dict_hash=syn_hash,
                poly_metadata_hash=poly_hash,
                kalshi_metadata_hash=kalshi_hash,
                equivalence_class=mapping.equivalence_class,
                validation_reason=mapping.mapping_reason,
                validation_timestamp=datetime.now(timezone.utc),
                config_hash=self.config.config_hash,
            )

            # Version tracking
            if mapping.mapping_id not in self.version_tracker:
                self.version_tracker[mapping.mapping_id] = MappingVersionRecord(
                    version_id=f"ver_{mapping.mapping_id}_1",
                    mapping_id=mapping.mapping_id,
                    version_index=1,
                    metadata_version="1.0",
                    contract_status=ContractStatus.ACTIVE,
                )

            # Add to graph
            self.graph.add_mapping(
                poly_id=cand.polymarket_id,
                kalshi_id=cand.kalshi_id,
                canonical_id=mapping.canonical_contract_id,
                mapping_result=mapping,
                provenance=provenance,
            )

            results.append((mapping, provenance))

        return results

    def invalidate_mapping_due_to_metadata_change(
        self,
        mapping_id: str,
        reason: str = "METADATA_VERSION_CHANGE"
    ) -> Optional[MappingVersionRecord]:
        """Invalidates a mapping version if settlement terms or metadata change."""
        rec = self.version_tracker.get(mapping_id)
        if not rec or rec.contract_status != ContractStatus.ACTIVE:
            return None

        now = datetime.now(timezone.utc)
        rec.mapping_end = now
        rec.contract_status = ContractStatus.INVALIDATED
        rec.invalidation_reason = reason

        new_rec = MappingVersionRecord(
            version_id=f"ver_{mapping_id}_{rec.version_index + 1}",
            mapping_id=mapping_id,
            version_index=rec.version_index + 1,
            metadata_version=f"1.{rec.version_index}",
            mapping_start=now,
            contract_status=ContractStatus.ACTIVE,
        )
        self.version_tracker[mapping_id] = new_rec
        return new_rec

    def run_discovery(
        self,
        polymarket_contracts: List[CanonicalEconomicContract],
        kalshi_contracts: List[CanonicalEconomicContract],
        persist: bool = True
    ) -> DiscoveryRunSummary:
        """Executes full discovery funnel and records append-only tables to DuckDB."""
        # 1. Generate candidates
        candidates = self.generate_candidates(polymarket_contracts, kalshi_contracts)
        accepted = [c for c in candidates if c.filter_status == CandidateFilterStatus.ACCEPTED]
        rejected = [c for c in candidates if c.filter_status == CandidateFilterStatus.REJECTED]

        filter_rejection_counts: Dict[str, int] = {}
        for r in rejected:
            key = r.filter_rejection_reason.value if r.filter_rejection_reason else "OTHER"
            filter_rejection_counts[key] = filter_rejection_counts.get(key, 0) + 1

        # 2. Validate accepted candidates
        validated_pairs = self.validate_candidates(candidates)

        # 3. Categorize settlement results
        exact_cnt = 0
        comp_cnt = 0
        nested_cnt = 0
        ambig_cnt = 0
        settlement_rejected_cnt = 0
        settlement_rejections: Dict[str, int] = {}

        for m, prov in validated_pairs:
            if m.equivalence_class == EquivalenceClass.EXACT_EQUIVALENT:
                exact_cnt += 1
            elif m.equivalence_class == EquivalenceClass.COMPLEMENTARY:
                comp_cnt += 1
            elif m.equivalence_class == EquivalenceClass.NESTED:
                nested_cnt += 1
            elif m.equivalence_class in (EquivalenceClass.SEMANTIC_ONLY, EquivalenceClass.NON_EQUIVALENT):
                settlement_rejected_cnt += 1
                if "AMBIGUOUS" in m.mapping_reason:
                    ambig_cnt += 1
                # Categorize reason
                r_key = "UNKNOWN"
                for reason_enum in RejectionReason:
                    if reason_enum.value in m.mapping_reason:
                        r_key = reason_enum.value
                        break
                settlement_rejections[r_key] = settlement_rejections.get(r_key, 0) + 1

        summary = DiscoveryRunSummary(
            polymarket_universe_size=len(polymarket_contracts),
            kalshi_universe_size=len(kalshi_contracts),
            candidate_pairs_generated=len(candidates),
            candidate_pairs_accepted=len(accepted),
            candidate_pairs_rejected=len(rejected),
            filter_rejections_by_reason=filter_rejection_counts,
            validation_count=len(validated_pairs),
            exact_equivalent_count=exact_cnt,
            complementary_count=comp_cnt,
            nested_count=nested_cnt,
            ambiguous_count=ambig_cnt,
            rejected_count=settlement_rejected_cnt,
            settlement_rejections_by_reason=settlement_rejections,
            config_hash=self.config.config_hash,
        )

        # 4. Optional Persistence
        if persist and self.db_store is not None:
            self._persist_discovery(candidates, validated_pairs, summary)

        return summary

    def _persist_discovery(
        self,
        candidates: List[MarketCandidatePair],
        validated_pairs: List[Tuple[ContractMappingResult, MappingProvenance]],
        summary: DiscoveryRunSummary
    ) -> None:
        """Records append-only records to Phase 10A.6H DuckDB tables."""
        if hasattr(self.db_store, "record_discovery_audit"):
            self.db_store.record_discovery_audit(
                candidates=candidates,
                validated_pairs=validated_pairs,
                version_records=list(self.version_tracker.values()),
                summary=summary,
                config=self.config,
            )
