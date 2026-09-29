"""Exploratory Data Analysis (EDA) for Prediction Market Universe."""
import json
import logging
from pathlib import Path
import numpy as np
import pandas as pd
from src.db.duckdb_store import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_market_eda() -> dict:
    db = get_db()
    with db.get_connection() as con:
        df_markets = con.execute("SELECT * FROM markets").df()
        df_canon = con.execute("SELECT * FROM canonical_markets").df()
        df_obs = con.execute("SELECT * FROM market_snapshots ORDER BY timestamp ASC").df()

    logger.info(f"Loaded {len(df_markets)} markets and {len(df_obs)} snapshots from DuckDB.")

    # 1. Market Distribution
    total_volume = df_markets["volume"].sum()
    total_liquidity = df_markets["liquidity"].sum()
    categories = df_markets["category"].value_counts().to_dict()

    volume_stats = {
        "mean": float(df_markets["volume"].mean()),
        "std": float(df_markets["volume"].std()),
        "min": float(df_markets["volume"].min()),
        "p25": float(df_markets["volume"].quantile(0.25)),
        "median": float(df_markets["volume"].median()),
        "p75": float(df_markets["volume"].quantile(0.75)),
        "max": float(df_markets["volume"].max()),
    }

    liquidity_stats = {
        "mean": float(df_markets["liquidity"].mean()),
        "std": float(df_markets["liquidity"].std()),
        "min": float(df_markets["liquidity"].min()),
        "median": float(df_markets["liquidity"].median()),
        "max": float(df_markets["liquidity"].max()),
    }

    # 2. Canonical entities & clusters
    all_entities = []
    for ents in df_canon["entities"]:
        if isinstance(ents, str):
            all_entities.extend(json.loads(ents))
        elif isinstance(ents, list):
            all_entities.extend(ents)

    entity_series = pd.Series(all_entities).value_counts().to_dict()

    # 3. Snapshot analysis
    unique_tokens = df_obs["market_id"].nunique()
    min_ts = str(df_obs["timestamp"].min()) if not df_obs.empty else None
    max_ts = str(df_obs["timestamp"].max()) if not df_obs.empty else None
    price_stats = {
        "min": float(df_obs["yes_mid"].min()) if not df_obs.empty else 0.0,
        "mean": float(df_obs["yes_mid"].mean()) if not df_obs.empty else 0.0,
        "median": float(df_obs["yes_mid"].median()) if not df_obs.empty else 0.0,
        "max": float(df_obs["yes_mid"].max()) if not df_obs.empty else 0.0,
        "std": float(df_obs["yes_mid"].std()) if not df_obs.empty else 0.0,
    }

    # Token to market title mapping
    token_to_title = {}
    for _, row in df_markets.iterrows():
        t_ids = row.get("clob_token_ids")
        if isinstance(t_ids, str):
            try:
                t_ids = json.loads(t_ids)
            except Exception:
                t_ids = []
        if isinstance(t_ids, list):
            for tid in t_ids:
                token_to_title[str(tid)] = row["title"]

    # 4. Pairwise price correlation among high-observation tokens
    df_obs_clean = df_obs.copy()
    df_obs_clean["hourly_ts"] = pd.to_datetime(df_obs_clean["timestamp"]).dt.floor("1h")
    # Average within the same hour if multiple snapshots exist
    hourly_df = df_obs_clean.groupby(["hourly_ts", "market_id"])["yes_mid"].mean().reset_index()

    pivoted = hourly_df.pivot(index="hourly_ts", columns="market_id", values="yes_mid")
    # Filter tokens with at least 50 observations
    valid_cols = [c for c in pivoted.columns if pivoted[c].count() >= 50]
    pivoted_clean = pivoted[valid_cols].ffill().bfill()
    corr_matrix = pivoted_clean.corr()

    # Find highest positive & negative correlation pairs
    correlations = []
    cols = list(corr_matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c_val = corr_matrix.iloc[i, j]
            if not np.isnan(c_val) and abs(c_val) < 0.9999: # exclude self/duplicates
                t_a = cols[i]
                t_b = cols[j]
                correlations.append({
                    "token_a": t_a,
                    "token_b": t_b,
                    "market_a_title": token_to_title.get(t_a, t_a[:20]),
                    "market_b_title": token_to_title.get(t_b, t_b[:20]),
                    "correlation": float(c_val)
                })

    correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    results = {
        "total_markets": len(df_markets),
        "total_canonical_records": len(df_canon),
        "total_snapshots": len(df_obs),
        "unique_tokens_with_history": unique_tokens,
        "time_range": {"start": min_ts, "end": max_ts},
        "total_volume_usd": float(total_volume),
        "total_liquidity_usd": float(total_liquidity),
        "volume_stats": volume_stats,
        "liquidity_stats": liquidity_stats,
        "top_entities": dict(list(entity_series.items())[:10]),
        "price_stats": price_stats,
        "top_correlated_pairs": correlations[:15]
    }

    out_file = Path("results/eda_summary.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"EDA successfully written to {out_file}")
    return results

if __name__ == "__main__":
    res = run_market_eda()
    print("\n================ EDA SUMMARY REPORT ================")
    print(f"Total Markets Analyzed: {res['total_markets']}")
    print(f"Total Price Observations: {res['total_snapshots']} across {res['unique_tokens_with_history']} tokens")
    print(f"Time Range: {res['time_range']['start']} to {res['time_range']['end']}")
    print(f"Total Universe Volume: ${res['total_volume_usd']:,.2f}")
    print(f"Total Universe Liquidity: ${res['total_liquidity_usd']:,.2f}")
    print("\nTop Entities Extracted:")
    for ent, cnt in res['top_entities'].items():
        print(f"  - {ent}: {cnt} contracts")
    print("\nTop Economically Correlated Prediction Market Pairs:")
    for pair in res['top_correlated_pairs'][:8]:
        print(f"  - Corr = {pair['correlation']:+.3f}: '{pair['market_a_title'][:38]}' <-> '{pair['market_b_title'][:38]}'")
    print("====================================================\n")
