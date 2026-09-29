"""Generate notebooks/01_market_eda.ipynb."""
import json
from pathlib import Path

def create_eda_notebook():
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Phase 1: Market Universe Exploratory Data Analysis (EDA)\n",
                    "This notebook connects to our local DuckDB database populated by official Polymarket APIs,\n",
                    "analyzes volume and liquidity distributions, examines canonical entity extractions, and evaluates\n",
                    "empirical cross-contract price correlations."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import duckdb\n",
                    "import pandas as pd\n",
                    "import numpy as np\n",
                    "import matplotlib.pyplot as plt\n",
                    "import json\n",
                    "\n",
                    "# Connect to DuckDB store\n",
                    "con = duckdb.connect('../data/prediction_market.duckdb')\n",
                    "df_markets = con.execute('SELECT * FROM markets').df()\n",
                    "df_canon = con.execute('SELECT * FROM canonical_markets').df()\n",
                    "df_obs = con.execute('SELECT * FROM market_snapshots ORDER BY timestamp ASC').df()\n",
                    "print(f'Markets: {len(df_markets)} | Canonical Records: {len(df_canon)} | Snapshots: {len(df_obs)}')\n",
                    "df_markets[['market_id', 'title', 'category', 'volume', 'liquidity']].head(10)"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 1. Volume & Liquidity Distribution\n",
                    "Examining capital allocation across prediction market contracts."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))\n",
                    "df_markets['volume'].plot(kind='hist', bins=20, ax=ax1, color='navy', alpha=0.7, title='Trading Volume Distribution ($)')\n",
                    "ax1.set_xlabel('Volume ($)')\n",
                    "df_markets['liquidity'].plot(kind='hist', bins=20, ax=ax2, color='teal', alpha=0.7, title='Order Book Liquidity Distribution ($)')\n",
                    "ax2.set_xlabel('Liquidity ($)')\n",
                    "plt.tight_layout()\n",
                    "plt.show()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 2. Canonical Entity Clusters\n",
                    "Entities extracted across contracts to group interconnected event domains."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "all_entities = []\n",
                    "for ents in df_canon['entities']:\n",
                    "    if isinstance(ents, str):\n",
                    "        all_entities.extend(json.loads(ents))\n",
                    "    elif isinstance(ents, list):\n",
                    "        all_entities.extend(ents)\n",
                    "pd.Series(all_entities).value_counts().head(10).plot(kind='barh', color='darkgreen', title='Top Canonical Entities in Active Markets')\n",
                    "plt.xlabel('Contract Count')\n",
                    "plt.gca().invert_yaxis()\n",
                    "plt.show()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 3. Hourly Price Time-Series for Key Clusters\n",
                    "Observing probability paths across complementary and conditional markets."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "df_obs_clean = df_obs.copy()\n",
                    "df_obs_clean['hourly_ts'] = pd.to_datetime(df_obs_clean['timestamp']).dt.floor('1h')\n",
                    "hourly_piv = df_obs_clean.groupby(['hourly_ts', 'market_id'])['yes_mid'].mean().unstack()\n",
                    "valid_tokens = [c for c in hourly_piv.columns if hourly_piv[c].count() > 100][:5]\n",
                    "hourly_piv[valid_tokens].plot(figsize=(14, 6), title='Hourly Midpoint Prices for Representative Prediction Contracts')\n",
                    "plt.ylabel('Implied Probability (Price)')\n",
                    "plt.grid(True, alpha=0.3)\n",
                    "plt.legend(valid_tokens, loc='upper left', bbox_to_anchor=(1, 1))\n",
                    "plt.show()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 4. Cross-Market Price Correlation Analysis"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "with open('../results/eda_summary.json') as f:\n",
                    "    eda_data = json.load(f)\n",
                    "corr_df = pd.DataFrame(eda_data['top_correlated_pairs'])\n",
                    "corr_df[['market_a_title', 'market_b_title', 'correlation']].head(10)"
                ]
            }
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python",
                "version": "3.11.15"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 4
    }

    out_path = Path("notebooks/01_market_eda.ipynb")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=2)
    print(f"Created notebook at {out_path}")

if __name__ == "__main__":
    create_eda_notebook()
