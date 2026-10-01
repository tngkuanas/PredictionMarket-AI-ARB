"""Kalshi Genuine Trade Stream Processor.

Parses genuine trade executions from Kalshi WebSocket messages without inferring trades
from order book movements. Preserves actual exchange flags (side, taker_side) and never
fabricates maker/taker classifications.
"""
from datetime import datetime, timezone
import json
import logging
from typing import List, Optional, Dict, Any
import uuid

from src.kalshi.schema import (
    KalshiRawMessageRecord,
    KalshiTradeRecord,
    KalshiDataQualityRecord,
    KalshiDataQualityStatus,
)

logger = logging.getLogger(__name__)


class KalshiTradeProcessor:
    """Processes genuine trade channel executions from Kalshi raw message stream."""

    def __init__(self):
        self.recorded_trades: List[KalshiTradeRecord] = []
        self.quality_anomalies: List[KalshiDataQualityRecord] = []

    def clear_buffers(self) -> None:
        """Clears accumulated trade buffers after persistence."""
        self.recorded_trades.clear()
        self.quality_anomalies.clear()

    def process_raw_trade(
        self,
        raw_rec: KalshiRawMessageRecord
    ) -> List[KalshiTradeRecord]:
        """Parses a raw message and extracts genuine trades if message_type is 'trade'."""
        if raw_rec.message_type != "trade":
            return []

        try:
            payload = json.loads(raw_rec.raw_payload)
        except Exception as e:
            logger.warning(f"Failed to parse trade JSON: {e}")
            return []

        msg_data = payload.get("msg", {}) if isinstance(payload.get("msg"), dict) else payload

        # Extract market id
        market_id = (
            msg_data.get("market_ticker") or
            msg_data.get("ticker") or
            raw_rec.market_id or
            payload.get("market_ticker") or
            payload.get("ticker")
        )
        if not market_id:
            logger.warning("Trade record missing market identifier.")
            return []
        market_id = str(market_id)

        # Extract price
        price_raw = (
            msg_data.get("price_dollars") or
            msg_data.get("price") or
            msg_data.get("yes_price") or
            payload.get("price")
        )
        if price_raw is None:
            self._log_anomaly(raw_rec, market_id, "Trade missing price field.")
            return []

        try:
            price = float(price_raw)
            if price > 1.0:
                price = price / 100.0
            price = round(price, 4)
        except (ValueError, TypeError):
            self._log_anomaly(raw_rec, market_id, f"Invalid trade price '{price_raw}'.")
            return []

        # Extract quantity
        qty_raw = (
            msg_data.get("count") or
            msg_data.get("quantity") or
            msg_data.get("amount") or
            payload.get("count") or
            1.0
        )
        try:
            quantity = float(qty_raw)
        except (ValueError, TypeError):
            quantity = 1.0

        # Extract trade side / taker side (never fabricate)
        side = msg_data.get("side") or payload.get("side")
        if side:
            side = str(side).lower()
        else:
            side = None

        taker_side = msg_data.get("taker_side") or payload.get("taker_side")
        if taker_side:
            taker_side = str(taker_side).lower()
        else:
            taker_side = None

        # Trade ID
        trade_id = (
            msg_data.get("trade_id") or
            payload.get("trade_id") or
            f"kalshi_trd_{raw_rec.session_id}_{len(self.recorded_trades) + 1}_{int(raw_rec.receive_timestamp.timestamp() * 1000)}"
        )

        trade = KalshiTradeRecord(
            trade_id=str(trade_id),
            session_id=raw_rec.session_id,
            market_id=market_id,
            price=price,
            quantity=quantity,
            side=side,
            taker_side=taker_side,
            exchange_timestamp=raw_rec.exchange_timestamp,
            receive_timestamp=raw_rec.receive_timestamp,
            raw_message_id=raw_rec.raw_message_id
        )

        self.recorded_trades.append(trade)
        return [trade]

    def _log_anomaly(self, raw_rec: KalshiRawMessageRecord, market_id: str, reason: str) -> None:
        rec = KalshiDataQualityRecord(
            record_id=f"dq_trd_{raw_rec.session_id}_{len(self.quality_anomalies) + 1}",
            session_id=raw_rec.session_id,
            market_id=market_id,
            timestamp=raw_rec.receive_timestamp,
            component="TRADE",
            status=KalshiDataQualityStatus.MALFORMED,
            details=reason
        )
        self.quality_anomalies.append(rec)
