"""Kalshi WebSocket Connection Supervisor and Session Manager.

Manages unattended-safe connection lifecycle, RSA-PSS authentication requirements,
heartbeat monitoring, subscription negotiation, failure detection, exponential
backoff with bounded retries, and explicit reconnect audit logging.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
import random
import time
from typing import Dict, List, Optional, Callable, Any
import uuid

from src.kalshi.schema import (
    KalshiSupervisorState,
    KalshiConnectionSessionRecord,
    KalshiReconnectEventRecord,
    KalshiDataQualityRecord,
    KalshiDataQualityStatus,
)

logger = logging.getLogger(__name__)


class KalshiConnectionSupervisor:
    """Production supervisor for Kalshi WebSocket connection lifecycle and resilience.

    WebSocket Interface Documentation:
    -----------------------------------
    - Production Endpoint: wss://external-api-ws.kalshi.com/trade-api/ws/v2
    - Demo Endpoint: wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2
    - Authentication:
        Headers during handshake:
        * KALSHI-ACCESS-KEY: API Key ID
        * KALSHI-ACCESS-TIMESTAMP: Unix timestamp milliseconds (string)
        * KALSHI-ACCESS-SIGNATURE: RSA-PSS with MGF1(SHA256) signature of `timestamp + "GET" + "/trade-api/ws/v2"`
    - Channels:
        * orderbook_delta: Delivers initial orderbook_snapshot followed by incremental deltas
        * trade: Delivers real executed trades
        * ticker: Delivers market ticker summary updates
    - Subscription Command:
        {"id": <req_id>, "cmd": "subscribe", "params": {"channels": ["orderbook_delta", "trade"], "market_tickers": [...]}}
    - Heartbeat:
        Ping/pong frame every 10 seconds.
    - Reconnect Behavior:
        On unexpected closure or network error, transitions through RECONNECTING with exponential backoff.
    """

    PROD_WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    DEMO_WS_URL = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        api_key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        max_reconnect_attempts: int = 10,
        initial_backoff_sec: float = 1.0,
        max_backoff_sec: float = 30.0,
        heartbeat_timeout_sec: float = 25.0,
    ):
        self.endpoint_url = endpoint_url or self.PROD_WS_URL
        self.api_key_id = api_key_id
        self.private_key_pem = private_key_pem
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_backoff_sec = initial_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.heartbeat_timeout_sec = heartbeat_timeout_sec

        self.current_state: KalshiSupervisorState = KalshiSupervisorState.STARTING
        self.session_id: str = f"kalshi_sess_{uuid.uuid4().hex[:12]}"
        self.start_timestamp: datetime = datetime.now(timezone.utc)
        self.end_timestamp: Optional[datetime] = None

        self.disconnect_count: int = 0
        self.reconnect_count: int = 0
        self.messages_received_count: int = 0
        self.messages_persisted_count: int = 0
        self.last_heartbeat_time: float = time.monotonic()

        self.reconnect_events: List[KalshiReconnectEventRecord] = []
        self.quality_anomalies: List[KalshiDataQualityRecord] = []
        self.state_listeners: List[Callable[[KalshiSupervisorState], None]] = []

    def register_state_listener(self, callback: Callable[[KalshiSupervisorState], None]) -> None:
        """Registers a callback for state transitions."""
        self.state_listeners.append(callback)

    def transition_to(self, new_state: KalshiSupervisorState, reason: str = "") -> None:
        """Transitions supervisor state with audit logging."""
        old_state = self.current_state
        self.current_state = new_state
        logger.info(f"KalshiSupervisor: State transition {old_state.value} -> {new_state.value} | Reason: {reason}")
        for listener in self.state_listeners:
            try:
                listener(new_state)
            except Exception as e:
                logger.error(f"Error in state listener: {e}")

    def generate_auth_headers(self) -> Dict[str, str]:
        """Generates required Kalshi authentication handshake headers.

        Raises ValueError if credentials are missing or unconfigured.
        """
        if not self.api_key_id or not self.private_key_pem:
            raise ValueError("Kalshi authentication credentials (api_key_id, private_key_pem) are not configured.")

        # Timestamp in milliseconds
        ts_ms = str(int(time.time() * 1000))
        message_to_sign = f"{ts_ms}GET/trade-api/ws/v2"

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            import base64

            priv_key = load_pem_private_key(self.private_key_pem.encode("utf-8"), password=None)
            signature = priv_key.sign(
                message_to_sign.encode("utf-8"),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            sig_b64 = base64.b64encode(signature).decode("utf-8")

            return {
                "KALSHI-ACCESS-KEY": self.api_key_id,
                "KALSHI-ACCESS-TIMESTAMP": ts_ms,
                "KALSHI-ACCESS-SIGNATURE": sig_b64,
            }
        except Exception as e:
            logger.error(f"Failed to generate RSA-PSS signature: {e}")
            raise RuntimeError(f"Authentication signature generation failed: {e}") from e

    def build_subscription_payload(
        self,
        channels: List[str],
        market_tickers: Optional[List[str]] = None,
        request_id: int = 1
    ) -> str:
        """Constructs subscription command JSON."""
        params: Dict[str, Any] = {"channels": channels}
        if market_tickers:
            params["market_tickers"] = market_tickers

        sub_msg = {
            "id": request_id,
            "cmd": "subscribe",
            "params": params
        }
        return json.dumps(sub_msg)

    def record_heartbeat(self) -> None:
        """Updates last seen heartbeat timestamp."""
        self.last_heartbeat_time = time.monotonic()

    def check_heartbeat(self) -> bool:
        """Checks if connection is dead due to missed heartbeats."""
        elapsed = time.monotonic() - self.last_heartbeat_time
        if elapsed > self.heartbeat_timeout_sec:
            logger.warning(f"Kalshi heartbeat timeout: {elapsed:.1f}s elapsed > {self.heartbeat_timeout_sec}s threshold.")
            self.transition_to(KalshiSupervisorState.DEGRADED, f"Heartbeat timed out ({elapsed:.1f}s)")
            return False
        return True

    def handle_disconnect(self, reason: str) -> None:
        """Handles socket disconnect, incrementing counters and marking state."""
        self.disconnect_count += 1
        disconnect_ts = datetime.now(timezone.utc)
        self.transition_to(KalshiSupervisorState.RECONNECTING, reason)

        # Log data quality anomaly
        self.quality_anomalies.append(KalshiDataQualityRecord(
            record_id=f"dq_disc_{self.session_id}_{self.disconnect_count}",
            session_id=self.session_id,
            market_id=None,
            timestamp=disconnect_ts,
            component="SUPERVISOR",
            status=KalshiDataQualityStatus.STALE,
            details=f"Disconnected: {reason}"
        ))

    def calculate_backoff(self, attempt: int) -> float:
        """Calculates exponential backoff with random jitter."""
        factor = min(self.max_backoff_sec, self.initial_backoff_sec * (2 ** (attempt - 1)))
        jitter = random.uniform(0.1, 0.5)
        return min(self.max_backoff_sec, factor + jitter)

    def record_reconnect_event(
        self,
        attempt: int,
        reason: str,
        latency_sec: float,
        success: bool,
        disconnect_ts: Optional[datetime] = None
    ) -> KalshiReconnectEventRecord:
        """Logs an explicit reconnect attempt event."""
        now = datetime.now(timezone.utc)
        disc_ts = disconnect_ts or now
        if success:
            self.reconnect_count += 1
            self.transition_to(KalshiSupervisorState.CONNECTED, f"Reconnected successfully on attempt {attempt}")
        else:
            if attempt >= self.max_reconnect_attempts:
                self.transition_to(KalshiSupervisorState.FAILED, f"Exceeded max reconnect attempts ({attempt})")

        rec = KalshiReconnectEventRecord(
            reconnect_id=f"rec_{self.session_id}_{attempt}_{int(now.timestamp())}",
            session_id=self.session_id,
            disconnect_timestamp=disc_ts,
            reconnect_attempt=attempt,
            reconnect_timestamp=now,
            reconnect_reason=reason,
            reconnect_latency_seconds=latency_sec,
            success=success
        )
        self.reconnect_events.append(rec)
        return rec

    def handle_fatal_error(self, reason: str) -> None:
        """Marks supervisor as permanently failed."""
        self.end_timestamp = datetime.now(timezone.utc)
        self.transition_to(KalshiSupervisorState.FAILED, reason)

    def mark_completed(self) -> None:
        """Marks supervisor as clean completion."""
        self.end_timestamp = datetime.now(timezone.utc)
        self.transition_to(KalshiSupervisorState.COMPLETED, "Supervisor stopped cleanly")

    def build_session_record(self) -> KalshiConnectionSessionRecord:
        """Constructs final session record for database persistence."""
        return KalshiConnectionSessionRecord(
            session_id=self.session_id,
            start_timestamp=self.start_timestamp,
            end_timestamp=self.end_timestamp,
            endpoint_url=self.endpoint_url,
            status=self.current_state.value,
            total_messages_received=self.messages_received_count,
            total_messages_persisted=self.messages_persisted_count,
            disconnect_count=self.disconnect_count,
            reconnect_count=self.reconnect_count
        )
