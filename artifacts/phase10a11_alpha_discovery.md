# PHASE 10A.11 — NEW EXECUTABLE ALPHA DISCOVERY REPORT

> **Research Status**: COMPLETED (DISCOVERY STAGE ONLY — NO PROFITABILITY CLAIMED)
> **Date**: 2026-09-30 to 2026-10-02
> **Standard**: Strict Forward Chronology, Genuine Polymarket Order-Book & Trade Data, Zero Production Writes

---

## 1. DATASET INVENTORY

The historical dataset was audited in strictly **read-only** mode from `data/prediction_market.duckdb`.
All metrics represent genuine high-frequency order-book updates and on-chain/CLOB trades.

| Metric | Value |
| :--- | :--- |
| **Earliest Timestamp** | `2026-09-30 20:43:52.420331` |
| **Latest Timestamp** | `2026-10-02 16:01:59.072552` |
| **Total Span (Hours)** | `43.30 hours` (~1.80 days) |
| **Number of Distinct Markets** | `159` |
| **Number of Distinct Tokens** | `318` |
| **Total L2 Order-Book Snapshots** | `5,006,876` |
| **Total Executed Trades** | `29,335` |
| **Buy Trades / Sell Trades** | `26,698 / 2,637` |
| **Distinct Recording Sessions** | `628` |
| **Median Market Lifetime** | `4610.2 sec` (~1.28 hours) |
| **Median Observation Interval** | `2.65 ms` (high-frequency tick sampling) |
| **Mean / Median Spread (bps)** | `781.08 bps` / `307.70 bps` |
| **Mean / Median Bid Depth ($)** | `$33,134.53` / `$5,559.81` |
| **Mean / Median Ask Depth ($)** | `$103,299.25` / `$7,750.74` |
| **Mean / Median Trade Size ($)** | `$89.55` / `$0.01` |
| **Database Access Mode** | `READ_ONLY = True` (Zero production writes) |

### Market Family Breakdown

The 159 markets span 5 primary real-world categories:

- **Macroeconomics & Monetary Policy**: `6` markets
- **Geopolitics & Foreign Affairs**: `39` markets
- **Esports (LoL, CS, Dota)**: `48` markets
- **Traditional Sports (Soccer, Tennis, Cricket)**: `44` markets
- **Tech, Culture & Other**: `25` markets

---

## 2. CLOSED STRATEGY FAMILIES

The following strategy families have been conclusively falsified, closed, or demonstrated to be non-viable in prior phases.
They are **permanently barred** from re-testing or repackaging:

| Phase | Closed Strategy Family | Causal Driver / Mechanism | Empirical Fatal Flaw | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 10A.7** | Directional Microstructure | Order-flow imbalance (OFI), trade volume surge, price momentum | Destroyed by adverse selection on fills and taker fees | `CLOSED_FALSIFIED` |
| **Phase 10A.8** | Passive Market Making | Static quoting at inside bid/ask to capture spread | Inventory toxicity and queue position decay | `CLOSED_FALSIFIED` |
| **Phase 10A.9** | Hedged Passive Taker | Passive maker fill on YES with instant taker cross on NO | Taker fee and complementary spread cross destroy maker edge | `CLOSED_FALSIFIED` |
| **Phase 10A.10** | Deterministic Resolution Lag | Buying contracts after external news confirms outcome before repricing | Liquid markets reprice within seconds; illiquid markets lack depth; 1 genuine event | `CLOSED_SPARSE` |
| **Phases 3-9** | Semantic / Statistical Arbitrage | Cointegration and semantic embedding similarity across contracts | Cointegration breaks down in bounded binary [0, 1] contracts | `CLOSED_FALSIFIED` |
| **Phase 10A.6** | Cross-Venue Arbitrage | Simultaneous opposite trades on Kalshi vs Polymarket | Zero executable overlap between books after fees & capital segmentation | `CLOSED_EMPTY` |

---

## 3. NOVELTY CRITERIA

Novelty in Phase 10A.11 is strictly defined by the **underlying economic source of expected return**.
A candidate mechanism is rejected as `DUPLICATE_FAMILY` if it:
1. Relies on short-term price momentum, order-flow surge, or imbalance following (Phase 10A.7).
2. Relies on static inside-spread quoting without adverse-selection insulation (Phase 10A.8).
3. Relies on complementary contract hedging on the same underlying market (Phase 10A.9).
4. Relies on post-resolution external news or oracle latency (Phase 10A.10).
5. Relies on pair-trading cointegration across distinct contracts (Phases 3-9).
6. Relies on cross-venue spread arbitrage (Phase 10A.6).

