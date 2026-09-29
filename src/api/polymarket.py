"""Polymarket API Client for Gamma and CLOB endpoints."""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import requests

from config.settings import get_settings
from src.api.base import BaseMarketClient
from src.normalization.schema import (
    Market,
    Observation,
    Trade,
    Platform,
    MarketStatus,
    OrderSide,
)

logger = logging.getLogger(__name__)

class PolymarketClient(BaseMarketClient):
    """Client for querying Polymarket Gamma (metadata) and CLOB (orderbook & trades) APIs."""

    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.settings = get_settings()
        self.gamma_url = self.settings.api.polymarket_gamma_url
        self.clob_url = self.settings.api.polymarket_clob_url
        self.timeout = self.settings.api.request_timeout_seconds
        self.raw_dir = raw_data_dir or (self.settings.db.raw_dir / "polymarket")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PredictionMarketResearch/1.0",
            "Accept": "application/json",
        })

    def _save_raw_response(self, category: str, endpoint: str, data: Any) -> None:
        """Store raw API response in versioned raw-data directory."""
        try:
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            dest_dir = self.raw_dir / category / today_str
            dest_dir.mkdir(parents=True, exist_ok=True)
            ts = int(datetime.utcnow().timestamp() * 1000)
            clean_endpoint = endpoint.replace("/", "_").strip("_")
            file_path = dest_dir / f"{clean_endpoint}_{ts}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save raw API payload: {e}")

    def _get(self, base_url: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{base_url}{endpoint}"
        retries = 3
        backoff = 1.0
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    self._save_raw_response("gamma" if base_url == self.gamma_url else "clob", endpoint, data)
                    return data
                elif resp.status_code == 429: # Rate limit
                    logger.warning(f"Rate limited on {url}, sleeping {backoff}s...")
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    logger.error(f"HTTP {resp.status_code} on {url}: {resp.text[:200]}")
                    return None
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(backoff)
                backoff *= 1.5
        return None

    def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> List[Market]:
        """Fetch active Polymarket markets from Gamma API."""
        params = {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
        }
        data = self._get(self.gamma_url, "/markets", params=params)
        if not data or not isinstance(data, list):
            return []

        markets: List[Market] = []
        for item in data:
            try:
                # Parse outcomes & tokens
                outcomes_raw = item.get("outcomes")
                if isinstance(outcomes_raw, str):
                    outcomes = json.loads(outcomes_raw)
                elif isinstance(outcomes_raw, list):
                    outcomes = outcomes_raw
                else:
                    outcomes = ["Yes", "No"]

                token_ids_raw = item.get("clobTokenIds")
                if isinstance(token_ids_raw, str):
                    token_ids = json.loads(token_ids_raw)
                elif isinstance(token_ids_raw, list):
                    token_ids = token_ids_raw
                else:
                    token_ids = []

                # Parse dates
                open_time = None
                if item.get("startDate"):
                    try:
                        open_time = datetime.fromisoformat(item["startDate"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                close_time = None
                if item.get("endDate"):
                    try:
                        close_time = datetime.fromisoformat(item["endDate"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                market = Market(
                    platform=Platform.POLYMARKET,
                    market_id=str(item.get("id")),
                    event_id=str(item.get("conditionId") or item.get("id")),
                    title=str(item.get("question", "")),
                    description=str(item.get("description", "")),
                    resolution_rules=str(item.get("resolutionSource", "") or item.get("description", "")),
                    outcome_labels=outcomes,
                    category=str(item.get("category", "General")),
                    open_time=open_time,
                    close_time=close_time,
                    status=MarketStatus.ACTIVE if item.get("active") else MarketStatus.CLOSED,
                    clob_token_ids=token_ids,
                    condition_id=item.get("conditionId"),
                    volume=float(item.get("volume", 0.0) or 0.0),
                    liquidity=float(item.get("liquidity", 0.0) or 0.0),
                    metadata={
                        "slug": item.get("slug"),
                        "volume24hr": item.get("volume24hr"),
                        "outcomePrices": item.get("outcomePrices"),
                        "bestBid": item.get("bestBid"),
                        "bestAsk": item.get("bestAsk"),
                    }
                )
                markets.append(market)
            except Exception as e:
                logger.debug(f"Skipping malformed market record {item.get('id')}: {e}")
                continue
        return markets

    def fetch_market_by_id(self, market_id: str) -> Optional[Market]:
        data = self._get(self.gamma_url, f"/markets/{market_id}")
        if not data or not isinstance(data, dict):
            return None
        # Convert single item
        return self.fetch_active_markets(limit=1, offset=0)[0] if data else None

    def fetch_order_book(self, token_id: str) -> Dict[str, Any]:
        """Fetch live CLOB orderbook for a given Polymarket token_id."""
        params = {"token_id": token_id}
        data = self._get(self.clob_url, "/book", params=params)
        if not data or not isinstance(data, dict):
            return {"bids": [], "asks": []}
        return data

    def fetch_price_history(self, token_id: str, interval: str = "all", fidelity_minutes: int = 60) -> List[Observation]:
        """Fetch historical prices from CLOB prices-history endpoint."""
        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity_minutes,
        }
        data = self._get(self.clob_url, "/prices-history", params=params)
        if not data or not isinstance(data, dict):
            return []

        history = data.get("history", [])
        observations: List[Observation] = []
        for point in history:
            try:
                t = point.get("t")
                p = float(point.get("p", 0.0))
                if t is not None:
                    ts = datetime.utcfromtimestamp(t)
                    obs = Observation(
                        timestamp=ts,
                        market_id=token_id,
                        platform=Platform.POLYMARKET,
                        yes_bid=p,
                        yes_ask=p,
                        yes_mid=p,
                        no_bid=round(1.0 - p, 4),
                        no_ask=round(1.0 - p, 4),
                    )
                    observations.append(obs)
            except Exception as e:
                logger.debug(f"Error parsing history point: {e}")
        return observations

    def fetch_recent_trades(self, token_id: str, limit: int = 50) -> List[Trade]:
        """Fetch recent trades for a token from CLOB endpoint."""
        params = {"market": token_id}
        data = self._get(self.clob_url, "/trades", params=params)
        if not data or not isinstance(data, list):
            return []

        trades: List[Trade] = []
        for item in data[:limit]:
            try:
                side = OrderSide.BUY if item.get("side", "").upper() == "BUY" else OrderSide.SELL
                t = item.get("timestamp") or time.time()
                ts = datetime.utcfromtimestamp(float(t)) if isinstance(t, (int, float)) else datetime.utcnow()
                trades.append(Trade(
                    timestamp=ts,
                    market_id=token_id,
                    platform=Platform.POLYMARKET,
                    side=side,
                    price=float(item.get("price", 0.0)),
                    quantity=float(item.get("size", 0.0)),
                ))
            except Exception as e:
                logger.debug(f"Error parsing trade: {e}")
        return trades
