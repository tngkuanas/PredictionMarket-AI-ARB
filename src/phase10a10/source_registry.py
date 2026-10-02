"""Authoritative Source Hierarchy and Registry for Phase 10A.10.

Maintains strict taxonomy:
- Tier 1: Official government, regulator, exchange, league, tournament, election authority.
- Tier 2: Primary organization publishing official result (direct wire releases).
- Tier 3: High-quality secondary sources, aggregators, social media (PROHIBITED for primary result).

Enforces source qualification, domain matching, and tier validation.
"""

from typing import Dict, Any, Optional
from src.phase10a10.schema import SourceTier, SourceRecord


class SourceRegistry:
    """Registry of verified authoritative sources across domains."""

    TIER_1_SOURCES = {
        "federal_reserve": {
            "name": "Federal Reserve Board of Governors",
            "tier": SourceTier.TIER_1,
            "domains": ["federalreserve.gov", "frb.gov"],
            "category": "macro_monetary",
        },
        "bls": {
            "name": "Bureau of Labor Statistics",
            "tier": SourceTier.TIER_1,
            "domains": ["bls.gov"],
            "category": "macro_indicator",
        },
        "cboe": {
            "name": "Chicago Board Options Exchange",
            "tier": SourceTier.TIER_1,
            "domains": ["cboe.com"],
            "category": "equity_derivatives",
        },
        "nyse": {
            "name": "New York Stock Exchange",
            "tier": SourceTier.TIER_1,
            "domains": ["nyse.com"],
            "category": "equities",
        },
        "cme": {
            "name": "Chicago Mercantile Exchange",
            "tier": SourceTier.TIER_1,
            "domains": ["cmegroup.com"],
            "category": "derivatives",
        },
        "binance": {
            "name": "Binance Official Exchange Fix",
            "tier": SourceTier.TIER_1,
            "domains": ["binance.com"],
            "category": "crypto_exchange",
        },
        "coinbase": {
            "name": "Coinbase Exchange Fix",
            "tier": SourceTier.TIER_1,
            "domains": ["coinbase.com"],
            "category": "crypto_exchange",
        },
        "atp_tour": {
            "name": "Association of Tennis Professionals",
            "tier": SourceTier.TIER_1,
            "domains": ["atptour.com"],
            "category": "tennis",
        },
        "wta_tennis": {
            "name": "Women's Tennis Association",
            "tier": SourceTier.TIER_1,
            "domains": ["wtatennis.com"],
            "category": "tennis",
        },
        "blast_premier": {
            "name": "BLAST Premier Official",
            "tier": SourceTier.TIER_1,
            "domains": ["blastpremier.com", "blast.tv"],
            "category": "esports",
        },
        "valve_dota": {
            "name": "Valve Corporation Dota 2 Official",
            "tier": SourceTier.TIER_1,
            "domains": ["dota2.com"],
            "category": "esports",
        },
        "riot_games": {
            "name": "Riot Games Esports",
            "tier": SourceTier.TIER_1,
            "domains": ["lolesports.com", "valorantesports.com"],
            "category": "esports",
        },
        "hltv": {
            "name": "HLTV Official CS Match Sheet",
            "tier": SourceTier.TIER_1,
            "domains": ["hltv.org"],
            "category": "esports",
        },
        "state_dept": {
            "name": "U.S. Department of State",
            "tier": SourceTier.TIER_1,
            "domains": ["state.gov"],
            "category": "geopolitical",
        },
        "supreme_court": {
            "name": "Supreme Court of the United States",
            "tier": SourceTier.TIER_1,
            "domains": ["supremecourt.gov"],
            "category": "legal_political",
        },
    }

    TIER_2_SOURCES = {
        "reuters_wire": {
            "name": "Reuters Official Direct Wire",
            "tier": SourceTier.TIER_2,
            "domains": ["reuters.com"],
            "category": "wire_service",
        },
        "ap_wire": {
            "name": "Associated Press Wire",
            "tier": SourceTier.TIER_2,
            "domains": ["apnews.com"],
            "category": "wire_service",
        },
        "bloomberg_wire": {
            "name": "Bloomberg First Word / Wire",
            "tier": SourceTier.TIER_2,
            "domains": ["bloomberg.com"],
            "category": "financial_wire",
        },
    }

    TIER_3_SOURCES = {
        "polymarket_comments": {
            "name": "Polymarket User Comments",
            "tier": SourceTier.TIER_3,
            "domains": ["polymarket.com"],
            "category": "social_aggregator",
        },
        "twitter_x": {
            "name": "X / Twitter Social Feed",
            "tier": SourceTier.TIER_3,
            "domains": ["x.com", "twitter.com"],
            "category": "social_media",
        },
        "reddit": {
            "name": "Reddit Communities",
            "tier": SourceTier.TIER_3,
            "domains": ["reddit.com"],
            "category": "social_forum",
        },
        "generic_news_aggregator": {
            "name": "Secondary News Aggregator",
            "tier": SourceTier.TIER_3,
            "domains": ["news.google.com", "yahoo.com"],
            "category": "aggregator",
        },
    }

    @classmethod
    def lookup_source(cls, source_id: str) -> Optional[Dict[str, Any]]:
        """Look up source details by identifier."""
        sid = source_id.lower().replace("-", "_").replace(" ", "_")
        if sid in cls.TIER_1_SOURCES:
            return cls.TIER_1_SOURCES[sid]
        if sid in cls.TIER_2_SOURCES:
            return cls.TIER_2_SOURCES[sid]
        if sid in cls.TIER_3_SOURCES:
            return cls.TIER_3_SOURCES[sid]
        return None

    @classmethod
    def get_tier(cls, source_id: str) -> SourceTier:
        """Determines the tier of a source. Defaults to TIER_3 if unknown."""
        meta = cls.lookup_source(source_id)
        if meta:
            return meta["tier"]
        return SourceTier.TIER_3

    @classmethod
    def is_eligible_for_primary_research(cls, source_tier: SourceTier) -> bool:
        """Strict rule: Only Tier 1 and Tier 2 sources are eligible for primary alpha."""
        return source_tier in (SourceTier.TIER_1, SourceTier.TIER_2)
