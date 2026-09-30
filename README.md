# PredictionMarket-AI-ARB

Quantitative research framework evaluating whether Large Language Models (LLMs) and relative-value statistical arbitrage can discover and execute profitable cross-market trading strategies on prediction markets (specifically Polymarket CLOB).

```
Phase 1: Market-Data Ingestion & CLOB Reconstruction
    ↓
Phase 2: LLM Multi-Market Semantic Discovery
    ↓
Phase 3: Multi-Month Statistical & OOS Falsification
    ↓
Phase 4: Realistic Execution & Capital Constraints
    ↓
Phase 5: Live Prospective Shadow Trading
    ↓
Phase 6: Causal Relative-Value Model & Multi-Horizon Decay
    ↓
Phase 7: Passive Execution & Market-Making Attack (d=1 Sweet Spot)
    ↓
Phase 8: Microstructure Realism & Prospective Stress Testing (N=120)
    ↓
Phase 9: Pre-Live Adversarial Validation (The 20-Point De-Biasing Battery)
    ↓
Scientific Verdict: Systematic Falsification of Backtest Artifacts
```

---

## 🎯 Executive Summary & Scientific Findings

This project investigates the core empirical question:
> **"Can an AI-driven quantitative system discover indirect, conditional cross-market prediction market relationships whose short-lived dislocations can be monetized in real CLOB order books?"**

Across 9 rigorously controlled phases spanning a 452-day Polymarket dataset (358,090 snapshots across 503 markets):

1. **Phase 1–3 (Discovery & Falsification)**: 40 LLM-generated second-order hypotheses were subjected to Benjamini-Hochberg False Discovery Rate (FDR) control and Walk-Forward OOS testing. **0 out of 40 novel hypotheses survived out-of-sample validation**.
2. **Phase 4–5 (Execution Frictions & Prospective Test)**: Theoretical structural arbitrage (e.g. BTC ladder bound violations) yielded zero executable volume under real CLOB depth walking. Prospective shadow trading demonstrated a collapse from $+7.83\%$ predicted edge to $-0.01\%$ realized return.
3. **Phase 6 (Localized 15-Minute Edge)**: Strict 9-dimensional causal prompting and Ornstein-Uhlenbeck cointegration revealed that cross-market dislocations exist at short horizons ($\sim 15\text{ minutes}$ with $+0.82\%\text{ to }+1.10\%$ gross move), but aggressive taker execution is systematically unviable because Polymarket CLOB round-trip friction is $\approx 1.60\%$.
4. **Phase 7–8 (Passive Market-Making Edge)**: Transitioning from aggressive taker to passive liquidity provider quoting $1\text{ tick}$ inside the spread ($d=1$) captured the half-spread ($+0.75\%$) with $0\text{ bps}$ maker fees, producing an apparent $+70.3\text{ bps}$ markout, $68.8\%$ win rate, and an annualized Sharpe ratio of $17.43$ across $N=120$ prospective events under Brownian-bridge touch simulation.
5. **Phase 9 (Pre-Live Adversarial Demolition)**: Subjected the candidate strategy to an adversarial battery with one rule: *"every experiment must be capable of proving the strategy wrong."*
   - **Placebo Negative Controls**: Randomized market pairs, time-shifted catalysts (+24h), reversed causal directions ($B \to A$), and permuted timestamps **all produced identical Sharpe ratios ($5.75\text{ to }24.71$) and $+60\text{ to }+81\text{ bps}$ markouts**, proving the return was driven by generic maker spread-bounce, not AI predictive alpha.
   - **Permutation Test ($p = 0.3833$)**: Permuting the signal $B=2,000$ times yielded a null distribution mean of $+0.6996\%$, identically matching the observed $+0.7000\%$ ($z = 0.00$). The signal is statistically indistinguishable from random noise.
   - **Fill Model Collapse**: Under conservative trade-through mechanics, fill rates collapsed from $51.7\%$ to **$0.8\%$ ($1\text{ fill}$)**, turning P&L negative ($-\$1.75$, Sharpe $-11.11$).
   - **Verdict**: **Falsified**. Capital deployment was halted, successfully preventing real-world capital loss from an illusory backtest artifact.