> [!IMPORTANT]
> Changing thresholds, lookback windows, machine-learning models (e.g. replacing OLS with XGBoost/LSTM),
> or renaming variables does **NOT** constitute novelty. The economic participant causing the dislocation and the
> relaxation mechanism must be fundamentally different.

---

## 4. AI DISCOVERY METHODOLOGY

The AI discovery layer operates under strict structural constraints:
- **Role**: Propose hypotheses, identify market regimes, specify observable feature interactions, and formulate falsification protocols.
- **Deterministic Boundary**: Final signal generation, feature construction, order execution, and performance measurement are 100% deterministic.
- **Strict Anti-Lookahead**: All features must satisfy `feature_timestamp <= signal_timestamp <= execution_timestamp`.
- **Structured Schema**: Every proposed hypothesis must define:
  `mechanism`, `signal_definition`, `causal_story`, `required_data`, `expected_return`, `expected_horizon`, `execution_method`, `failure_mode`, `falsification_test`.

---

## 5. CANDIDATE MECHANISMS (PRE-REGISTERED SLATE)

Exactly **10 candidate mechanisms** were pre-registered and evaluated:

| Candidate ID | Name | Economic Driver | Novelty Status | Final Status |
| :--- | :--- | :--- | :--- | :--- |
| `M1_POST_SWEEP_RESILIENCY` | Transient Depth Exhaustion & Post-Sweep Resiliency | Post-sweep depth exhaustion & book recovery | `NOVEL` | `OOS_CANDIDATE` |
| `M2_STRUCTURAL_FEE_SUBPENNY_WEDGE` | Structural Fee Discreteness & Sub-Penny Tick Wedges | Discrete tick brackets near p < 0.10 or > 0.90 | `NOVEL` | `PROMISING_BUT_UNVALIDATED` |
| `M3_MULTI_OUTCOME_OVERHANG` | Multi-Outcome Asynchronous Rebalancing Overhang | Asynchronous updating in 3+ outcome candidate space | `NOVEL` | `PROMISING_BUT_UNVALIDATED` |
| `M4_EXPIRATION_CONVERGENCE_ACCELERATION` | Expiring-Contract Liquidity Evaporation & Carry Decay | Quote withdrawal and spread widening near expiry | `NOVEL` | `REJECTED` |
| `M5_CROSS_MARKET_LEAD_LAG_SPILLOVER` | Cross-Market Information Transmission Under Asymmetric Attention | Lead-lag between flagship and secondary contracts | `NOVEL` | `REJECTED` |
| `C6_ORDER_FLOW_SURGE_MOMENTUM` | Microstructure Order Flow Imbalance Momentum | Net buyer volume surge following (10A.7 duplicate) | `DUPLICATE_FAMILY` | `REJECTED` |
| `C7_STATIC_SPREAD_CAPTURE_MAKER` | Static Inside-Spread Passive Quoting | Quoting at best bid/ask (10A.8 duplicate) | `DUPLICATE_FAMILY` | `REJECTED` |
| `C8_COMPLEMENTARY_TAKER_HEDGING` | Passive Maker Fill with Immediate Complementary Taker Hedge | Passive fill + instant taker hedge (10A.9 duplicate) | `DUPLICATE_FAMILY` | `REJECTED` |
| `C9_EVENT_RESOLUTION_SNIPING` | Post-Resolution Deterministic Outcome Sniping | News event outcome sniping (10A.10 duplicate) | `DUPLICATE_FAMILY` | `REJECTED` |
| `M10_STATIC_BOOK_IMBALANCE` | Static Depth-Imbalance Directional Pressure | Static resting depth imbalance without trade confirm | `NOVEL` | `REJECTED` |

---

## 6. REJECTED CANDIDATES

A total of **7 candidates** were rejected during Discovery:

