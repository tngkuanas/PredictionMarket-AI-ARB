"""Conservative Historical Passive Fill Model for Phase 10A.8.

Responsibilities:
1. Rigorous evaluation of hypothetical passive fills against genuine historical trades and book evolutions.
2. Enforce 4 distinct cases:
   - Case A: Trade-Through (genuine trades strictly beyond quote price)
   - Case B: Touch (trades at quote price evaluated against queue ahead)
   - Case C: Quote Disappearance (book movement without trades -> NOT A FILL)
   - Case D: Ambiguous (data gaps, unverified sequence -> AMBIGUOUS, non-profitable)
3. Support Queue Models Q1 (Back of Queue), Q2 (Conservative Partial), Q3 (Worst Case).
4. Strictly prevent retroactive fill manufacture.
"""

from datetime import datetime, timedelta
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from src.phase10a8.schema import (
    QuoteSide,
    QueueModelType,
    FillStatus,
    FillMechanism,
    PassiveQuote,
    FillResult,
)


class ConservativePassiveFillModel:
    """Evaluates whether and how a hypothetical passive quote was filled by historical market data."""

    def __init__(
        self,
        queue_model: QueueModelType = QueueModelType.Q1_BACK_OF_QUEUE,
        max_holding_seconds: float = 60.0,
    ):
        self.queue_model = queue_model
        self.max_holding_seconds = max_holding_seconds

    def evaluate_fill(
        self,
        quote: PassiveQuote,
        subsequent_trades: List[Dict[str, Any]],
        subsequent_snapshots: Optional[List[Dict[str, Any]]] = None,
    ) -> FillResult:
        """Evaluates fill status for a quote using subsequent genuine trades and book updates."""
        quote_t = quote.timestamp
        max_t = quote_t + timedelta(seconds=self.max_holding_seconds)
        subsequent_snapshots = subsequent_snapshots or []

        # Filter relevant trades strictly after quote timestamp and within max holding horizon
        relevant_trades = [
            t for t in subsequent_trades
            if t["market_id"] == quote.market_id
            and t["token_id"] == quote.token_id
            and quote_t < t["receive_timestamp"] <= max_t
        ]

        # Case D: Check for data anomalies or ambiguity
        if subsequent_snapshots:
            # Check for large time gaps > 15s where market state is unobserved
            for i in range(1, len(subsequent_snapshots)):
                dt = (subsequent_snapshots[i]["timestamp"] - subsequent_snapshots[i - 1]["timestamp"]).total_seconds()
                if dt > 15.0:
                    return self._make_ambiguous_result(quote, "Data gap in snapshots exceeding 15s")

        # Track cumulative volumes
        trade_through_vol = 0.0
        touch_vol = 0.0
        trade_count = len(relevant_trades)
        queue_ahead = quote.queue_depth_ahead_usd
        order_size = quote.quote_size_usd
        price = quote.quote_price
        side = quote.side

        first_fill_time: Optional[datetime] = None
        fill_status = FillStatus.UNFILLED
        fill_mechanism = FillMechanism.NONE
        fill_size = 0.0

        for t in relevant_trades:
            trade_p = round(float(t["price"]), 4)
            trade_vol = float(t["size_usd"])
            trade_t = t["receive_timestamp"]
            trade_side = t.get("side", "")

            # Check trade relationship to quote
            is_trade_through = False
            is_touch = False

            if side == QuoteSide.BUY:
                # BUY quote is filled by market selling into it
                # Trade-through: trade at price strictly lower than quote_price
                if trade_p < price:
                    is_trade_through = True
                elif abs(trade_p - price) < 1e-5:
                    is_touch = True
            else:  # QuoteSide.SELL
                # SELL quote is filled by market buying into it
                # Trade-through: trade at price strictly higher than quote_price
                if trade_p > price:
                    is_trade_through = True
                elif abs(trade_p - price) < 1e-5:
                    is_touch = True

            if is_trade_through:
                trade_through_vol += trade_vol
                if not first_fill_time:
                    first_fill_time = trade_t

                # In Case A: Trade-Through
                if self.queue_model == QueueModelType.Q1_BACK_OF_QUEUE:
                    # Trade-through proves price traded through level
                    fill_status = FillStatus.FILLED
                    fill_mechanism = FillMechanism.TRADE_THROUGH
                    fill_size = order_size
                    break
                elif self.queue_model == QueueModelType.Q2_CONSERVATIVE_PARTIAL:
                    cum_vol = trade_through_vol + touch_vol
                    if cum_vol >= queue_ahead + order_size:
                        fill_status = FillStatus.FILLED
                        fill_mechanism = FillMechanism.TRADE_THROUGH
                        fill_size = order_size
                        break
                    elif cum_vol > queue_ahead:
                        fill_status = FillStatus.PARTIALLY_FILLED
                        fill_mechanism = FillMechanism.TRADE_THROUGH
                        fill_size = min(order_size, cum_vol - queue_ahead)
                elif self.queue_model == QueueModelType.Q3_WORST_CASE:
                    if trade_through_vol >= queue_ahead + order_size:
                        fill_status = FillStatus.FILLED
                        fill_mechanism = FillMechanism.TRADE_THROUGH
                        fill_size = order_size
                        break

            elif is_touch:
                touch_vol += trade_vol
                cum_vol = touch_vol

                # In Case B: Touch
                if self.queue_model == QueueModelType.Q1_BACK_OF_QUEUE:
                    if cum_vol >= queue_ahead + order_size:
                        fill_status = FillStatus.FILLED
                        fill_mechanism = FillMechanism.TOUCH_VOLUME
                        fill_size = order_size
                        if not first_fill_time:
                            first_fill_time = trade_t
                        break
                    elif cum_vol > queue_ahead:
                        fill_status = FillStatus.PARTIALLY_FILLED
                        fill_mechanism = FillMechanism.TOUCH_VOLUME
                        fill_size = min(order_size, cum_vol - queue_ahead)
                        if not first_fill_time:
                            first_fill_time = trade_t
                elif self.queue_model == QueueModelType.Q2_CONSERVATIVE_PARTIAL:
                    if cum_vol > queue_ahead:
                        fill_status = FillStatus.PARTIALLY_FILLED
                        fill_mechanism = FillMechanism.TOUCH_VOLUME
                        fill_size = min(order_size, (cum_vol - queue_ahead) * 0.75)
                        if not first_fill_time:
                            first_fill_time = trade_t
                        if fill_size >= order_size:
                            fill_status = FillStatus.FILLED
                            break
                elif self.queue_model == QueueModelType.Q3_WORST_CASE:
                    # Worst case: Touch alone rarely fills under worst case
                    if cum_vol >= (queue_ahead + order_size) * 1.5:
                        fill_status = FillStatus.FILLED
                        fill_mechanism = FillMechanism.TOUCH_VOLUME
                        fill_size = order_size
                        if not first_fill_time:
                            first_fill_time = trade_t
                        break

        # Check Case C: Quote Disappearance without trades
        if fill_status == FillStatus.UNFILLED and subsequent_snapshots:
            for s in subsequent_snapshots:
                if s["timestamp"] > quote_t:
                    # Check if book moved away
                    b_bid = s.get("best_bid", 0.0)
                    b_ask = s.get("best_ask", 1.0)
                    if side == QuoteSide.BUY and b_bid < price - 0.005:
                        # Price dropped without trades -> Quote disappeared / cancelled
                        fill_mechanism = FillMechanism.QUOTE_DISAPPEARED
                        break
                    elif side == QuoteSide.SELL and b_ask > price + 0.005:
                        # Price rose without trades -> Quote disappeared / cancelled
                        fill_mechanism = FillMechanism.QUOTE_DISAPPEARED
                        break

        time_to_fill_ms = None
        if first_fill_time:
            time_to_fill_ms = max(0.0, (first_fill_time - quote_t).total_seconds() * 1000.0)

        shares = fill_size / price if (price > 0 and fill_size > 0) else 0.0

        fid = hashlib.sha256(
            f"{quote.quote_id}_{self.queue_model.value}_{fill_status.value}_{fill_size}".encode()
        ).hexdigest()[:24]

        return FillResult(
            fill_id=fid,
            quote_id=quote.quote_id,
            fill_status=fill_status,
            fill_mechanism=fill_mechanism,
            queue_model=self.queue_model,
            fill_timestamp=first_fill_time,
            fill_price=price,
            fill_size_usd=round(fill_size, 4),
            fill_shares=round(shares, 4),
            queue_depth_ahead_usd=queue_ahead,
            subsequent_trade_count=trade_count,
            trade_through_volume_usd=round(trade_through_vol, 4),
            touch_volume_usd=round(touch_vol, 4),
            time_to_fill_ms=time_to_fill_ms,
            provenance="POLYMARKET_LIVE",
        )

    def _make_ambiguous_result(self, quote: PassiveQuote, reason: str) -> FillResult:
        """Constructs an ambiguous fill record."""
        fid = hashlib.sha256(f"{quote.quote_id}_{self.queue_model.value}_AMBIGUOUS".encode()).hexdigest()[:24]
        return FillResult(
            fill_id=fid,
            quote_id=quote.quote_id,
            fill_status=FillStatus.AMBIGUOUS,
            fill_mechanism=FillMechanism.NONE,
            queue_model=self.queue_model,
            fill_price=quote.quote_price,
            fill_size_usd=0.0,
            fill_shares=0.0,
            queue_depth_ahead_usd=quote.queue_depth_ahead_usd,
            subsequent_trade_count=0,
            provenance="POLYMARKET_LIVE",
        )
