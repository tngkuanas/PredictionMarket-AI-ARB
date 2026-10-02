"""L2 Order Book Parsing and Microstructure Feature Extraction for Phase 10A.8.

Responsibilities:
1. Parse and validate raw L2 bid/ask ladders without lookahead.
2. Calculate top-of-book metrics: best bid, best ask, midpoint, spread bps.
3. Calculate multi-level depth and book order-flow imbalance.
4. Calculate exact queue depth ahead for hypothetical passive orders.
5. Classify descriptive market-state regimes (spread, depth, imbalance, probability).
"""

import json
from typing import Dict, Any, List, Optional, Tuple, Union
from src.phase10a8.schema import (
    QuoteSide,
    SpreadRegime,
    DepthRegime,
    ImbalanceRegime,
    ProbabilityRegime,
)


class BookFeatureExtractor:
    """Extracts features from level-2 book snapshots."""

    @staticmethod
    def parse_ladder(ladder_raw: Union[str, List[Any], None]) -> List[Dict[str, float]]:
        """Parses and normalizes order book ladder from JSON string or list."""
        if not ladder_raw:
            return []
        if isinstance(ladder_raw, str):
            try:
                data = json.loads(ladder_raw)
            except Exception:
                return []
        elif isinstance(ladder_raw, list):
            data = ladder_raw
        else:
            return []

        clean_ladder = []
        for level in data:
            if isinstance(level, dict):
                p = float(level.get("price", 0.0))
                s = float(level.get("size", 0.0))
                u = float(level.get("size_usd", p * s))
                if p > 0.0 and s > 0.0:
                    clean_ladder.append({"price": round(p, 4), "size": round(s, 4), "size_usd": round(u, 4)})
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                p = float(level[0])
                s = float(level[1])
                if p > 0.0 and s > 0.0:
                    clean_ladder.append({"price": round(p, 4), "size": round(s, 4), "size_usd": round(p * s, 4)})
        return clean_ladder

    @classmethod
    def extract_features(
        cls,
        bids_raw: Union[str, List[Any], None],
        asks_raw: Union[str, List[Any], None],
    ) -> Dict[str, Any]:
        """Extracts complete L2 microstructure features."""
        bids = cls.parse_ladder(bids_raw)
        asks = cls.parse_ladder(asks_raw)

        # Sort bids descending, asks ascending
        bids = sorted(bids, key=lambda x: x["price"], reverse=True)
        asks = sorted(asks, key=lambda x: x["price"], reverse=False)

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 1.0
        midpoint = round((best_bid + best_ask) / 2.0, 6) if (bids and asks) else 0.50

        # Spread bps
        if midpoint > 0.0 and asks and bids and best_ask > best_bid:
            spread_bps = round(((best_ask - best_bid) / midpoint) * 10000.0, 2)
        else:
            spread_bps = 0.0

        # Depth
        depth_bid_usd = sum(level["size_usd"] for level in bids)
        depth_ask_usd = sum(level["size_usd"] for level in asks)
        total_depth_usd = depth_bid_usd + depth_ask_usd

        # Imbalance [-1.0, 1.0]
        if total_depth_usd > 0.0:
            book_imbalance = round((depth_bid_usd - depth_ask_usd) / total_depth_usd, 4)
        else:
            book_imbalance = 0.0

        # Regimes
        spread_regime = cls.classify_spread_regime(spread_bps)
        depth_regime = cls.classify_depth_regime(total_depth_usd)
        imbalance_regime = cls.classify_imbalance_regime(book_imbalance)
        prob_regime = cls.classify_probability_regime(midpoint)

        return {
            "bids": bids,
            "asks": asks,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "midpoint": midpoint,
            "spread_bps": spread_bps,
            "depth_bid_usd": depth_bid_usd,
            "depth_ask_usd": depth_ask_usd,
            "total_depth_usd": total_depth_usd,
            "book_imbalance": book_imbalance,
            "spread_regime": spread_regime,
            "depth_regime": depth_regime,
            "imbalance_regime": imbalance_regime,
            "probability_regime": prob_regime,
            "is_valid": (best_bid > 0.0 and best_ask > 0.0 and best_ask > best_bid),
        }

    @staticmethod
    def get_queue_depth_ahead(
        ladder: List[Dict[str, float]],
        side: QuoteSide,
        quote_price: float,
        join_back: bool = True,
    ) -> float:
        """Calculates observable queue depth ahead of our order in USD.
        
        For a BUY order at quote_price:
          - Any bids strictly higher than quote_price have priority.
          - If join_back is True, any existing displayed bids AT quote_price also have priority.
        
        For a SELL order at quote_price:
          - Any asks strictly lower than quote_price have priority.
          - If join_back is True, any existing displayed asks AT quote_price also have priority.
        """
        depth_ahead_usd = 0.0
        for level in ladder:
            p = level["price"]
            u = level["size_usd"]
            if side == QuoteSide.BUY:
                if p > quote_price:
                    depth_ahead_usd += u
                elif abs(p - quote_price) < 1e-5 and join_back:
                    depth_ahead_usd += u
            else:  # SELL
                if p < quote_price:
                    depth_ahead_usd += u
                elif abs(p - quote_price) < 1e-5 and join_back:
                    depth_ahead_usd += u
        return round(depth_ahead_usd, 4)

    @staticmethod
    def classify_spread_regime(spread_bps: float) -> SpreadRegime:
        if spread_bps < 100.0:
            return SpreadRegime.NARROW
        elif spread_bps <= 300.0:
            return SpreadRegime.MEDIUM
        return SpreadRegime.WIDE

    @staticmethod
    def classify_depth_regime(total_depth_usd: float) -> DepthRegime:
        if total_depth_usd < 500.0:
            return DepthRegime.SHALLOW
        elif total_depth_usd <= 2500.0:
            return DepthRegime.MEDIUM
        return DepthRegime.DEEP

    @staticmethod
    def classify_imbalance_regime(imbalance: float) -> ImbalanceRegime:
        if imbalance < -0.30:
            return ImbalanceRegime.SELL_PRESSURE
        elif imbalance <= 0.30:
            return ImbalanceRegime.NEUTRAL
        return ImbalanceRegime.BUY_PRESSURE

    @staticmethod
    def classify_probability_regime(midpoint: float) -> ProbabilityRegime:
        if midpoint < 0.10:
            return ProbabilityRegime.P_00_10
        elif midpoint < 0.25:
            return ProbabilityRegime.P_10_25
        elif midpoint < 0.50:
            return ProbabilityRegime.P_25_50
        elif midpoint < 0.75:
            return ProbabilityRegime.P_50_75
        elif midpoint < 0.90:
            return ProbabilityRegime.P_75_90
        return ProbabilityRegime.P_90_100
