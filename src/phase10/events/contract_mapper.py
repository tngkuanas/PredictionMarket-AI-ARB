"""Deterministic Contract Mapping Engine for Information Latency.
Verifies real-world InformationEvents against CanonicalMarket resolution criteria:
- Entity match & synonym expansion
- Temporal alignment (expiry vs publication)
- Threshold & strike consistency
- Resolution source & oracle compatibility
- Semantic wording ambiguity detection (e.g. popular vote vs presidency)
- YES/NO outcome polarity inversion
"""
import re
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional, Set, Tuple
from pydantic import BaseModel, Field, ConfigDict

from src.normalization.schema import CanonicalMarket
from src.phase10.events.schema import InformationEvent, EventDirection


class MappingDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class AmbiguityFlag(str, Enum):
    ENTITY_DISCREPANCY = "entity_discrepancy"
    TEMPORAL_EXPIRED = "temporal_expired"
    TEMPORAL_MISMATCH = "temporal_mismatch"
    THRESHOLD_MISMATCH = "threshold_mismatch"
    RESOLUTION_SOURCE_MISMATCH = "resolution_source_mismatch"
    WORDING_AMBIGUITY = "wording_ambiguity"
    SCOPE_MISMATCH = "scope_mismatch"
    UNVERIFIED_SOURCE_HIERARCHY = "unverified_source_hierarchy"


class ContractMapping(BaseModel):
    """Audit object recording deterministic mapping decision between event and contract."""
    model_config = ConfigDict(frozen=True)

    mapping_id: str = Field(..., description="Unique deterministic identifier for this mapping evaluation")
    event_id: str = Field(..., description="ID of the information event")
    market_id: str = Field(..., description="ID of the target prediction market contract")
    canonical_title: str = Field(..., description="Normalized title of the target market")
    entity_match: bool = Field(..., description="Whether entities overlap cleanly")
    entity_match_score: float = Field(..., ge=0.0, le=1.0, description="Jaccard entity overlap score")
    temporal_match: bool = Field(..., description="Whether event occurred within active contract window")
    outcome_match: bool = Field(..., description="Whether event outcome aligns with contract settlement criteria")
    resolution_match: bool = Field(..., description="Whether event source matches contract resolution rules")
    semantic_match_score: float = Field(..., ge=0.0, le=1.0, description="Normalized lexical/semantic similarity score")
    is_inverted: bool = Field(..., description="True if positive event impact implies contract NO outcome")
    ambiguity_flags: List[AmbiguityFlag] = Field(default_factory=list, description="List of identified ambiguity flags")
    mapping_decision: MappingDecision = Field(..., description="Final validation verdict: ACCEPTED, REJECTED, AMBIGUOUS")
    decision_reason: str = Field(..., description="Explicit human-readable rationale for the decision")


