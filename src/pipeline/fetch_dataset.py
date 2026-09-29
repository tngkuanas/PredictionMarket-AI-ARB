"""Pipeline script to download markets, metadata, price histories, and build the initial dataset."""
import logging
import time
from typing import List
from src.api.polymarket import PolymarketClient
from src.normalization.normalizer import MarketNormalizer
from src.db.duckdb_store import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def build_polymarket_dataset(target_count: int = 40) -> None:
    db = get_db()
    client = PolymarketClient()
    normalizer = MarketNormalizer()

    logger.info(f"Step 1: Downloading active markets from Polymarket Gamma API (target={target_count})...")
    # Fetch in batches
    all_markets = []
    offset = 0
    batch_size = 20
    while len(all_markets) < target_count:
        markets = client.fetch_active_markets(limit=batch_size, offset=offset)
        if not markets:
            break
        all_markets.extend(markets)
        offset += batch_size
        time.sleep(0.5)

    all_markets = all_markets[:target_count]
    logger.info(f"Downloaded {len(all_markets)} active markets.")

    # Save markets to DuckDB
    logger.info("Step 2: Storing market metadata into DuckDB...")
    db.save_markets(all_markets)

    # Normalize contracts
    logger.info("Step 3: Extracting canonical representations...")
    canonicals = normalizer.normalize_batch(all_markets)
    db.save_canonical_markets(canonicals)
    logger.info(f"Saved {len(canonicals)} canonical markets.")

    # Download price history for markets with CLOB tokens
    logger.info("Step 4: Fetching historical price snapshots from CLOB...")
    total_observations = 0
    for idx, market in enumerate(all_markets):
        if not market.clob_token_ids:
            continue
        token_id = market.clob_token_ids[0]
        try:
            # interval='all' or '1m' with fidelity=60 (hourly)
            history = client.fetch_price_history(token_id, interval="all", fidelity_minutes=60)
            if history:
                db.save_observations(history)
                total_observations += len(history)
                logger.info(f"[{idx+1}/{len(all_markets)}] Market '{market.title[:40]}...': {len(history)} price points.")
            else:
                # If 'all' had no data, try '1m'
                history_1m = client.fetch_price_history(token_id, interval="1m", fidelity_minutes=60)
                if history_1m:
                    db.save_observations(history_1m)
                    total_observations += len(history_1m)
                    logger.info(f"[{idx+1}/{len(all_markets)}] (1m) Market '{market.title[:40]}...': {len(history_1m)} price points.")
        except Exception as e:
            logger.warning(f"Failed to fetch price history for {market.market_id}: {e}")
        time.sleep(0.3)

    logger.info(f"Step 5: Dataset collection complete! Stored {len(all_markets)} markets and {total_observations} historical price observations.")

if __name__ == "__main__":
    build_polymarket_dataset(target_count=30)
