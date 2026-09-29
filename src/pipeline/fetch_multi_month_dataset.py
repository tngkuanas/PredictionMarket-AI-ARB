"""High-throughput pipeline to collect 90-180 days of historical data for long-horizon prediction markets."""
import concurrent.futures
import json
import logging
import time
from datetime import datetime
from typing import List, Tuple
import pandas as pd

from src.api.polymarket import PolymarketClient
from src.normalization.normalizer import MarketNormalizer
from src.normalization.schema import Market, Observation
from src.db.duckdb_store import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def fetch_multi_month_universe(target_markets: int = 500, max_workers: int = 8) -> dict:
    db = get_db()
    client = PolymarketClient()

    logger.info(f"=== STEP 1: Identifying markets with long historical horizons from DuckDB ===")
    with db.get_connection() as con:
        df_markets = con.execute("SELECT * FROM markets").df()

    logger.info(f"Found {len(df_markets)} markets in DuckDB.")

    # Collect valid token tasks
    token_tasks: List[Tuple[str, str, str]] = [] # (token_id, market_id, title)
    for _, row in df_markets.iterrows():
        t_ids = row.get("clob_token_ids")
        if isinstance(t_ids, str):
            try:
                t_ids = json.loads(t_ids)
            except Exception:
                t_ids = []
        if isinstance(t_ids, list) and t_ids:
            token_tasks.append((str(t_ids[0]), str(row["market_id"]), str(row["title"])))

    logger.info(f"Identified {len(token_tasks)} valid tokens. Commencing 90-180 day price fetch...")

    def fetch_extended_history(task: Tuple[str, str, str]) -> List[Observation]:
        tok, m_id, title = task
        observations = []
        try:
            # 1. Fetch multi-month snapshots (fidelity=720 spans up to 220 days)
            obs_720 = client.fetch_price_history(tok, interval="all", fidelity_minutes=720)
            if obs_720:
                observations.extend(obs_720)

            # 2. Also fetch fidelity=1440 if needed for older coverage
            obs_1440 = client.fetch_price_history(tok, interval="all", fidelity_minutes=1440)
            if obs_1440:
                # Merge and deduplicate by timestamp
                existing_ts = {o.timestamp for o in observations}
                for o in obs_1440:
                    if o.timestamp not in existing_ts:
                        observations.append(o)
                        existing_ts.add(o.timestamp)
        except Exception as e:
            logger.debug(f"Error fetching extended history for {tok}: {e}")
        return observations

    total_extended_observations = 0
    markets_with_90d = 0
    markets_with_180d = 0
    obs_batch: List[Observation] = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(fetch_extended_history, task): task for task in token_tasks}
        completed = 0
        for future in concurrent.futures.as_completed(future_to_task):
            completed += 1
            obs = future.result()
            if obs:
                # Sort by timestamp
                obs.sort(key=lambda x: x.timestamp)
                t_start = obs[0].timestamp
                t_end = obs[-1].timestamp
                span_days = (t_end - t_start).total_seconds() / 86400.0

                if span_days >= 90.0:
                    markets_with_90d += 1
                if span_days >= 180.0:
                    markets_with_180d += 1

                obs_batch.extend(obs)
                total_extended_observations += len(obs)

            if len(obs_batch) >= 10000:
                db.save_observations(obs_batch)
                obs_batch = []

            if completed % 50 == 0 or completed == len(token_tasks):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: [{completed}/{len(token_tasks)}] tokens processed "
                    f"({markets_with_90d} have >=90d, {markets_with_180d} have >=180d, "
                    f"{total_extended_observations:,} snapshots, {rate:.1f} tokens/sec)"
                )

    if obs_batch:
        db.save_observations(obs_batch)

    elapsed_total = time.time() - start_time
    logger.info(
        f"\n=== MULTI-MONTH DATA COLLECTION COMPLETE ===\n"
        f"Tokens Processed: {len(token_tasks)}\n"
        f"Markets with >= 90 Days History: {markets_with_90d}\n"
        f"Markets with >= 180 Days History: {markets_with_180d}\n"
        f"Total Snapshots Added: {total_extended_observations:,}\n"
        f"Elapsed Time: {elapsed_total:.1f}s"
    )

    return {
        "tokens_processed": len(token_tasks),
        "markets_with_90d": markets_with_90d,
        "markets_with_180d": markets_with_180d,
        "total_snapshots": total_extended_observations,
        "elapsed_seconds": elapsed_total
    }

if __name__ == "__main__":
    fetch_multi_month_universe(max_workers=8)