---

## 🏗️ System Architecture

```
PredictionMarketModel/
├── src/
│   ├── api/                  # Polymarket & Kalshi CLOB API clients
│   ├── normalization/        # Unified data schema & canonical market mapping
│   ├── db/                   # DuckDB high-performance analytical storage
│   ├── llm/                  # Structured causal prompt engines & validators
│   ├── statistics/           # FDR, Walk-Forward, & Permutation engines
│   ├── execution/            # Order book depth walker, fee & slippage models
│   ├── phase6/               # Relative-value stat-arb & multi-horizon decay
│   ├── phase7/               # Event-response models & Brownian-bridge simulator
│   ├── phase8/               # Latency sweep, dynamic cancellation, & queue stress
│   ├── phase9/               # 20-Point pre-live adversarial validation battery
│   └── pipeline/             # Automated execution pipelines (Phases 1-9)
├── tests/                    # 34 comprehensive unit and integration tests
├── config/                   # System & database configuration
└── pyproject.toml            # Poetry / setuptools configuration
```

---

## 🔬 The 9 Research Phases

| Phase | Title | Core Objective | Key Result |
|:---:|---|---|---|
| **Phase 1** | Market Data Ingestion | High-frequency snapshots, order book reconstruction | 358k snapshots across 503 Polymarket tokens |
| **Phase 2** | AI Hypothesis Discovery | Semantic cross-market relationship generation | 40 candidate pairs spanning Macro, Crypto, Politics |
| **Phase 3** | Statistical Falsification | Benjamini-Hochberg FDR, event clustering, OOS test | **0/40 novel hypotheses survived** (all falsified) |
| **Phase 4** | Microstructure Execution | CLOB depth walking, partial fills, liquidity capacity | Structural BTC ladders had 0 executable depth |
| **Phase 5** | Prospective Shadow Trading | Immutable prospective run with frozen parameters | Predicted $+7.83\% \to -0.01\%$ realized return |
| **Phase 6** | Relative-Value Stat-Arb | 9D causal prompt, OU mean-reversion, horizon decay | Discovered 15m dislocation; taker execution failed |
| **Phase 7** | Passive Execution Attack | Quoting $d$ ticks from mid inside the spread | $d=1$ achieved $+1.74\%$ unconditional net expected P&L |
| **Phase 8** | Microstructure Realism | Latency sweep (0–5s), queue stress (0–99%), $N=120$ | Appeared validated: $+70.3\text{ bps}$ markout, Sharpe 17.43 |
| **Phase 9** | Adversarial Validation | 20-point de-biasing battery (Placebos, Permutations, Strict Fills) | **Falsified**: Placebos produce equal Sharpe; trade-through fills collapse to 0.8% |

---

## 🧪 Running the Test Suite

All 34 tests across all phases pass with zero warnings:

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run full test suite
pytest tests/ -v
```

---

## 🚀 Running the Research Pipelines

```bash
# Phase 6: Stat-Arb Attack & Horizon Decay
python src/pipeline/run_phase6_attack.py

# Phase 7: Passive Execution & Market-Making Evaluation
python src/pipeline/run_phase7_passive_execution.py

# Phase 8: Microstructure Realism & Prospective Stress Testing
python src/pipeline/run_phase8_stress_test.py

# Phase 9: Pre-Live Adversarial Validation Battery (20 Stress Gates)
python src/pipeline/run_phase9_adversarial_validation.py
```

---

## 📜 Research Philosophy

> *"Don't ask: 'What else can I add to make this profitable?' Ask: 'What experiment would convince me that this isn't real?'"*

This codebase stands as a fully transparent, reproducible demonstration of quantitative rigor: using adversarial validation to aggressively hunt down lookahead bias, queue priority assumptions, and spread-capture artifacts before risking real capital.
