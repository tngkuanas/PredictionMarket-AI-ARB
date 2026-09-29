"""Base market data client."""
import abc
import socket
import logging
from typing import List, Optional, Dict, Any
from src.normalization.schema import Market, Observation, Trade

logger = logging.getLogger(__name__)

# Transparent DNS fallback for regions with ISP DNS filtering
_DNS_FALLBACK_MAP = {
    "gamma-api.polymarket.com": "104.18.34.205",
    "clob.polymarket.com": "104.18.34.205",
}

_ORIGINAL_GETADDRINFO = socket.getaddrinfo

def _safe_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        res = _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)
        # Check if resolved to known ISP blackhole IP (e.g. 175.139.142.25)
        if any("175.139." in str(addr[4]) for addr in res if len(addr) > 4 and isinstance(addr[4], tuple)):
            if host in _DNS_FALLBACK_MAP:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (_DNS_FALLBACK_MAP[host], port))]
        return res
    except Exception:
        if host in _DNS_FALLBACK_MAP:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (_DNS_FALLBACK_MAP[host], port))]
        raise

# Enable DNS fallback globally
socket.getaddrinfo = _safe_getaddrinfo

class BaseMarketClient(abc.ABC):
    """Abstract interface for prediction market platforms."""

    @abc.abstractmethod
    def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> List[Market]:
        """Fetch currently active markets with metadata."""
        pass

    @abc.abstractmethod
    def fetch_market_by_id(self, market_id: str) -> Optional[Market]:
        """Fetch metadata for a specific market."""
        pass

    @abc.abstractmethod
    def fetch_order_book(self, market_id: str) -> Dict[str, Any]:
        """Fetch live order book depth (bids and asks)."""
        pass

    @abc.abstractmethod
    def fetch_price_history(self, market_id: str, interval: str = "1h", fidelity_minutes: int = 60) -> List[Observation]:
        """Fetch historical price snapshots."""
        pass

    @abc.abstractmethod
    def fetch_recent_trades(self, market_id: str, limit: int = 50) -> List[Trade]:
        """Fetch recent trades executed on the market."""
        pass
