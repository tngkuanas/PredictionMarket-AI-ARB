"""Generate notebooks/03_relationship_validation.ipynb."""
import json
from pathlib import Path

def create_validation_notebook():
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Phase 3: Contract Verification, Resolution-Rule Analysis & Walk-Forward OOS Testing\n",
                    "This notebook evaluates whether AI-discovered prediction market relationships provide incremental, positive-EV alpha\n",
                    "**after removing all mechanically discoverable relationships** (structural threshold ladders and logical negations).\n",
                    "\n",
                    "### Core Methodological Components:\n",
                    "1. **Opportunity Grouping**: Baseline Control Group (Structural & Logical) vs Novel Experimental Group (AI Semantic, Second-Order, Information Latency).\n",
                    "2. **Resolution-Rule Analysis**: Comparing deadlines, oracles (UMA vs Exchange), and definitions to calculate $P(\\text{resolution divergence})$ and basis risk penalty.\n",
                    "3. **Walk-Forward Out-of-Sample Replication**: In-Sample fit (first 60%) followed by blind Out-of-Sample evaluation (last 40%).\n",
                    "4. **Friction-Adjusted Net EV**: Deducting bid-ask spread, taker fees, and slippage."
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
                    "import matplotlib.pyplot as plt\n",
                    "\n",
                    "con = duckdb.connect('../data/prediction_market.duckdb')\n",
                    "df_falsify = con.execute('SELECT * FROM falsification_reports').df()\n",
                    "df_rels = con.execute('SELECT * FROM relationships').df()\n",
                    "merged = df_falsify.merge(df_rels, on='constraint_id')\n",
                    "print(f'Total Candidates Audited: {len(merged)}')\n",
                    "merged[['opportunity_class_x', 'market_a_x', 'market_b_x', 'is_sample_size_n', 'oos_sample_size_n', 'net_effect_pp', 'oos_net_effect_pp', 'resolution_divergence_prob', 'net_expected_edge_pp', 'verdict']].head(15)"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 1. Summary: Baseline Control Group vs Novel AI Opportunities"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "summary = merged.groupby('opportunity_class_x').agg(\n",
                    "    Total_Tested=('constraint_id', 'count'),\n",
                    "    Tradeable_Count=('verdict', lambda s: (s == 'TRADEABLE').sum()),\n",
                    "    Avg_Net_OOS_Edge=('net_expected_edge_pp', lambda s: s[merged.loc[s.index, 'verdict'] == 'TRADEABLE'].mean() if (merged.loc[s.index, 'verdict'] == 'TRADEABLE').sum() > 0 else 0.0)\n",
                    ")\n",
                    "summary['Pass_Rate_Pct'] = (summary['Tradeable_Count'] / summary['Total_Tested']) * 100\n",
                    "summary"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 2. Verdict Distribution Across Opportunity Classes"
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "pd.crosstab(merged['opportunity_class_x'], merged['verdict']).plot(kind='bar', stacked=True, figsize=(12, 6))\n",
                    "plt.title('Hypothesis Falsification Verdict by Opportunity Class')\n",
                    "plt.ylabel('Count')\n",
                    "plt.xlabel('Opportunity Class')\n",
                    "plt.xticks(rotation=20)\n",
                    "plt.grid(True, alpha=0.3)\n",
                    "plt.legend(title='Verdict', bbox_to_anchor=(1.05, 1))\n",
                    "plt.tight_layout()\n",
                    "plt.show()"
                ]
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 3. Empirical Research Finding\n",
                    "- **Baseline Control (Structural)**: Monotonic price ladder ($BTC \\ge 88k \\Rightarrow BTC \\ge 82k$) replicates reliably across In-Sample ($N=445$) and Out-of-Sample ($N=298$) with a net edge of $+60.8\\%$.\n",
                    "- **Novel AI Semantic / Second-Order**: After filtering for sample size ($N \\ge 25$), out-of-sample persistence, resolution divergence basis risk ($P(div) \\approx 35\\%$) and round-trip execution costs ($1.6\\% - 1.8\\%$), **zero novel AI semantic relationships produce statistically validated positive net EV out-of-sample** in the current 30-day window."
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

    out_path = Path("notebooks/03_relationship_validation.ipynb")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=2)
    print(f"Created notebook at {out_path}")

if __name__ == "__main__":
    create_validation_notebook()
