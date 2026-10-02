"""Trade Feature Extraction and Pre-Quote Flow Metrics for Phase 10A.8.

Responsibilities:
1. Calculate signed trade flow, volume, and trade intensity without lookahead.
2. Measure short-term price volatility and velocity over pre-quote lookback windows.
3. Provide descriptive pre-trade toxicity signals.
"""

from datetime import datetime, timedelta
import math
from typing import Dict, Any, List, Optional
import numpy as np


class TradeFeatureExtractor:
    """Computes pre-quote trade flow and volatility features."""

    @staticmethod
    def extract_features(
        trades: List[Dict[str, Any]],
        quote_timestamp: datetime,
        lookback_seconds: float = 60.0,
    ) -> Dict[str, Any]:
        """Extracts pre-quote trade features strictly for trades with timestamp <= quote_timestamp."""
        cutoff = quote_timestamp - timedelta(seconds=lookback_seconds)
        
        # Filter trades in window [cutoff, quote_timestamp]
        window_trades = [
            t for t in trades
            if cutoff <= t["receive_timestamp"] <= quote_timestamp
        ]

        if not window_trades:
            return {
                "recent_trade_flow_usd": 0.0,
                "recent_trade_volume_usd": 0.0,
                "recent_trade_count": 0,
                "recent_trade_intensity": 0.0,
                "recent_volatility_bps": 0.0,
                "price_velocity_bps": 0.0,
            }

        buy_vol = sum(t["size_usd"] for t in window_trades if t.get("side") == "BUY")
        sell_vol = sum(t["size_usd"] for t in window_trades if t.get("side") == "SELL")
        total_vol = sum(t["size_usd"] for t in window_trades)
        signed_flow = buy_vol - sell_vol

        trade_count = len(window_trades)
        trade_intensity = trade_count / (lookback_seconds / 60.0)  # trades per minute

        # Price metrics
        prices = [t["price"] for t in window_trades if t["price"] > 0]
        if len(prices) >= 2:
            mean_p = float(np.mean(prices))
            std_p = float(np.std(prices))
            volatility_bps = round((std_p / mean_p) * 10000.0, 2) if mean_p > 0 else 0.0
            p_first = prices[0]
            p_last = prices[-1]
            price_velocity_bps = round(((p_last - p_first) / p_first) * 10000.0, 2) if p_first > 0 else 0.0
        else:
            volatility_bps = 0.0
            price_velocity_bps = 0.0

        return {
            "recent_trade_flow_usd": round(signed_flow, 4),
            "recent_trade_volume_usd": round(total_vol, 4),
            "recent_trade_count": trade_count,
            "recent_trade_intensity": round(trade_intensity, 2),
            "recent_volatility_bps": volatility_bps,
            "price_velocity_bps": price_velocity_bps,
        }