class DeterministicContractMapper:
    """Rigorous, deterministic validator mapping real-world events to prediction contracts."""

    # Entity synonym dictionary for robust canonical matching
    SYNONYM_MAP: Dict[str, Set[str]] = {
        "federal reserve": {"fed", "federal reserve", "fomc", "jerome powell", "powell"},
        "bureau of labor statistics": {"bls", "bureau of labor statistics", "labor department"},
        "bureau of economic analysis": {"bea", "bureau of economic analysis", "commerce department"},
        "securities and exchange commission": {"sec", "securities and exchange commission", "gary gensler"},
        "donald trump": {"trump", "donald trump", "donald j trump"},
        "kamala harris": {"harris", "kamala harris"},
        "joe biden": {"biden", "joe biden"},
        "bitcoin": {"btc", "bitcoin"},
        "ethereum": {"eth", "ethereum"},
        "european central bank": {"ecb", "european central bank", "christine lagarde"},
        "bank of japan": {"boj", "bank of japan", "kazuo ueda"},
        "supreme court": {"scotus", "supreme court", "us supreme court"}
    }

    # Known superficial wording traps where semantic similarity is high but legal criteria diverge
    SUPERFICIAL_TRAPS: List[Tuple[re.Pattern, re.Pattern, str]] = [
        (
            re.compile(r"\bpopular vote\b", re.I),
            re.compile(r"\bwin (the )?presidency\b|\belectoral college\b", re.I),
            "Event concerns popular vote, but contract resolves based on electoral college / presidential victory"
        ),
        (
            re.compile(r"\bindicted\b|\bindictment\b", re.I),
            re.compile(r"\bconvicted\b|\bconviction\b|\bguilty verdict\b", re.I),
            "Event is an indictment/charge, but contract requires criminal conviction"
        ),
        (
            re.compile(r"\bceasefire\b|\btruce\b", re.I),
            re.compile(r"\bpeace treaty\b|\bformal surrender\b", re.I),
            "Event is a temporary ceasefire, but contract requires formal peace treaty settlement"
        ),
        (
            re.compile(r"\bapproval\b|\b19b-4\b", re.I),
            re.compile(r"\btrading commences\b|\bs-1 effective\b", re.I),
            "Event is regulatory approval, but contract resolves on trading commencement"
        ),
        (
            re.compile(r"\bprovisional count\b|\blead\b", re.I),
            re.compile(r"\bofficially certified\b|\bcertification\b", re.I),
            "Event is uncertified provisional tallies, but contract requires official certification"
        ),
    ]

    def _canonicalize_entity(self, entity_str: str) -> str:
        clean = re.sub(r"[^\w\s]", "", entity_str.lower()).strip()
        for canonical, syns in self.SYNONYM_MAP.items():
            if clean in syns or any(s in clean for s in syns):
                return canonical
        return clean

    def _extract_numbers(self, text: str) -> List[Tuple[float, str]]:
        """Extract numerical values from text along with unit."""
        numbers = []
        matches = re.finditer(r"(\$)?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%|bps|\bk\b|\bm\b)?", text.lower())
        for m in matches:
            is_dollar = bool(m.group(1))
            val_str = m.group(2)
            unit = m.group(3) or ("$" if is_dollar else "raw")
            try:
                num = float(val_str.replace(",", ""))
                if unit == "%":
                    num = num / 100.0
                elif unit == "bps":
                    num = num / 10000.0
                elif unit == "k":
                    num = num * 1000.0
                elif unit == "m":
                    num = num * 1000000.0
                # Exclude calendar years
                if unit == "raw" and (2020 <= num <= 2030):
                    continue
                # Exclude days of month (1-31) when no financial unit is attached
                if unit == "raw" and num <= 31:
                    continue
                numbers.append((num, unit))
            except ValueError:
                continue
        return numbers

    def map_event_to_market(
        self,
        event: InformationEvent,
        market: CanonicalMarket
    ) -> ContractMapping:
        """Deterministically evaluates whether an InformationEvent maps to a CanonicalMarket."""
        ambiguity_flags: List[AmbiguityFlag] = []
        mapping_id = f"map_{event.event_id}_{market.market_id}"

        # 1. Entity Match
        event_entities = {self._canonicalize_entity(e) for e in event.entities}
        market_entities = {self._canonicalize_entity(e) for e in market.entities}
        # Also inspect market title text for entity keywords
        market_title_lower = market.title.lower()
        for can_ent, syns in self.SYNONYM_MAP.items():
            if any(re.search(rf"\b{re.escape(s)}\b", market_title_lower) for s in syns):
                market_entities.add(can_ent)

        intersection = event_entities.intersection(market_entities)
        union = event_entities.union(market_entities)
        entity_score = float(len(intersection) / len(union)) if union else 0.0
        entity_match = (len(intersection) > 0)
        if not entity_match:
            ambiguity_flags.append(AmbiguityFlag.ENTITY_DISCREPANCY)

        # 2. Temporal Match
        temporal_match = True
        if market.resolution_date:
            try:
                # Support YYYY-MM-DD or ISO strings
                res_date_clean = market.resolution_date.split("T")[0]
                res_dt = datetime.strptime(res_date_clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if event.timestamp_publication > res_dt:
                    temporal_match = False
                    ambiguity_flags.append(AmbiguityFlag.TEMPORAL_EXPIRED)
            except (ValueError, TypeError):
                pass

        # Check target month / meeting alignment
        MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
        event_months = {w for w in re.findall(r"\b[a-z]+\b", event.title.lower()) if w in MONTHS}
        market_months = {w for w in re.findall(r"\b[a-z]+\b", market.title.lower()) if w in MONTHS}
        if event_months and market_months and not event_months.intersection(market_months):
            temporal_match = False
            ambiguity_flags.append(AmbiguityFlag.TEMPORAL_MISMATCH)

        # 3. Resolution Source Match
        resolution_match = True
        if market.resolution_source:
            res_source_lower = market.resolution_source.lower()
            event_source_lower = event.source.lower()
            
            from src.phase10.events.schema import SourceType
            if event.source_type == SourceType.SOCIAL_MEDIA:
                resolution_match = False
                ambiguity_flags.append(AmbiguityFlag.UNVERIFIED_SOURCE_HIERARCHY)
            else:
                GENERIC_SOURCES = {
                    "official market resolution source",
                    "official resolution source",
                    "polymarket",
                    "uma",
                    "consensus"
                }
                if res_source_lower not in GENERIC_SOURCES:
                    source_tokens_event = set(re.findall(r"\w+", event_source_lower))
                    source_tokens_market = set(re.findall(r"\w+", res_source_lower)) - {"official", "resolution", "source", "release", "press"}
                    has_source_overlap = bool(source_tokens_event.intersection(source_tokens_market))
                    if not has_source_overlap and len(source_tokens_market) >= 1:
                        resolution_match = False
                        ambiguity_flags.append(AmbiguityFlag.RESOLUTION_SOURCE_MISMATCH)

        # 4. Superficial Wording & Semantic Traps
        combined_event_text = f"{event.title} {event.raw_content}"
        combined_market_text = f"{market.title} {market.underlying_event} {market.resolution_methodology or ''}"

        for event_pattern, market_pattern, reason in self.SUPERFICIAL_TRAPS:
            if event_pattern.search(combined_event_text) and market_pattern.search(combined_market_text):
                ambiguity_flags.append(AmbiguityFlag.WORDING_AMBIGUITY)
            elif market_pattern.search(combined_event_text) and event_pattern.search(combined_market_text):
                ambiguity_flags.append(AmbiguityFlag.WORDING_AMBIGUITY)

        # Indirect macro transmission detection
        if event.event_type in {"macro_inflation", "macro_employment"} and market.event_type == "rate_decision":
            ambiguity_flags.append(AmbiguityFlag.SCOPE_MISMATCH)

        # 5. Threshold Consistency
        market_num_pairs = self._extract_numbers(market.title)
        if not market_num_pairs and market.threshold:
            market_num_pairs = self._extract_numbers(market.threshold)
        event_num_pairs = self._extract_numbers(event.title)
        if market_num_pairs and event_num_pairs:
            has_matching_num = any(
                abs(m_val - e_val) <= (0.05 * max(m_val, 1e-4))
                for m_val, _ in market_num_pairs
                for e_val, _ in event_num_pairs
            )
            if not has_matching_num:
                ambiguity_flags.append(AmbiguityFlag.THRESHOLD_MISMATCH)

        # 6. Lexical / Semantic Score
        event_words = set(re.findall(r"\b\w{3,}\b", combined_event_text.lower()))
        market_words = set(re.findall(r"\b\w{3,}\b", f"{market.title} {market.underlying_event}".lower()))
        w_inter = event_words.intersection(market_words)
        w_union = event_words.union(market_words)
        jaccard = float(len(w_inter) / len(w_union)) if w_union else 0.0
        containment = float(len(w_inter) / len(market_words)) if market_words else 0.0
        semantic_score = max(jaccard, containment * 0.4)

        # 7. YES/NO Outcome Polarity Inversion
        # Detect if positive event implies NO on the contract
        is_inverted = False
        negation_terms = [r"\bbelow\b", r"\bless than\b", r"\bunder\b", r"\bnot\b", r"\bfails\b", r"\bdrop\b"]
        has_market_negation = any(re.search(term, market.title.lower()) for term in negation_terms)
        if has_market_negation:
            is_inverted = True

        outcome_match = (event.direction != EventDirection.UNCERTAIN)

        # 8. Deterministic Decision Gate
        fatal_flags = {
            AmbiguityFlag.ENTITY_DISCREPANCY,
            AmbiguityFlag.TEMPORAL_EXPIRED,
            AmbiguityFlag.TEMPORAL_MISMATCH,
            AmbiguityFlag.THRESHOLD_MISMATCH,
            AmbiguityFlag.RESOLUTION_SOURCE_MISMATCH,
            AmbiguityFlag.WORDING_AMBIGUITY,
            AmbiguityFlag.UNVERIFIED_SOURCE_HIERARCHY,
        }
        active_fatal_flags = fatal_flags.intersection(set(ambiguity_flags))

        if AmbiguityFlag.SCOPE_MISMATCH in ambiguity_flags:
            decision = MappingDecision.AMBIGUOUS
            decision_reason = "Ambiguous: indirect macro transmission (e.g. CPI/NFP impulse on policy rate contract)"
        elif active_fatal_flags or not entity_match or not temporal_match or not resolution_match:
            decision = MappingDecision.REJECTED
            reasons = [f.value for f in ambiguity_flags] or ["Failed core matching criteria"]
            decision_reason = f"Rejected due to fatal criteria failures: {', '.join(reasons)}"
        elif semantic_score < 0.15:
            decision = MappingDecision.AMBIGUOUS
            decision_reason = f"Low lexical overlap ({semantic_score:.2f}) despite shared entity"
        else:
            decision = MappingDecision.ACCEPTED
            decision_reason = "Verified: Clean entity overlap, active contract window, compatible resolution criteria, and zero fatal ambiguities."

        return ContractMapping(
            mapping_id=mapping_id,
            event_id=event.event_id,
            market_id=market.market_id,
            canonical_title=market.title,
            entity_match=entity_match,
            entity_match_score=entity_score,
            temporal_match=temporal_match,
            outcome_match=outcome_match,
            resolution_match=resolution_match,
            semantic_match_score=semantic_score,
            is_inverted=is_inverted,
            ambiguity_flags=ambiguity_flags,
            mapping_decision=decision,
            decision_reason=decision_reason
        )
