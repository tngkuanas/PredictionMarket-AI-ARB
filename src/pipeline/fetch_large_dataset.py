"""High-throughput pipeline to collect 500-1000 active prediction markets and their historical price series."""
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

def fetch_large_universe(target_markets: int = 500, max_history_workers: int = 8) -> None:
    db = get_db()
    client = PolymarketClient()
    normalizer = MarketNormalizer()

    logger.info(f"=== STEP 1: Fetching {target_markets} active markets from Polymarket ===")
    all_markets: List[Market] = []
    batch_size = 100
    offset = 0

    while len(all_markets) < target_markets:
        limit = min(batch_size, target_markets - len(all_markets))
        batch = client.fetch_active_markets(limit=limit, offset=offset)
        if not batch:
            logger.info("No more markets returned from API.")
            break
        all_markets.extend(batch)
        offset += len(batch)
        logger.info(f"Fetched {len(all_markets)}/{target_markets} markets (offset={offset})...")
        time.sleep(0.3)

    logger.info(f"Total active markets collected: {len(all_markets)}")

    # Step 2: Store Market Metadata
    logger.info("=== STEP 2: Storing market metadata in DuckDB ===")
    db.save_markets(all_markets)

    # Step 3: Canonical Market Normalization
    logger.info("=== STEP 3: Normalizing contracts to canonical representations ===")
    t0 = time.time()
    canonicals = normalizer.normalize_batch(all_markets)
    db.save_canonical_markets(canonicals)
    logger.info(f"Normalized {len(canonicals)} canonical markets in {time.time()-t0:.2f}s.")

    # Step 4: Parallel Price History Collection
    logger.info(f"=== STEP 4: Downloading historical price observations (workers={max_history_workers}) ===")
    
    # Collect all valid token IDs
    token_tasks: List[Tuple[str, str]] = [] # (token_id, market_id)
    for m in all_markets:
        if m.clob_token_ids:
            token_tasks.append((m.clob_token_ids[0], m.market_id))

    logger.info(f"Identified {len(token_tasks)} valid CLOB tokens for historical timeseries.")

    def fetch_token_history(task: Tuple[str, str]) -> List[Observation]:
        token_id, m_id = task
        try:
            # interval='all' captures full 30-90 day history
            obs = client.fetch_price_history(token_id, interval="all", fidelity_minutes=60)
            if not obs:
                # Fallback to 1m
                obs = client.fetch_price_history(token_id, interval="1m", fidelity_minutes=60)
            return obs
        except Exception as e:
            logger.debug(f"Error fetching history for token {token_id}: {e}")
            return []

    total_observations = 0
    tokens_with_data = 0
    obs_batch: List[Observation] = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_history_workers) as executor:
        future_to_token = {executor.submit(fetch_token_history, task): task for task in token_tasks}
        completed = 0
        for future in concurrent.futures.as_completed(future_to_token):
            completed += 1
            obs = future.result()
            if obs:
                obs_batch.extend(obs)
                tokens_with_data += 1
                total_observations += len(obs)

            # Flush observations to DuckDB in chunks of >= 10,000
            if len(obs_batch) >= 10000:
                db.save_observations(obs_batch)
                obs_batch = []

            if completed % 50 == 0 or completed == len(token_tasks):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: [{completed}/{len(token_tasks)}] tokens processed "
                    f"({tokens_with_data} with data, {total_observations:,} snapshots, {rate:.1f} tokens/sec)"
                )

    if obs_batch:
        db.save_observations(obs_batch)

    logger.info(
        f"=== STEP 5: Universe scaling complete! ===\n"
        f"Markets: {len(all_markets)}\n"
        f"Tokens with History: {tokens_with_data}/{len(token_tasks)}\n"
        f"Total Observations: {total_observations:,}\n"
        f"Elapsed Time: {time.time()-start_time:.1f}s"
    )

if __name__ == "__main__":
    fetch_large_universe(target_markets=500, max_history_workers=8)
