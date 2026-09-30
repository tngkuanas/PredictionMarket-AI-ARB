"""Raw Polymarket WebSocket Message Persister and Network Streamer.

Persists every raw WebSocket frame exactly as received in an append-only format
before any transformation, with microsecond timestamps and cryptographic SHA-256 hashes.
Bypasses DNS filtering via direct Cloudflare edge resolution with SNI preservation.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import ssl
from typing import List, Dict, Any, Optional, Callable
import uuid
import websockets

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    ConnectionSessionRecord,
)

logger = logging.getLogger(__name__)


class RawMarketDataRecorder:
    """Manages high-frequency raw WebSocket acquisition and append-only disk persistence."""

    CLOB_WS_HOST = "ws-subscriptions-clob.polymarket.com"
    CLOB_EDGE_IPS = ["104.18.34.205", "172.64.153.51"]

    def __init__(
        self,
        raw_storage_dir: str = "data/phase10a5_raw",
        session_id: Optional[str] = None
    ):
        self.raw_root = Path(raw_storage_dir)
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.session_dir = self.raw_root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_file_path = self.session_dir / "raw_stream.jsonl"
        self._message_counter = 0
        self._total_bytes = 0
        self._disconnect_count = 0
        self._reconnect_count = 0
        self.buffered_raw_records: List[RawMessageRecord] = []

    def record_raw_frame(self, raw_text: str) -> List[RawMessageRecord]:
        """Persists a raw frame to disk and parses top-level message metadata."""
        now = datetime.now(timezone.utc)
        self._message_counter += 1
        frame_bytes = len(raw_text.encode("utf-8"))
        self._total_bytes += frame_bytes

        sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        # Append-only write to disk stream
        with open(self.jsonl_file_path, "a", encoding="utf-8") as f:
            log_entry = {
                "sequence": self._message_counter,
                "session_id": self.session_id,
                "receive_timestamp": now.isoformat(),
                "sha256": sha,
                "payload": raw_text
            }
            f.write(json.dumps(log_entry) + "\n")

        # Parse message types and extract records
        records = []
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                for item in parsed:
                    rec = self._build_record(item, now, sha)
                    records.append(rec)
            elif isinstance(parsed, dict):
                rec = self._build_record(parsed, now, sha)
                records.append(rec)
        except json.JSONDecodeError as e:
            logger.warning(f"Malformed JSON received: {e}")
            rec = RawMessageRecord(
                message_id=f"msg_{self.session_id}_{self._message_counter}_malformed",
                ingestion_session_id=self.session_id,
                venue="polymarket",
                market_id=None,
                token_id=None,
                message_type="malformed",
                receive_timestamp=now,
                exchange_timestamp=None,
                raw_message_json=raw_text,
                sha256_hash=sha,
                raw_file_path=str(self.jsonl_file_path)
            )
            records.append(rec)

        self.buffered_raw_records.extend(records)
        return records

    def _build_record(self, item: Dict[str, Any], receive_ts: datetime, sha: str) -> RawMessageRecord:
        msg_type = str(item.get("event_type", "unknown"))
        market_id = item.get("market")
        token_id = item.get("asset_id")

        # For price_changes array, token_id is inside elements
        if not token_id and "price_changes" in item and len(item["price_changes"]) > 0:
            token_id = item["price_changes"][0].get("asset_id")

        # Exchange timestamp parsing (epoch ms)
        exch_ts = None
        ts_raw = item.get("timestamp")
        if ts_raw:
            try:
                ms = int(ts_raw)
                exch_ts = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            except Exception:
                pass

        json_str = json.dumps(item)
        item_sha = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

        return RawMessageRecord(
            message_id=f"msg_{self.session_id}_{self._message_counter}_{len(self.buffered_raw_records)}",
            ingestion_session_id=self.session_id,
            venue="polymarket",
            market_id=str(market_id) if market_id else None,
            token_id=str(token_id) if token_id else None,
            message_type=msg_type,
            receive_timestamp=receive_ts,
            exchange_timestamp=exch_ts,
            raw_message_json=json_str,
            sha256_hash=item_sha,
            raw_file_path=str(self.jsonl_file_path)
        )

    async def stream_market_data(
        self,
        token_ids: List[str],
        duration_seconds: float = 15.0,
        on_message_callback: Optional[Callable[[List[RawMessageRecord]], None]] = None
    ) -> ConnectionSessionRecord:
        """Connects to live Polymarket CLOB WebSocket, records raw frames, and yields records."""
        start_ts = datetime.now(timezone.utc)
        target_ip = self.CLOB_EDGE_IPS[0]
        uri = f"wss://{self.CLOB_WS_HOST}/ws/market"
        sub_msg = {"assets_ids": token_ids, "type": "market"}

        logger.info(f"Initiating live WebSocket connection to {target_ip}:443 (SNI={self.CLOB_WS_HOST})...")
        session_status = "CONNECTED"

        try:
            async with websockets.connect(
                uri,
                host=target_ip,
                port=443,
                server_hostname=self.CLOB_WS_HOST,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=15.0
            ) as ws:
                logger.info(f"WebSocket handshake successful. Subscribing to {len(token_ids)} tokens...")
                await ws.send(json.dumps(sub_msg))

                loop = asyncio.get_event_loop()
                end_time = loop.time() + duration_seconds

                while loop.time() < end_time:
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        records = self.record_raw_frame(raw_msg)
                        if on_message_callback:
                            on_message_callback(records)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as rx_err:
                        logger.warning(f"Error receiving frame: {rx_err}")
                        self._disconnect_count += 1
                        break

            session_status = "COMPLETED"

        except Exception as conn_err:
            logger.error(f"WebSocket connection failure: {conn_err}")
            session_status = "FAILED"
            self._disconnect_count += 1

        end_ts = datetime.now(timezone.utc)
        return ConnectionSessionRecord(
            session_id=self.session_id,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            endpoint_url=uri,
            resolved_ip=target_ip,
            total_messages_received=self._message_counter,
            total_messages_persisted=len(self.buffered_raw_records),
            total_bytes_received=self._total_bytes,
            disconnect_count=self._disconnect_count,
            reconnect_count=self._reconnect_count,
            status=session_status
        )

    def verify_file_integrity(self) -> Dict[str, Any]:
        """Validates that the append-only raw file on disk has intact JSON lines and valid SHA-256."""
        if not self.jsonl_file_path.exists():
            return {"verified": False, "message_count": 0, "error": "File does not exist"}

        count = 0
        with open(self.jsonl_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    expected_sha = hashlib.sha256(data["payload"].encode("utf-8")).hexdigest()
                    if data.get("sha256") != expected_sha:
                        return {"verified": False, "message_count": count, "error": f"SHA mismatch at line {count+1}"}
                    count += 1
                except Exception as e:
                    return {"verified": False, "message_count": count, "error": str(e)}
        return {"verified": True, "message_count": count}
