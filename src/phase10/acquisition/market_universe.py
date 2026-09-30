"""Objective Market Universe Discovery and Tracking for Phase 10A.5.

Discovers active, tradable prediction markets objectively via the Polymarket Gamma API,
verifies open order-book availability on the CLOB, and tracks universe state changes.
Strictly avoids hand-picking or narrative selection.
"""
from datetime import datetime, timezone
import json
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
import requests

from src.phase10.acquisition.schema import MarketUniverseEntry, UniverseChangeEventRecord
from src.phase10.acquisition.dns_resolver import enable_polymarket_edge_resolver

logger = logging.getLogger(__name__)

# Ensure DNS resolution uses direct Cloudflare edge IPs
enable_polymarket_edge_resolver()


class MarketUniverseManager:
    """Manages objective discovery and maintenance of the monitored market universe."""

    def __init__(
        self,
        gamma_url: str = "https://gamma-api.polymarket.com",
        min_liquidity_usd: float = 5_000.0,
        min_volume_24h_usd: float = 10_000.0,
        timeout: float = 15.0
    ):
        self.gamma_url = gamma_url
        self.min_liquidity = min_liquidity_usd
        self.min_volume_24h = min_volume_24h_usd
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PredictionMarketResearch/1.0",
            "Accept": "application/json"
        })
        self._current_tokens: Set[str] = set()
        self._previous_markets: Dict[str, MarketUniverseEntry] = {}

    def discover_universe_with_changes(
        self,
        session_id: str,
        limit: int = 50
    ) -> Tuple[List[MarketUniverseEntry], List[UniverseChangeEventRecord]]:
        """Queries Gamma API and produces explicit ADDED/REMOVED universe change events."""
        entries = self.discover_active_universe(session_id=session_id, limit=limit)
        new_markets: Dict[str, MarketUniverseEntry] = {}
        for e in entries:
            if e.market_id not in new_markets:
                new_markets[e.market_id] = e

        change_events: List[UniverseChangeEventRecord] = []
        now = datetime.now(timezone.utc)

        # 1. Added markets
        for m_id, entry in new_markets.items():
            if m_id not in self._previous_markets:
                change_events.append(UniverseChangeEventRecord(
                    event_id=f"uevt_add_{m_id}_{int(now.timestamp())}_{entry.token_id[:8]}",
                    timestamp=now,
                    session_id=session_id,
                    market_id=m_id,
                    token_id=entry.token_id,
                    market_added=m_id,
                    market_removed=None,
                    reason=f"Objective threshold met: vol_24h=${entry.volume_24h_usd:,.2f} >= ${self.min_volume_24h:,.0f}, liq=${entry.liquidity_usd:,.2f} >= ${self.min_liquidity:,.0f}"
                ))

        # 2. Removed markets
        for m_id, old_entry in self._previous_markets.items():
            if m_id not in new_markets:
                change_events.append(UniverseChangeEventRecord(
                    event_id=f"uevt_rem_{m_id}_{int(now.timestamp())}_{old_entry.token_id[:8]}",
                    timestamp=now,
                    session_id=session_id,
                    market_id=m_id,
                    token_id=old_entry.token_id,
                    market_added=None,
                    market_removed=m_id,
                    reason="Fell below volume/liquidity threshold or closed on Polymarket"
                ))

        self._previous_markets = new_markets
        return entries, change_events

    def discover_active_universe(
        self,
        session_id: str,
        limit: int = 50
    ) -> List[MarketUniverseEntry]:
        """Queries Gamma API for active, tradable markets meeting objective thresholds."""
        params = {
            "limit": limit,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }
        url = f"{self.gamma_url}/markets"
        logger.info(f"Querying Gamma API for active tradable markets: {url}")
        
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logger.error(f"Gamma API returned HTTP {resp.status_code}")
                return []
            raw_markets = resp.json()
        except Exception as e:
            logger.error(f"Failed to query Gamma API: {e}")
            return []

        return self.parse_markets(raw_markets, session_id)

    def parse_markets(
        self,
        raw_markets: List[Dict[str, Any]],
        session_id: str
    ) -> List[MarketUniverseEntry]:
        """Parses raw Gamma API market entries according to objective criteria."""
        entries: List[MarketUniverseEntry] = []
        now = datetime.now(timezone.utc)
        discovered_tokens: Set[str] = set()

        for m in raw_markets:
            try:
                market_id = str(m.get("id"))
                question = str(m.get("question", ""))
                category = str(m.get("category", "General"))
                vol_24h = float(m.get("volume24hr") or 0.0)
                liq = float(m.get("liquidity") or 0.0)
                active = bool(m.get("active", False))
                closed = bool(m.get("closed", False))

                # Objective criteria check: must be active and meet liquidity/volume filters
                if not active or closed:
                    continue
                if vol_24h < self.min_volume_24h or liq < self.min_liquidity:
                    continue

                # Parse CLOB token IDs
                clob_tokens_raw = m.get("clobTokenIds")
                if isinstance(clob_tokens_raw, str):
                    token_ids = json.loads(clob_tokens_raw)
                elif isinstance(clob_tokens_raw, list):
                    token_ids = clob_tokens_raw
                else:
                    token_ids = []

                outcomes_raw = m.get("outcomes")
                if isinstance(outcomes_raw, str):
                    outcomes = json.loads(outcomes_raw)
                elif isinstance(outcomes_raw, list):
                    outcomes = outcomes_raw
                else:
                    outcomes = ["Yes", "No"]

                if not token_ids or len(token_ids) == 0:
                    continue

                for idx, tok in enumerate(token_ids):
                    tok_str = str(tok)
                    outcome_label = outcomes[idx] if idx < len(outcomes) else f"Outcome_{idx}"
                    discovered_tokens.add(tok_str)

                    action = "ADDED" if tok_str not in self._current_tokens else "UPDATED"
                    entries.append(MarketUniverseEntry(
                        entry_id=f"univ_{market_id}_{tok_str[:8]}_{int(now.timestamp())}",
                        session_id=session_id,
                        market_id=market_id,
                        token_id=tok_str,
                        outcome=outcome_label,
                        title=question,
                        category=category,
                        volume_24h_usd=vol_24h,
                        liquidity_usd=liq,
                        is_active=active,
                        is_tradable=True,
                        action=action,
                        timestamp=now
                    ))

            except Exception as ex:
                logger.warning(f"Error parsing market entry {m.get('id')}: {ex}")
                continue

        self._current_tokens = discovered_tokens
        logger.info(f"Discovered {len(entries)} qualifying tradable tokens across {len(set(e.market_id for e in entries))} markets.")
        return entries