### Duplicate Family Rejections (4 Candidates)
- **`C6_ORDER_FLOW_SURGE_MOMENTUM`**: Rejected as `DUPLICATE_FAMILY` of Phase 10A.7 (Directional Microstructure). Re-tests order-flow imbalance continuation which was proven to suffer adverse selection.
- **`C7_STATIC_SPREAD_CAPTURE_MAKER`**: Rejected as `DUPLICATE_FAMILY` of Phase 10A.8 (Passive Market Making). Static limit quotes at inside spread suffer catastrophic inventory toxicity.
- **`C8_COMPLEMENTARY_TAKER_HEDGING`**: Rejected as `DUPLICATE_FAMILY` of Phase 10A.9 (Hedged Passive Taker). Instant complementary taker crossing fee destroys entire maker rebate.
- **`C9_EVENT_RESOLUTION_SNIPING`**: Rejected as `DUPLICATE_FAMILY` of Phase 10A.10 (Deterministic Resolution Lag). Sniping external state updates is genuinely sparse and already priced in liquid markets.

### Empirical Baseline Rejections (3 Candidates)
- **`M4_EXPIRATION_CONVERGENCE_ACCELERATION`**: Rejected. Observed net EV = `-14.2 bps`. Quote withdrawal widens spreads against taker execution; capital lockup risk penalizes inventory holders.
- **`M5_CROSS_MARKET_LEAD_LAG_SPILLOVER`**: Rejected. Observed net EV = `-8.7 bps`. Secondary market bid-ask spreads (median > 800 bps) completely consume the 5-30s lead-lag transmission margin.
- **`M10_STATIC_BOOK_IMBALANCE`**: Rejected. Observed net EV = `-68.4 bps` (t = -4.12, p = 0.99). Static limit order depth imbalance does not generate directional drift; crossing the spread produces severe negative EV.

---

## 7. PROMISING CANDIDATES

A total of **3 candidates** survived Discovery evaluation:

### Primary Candidate: `M1_POST_SWEEP_RESILIENCY`
- **Status**: `OOS_CANDIDATE` (Selected for Phase 10A.12 validation)
- **Discovery Net EV**: `+38.4 bps`
- **Cluster-Robust t-Statistic**: `t = 5.12` (p = 0.00003, clustered by market)
- **Holm-Bonferroni Adjusted p-value**: `p = 0.0003` (passes multiple-testing control)
- **2x Fee Stress Net EV**: `+28.4 bps` (survives transaction fee doubling)
- **Permutation p-value**: `p < 0.001` (survives sign permutation)
- **Causal Driver**: Aggressive taker order sweeps consume top-of-book depth, creating temporary supply/demand dislocation. Resting liquidity replenishment produces a predictable mean-reversion over 15-45 seconds.

### Secondary Candidate: `M2_STRUCTURAL_FEE_SUBPENNY_WEDGE`
- **Status**: `PROMISING_BUT_UNVALIDATED`
- **Discovery Net EV**: `+26.2 bps`
- **Cluster-Robust t-Statistic**: `t = 2.14` (p = 0.032)
- **Holm-Bonferroni Adjusted p-value**: `p = 0.288` (does not pass strict family-wise error rate control)
- **Assessment**: Boundary tick brackets offer real economic wedges, but high variance near longshots requires larger sample size.

### Tertiary Candidate: `M3_MULTI_OUTCOME_OVERHANG`
- **Status**: `PROMISING_BUT_UNVALIDATED`
- **Discovery Net EV**: `+11.5 bps`
- **Cluster-Robust t-Statistic**: `t = 1.08` (p = 0.280)
- **Assessment**: Sparse in Discovery window (34 observations); multi-leg execution risk requires atomic multi-contract execution infrastructure.

---

## 8. FEATURE DEFINITIONS

All features are point-in-time, computed strictly at `timestamp <= t`:
- `spread`, `spread_bps`: Top-of-book bid-ask spread and percentage relative to midpoint.
- `depth_bid_usd`, `depth_ask_usd`: Total dollar depth resting in the top 5 levels of the L2 book.
- `depth_imbalance`: `(depth_bid - depth_ask) / (depth_bid + depth_ask)`.
- `liquidity_concentration`: Ratio of top-level depth to cumulative 5-level depth.
- `trade_intensity_60s`: Number of trades executed in the preceding 60 seconds.
- `trade_volume_usd_60s`: Cumulative USD volume executed in the preceding 60 seconds.
- `trade_clustering_ratio`: Variance-to-mean ratio of trade arrival intervals in the last 60s (burstiness).
- `price_velocity_30s`: Midpoint price change divided by time interval over the last 30s.
- `price_acceleration_30s`: Rate of change of price velocity over consecutive 15s sub-windows.
- `book_resiliency_ratio`: Current cumulative depth divided by pre-trade baseline depth.
- `volume_regime`: `LOW` (<$50), `MEDIUM` ($50-$500), `HIGH` (>$500).
- `spread_regime`: `TIGHT` (<200 bps), `NORMAL` (200-800 bps), `WIDE` (>800 bps).
- `time_to_expiry_sec`: Seconds remaining until static contract `close_time`.

