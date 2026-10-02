"""Hypothetical Passive Quote Simulator for Phase 10A.8.

Responsibilities:
1. Generate hypothetical quotes according to policies M1, M2, M3.
2. Determine displayed queue depth ahead directly from observable L2 book ladders.
3. Attach pre-quote microstructure and trade-flow context.
4. Maintain strict provenance and immutability.
"""

from datetime import datetime
import hashlib
from typing import Dict, Any, List, Optional
from src.phase10a8.schema import (
    QuoteSide,
    QuotePolicy,
    PassiveQuote,
)
from src.phase10a8.book_features import BookFeatureExtractor


class PassiveQuoteSimulator:
    """Generates candidate hypothetical passive quotes from L2 snapshots."""

    def __init__(self, quote_size_usd: float = 50.0, tick_size: float = 0.01):
        self.quote_size_usd = quote_size_usd
        self.tick_size = tick_size

    def generate_quotes_for_snapshot(
        self,
        snapshot: Dict[str, Any],
        trade_features: Optional[Dict[str, Any]] = None,
        policies: Optional[List[QuotePolicy]] = None,
        is_out_of_sample: bool = False,
    ) -> List[PassiveQuote]:
        """Generates BUY and SELL quotes under specified policies for a valid book snapshot."""
        if not snapshot.get("best_bid") or not snapshot.get("best_ask"):
            return []
        
        bids_raw = snapshot.get("bids")
        asks_raw = snapshot.get("asks")
        book_feats = BookFeatureExtractor.extract_features(bids_raw, asks_raw)
        if not book_feats["is_valid"]:
            return []

        best_bid = book_feats["best_bid"]
        best_ask = book_feats["best_ask"]
        midpoint = book_feats["midpoint"]
        spread_bps = book_feats["spread_bps"]
        book_imbalance = book_feats["book_imbalance"]

        tf = trade_features or {
            "recent_trade_flow_usd": 0.0,
            "recent_volatility_bps": 0.0,
            "recent_trade_intensity": 0.0,
        }

        policies = policies or [
            QuotePolicy.M1_BEST_PRICE,
            QuotePolicy.M2_ONE_TICK_AWAY,
            QuotePolicy.M3_TWO_TICKS_AWAY,
        ]

        quotes: List[PassiveQuote] = []
        market_id = snapshot["market_id"]
        token_id = snapshot["token_id"]
        timestamp = snapshot["timestamp"]
        snapshot_id = snapshot.get("snapshot_id", "")
        session_id = snapshot.get("session_id", "live_session")

        for policy in policies:
            # Determine quote prices
            if policy == QuotePolicy.M1_BEST_PRICE:
                bid_px = round(best_bid, 4)
                ask_px = round(best_ask, 4)
            elif policy == QuotePolicy.M2_ONE_TICK_AWAY:
                bid_px = round(best_bid - self.tick_size, 4)
                ask_px = round(best_ask + self.tick_size, 4)
            elif policy == QuotePolicy.M3_TWO_TICKS_AWAY:
                bid_px = round(best_bid - 2.0 * self.tick_size, 4)
                ask_px = round(best_ask + 2.0 * self.tick_size, 4)
            else:
                continue

            # Generate BUY Quote
            if 0.001 < bid_px < 0.999:
                queue_ahead_bid = BookFeatureExtractor.get_queue_depth_ahead(
                    book_feats["bids"], QuoteSide.BUY, bid_px, join_back=True
                )
                qid_buy = hashlib.sha256(
                    f"{snapshot_id}_BUY_{policy.value}_{bid_px}".encode()
                ).hexdigest()[:24]

                quotes.append(
                    PassiveQuote(
                        quote_id=qid_buy,
                        market_id=market_id,
                        token_id=token_id,
                        timestamp=timestamp,
                        side=QuoteSide.BUY,
                        policy=policy,
                        quote_price=bid_px,
                        quote_size_usd=self.quote_size_usd,
                        queue_depth_ahead_usd=queue_ahead_bid,
                        spread_bps=spread_bps,
                        midpoint=midpoint,
                        book_imbalance=book_imbalance,
                        recent_trade_flow_usd=tf.get("recent_trade_flow_usd", 0.0),
                        recent_volatility_bps=tf.get("recent_volatility_bps", 0.0),
                        recent_trade_intensity=tf.get("recent_trade_intensity", 0.0),
                        snapshot_id=snapshot_id,
                        session_id=session_id,
                        is_out_of_sample=is_out_of_sample,
                        provenance="POLYMARKET_LIVE",
                    )
                )

            # Generate SELL Quote
            if 0.001 < ask_px < 0.999:
                queue_ahead_ask = BookFeatureExtractor.get_queue_depth_ahead(
                    book_feats["asks"], QuoteSide.SELL, ask_px, join_back=True
                )
                qid_sell = hashlib.sha256(
                    f"{snapshot_id}_SELL_{policy.value}_{ask_px}".encode()
                ).hexdigest()[:24]

                quotes.append(
                    PassiveQuote(
                        quote_id=qid_sell,
                        market_id=market_id,
                        token_id=token_id,
                        timestamp=timestamp,
                        side=QuoteSide.SELL,
                        policy=policy,
                        quote_price=ask_px,
                        quote_size_usd=self.quote_size_usd,
                        queue_depth_ahead_usd=queue_ahead_ask,
                        spread_bps=spread_bps,
                        midpoint=midpoint,
                        book_imbalance=book_imbalance,
                        recent_trade_flow_usd=tf.get("recent_trade_flow_usd", 0.0),
                        recent_volatility_bps=tf.get("recent_volatility_bps", 0.0),
                        recent_trade_intensity=tf.get("recent_trade_intensity", 0.0),
                        snapshot_id=snapshot_id,
                        session_id=session_id,
                        is_out_of_sample=is_out_of_sample,
                        provenance="POLYMARKET_LIVE",
                    )
                )

        return quotes
