"""Pipeline Runner for Phase 10A.5b Multi-Session Data Accumulation & Integrity Audit.

Runs the continuous multi-session market data accumulator against live Polymarket CLOB
WebSocket feeds, enforces objective universe discovery, performs multi-session rollover,
verifies sequence continuity and L2 order-book reconstruction, executes strict accounting
reconciliation, and certifies zero synthetic contamination.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Dict, Any

import duckdb

from src.phase10.acquisition.multi_session_recorder import (
    MultiSessionContinuousRecorder,
    AccountingReconciler,
)
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard
from src.phase10.acquisition.db_store import Phase10A5DbStore
from src.phase10.acquisition.dns_resolver import enable_polymarket_edge_resolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

enable_polymarket_edge_resolver()


async def run_phase10a5b_pipeline(
    db_path: str = "data/prediction_market.duckdb",
    raw_storage_dir: str = "data/phase10a5_raw",
    target_accumulation_sec: float = 30.0,
    cycle_duration_sec: float = 15.0,
    output_metrics_json: str = "data/phase10a5b_multi_day_metrics.json"
) -> Dict[str, Any]:
    logger.info("================================================================================")
    logger.info("PHASE 10A.5b MULTI-SESSION DATA ACCUMULATION & INTEGRITY AUDIT")
    logger.info("================================================================================")

    recorder = MultiSessionContinuousRecorder(
        db_path=db_path,
        raw_storage_dir=raw_storage_dir,
        min_liquidity_usd=10_000.0,
        min_volume_24h_usd=20_000.0
    )

    logger.info(f"Target accumulation duration: {target_accumulation_sec}s across multiple {cycle_duration_sec}s cycles...")
    summary = await recorder.run_continuous_accumulation(
        target_total_duration_sec=target_accumulation_sec,
        session_cycle_duration_sec=cycle_duration_sec,
        universe_refresh_interval_sec=60.0,
        market_limit=20
    )

    # Save summary JSON
    out_path = Path(output_metrics_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"Saved Phase 10A.5b integrity metrics summary to {output_metrics_json}")

    print("\n" + "=" * 80)
    print("PHASE 10A.5b ACCUMULATION & RECONCILIATION SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2, default=str))

    return summary


def main():
    asyncio.run(run_phase10a5b_pipeline(target_accumulation_sec=30.0, cycle_duration_sec=15.0))


if __name__ == "__main__":
    main()
