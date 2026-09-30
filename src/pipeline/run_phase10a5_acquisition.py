"""Pipeline Runner for Phase 10A.5 Genuine High-Frequency Market Data Acquisition.

Executes objective market universe discovery, starts live WebSocket stream to Polymarket CLOB,
persists raw append-only message frames to disk, deterministically reconstructs L2 order books,
records real market trades, calculates integrity metrics, and enforces the anti-synthetic guard.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

import duckdb

from src.phase10.acquisition.schema import (
    RawMessageRecord,
    BookUpdateRecord,
    ReconstructedBookSnapshot,
    GenuineTradeRecord,
    MarketUniverseEntry,
    ConnectionSessionRecord,
)
from src.phase10.acquisition.market_universe import MarketUniverseManager
from src.phase10.acquisition.raw_recorder import RawMarketDataRecorder
from src.phase10.acquisition.order_book_reconstructor import OrderBookReconstructor
from src.phase10.acquisition.trade_processor import TradeStreamProcessor
from src.phase10.acquisition.metrics_tracker import DataIntegrityMetricsTracker
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard
from src.phase10.acquisition.db_store import Phase10A5DbStore
from src.phase10.acquisition.dns_resolver import enable_polymarket_edge_resolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Ensure DNS resolution uses direct Cloudflare edge IPs to prevent DNS filtering
enable_polymarket_edge_resolver()


async def run_acquisition_pipeline(
    db_path: str = "data/prediction_market.duckdb",
    raw_storage_dir: str = "data/phase10a5_raw",
    validation_duration_seconds: float = 25.0,
    output_metrics_json: str = "data/phase10a5_integrity_metrics.json"
) -> Dict[str, Any]:
    """Runs the live high-frequency acquisition validation run."""
    logger.info("================================================================================")
    logger.info("PHASE 10A.5 GENUINE HIGH-FREQUENCY DATA ACQUISITION RUN")
    logger.info("================================================================================")

    # 1. Initialize DuckDB schema
    db_store = Phase10A5DbStore(db_path=db_path)
    conn = duckdb.connect(db_path)
    try:
        db_store.init_schema(conn)
    finally:
        conn.close()

    # 2. Objective Market Universe Discovery (Gamma API)
    session_id = f"sess_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    universe_mgr = MarketUniverseManager(
        min_liquidity_usd=10_000.0,
        min_volume_24h_usd=20_000.0
    )
    universe_entries = universe_mgr.discover_active_universe(session_id=session_id, limit=20)
    
    if not universe_entries:
        logger.error("Failed to discover active Polymarket universe. Aborting acquisition run.")
        return {"error": "Universe discovery failed"}

    monitored_tokens = [u.token_id for u in universe_entries]
    logger.info(f"Targeting {len(monitored_tokens)} active tokens for real-time WebSocket ingestion.")

    # 3. Initialize Ingestion, Reconstructor, Trade Processor, Metrics Tracker
    recorder = RawMarketDataRecorder(raw_storage_dir=raw_storage_dir, session_id=session_id)
    reconstructor = OrderBookReconstructor(depth_levels_limit=10)
    trade_processor = TradeStreamProcessor()
    metrics_tracker = DataIntegrityMetricsTracker()

    # 4. Define streaming callback
    def on_raw_records_received(records: List[RawMessageRecord]):
        for r in records:
            metrics_tracker.log_raw_message(r)
            # Reconstruct order book
            upds, snap = reconstructor.process_raw_record(r)
            if snap:
                metrics_tracker.log_snapshot(snap)
            # Process trade
            trade_processor.process_raw_trade(r)

    # 5. Connect and stream live market data
    logger.info(f"Streaming live Polymarket CLOB data for {validation_duration_seconds}s...")
    session_record = await recorder.stream_market_data(
        token_ids=monitored_tokens,
        duration_seconds=validation_duration_seconds,
        on_message_callback=on_raw_records_received
    )

    # 6. Persist all records to DuckDB
    logger.info(f"Persisting {len(recorder.buffered_raw_records)} raw messages, {len(reconstructor.reconstructed_snapshots)} snapshots, and {len(trade_processor.recorded_trades)} trades to DuckDB...")
    conn = duckdb.connect(db_path)
    try:
        n_raw = db_store.persist_raw_messages(conn, recorder.buffered_raw_records)
        n_upd = db_store.persist_book_updates(conn, reconstructor.book_updates)
        n_snaps = db_store.persist_book_snapshots(conn, reconstructor.reconstructed_snapshots)
        n_trades = db_store.persist_trades(conn, trade_processor.recorded_trades)
        n_univ = db_store.persist_market_universe(conn, universe_entries)
        db_store.persist_session(conn, session_record)
        n_dq = db_store.persist_data_quality(conn, trade_processor.quality_anomalies)

        # 7. Anti-Synthetic Guard Audit
        guard_scan = AntiSyntheticGuard.scan_production_tables(conn)
        if not guard_scan["clean"]:
            logger.error(f"Anti-synthetic guard failed: {guard_scan['violations']}")
            raise RuntimeError(f"Synthetic data detected in Phase 10A.5 tables: {guard_scan['violations']}")
        logger.info("Anti-synthetic guard certified: ZERO synthetic data present in Phase 10A.5 production tables.")

    finally:
        conn.close()

    # 8. Compile Integrity Metrics Summary
    metrics_summary = metrics_tracker.compile_metrics_report(
        session_record=session_record,
        snapshots=reconstructor.reconstructed_snapshots,
        trades=trade_processor.recorded_trades,
        universe_entries=universe_entries
    )
    metrics_summary["anti_synthetic_certification"] = guard_scan

    # 9. Save Summary JSON
    out_file = Path(output_metrics_json)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(metrics_summary, f, indent=2, default=str)
    logger.info(f"Saved Phase 10A.5 integrity metrics summary JSON to {output_metrics_json}")

    print("\n" + "=" * 80)
    print("PHASE 10A.5 REAL-DATA ACQUISITION SUMMARY")
    print("=" * 80)
    print(json.dumps(metrics_summary, indent=2, default=str))

    return metrics_summary


def main():
    asyncio.run(run_acquisition_pipeline(validation_duration_seconds=15.0))


if __name__ == "__main__":
    main()
