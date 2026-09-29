"""Generate notebooks/02_relationship_discovery.ipynb."""
import json
from pathlib import Path

def create_discovery_notebook():
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Phase 2: AI Relationship Discovery & Quantitative Falsification Layer\n",
                    "This notebook demonstrates the falsification architecture:\n",
                    "1. **Output A**: Relationship Discovery (economic mechanism, non-obvious cross-domain links).\n",
                    "2. **Output B**: Economic Constraint (falsifiable mathematical pricing constraints).\n",
                    "3. **Hypothesis Falsification Engine**: Designed to kill spurious hypotheses through return-differencing, sample-size tests, 95% confidence intervals, and friction costs."
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
                    "import json\n",
                    "\n",
                    "con = duckdb.connect('../data/prediction_market.duckdb')\n",
                    "df_rels = con.execute('SELECT * FROM relationships').df()\n",
                    "df_falsify = con.execute('SELECT * FROM falsification_reports').df()\n",
                    "merged = df_rels.merge(df_falsify, on='constraint_id')\n",
                    "print(f'Total Candidates Evaluated: {len(merged)}')\n",
                    "merged['verdict'].value_counts()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 1. Verdict Breakdown: Killing Spurious Hypotheses\n",
                    "The system classifies hypotheses into:\n",
                    "- `TRADEABLE`: Statistically significant, sign-aligned, survives all transaction friction.\n",
                    "- `REJECTED_SPURIOUS`: Common macro trend artifact or 95% CI spans zero.\n",
                    "- `REJECTED_COSTS`: Gross effect positive but erased by spread, fee, and slippage.\n",
                    "- `REJECTED_DIRECTION_MISMATCH`: Empirical response sign contradicts hypothesis.\n",
                    "- `REJECTED_UNDERPOWERED`: Insufficient sample size (N < N_min)."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import matplotlib.pyplot as plt\n",
                    "merged['verdict'].value_counts().plot(kind='barh', color=['crimson', 'orange', 'salmon', 'forestgreen'])\n",
                    "plt.title('Distribution of Hypothesis Falsification Verdicts')\n",
                    "plt.xlabel('Count')\n",
                    "plt.gca().invert_yaxis()\n",
                    "plt.show()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 2. Surviving Tradeable Constraints vs Killed Candidates"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "display_cols = ['domain_cluster', 'economic_mechanism', 'constraint_type', 'sample_size_n', 'net_effect_pp', 'net_expected_edge_pp', 'verdict', 'kill_reason']\n",
                    "merged[display_cols].head(10)"
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

    out_path = Path("notebooks/02_relationship_discovery.ipynb")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=2)
    print(f"Created notebook at {out_path}")

if __name__ == "__main__":
    create_discovery_notebook()
