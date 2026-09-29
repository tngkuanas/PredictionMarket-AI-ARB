"""Kalshi API Client."""
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

class KalshiClient(BaseMarketClient):
    """Client for Kalshi Public Trade API v2."""

    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.settings = get_settings()
        self.base_url = self.settings.api.kalshi_base_url
        self.timeout = self.settings.api.request_timeout_seconds
        self.raw_dir = raw_data_dir or (self.settings.db.raw_dir / "kalshi")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PredictionMarketResearch/1.0",
            "Accept": "application/json",
        })

    def _save_raw_response(self, endpoint: str, data: Any) -> None:
        try:
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            dest_dir = self.raw_dir / today_str
            dest_dir.mkdir(parents=True, exist_ok=True)
            ts = int(datetime.utcnow().timestamp() * 1000)
            clean_endpoint = endpoint.replace("/", "_").strip("_")
            file_path = dest_dir / f"{clean_endpoint}_{ts}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save Kalshi raw API payload: {e}")

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        retries = 3
        backoff = 1.0
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    self._save_raw_response(endpoint, data)
                    return data
                elif resp.status_code == 429:
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

    def fetch_active_markets(self, limit: int = 100, cursor: Optional[str] = None) -> List[Market]:
        """Fetch active markets from Kalshi API."""
        params = {
            "limit": limit,
            "status": "open",
        }
        if cursor:
            params["cursor"] = cursor

        data = self._get("/markets", params=params)
        if not data or "markets" not in data:
            return []

        markets: List[Market] = []
        for item in data.get("markets", []):
            try:
                open_time = None
                if item.get("open_time"):
                    try:
                        open_time = datetime.fromisoformat(item["open_time"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                close_time = None
                if item.get("close_time"):
                    try:
                        close_time = datetime.fromisoformat(item["close_time"].replace("Z", "+00:00"))
                    except Exception:
                        pass

                # Prices are in cents (1-99)
                yes_bid = (item.get("yes_bid") or 0) / 100.0
                yes_ask = (item.get("yes_ask") or 0) / 100.0
                last_price = (item.get("last_price") or 0) / 100.0

                m = Market(
                    platform=Platform.KALSHI,
                    market_id=str(item.get("ticker")),
                    event_id=str(item.get("event_ticker") or item.get("ticker")),
                    title=str(item.get("title") or item.get("subtitle", "")),
                    description=str(item.get("subtitle", "")),
                    resolution_rules=str(item.get("rules_primary", "") or item.get("title", "")),
                    outcome_labels=["Yes", "No"],
                    category=str(item.get("category", "General")),
                    open_time=open_time,
                    close_time=close_time,
                    status=MarketStatus.ACTIVE if item.get("status") == "open" else MarketStatus.CLOSED,
                    volume=float(item.get("volume", 0.0) or 0.0),
                    liquidity=float(item.get("liquidity", 0.0) or (item.get("open_interest", 0.0) or 0.0)),
                    metadata={
                        "ticker": item.get("ticker"),
                        "event_ticker": item.get("event_ticker"),
                        "yes_bid": yes_bid,
                        "yes_ask": yes_ask,
                        "last_price": last_price,
                        "open_interest": item.get("open_interest"),
                        "rules_secondary": item.get("rules_secondary"),
                    }
                )
                markets.append(m)
            except Exception as e:
                logger.debug(f"Error parsing Kalshi market {item.get('ticker')}: {e}")
                continue
        return markets

    def fetch_market_by_id(self, ticker: str) -> Optional[Market]:
        data = self._get(f"/markets/{ticker}")
        if not data or "market" not in data:
            return None
        item = data["market"]
        return Market(
            platform=Platform.KALSHI,
            market_id=str(item.get("ticker")),
            event_id=str(item.get("event_ticker") or item.get("ticker")),
            title=str(item.get("title") or item.get("subtitle", "")),
            description=str(item.get("subtitle", "")),
            resolution_rules=str(item.get("rules_primary", "")),
            outcome_labels=["Yes", "No"],
            category=str(item.get("category", "General")),
            status=MarketStatus.ACTIVE if item.get("status") == "open" else MarketStatus.CLOSED,
            volume=float(item.get("volume", 0.0) or 0.0),
            liquidity=float(item.get("open_interest", 0.0) or 0.0),
            metadata=item
        )

    def fetch_order_book(self, ticker: str) -> Dict[str, Any]:
        """Fetch live orderbook for a Kalshi market ticker."""
        data = self._get(f"/markets/{ticker}/orderbook")
        if not data or "orderbook" not in data:
            return {"bids": [], "asks": []}
        ob = data["orderbook"]
        # Convert cents to dollars (0.0 - 1.0)
        yes_bids = [[p / 100.0, qty] for p, qty in ob.get("yes", [])]
        no_bids = [[p / 100.0, qty] for p, qty in ob.get("no", [])]
        return {"bids": yes_bids, "no_bids": no_bids}

    def fetch_price_history(self, ticker: str, interval: str = "1h", fidelity_minutes: int = 60) -> List[Observation]:
        """Fetch historical candlestick snapshots."""
        data = self._get(f"/markets/{ticker}/candlesticks")
        if not data or "candlesticks" not in data:
            return []

        observations: List[Observation] = []
        for c in data.get("candlesticks", []):
            try:
                t = c.get("end_period_ts")
                if t is not None:
                    ts = datetime.utcfromtimestamp(t)
                    close_p = (c.get("price", {}).get("close") or 50) / 100.0
                    obs = Observation(
                        timestamp=ts,
                        market_id=ticker,
                        platform=Platform.KALSHI,
                        yes_bid=close_p,
                        yes_ask=close_p,
                        yes_mid=close_p,
                        no_bid=round(1.0 - close_p, 4),
                        no_ask=round(1.0 - close_p, 4),
                        volume=float(c.get("volume", 0.0)),
                    )
                    observations.append(obs)
            except Exception as e:
                logger.debug(f"Error parsing candlestick: {e}")
        return observations

    def fetch_recent_trades(self, ticker: str, limit: int = 50) -> List[Trade]:
        data = self._get(f"/markets/{ticker}/trades", params={"limit": limit})
        if not data or "trades" not in data:
            return []

        trades: List[Trade] = []
        for item in data.get("trades", []):
            try:
                side = OrderSide.BUY if item.get("taker_side") == "yes" else OrderSide.SELL
                t = item.get("created_time")
                ts = datetime.fromisoformat(t.replace("Z", "+00:00")) if t else datetime.utcnow()
                trades.append(Trade(
                    timestamp=ts,
                    market_id=ticker,
                    platform=Platform.KALSHI,
                    side=side,
                    price=(item.get("yes_price") or 50) / 100.0,
                    quantity=float(item.get("count", 1.0)),
                ))
            except Exception as e:
                logger.debug(f"Error parsing trade: {e}")
        return trades