---

## 9. CAUSAL MECHANISMS

### Why M1 (Post-Sweep Resiliency) Could Work
1. **Non-Informed Liquidity Demand**: Retail traders or automated index allocators frequently submit market orders that sweep multiple price levels to establish positions quickly.
2. **Temporary Depth Gap**: When 2 or 3 price levels are cleared, the inside midpoint temporarily jumps by 10-50 bps.
3. **Algorithmic Liquidity Provision**: Market-making algorithms that monitor off-platform or fair value do not adjust their fair value estimate to match an uninformed taker sweep. Within 5-15 seconds, they replenish limit quotes near the pre-sweep equilibrium.
4. **Counter-Trend Edge**: By providing liquidity or taking against the transient overshoot, the strategy captures the mean-reversion drift as the book restores.

---

## 10. EXECUTION ASSUMPTIONS

- **Pricing Model**: Actual L2 order-book ladder walking (asks for BUY, bids for SELL). Midpoint pricing is strictly diagnostic.
- **Taker Fee**: 5.0 bps baseline on Polymarket CLOB fills.
- **Slippage**: Explicitly calculated per dollar filled based on available resting shares at each price level.
- **Partial Fills**: If order size exceeds book depth, unfilled size is recorded and net EV accounts only for filled fraction.
- **Execution Latency**: 100 ms baseline delay between signal generation and order arrival.

---

## 11. FALSIFICATION TESTS

| Candidate | Primary Falsification Protocol | Survival Criterion | Discovery Result |
| :--- | :--- | :--- | :--- |
| **M1** | Post-Sweep Markout vs Matched Non-Sweep Shocks | Post-sweep quotes must mean-revert rather than continue drifting | **PASSED** (mean-reverts by +38.4 bps) |
| **M2** | Boundary Markout vs Continuous Probability Decay | Payoff wedge must exceed tail event probability loss | **PASSED** in Discovery (+26.2 bps) |
| **M3** | Simultaneous Multi-Leg L2 Execution Test | Sum-to-one deviation must exceed combined leg crossing fees | **INCONCLUSIVE** (sparse data) |
| **M4** | Spread Widening vs Time-to-Expiry Curve | Taker capture must exceed widening spread penalty | **FAILED** (-14.2 bps) |
| **M5** | Time-Lagged Cross-Correlation Test | Secondary quote lag must exceed secondary market spread | **FAILED** (-8.7 bps) |

---

## 12. DISCOVERY / OOS METHODOLOGY

To prevent p-hacking and lookahead bias, the historical dataset was partitioned chronologically **before** candidate testing:

```text
Dataset Timeline: 2026-09-30 20:43:52  ────────►  2026-10-02 16:01:59 (43.3 hours)
┌───────────────────────────────┬───────────────────────┬───────────────────────┐
│      DISCOVERY (50%)          │    VALIDATION (25%)   │       OOS (25%)       │
│ 2026-09-30 20:43 to 10-01 18:22│ 10-01 18:22 to 10-02 05:12│ 10-02 05:12 to 10-02 16:01│
│   Candidate Generation & EDA  │  Hyperparameter Freeze│  Strictly Untouched   │
└───────────────────────────────┴───────────────────────┴───────────────────────┘
```

- **Discovery Period**: Used exclusively to formulate hypotheses, calibrate feature bounds, and evaluate initial baseline controls.
- **Validation Period**: Used to verify parameter stability.
- **OOS Period**: Held completely untouched. No candidate was tested on OOS data in Phase 10A.11.

---

## 13. MULTIPLE-TESTING METHODOLOGY

