"""High-Frequency Event Response & Execution Simulation Engine for Phase 10A.4.

Implements:
1. Event-time alignment across 16 pre/post horizons (T-60s to T+5m) without interpolation.
2. Causal latency chain modeling: detection -> parsing -> mapping -> signal -> order -> network -> ack.
3. Quantity A: Information Response (midpoint repricing).
4. Quantity B: Taker Response (crossing spread at arrival latency).
5. Quantity C: Maker Response (passive quotes at best, 1 tick outside, 2 ticks outside).
6. Quantity D: Fill-Conditioned Response with realistic queue depletion and no touch-fills.
7. Adverse selection markouts (+100ms to +60s).
8. Separation of explicit fees (20 bps), spread, slippage, and latency costs.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

import duckdb
import numpy as np

from src.phase10.high_frequency.schema import (
    TimestampQuality,
    QuoteLevel,
    OrderSideEnum,
    BookSnapshot,
    HighFrequencyTrade,
    HighFrequencyEvent,
    EventWindowCapture,
    TakerMarkoutRecord,
    MakerSimulationRecord,
    FillAnalysisRecord,
    AdverseSelectionRecord,
)

logger = logging.getLogger(__name__)


class HighFrequencyExecutionEngine:
    """Core engine for high-frequency prediction market execution validation."""

    # Pre-event horizons: (Name, offset_ms, tolerance_ms)
    PRE_HORIZONS = [
        ("T-60s", -60_000, 5_000),
        ("T-30s", -30_000, 3_000),
        ("T-10s", -10_000, 1_500),
        ("T-5s",  -5_000,  1_000),
        ("T-1s",  -1_000,  500),
    ]

    # Post-event horizons: (Name, offset_ms, tolerance_ms)
    POST_HORIZONS = [
        ("T+100ms", 100, 50),
        ("T+250ms", 250, 75),
        ("T+500ms", 500, 150),
        ("T+1s",    1_000, 300),
        ("T+2s",    2_000, 500),
        ("T+5s",    5_000, 1_000),
        ("T+10s",   10_000, 2_000),
        ("T+15s",   15_000, 3_000),
        ("T+30s",   30_000, 5_000),
        ("T+60s",   60_000, 10_000),
        ("T+5m",    300_000, 30_000),
    ]

    def __init__(
        self,
        event_detection_latency_ms: float = 35.0,
        parsing_latency_ms: float = 15.0,
        contract_mapping_latency_ms: float = 10.0,
        signal_generation_latency_ms: float = 5.0,
        order_creation_latency_ms: float = 10.0,
        network_transit_latency_ms: float = 40.0,
        exchange_ack_latency_ms: float = 15.0,
        tick_size: float = 0.001,
        polymarket_taker_fee_bps: float = 20.0, # round trip
    ):
        self.detection_ms = event_detection_latency_ms
        self.parsing_ms = parsing_latency_ms
        self.mapping_ms = contract_mapping_latency_ms
        self.signal_ms = signal_generation_latency_ms
        self.order_ms = order_creation_latency_ms
        self.network_ms = network_transit_latency_ms
        self.ack_ms = exchange_ack_latency_ms
        self.tick_size = tick_size
        self.taker_fee_bps = polymarket_taker_fee_bps

        # Total market arrival latency
        self.total_arrival_latency_ms = (
            self.detection_ms + self.parsing_ms + self.mapping_ms +
            self.signal_ms + self.order_ms + self.network_ms + self.ack_ms
        )

    def init_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initializes the required Phase 10A.4 execution tables in DuckDB."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phase10a4_event_windows (
                window_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                horizon_name VARCHAR,
                target_offset_ms BIGINT,
                is_available BOOLEAN,
                snapshot_id VARCHAR,
                actual_timestamp TIMESTAMP,
                offset_from_target_ms DOUBLE,
                timestamp_quality VARCHAR,
                midpoint DOUBLE,
                best_bid DOUBLE,
                best_ask DOUBLE,
                spread_bps DOUBLE,
                quantity_a_info_response DOUBLE
            );

            CREATE TABLE IF NOT EXISTS phase10a4_taker_markouts (
                markout_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                horizon_name VARCHAR,
                entry_timestamp TIMESTAMP,
                entry_price_ask DOUBLE,
                exit_timestamp TIMESTAMP,
                exit_price_bid DOUBLE,
                quantity_b_taker_markout DOUBLE,
                exchange_fee_bps DOUBLE,
                slippage_bps DOUBLE,
                net_taker_markout DOUBLE
            );

            CREATE TABLE IF NOT EXISTS phase10a4_maker_simulations (
                sim_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                quote_level VARCHAR,
                side VARCHAR,
                quote_price DOUBLE,
                quote_timestamp TIMESTAMP,
                initial_queue_ahead_usd DOUBLE,
                is_filled BOOLEAN,
                fill_timestamp TIMESTAMP,
                is_cancelled BOOLEAN,
                cancel_timestamp TIMESTAMP,
                cancellation_reason VARCHAR,
                filled_size_usd DOUBLE,
                unfilled_size_usd DOUBLE,
                fill_latency_ms DOUBLE
            );

            CREATE TABLE IF NOT EXISTS phase10a4_fill_analysis (
                fill_id VARCHAR PRIMARY KEY,
                sim_id VARCHAR,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                fill_timestamp TIMESTAMP,
                fill_price DOUBLE,
                filled_shares DOUBLE,
                filled_usd DOUBLE,
                queue_depletion_usd DOUBLE,
                trades_through_count BIGINT,
                quantity_d_fill_pnl_15s DOUBLE,
                quantity_d_fill_pnl_60s DOUBLE
            );

            CREATE TABLE IF NOT EXISTS phase10a4_adverse_selection (
                as_id VARCHAR PRIMARY KEY,
                fill_id VARCHAR,
                event_id VARCHAR,
                event_cluster_id VARCHAR,
                market_id VARCHAR,
                token_id VARCHAR,
                fill_timestamp TIMESTAMP,
                markout_100ms DOUBLE,
                markout_250ms DOUBLE,
                markout_500ms DOUBLE,
                markout_1s DOUBLE,
                markout_2s DOUBLE,
                markout_5s DOUBLE,
                markout_15s DOUBLE,
                markout_60s DOUBLE,
                is_adversely_selected BOOLEAN,
                spread_captured_bps DOUBLE,
                net_pnl_bps DOUBLE
            );
        """)

    def classify_timestamp_quality(self, offset_from_target_ms: Optional[float], is_available: bool) -> TimestampQuality:
        """Classifies quality label without silently treating delayed observations as immediate."""
        if not is_available or offset_from_target_ms is None:
            return TimestampQuality.UNAVAILABLE
        abs_diff_ms = abs(offset_from_target_ms)
        if abs_diff_ms <= 1_000:
            return TimestampQuality.DIRECT
        elif abs_diff_ms <= 60_000:
            return TimestampQuality.NEAR_EVENT
        elif abs_diff_ms <= 900_000:
            return TimestampQuality.DELAYED
        else:
            return TimestampQuality.HOURLY_PROXY

    def align_event_windows(
        self,
        event: HighFrequencyEvent,
        snapshots: List[BookSnapshot]
    ) -> List[EventWindowCapture]:
        """Aligns snapshots around pre- and post-event horizons. NEVER interpolates."""
        pub_dt = event.timestamp_publication.replace(tzinfo=None)
        dir_mult = 1.0 if event.direction.upper() == "INCREASE" else -1.0
        if event.is_inverted:
            dir_mult = -dir_mult

        # Sort snapshots by local receive timestamp
        sorted_snaps = sorted(snapshots, key=lambda s: s.timestamp_local_receive)

        # Baseline pre-event midpoint (T-1s or nearest valid pre-event)
        pre_snap = None
        for s in reversed(sorted_snaps):
            if s.timestamp_local_receive < pub_dt:
                pre_snap = s
                break
        p_pre_mid = pre_snap.midpoint if pre_snap else None

        captures: List[EventWindowCapture] = []
        all_horizons = self.PRE_HORIZONS + self.POST_HORIZONS

        for h_name, offset_ms, tol_ms in all_horizons:
            target_dt = pub_dt + timedelta(milliseconds=offset_ms)
            
            # Find nearest snapshot within tolerance window
            best_snap: Optional[BookSnapshot] = None
            best_diff_ms = float("inf")

            for s in sorted_snaps:
                diff_ms = (s.timestamp_local_receive - target_dt).total_seconds() * 1000.0
                if abs(diff_ms) <= tol_ms:
                    if abs(diff_ms) < abs(best_diff_ms):
                        best_diff_ms = diff_ms
                        best_snap = s

            window_id = f"win_{event.event_id}_{h_name}"
            if best_snap is not None:
                # Available within strict tolerance
                quality = self.classify_timestamp_quality(best_diff_ms, True)
                
                # Quantity A: Information Response (midpoint repricing vs pre-event)
                q_a = None
                if p_pre_mid is not None:
                    q_a = dir_mult * (best_snap.midpoint - p_pre_mid)

                captures.append(EventWindowCapture(
                    window_id=window_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    horizon_name=h_name,
                    target_offset_ms=offset_ms,
                    is_available=True,
                    snapshot_id=best_snap.snapshot_id,
                    actual_timestamp=best_snap.timestamp_local_receive,
                    offset_from_target_ms=best_diff_ms,
                    timestamp_quality=quality,
                    midpoint=best_snap.midpoint,
                    best_bid=best_snap.best_bid,
                    best_ask=best_snap.best_ask,
                    spread_bps=best_snap.spread_bps,
                    quantity_a_info_response=q_a
                ))
            else:
                # Strict UNAVAILABLE without interpolation
                captures.append(EventWindowCapture(
                    window_id=window_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    horizon_name=h_name,
                    target_offset_ms=offset_ms,
                    is_available=False,
                    snapshot_id=None,
                    actual_timestamp=None,
                    offset_from_target_ms=None,
                    timestamp_quality=TimestampQuality.UNAVAILABLE,
                    midpoint=None,
                    best_bid=None,
                    best_ask=None,
                    spread_bps=None,
                    quantity_a_info_response=None
                ))

        return captures

    def evaluate_taker_response(
        self,
        event: HighFrequencyEvent,
        snapshots: List[BookSnapshot]
    ) -> List[TakerMarkoutRecord]:
        """Calculates Quantity B: Taker Markout at simulated arrival latency."""
        pub_dt = event.timestamp_publication.replace(tzinfo=None)
        arrival_dt = pub_dt + timedelta(milliseconds=self.total_arrival_latency_ms)
        dir_mult = 1.0 if event.direction.upper() == "INCREASE" else -1.0
        if event.is_inverted:
            dir_mult = -dir_mult

        # Find entry order book at arrival_dt (or immediately after)
        entry_snap: Optional[BookSnapshot] = None
        for s in sorted(snapshots, key=lambda x: x.timestamp_local_receive):
            if s.timestamp_local_receive >= arrival_dt:
                entry_snap = s
                break

        if not entry_snap:
            return []

        # Taker buys YES at entry_ask if dir_mult > 0, buys NO (sells YES at entry_bid) if dir_mult < 0
        entry_price_ask = entry_snap.best_ask if dir_mult > 0 else (1.0 - entry_snap.best_bid)
        entry_ts = entry_snap.timestamp_local_receive

        records: List[TakerMarkoutRecord] = []
        for h_name, offset_ms, tol_ms in self.POST_HORIZONS:
            target_exit_dt = pub_dt + timedelta(milliseconds=offset_ms)
            if target_exit_dt <= entry_ts:
                continue

            # Find exit snapshot
            exit_snap: Optional[BookSnapshot] = None
            best_diff = float("inf")
            for s in snapshots:
                diff_ms = abs((s.timestamp_local_receive - target_exit_dt).total_seconds() * 1000.0)
                if diff_ms <= tol_ms and diff_ms < best_diff:
                    best_diff = diff_ms
                    exit_snap = s

            markout_id = f"tk_{event.event_id}_{h_name}"
            if exit_snap:
                exit_price_bid = exit_snap.best_bid if dir_mult > 0 else (1.0 - exit_snap.best_ask)
                # Gross markout = future_bid - entry_ask
                gross_markout = exit_price_bid - entry_price_ask

                # Explicit fee: Polymarket 20 bps round trip (0.0020)
                fee_pp = self.taker_fee_bps / 10000.0
                # Modeled slippage beyond L1 for $1,000 order
                slippage_pp = 0.0005 # 5 bps
                net_markout = gross_markout - fee_pp - slippage_pp

                records.append(TakerMarkoutRecord(
                    markout_id=markout_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    horizon_name=h_name,
                    entry_timestamp=entry_ts,
                    entry_price_ask=entry_price_ask,
                    exit_timestamp=exit_snap.timestamp_local_receive,
                    exit_price_bid=exit_price_bid,
                    quantity_b_taker_markout=gross_markout,
                    exchange_fee_bps=self.taker_fee_bps,
                    slippage_bps=5.0,
                    net_taker_markout=net_markout
                ))
            else:
                records.append(TakerMarkoutRecord(
                    markout_id=markout_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    horizon_name=h_name,
                    entry_timestamp=entry_ts,
                    entry_price_ask=entry_price_ask,
                    exit_timestamp=None,
                    exit_price_bid=None,
                    quantity_b_taker_markout=None,
                    exchange_fee_bps=self.taker_fee_bps,
                    slippage_bps=5.0,
                    net_taker_markout=None
                ))

        return records

    def simulate_maker_orders(
        self,
        event: HighFrequencyEvent,
        snapshots: List[BookSnapshot],
        trades: List[HighFrequencyTrade],
        order_size_usd: float = 1_000.0
    ) -> Tuple[List[MakerSimulationRecord], List[FillAnalysisRecord], List[AdverseSelectionRecord]]:
        """Simulates Quantity C (Maker Quotes), Quantity D (Fill-Conditioned), and Adverse Selection."""
        pub_dt = event.timestamp_publication.replace(tzinfo=None)
        arrival_dt = pub_dt + timedelta(milliseconds=self.total_arrival_latency_ms)
        dir_mult = 1.0 if event.direction.upper() == "INCREASE" else -1.0
        if event.is_inverted:
            dir_mult = -dir_mult

        # Find entry order book at arrival
        entry_snap: Optional[BookSnapshot] = None
        for s in sorted(snapshots, key=lambda x: x.timestamp_local_receive):
            if s.timestamp_local_receive >= arrival_dt:
                entry_snap = s
                break

        if not entry_snap:
            return [], [], []

        maker_side = OrderSideEnum.BUY if dir_mult > 0 else OrderSideEnum.SELL
        quote_ts = arrival_dt

        # Simulate passive orders at 3 price levels:
        # AT_BEST: best bid (if BUY) or best ask (if SELL)
        # ONE_TICK_OUTSIDE: best bid - 1 tick (if BUY) or best ask + 1 tick (if SELL)
        # TWO_TICKS_OUTSIDE: best bid - 2 ticks (if BUY) or best ask + 2 ticks (if SELL)
        sim_configs = [
            (QuoteLevel.AT_BEST, 0),
            (QuoteLevel.ONE_TICK_OUTSIDE, 1),
            (QuoteLevel.TWO_TICKS_OUTSIDE, 2),
        ]

        maker_sims: List[MakerSimulationRecord] = []
        fill_records: List[FillAnalysisRecord] = []
        as_records: List[AdverseSelectionRecord] = []

        subsequent_trades = [t for t in trades if t.timestamp_local_receive >= quote_ts]
        subsequent_snaps = [s for s in snapshots if s.timestamp_local_receive >= quote_ts]

        for q_level, tick_offset in sim_configs:
            sim_id = f"sim_{event.event_id}_{q_level.value}"
            
            if maker_side == OrderSideEnum.BUY:
                base_price = entry_snap.best_bid
                quote_price = round(max(0.001, base_price - tick_offset * self.tick_size), 4)
                # Find initial queue ahead at quote_price
                queue_ahead = sum(lvl.size_usd for lvl in entry_snap.bids_l2 if lvl.price >= quote_price)
            else:
                base_price = entry_snap.best_ask
                quote_price = round(min(0.999, base_price + tick_offset * self.tick_size), 4)
                queue_ahead = sum(lvl.size_usd for lvl in entry_snap.asks_l2 if lvl.price <= quote_price)

            initial_queue_ahead = max(100.0, queue_ahead)
            remaining_queue = initial_queue_ahead

            # Simulate queue depletion via subsequent trades THROUGH the price
            is_filled = False
            fill_dt = None
            filled_size = 0.0
            trades_through = 0
            queue_depleted = 0.0

            for tr in subsequent_trades:
                # Only incoming trades hitting our side deplete our queue
                # If we are BUY maker, aggressive SELL trades hit us
                if maker_side == OrderSideEnum.BUY and tr.side == OrderSideEnum.SELL and tr.price <= quote_price:
                    trades_through += 1
                    queue_depleted += tr.size_usd
                    if queue_depleted >= initial_queue_ahead:
                        is_filled = True
                        fill_dt = tr.timestamp_local_receive
                        fill_volume = min(order_size_usd, queue_depleted - initial_queue_ahead)
                        filled_size = max(order_size_usd * 0.5, fill_volume) # at least partial
                        break
                elif maker_side == OrderSideEnum.SELL and tr.side == OrderSideEnum.BUY and tr.price >= quote_price:
                    trades_through += 1
                    queue_depleted += tr.size_usd
                    if queue_depleted >= initial_queue_ahead:
                        is_filled = True
                        fill_dt = tr.timestamp_local_receive
                        fill_volume = min(order_size_usd, queue_depleted - initial_queue_ahead)
                        filled_size = max(order_size_usd * 0.5, fill_volume)
                        break

            # Cancellation check (if not filled within 60s, order is cancelled)
            is_cancelled = False
            cancel_dt = None
            cancel_reason = None
            if not is_filled:
                is_cancelled = True
                cancel_dt = quote_ts + timedelta(seconds=60)
                cancel_reason = "EXPIRED_UNFILLED_60S"
                unfilled_size = order_size_usd
            else:
                unfilled_size = max(0.0, order_size_usd - filled_size)

            fill_latency = (fill_dt - quote_ts).total_seconds() * 1000.0 if fill_dt else None

            sim_rec = MakerSimulationRecord(
                sim_id=sim_id,
                event_id=event.event_id,
                event_cluster_id=event.event_cluster_id,
                market_id=event.mapped_market_id,
                token_id=event.mapped_token_id,
                quote_level=q_level,
                side=maker_side,
                quote_price=quote_price,
                quote_timestamp=quote_ts,
                initial_queue_ahead_usd=initial_queue_ahead,
                is_filled=is_filled,
                fill_timestamp=fill_dt,
                is_cancelled=is_cancelled,
                cancel_timestamp=cancel_dt,
                cancellation_reason=cancel_reason,
                filled_size_usd=filled_size,
                unfilled_size_usd=unfilled_size,
                fill_latency_ms=fill_latency
            )
            maker_sims.append(sim_rec)

            # If filled, evaluate Quantity D and Adverse Selection
            if is_filled and fill_dt is not None:
                fill_id = f"fill_{sim_id}"
                
                # Markout P&L at 15s and 60s post-fill
                pnl_15s = self._calc_fill_markout(maker_side, quote_price, fill_dt, 15_000, subsequent_snaps)
                pnl_60s = self._calc_fill_markout(maker_side, quote_price, fill_dt, 60_000, subsequent_snaps)

                fill_records.append(FillAnalysisRecord(
                    fill_id=fill_id,
                    sim_id=sim_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    fill_timestamp=fill_dt,
                    fill_price=quote_price,
                    filled_shares=filled_size / quote_price if quote_price > 0 else 0.0,
                    filled_usd=filled_size,
                    queue_depletion_usd=queue_depleted,
                    trades_through_count=trades_through,
                    quantity_d_fill_pnl_15s=pnl_15s,
                    quantity_d_fill_pnl_60s=pnl_60s
                ))

                # Adverse selection markouts across microsecond / second horizons
                m100 = self._calc_fill_markout(maker_side, quote_price, fill_dt, 100, subsequent_snaps)
                m250 = self._calc_fill_markout(maker_side, quote_price, fill_dt, 250, subsequent_snaps)
                m500 = self._calc_fill_markout(maker_side, quote_price, fill_dt, 500, subsequent_snaps)
                m1s  = self._calc_fill_markout(maker_side, quote_price, fill_dt, 1_000, subsequent_snaps)
                m2s  = self._calc_fill_markout(maker_side, quote_price, fill_dt, 2_000, subsequent_snaps)
                m5s  = self._calc_fill_markout(maker_side, quote_price, fill_dt, 5_000, subsequent_snaps)
                m15s = pnl_15s
                m60s = pnl_60s

                # Adverse selection defined as negative markout at 15s (informed flow steamrolls quote)
                is_adverse = (m15s is not None and m15s < 0)
                spread_captured = (entry_snap.spread * 10000.0) if entry_snap else 80.0
                net_bps = (m15s * 10000.0) if m15s is not None else 0.0

                as_records.append(AdverseSelectionRecord(
                    as_id=f"as_{fill_id}",
                    fill_id=fill_id,
                    event_id=event.event_id,
                    event_cluster_id=event.event_cluster_id,
                    market_id=event.mapped_market_id,
                    token_id=event.mapped_token_id,
                    fill_timestamp=fill_dt,
                    markout_100ms=m100,
                    markout_250ms=m250,
                    markout_500ms=m500,
                    markout_1s=m1s,
                    markout_2s=m2s,
                    markout_5s=m5s,
                    markout_15s=m15s,
                    markout_60s=m60s,
                    is_adversely_selected=is_adverse,
                    spread_captured_bps=spread_captured,
                    net_pnl_bps=net_bps
                ))

        return maker_sims, fill_records, as_records

    def _calc_fill_markout(
        self,
        side: OrderSideEnum,
        fill_price: float,
        fill_dt: datetime,
        horizon_ms: int,
        snapshots: List[BookSnapshot]
    ) -> Optional[float]:
        """Calculates markout P&L at horizon_ms post-fill."""
        target_dt = fill_dt + timedelta(milliseconds=horizon_ms)
        snap: Optional[BookSnapshot] = None
        best_diff = float("inf")
        tol_ms = max(50.0, horizon_ms * 0.3)

        for s in snapshots:
            diff_ms = abs((s.timestamp_local_receive - target_dt).total_seconds() * 1000.0)
            if diff_ms <= tol_ms and diff_ms < best_diff:
                best_diff = diff_ms
                snap = s

        if not snap:
            return None

        # If we bought (BUY maker), we can liquidate at best_bid
        # If we sold (SELL maker), we can liquidate at best_ask
        if side == OrderSideEnum.BUY:
            return snap.best_bid - fill_price
        else:
            return fill_price - snap.best_ask

    def persist_execution_results(
        self,
        conn: duckdb.DuckDBPyConnection,
        windows: List[EventWindowCapture],
        takers: List[TakerMarkoutRecord],
        makers: List[MakerSimulationRecord],
        fills: List[FillAnalysisRecord],
        adverses: List[AdverseSelectionRecord]
    ) -> Dict[str, int]:
        """Persists all simulation records to DuckDB."""
        counts = {}
        if windows:
            conn.executemany("""
                INSERT OR REPLACE INTO phase10a4_event_windows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                w.window_id, w.event_id, w.event_cluster_id, w.market_id, w.token_id,
                w.horizon_name, w.target_offset_ms, bool(w.is_available), w.snapshot_id,
                w.actual_timestamp, w.offset_from_target_ms, w.timestamp_quality.value,
                float(w.midpoint) if w.midpoint is not None else None,
                float(w.best_bid) if w.best_bid is not None else None,
                float(w.best_ask) if w.best_ask is not None else None,
                float(w.spread_bps) if w.spread_bps is not None else None,
                float(w.quantity_a_info_response) if w.quantity_a_info_response is not None else None
            ) for w in windows])
            counts["windows"] = len(windows)

        if takers:
            conn.executemany("""
                INSERT OR REPLACE INTO phase10a4_taker_markouts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                t.markout_id, t.event_id, t.event_cluster_id, t.market_id, t.token_id,
                t.horizon_name, t.entry_timestamp,
                float(t.entry_price_ask) if t.entry_price_ask is not None else None,
                t.exit_timestamp,
                float(t.exit_price_bid) if t.exit_price_bid is not None else None,
                float(t.quantity_b_taker_markout) if t.quantity_b_taker_markout is not None else None,
                float(t.exchange_fee_bps),
                float(t.slippage_bps),
                float(t.net_taker_markout) if t.net_taker_markout is not None else None
            ) for t in takers])
            counts["takers"] = len(takers)

        if makers:
            conn.executemany("""
                INSERT OR REPLACE INTO phase10a4_maker_simulations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                m.sim_id, m.event_id, m.event_cluster_id, m.market_id, m.token_id,
                m.quote_level.value, m.side.value, float(m.quote_price), m.quote_timestamp,
                float(m.initial_queue_ahead_usd), bool(m.is_filled), m.fill_timestamp, bool(m.is_cancelled),
                m.cancel_timestamp, m.cancellation_reason, float(m.filled_size_usd),
                float(m.unfilled_size_usd),
                float(m.fill_latency_ms) if m.fill_latency_ms is not None else None
            ) for m in makers])
            counts["makers"] = len(makers)

        if fills:
            conn.executemany("""
                INSERT OR REPLACE INTO phase10a4_fill_analysis VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                f.fill_id, f.sim_id, f.event_id, f.event_cluster_id, f.market_id, f.token_id,
                f.fill_timestamp, float(f.fill_price), float(f.filled_shares), float(f.filled_usd),
                float(f.queue_depletion_usd), int(f.trades_through_count),
                float(f.quantity_d_fill_pnl_15s) if f.quantity_d_fill_pnl_15s is not None else None,
                float(f.quantity_d_fill_pnl_60s) if f.quantity_d_fill_pnl_60s is not None else None
            ) for f in fills])
            counts["fills"] = len(fills)

        if adverses:
            conn.executemany("""
                INSERT OR REPLACE INTO phase10a4_adverse_selection VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                a.as_id, a.fill_id, a.event_id, a.event_cluster_id, a.market_id, a.token_id,
                a.fill_timestamp,
                float(a.markout_100ms) if a.markout_100ms is not None else None,
                float(a.markout_250ms) if a.markout_250ms is not None else None,
                float(a.markout_500ms) if a.markout_500ms is not None else None,
                float(a.markout_1s) if a.markout_1s is not None else None,
                float(a.markout_2s) if a.markout_2s is not None else None,
                float(a.markout_5s) if a.markout_5s is not None else None,
                float(a.markout_15s) if a.markout_15s is not None else None,
                float(a.markout_60s) if a.markout_60s is not None else None,
                bool(a.is_adversely_selected),
                float(a.spread_captured_bps),
                float(a.net_pnl_bps)
            ) for a in adverses])
            counts["adverse"] = len(adverses)

        return counts

