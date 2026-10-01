"""Kalshi Raw WebSocket Message Persister and Recorder.

Persists every raw WebSocket payload exactly as received in an append-only JSONL format
before any mutation or transformation, with microsecond timestamps and SHA-256 hashes.
"""
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import uuid

from src.kalshi.schema import KalshiRawMessageRecord

logger = logging.getLogger(__name__)


class KalshiRawRecorder:
    """Manages raw Kalshi WebSocket payload logging, hashing, and memory buffering."""

    def __init__(
        self,
        raw_storage_dir: str = "data/raw/kalshi_ws",
        session_id: Optional[str] = None
    ):
        self.raw_root = Path(raw_storage_dir)
        self.session_id = session_id or f"kalshi_sess_{uuid.uuid4().hex[:12]}"
        self.session_dir = self.raw_root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_file_path = self.session_dir / "raw_stream.jsonl"
        self._message_counter = 0
        self._total_bytes = 0
        self.buffered_raw_records: List[KalshiRawMessageRecord] = []

    def clear_buffer(self) -> None:
        """Clears memory buffer after persisting to database."""
        self.buffered_raw_records.clear()

    def record_raw_frame(
        self,
        raw_text: str,
        channel_hint: Optional[str] = None
    ) -> List[KalshiRawMessageRecord]:
        """Persists a raw payload to disk stream and builds raw message records."""
        now = datetime.now(timezone.utc)
        self._message_counter += 1
        frame_bytes = len(raw_text.encode("utf-8"))
        self._total_bytes += frame_bytes

        sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        # Append-only write to disk log
        with open(self.jsonl_file_path, "a", encoding="utf-8") as f:
            log_entry = {
                "sequence": self._message_counter,
                "session_id": self.session_id,
                "receive_timestamp": now.isoformat(),
                "sha256": sha,
                "payload": raw_text
            }
            f.write(json.dumps(log_entry) + "\n")

        records: List[KalshiRawMessageRecord] = []
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed):
                    rec = self._build_record(item, now, sha, raw_text, channel_hint, item_idx=idx)
                    records.append(rec)
            elif isinstance(parsed, dict):
                rec = self._build_record(parsed, now, sha, raw_text, channel_hint, item_idx=0)
                records.append(rec)
            else:
                # Primitive JSON
                rec = self._build_malformed_record(raw_text, now, sha, "Non-object JSON payload")
                records.append(rec)
        except json.JSONDecodeError as e:
            logger.warning(f"Malformed JSON in Kalshi stream: {e}")
            rec = self._build_malformed_record(raw_text, now, sha, f"JSONDecodeError: {str(e)}")
            records.append(rec)

        self.buffered_raw_records.extend(records)
        return records

    def _build_record(
        self,
        item: Dict[str, Any],
        receive_ts: datetime,
        sha: str,
        raw_text: str,
        channel_hint: Optional[str] = None,
        item_idx: int = 0
    ) -> KalshiRawMessageRecord:
        msg_type = str(item.get("type", "unknown"))
        channel = str(item.get("channel", channel_hint or msg_type))
        msg_data = item.get("msg", {}) if isinstance(item.get("msg"), dict) else item

        market_id = (
            msg_data.get("market_ticker") or
            msg_data.get("ticker") or
            item.get("market_ticker") or
            item.get("ticker") or
            msg_data.get("market_id")
        )
        if market_id:
            market_id = str(market_id)

        # Extract exchange timestamp if provided
        exch_ts: Optional[datetime] = None
        ts_val = (
            msg_data.get("ts_ms") or
            item.get("sending_ts_ms") or
            msg_data.get("ts") or
            msg_data.get("created_ts") or
            item.get("ts")
        )
        if ts_val is not None:
            try:
                if isinstance(ts_val, (int, float)):
                    # Distinguish milliseconds vs seconds
                    if ts_val > 1e11:
                        exch_ts = datetime.fromtimestamp(ts_val / 1000.0, tz=timezone.utc)
                    else:
                        exch_ts = datetime.fromtimestamp(float(ts_val), tz=timezone.utc)
                elif isinstance(ts_val, str):
                    if ts_val.isdigit():
                        iv = int(ts_val)
                        exch_ts = datetime.fromtimestamp(iv / 1000.0 if iv > 1e11 else iv, tz=timezone.utc)
                    else:
                        exch_ts = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            except Exception:
                exch_ts = None

        msg_id = f"kalshi_raw_{self.session_id}_{self._message_counter}_{item_idx}"
        return KalshiRawMessageRecord(
            raw_message_id=msg_id,
            session_id=self.session_id,
            receive_timestamp=receive_ts,
            exchange_timestamp=exch_ts,
            channel=channel,
            market_id=market_id,
            message_type=msg_type,
            raw_payload=raw_text,
            payload_sha256=sha,
            message_seq=self._message_counter
        )

    def _build_malformed_record(
        self,
        raw_text: str,
        receive_ts: datetime,
        sha: str,
        reason: str
    ) -> KalshiRawMessageRecord:
        msg_id = f"kalshi_raw_{self.session_id}_{self._message_counter}_malformed"
        return KalshiRawMessageRecord(
            raw_message_id=msg_id,
            session_id=self.session_id,
            receive_timestamp=receive_ts,
            exchange_timestamp=None,
            channel="unknown",
            market_id=None,
            message_type="malformed",
            raw_payload=raw_text,
            payload_sha256=sha,
            message_seq=self._message_counter
        )
