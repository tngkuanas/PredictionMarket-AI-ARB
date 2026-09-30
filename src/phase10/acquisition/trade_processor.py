"""Trade Stream Processor for Polymarket WebSocket Fills.

Parses, validates, and records genuine executed market trades emitted
via the `last_trade_price` event channel on the Polymarket CLOB WebSocket.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Optional, Dict, Any, List

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    GenuineTradeRecord,
    DataQualityStatus,
    DataQualityRecord,
)

logger = logging.getLogger(__name__)


class TradeStreamProcessor:
    """Parses and validates genuine executed trades from WebSocket frames."""

    def __init__(self):
        self.recorded_trades: List[GenuineTradeRecord] = []
        self.quality_anomalies: List[DataQualityRecord] = []
        self._seen_tx_hashes = set()

    def clear_buffers(self) -> None:
        """Clears accumulated trades buffer to bound memory and avoid quadratic re-persistence."""
        self.recorded_trades.clear()
        self.quality_anomalies.clear()

    def process_raw_trade(
        self,
        raw_rec: RawMessageRecord
    ) -> Optional[GenuineTradeRecord]:
        """Parses a raw message if event_type is last_trade_price."""
        if raw_rec.message_type != "last_trade_price":
            return None

        try:
            payload = json.loads(raw_rec.raw_message_json)
        except Exception as e:
            logger.warning(f"Error parsing raw trade JSON: {e}")
            return None

        market_id = str(payload.get("market") or raw_rec.market_id or "")
        token_id = str(payload.get("asset_id") or raw_rec.token_id or "")
        side = str(payload.get("side", "BUY")).upper()
        tx_hash = payload.get("transaction_hash")

        # Deduplication
        if tx_hash and tx_hash in self._seen_tx_hashes:
            return None
        if tx_hash:
            self._seen_tx_hashes.add(tx_hash)

        try:
            price = round(float(payload.get("price", 0.0)), 4)
            size = round(float(payload.get("size", 0.0)), 4)
            fee_bps = float(payload.get("fee_rate_bps") or 0.0)
            
            # Validation
            if price <= 0.0 or price >= 1.0 or size <= 0.0:
                self.quality_anomalies.append(DataQualityRecord(
                    record_id=f"dq_tr_invalid_{raw_rec.message_id}",
                    session_id=raw_rec.ingestion_session_id,
                    market_id=market_id,
                    token_id=token_id,
                    timestamp=raw_rec.receive_timestamp,
                    status=DataQualityStatus.MALFORMED,
                    component="TRADE",
                    details=f"Invalid price ({price}) or size ({size})"
                ))
                return None

            size_usd = round(price * size, 2)

            # Exchange timestamp
            ms_raw = payload.get("timestamp")
            if ms_raw:
                ms = int(ms_raw)
                exch_ts = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            else:
                exch_ts = raw_rec.receive_timestamp

            trade_id = f"tr_{raw_rec.ingestion_session_id}_{len(self.recorded_trades) + 1}_{token_id[:8]}"
            trade = GenuineTradeRecord(
                trade_id=trade_id,
                session_id=raw_rec.ingestion_session_id,
                market_id=market_id,
                token_id=token_id,
                receive_timestamp=raw_rec.receive_timestamp,
                exchange_timestamp=exch_ts,
                price=price,
                size=size,
                size_usd=size_usd,
                side=side,
                fee_rate_bps=fee_bps,
                transaction_hash=tx_hash
            )
            self.recorded_trades.append(trade)
            return trade

        except Exception as ex:
            logger.warning(f"Error processing trade frame: {ex}")
            return None