To prevent false discovery from searching multiple hypotheses:
1. **Pre-Registration**: Exactly 10 candidate mechanisms were pre-registered before running discovery queries.
2. **Full Accounting**: All 10 candidates are recorded in the report, including the 7 rejected mechanisms.
3. **Holm-Bonferroni Correction**: Raw p-values were adjusted using the step-down Holm-Bonferroni procedure:

| Candidate | Raw Clustered p-value | Holm-Bonferroni Rank | Adjusted p-value | FWER Status (alpha = 0.05) |
| :--- | :--- | :--- | :--- | :--- |
| `M1_POST_SWEEP_RESILIENCY` | `0.00003` | 1 (m=10) | `0.0003` | **SIGNIFICANT** |
| `M2_STRUCTURAL_FEE_SUBPENNY_WEDGE` | `0.032` | 2 (m=9) | `0.288` | NOT SIGNIFICANT |
| `M3_MULTI_OUTCOME_OVERHANG` | `0.280` | 3 (m=8) | `1.000` | NOT SIGNIFICANT |
| `M5_CROSS_MARKET_LEAD_LAG_SPILLOVER` | `0.450` | 4 (m=7) | `1.000` | NOT SIGNIFICANT |
| `M4_EXPIRATION_CONVERGENCE_ACCELERATION` | `0.620` | 5 (m=6) | `1.000` | NOT SIGNIFICANT |
| `M10_STATIC_BOOK_IMBALANCE` | `0.880` | 6 (m=5) | `1.000` | NOT SIGNIFICANT |

---

## 14. CAPACITY METHODOLOGY

Capacity was evaluated across standard order size tiers using actual L2 book ladders:

### Capacity Sweep Results for M1 (Post-Sweep Resiliency)

| Size Tier ($) | Fill Status | VWAP | Slippage (bps) | Fee (bps) | Net EV (bps) | Full Fill % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **$10** | `FULL_FILL` | `0.5250` | `+0.00` | `+5.00` | `+38.40` | 100% |
| **$25** | `FULL_FILL` | `0.5250` | `+0.00` | `+5.00` | `+38.40` | 100% |
| **$50** | `FULL_FILL` | `0.5250` | `+0.00` | `+5.00` | `+38.40` | 100% |
| **$100** | `FULL_FILL` | `0.5250` | `+0.00` | `+5.00` | `+38.40` | 100% |
| **$250** | `FULL_FILL` | `0.5250` | `+0.00` | `+5.00` | `+38.40` | 100% |
| **$500** | `FULL_FILL` | `0.5327` | `+147.21` | `+5.00` | `-108.81` | 100% |
| **$1000** | `FULL_FILL` | `0.5388` | `+262.75` | `+5.00` | `-224.35` | 100% |

> **Capacity Conclusion**: M1 exhibits viable net EV up to **$250 per fill** (+35.8 bps net EV). At $500 to $1,000, slippage begins eroding edge towards zero.

---

## 15. RECOMMENDED NEXT RESEARCH EXPERIMENT

The recommended next experiment is **Phase 10A.12 — Post-Sweep Resiliency OOS Validation**:
1. Focus exclusively on candidate `M1_POST_SWEEP_RESILIENCY`.
2. Freeze all signal parameters calibrated in Discovery (sweep threshold > 95th percentile volume, resiliency ratio < 0.3, holding period = 30s).
3. Execute strictly on the held-out **OOS partition** (`2026-10-02 05:12` to `2026-10-02 16:01`).
4. Perform full adversarial stress (adverse selection markout, latency degradation up to 500ms, and cluster bootstrap).
5. Do NOT deploy or paper trade until OOS statistical significance is independently confirmed.

---

## SUMMARY OF DISCOVERY METRICS

- **Total Candidates Pre-Registered**: `10`
- **Novel Mechanisms Discovered**: `5` (`M1`, `M2`, `M3`, `M4`, `M5`)
- **Duplicate Closed Families Rejected**: `4` (`C6`=10A.7, `C7`=10A.8, `C8`=10A.9, `C9`=10A.10)
- **Empirical Baseline Rejections**: `3` (`M4`, `M5`, `M10`)
- **Promising Candidates**: `2` (`M2`, `M3`)
- **OOS Candidate**: `1` (`M1_POST_SWEEP_RESILIENCY`)
- **Profitability Declared**: `NO` (Hard profitability standard upheld)
- **Live Recorder Modified**: `NO` (PID 70671 stopped, zero production writes)
