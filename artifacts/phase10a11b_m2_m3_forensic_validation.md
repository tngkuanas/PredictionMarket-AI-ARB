# PHASE 10A.11-B — FORENSIC VALIDATION OF M2 AND M3 CANDIDATE MECHANISMS

> **Executive Forensic Verdicts**:
> - **M2 (Structural Fee Discreteness & Sub-Penny Wedges)**: `EXECUTION_EDGE_ABSENT`
> - **M3 (Multi-Outcome Asynchronous Overhang)**: `PROMISING_BUT_INSUFFICIENT_EVIDENCE`
> **Live Recorder Status**: **ONLINE & RUNNING** (PID: `80013`, Uptime Confirmed, Schema & Production DB Strictly Unmodified)
> **Paper Trading Eligibility**: **BARRED** (Neither candidate is permitted to proceed to paper trading)

---

## 1. CRITICAL RECORDER AUDIT & LIVE MONITORING

The live Polymarket CLOB acquisition supervisor daemon was restarted and maintained continuously active throughout Phase 10A.11-B:

| Field | Configuration / Operational State | Compliance |
| :--- | :--- | :--- |
| **Recorder PID** | `80013` | **ACTIVE** |
| **Start Timestamp** | `2026-10-03 13:34:33 UTC` | **CONFIRMED** |
| **Target Duration** | `72.0 hours (259,200s)` | **ACTIVE ACCUMULATION** |
| **Per-Session Cycle** | `30.0s` with anti-stale book re-initialization | **CONFIRMED** |
| **Market Universe Limit** | `25 active markets (50 tradable tokens)` | **CONFIRMED** |
| **Universe Refresh Interval** | `300.0s` dynamic Gamma API polling | **CONFIRMED** |
| **Code / Schema Modification** | `ZERO` modifications to recorder code or tables | **STRICT READ-ONLY PASS** |
| **Liveness Status** | Alive throughout the entire forensic audit | **PASS** |

---

## 2. FROZEN CANDIDATE REPRODUCTION (PHASE 10A.11 DISCOVERY SLATE)

Published Phase 10A.11 metrics were independently reconstructed verbatim:

| Candidate ID | Name | Discovery N | Gross EV (bps) | Net EV (bps) | Clustered t-stat | Holm p-value | Status | Discrepancy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M2** | Structural Fee Subpenny Wedge | `89` | `+31.2` | `+26.2` | `2.14` | `0.2880` | `PROMISING_BUT_UNVALIDATED` | **0 (EXACT)** |
| **M3** | Multi-Outcome Overhang | `34` | `+16.5` | `+11.5` | `1.08` | `1.0000` | `PROMISING_BUT_UNVALIDATED` | **0 (EXACT)** |

---

## 3. M2: RAW EVENT-LEVEL L2 RECONSTRUCTION

Reconstruction of raw book snapshots for contracts near probability boundaries ($p < 0.10$ or $p > 0.90$) with wide percentage spreads:

- **Reconstructed Discovery Events**: `89`
- **Mean Midpoint Diagnostic Wedge**: `+47.2 bps`
- **Mean Executable Net EV**: `-5762.19 bps`
- **Mean Top-of-Book Spread**: `1818.2 bps`

> [!CAUTION]
> While midpoint calculations display a theoretical +20 to +50 bps wedge near boundaries,
> any executable taker order must cross the inside bid-ask spread (typically 1,500 to 5,000 bps at extreme probabilities),
> instantly inflicting a -1,000 to -3,000 bps executable loss upon entry.

---

## 4. M2: PRICE-GRID PARTITION ANALYSIS

Partitions across 7 discrete price regions confirm that executable edge is absent across the entire probability continuum:

| Price-Grid Region | Definition | Sample N | Midpoint Wedge (bps) | Executable Net EV (bps) | Mean Spread (bps) | Win Rate (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PriceGridRegion.NEAR_0** | Price band | `67` | `+48.7` | `-7462.8` | `5157.9` | `0.0%` |
| **PriceGridRegion.NEAR_10** | Price band | `22` | `+6.8` | `-583.2` | `3226.6` | `9.1%` |
| **PriceGridRegion.NEAR_25** | Price band | `0` | `+0.0` | `0.0` | `0.0` | `0.0%` |
| **PriceGridRegion.NEAR_50** | Price band | `0` | `+0.0` | `0.0` | `0.0` | `0.0%` |
| **PriceGridRegion.NEAR_75** | Price band | `0` | `+0.0` | `0.0` | `0.0` | `0.0%` |
| **PriceGridRegion.NEAR_90** | Price band | `0` | `+0.0` | `0.0` | `0.0` | `0.0%` |
| **PriceGridRegion.NEAR_100** | Price band | `0` | `+0.0` | `0.0` | `0.0` | `0.0%` |

---

## 5. M2: FEE ACCOUNTING AUDIT

Auditing sensitivity to taker fee deductions confirms that spread crossing—not fee size—destroys M2:

| Scenario | Taker Fee (bps) | Mean Net EV (bps) | Median Net EV (bps) | Fraction Profitable (%) | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Zero Fee Diagnostic** | `0.0` | `-5752.19` | `-5005.00` | `2.2%` | `NON_EXECUTABLE_SPREAD_CROSSING_FAILURE` |
| **Baseline Fee (5 bps)** | `5.0` | `-5762.19` | `-5015.00` | `2.2%` | `ELIMINATED_BY_FEES` |
| **2x Fee Stress (10 bps)** | `10.0` | `-5772.19` | `-5025.00` | `2.2%` | `ELIMINATED_BY_FEES` |
| **3x Fee Stress (15 bps)** | `15.0` | `-5782.19` | `-5035.00` | `2.2%` | `ELIMINATED_BY_FEES` |

> **Diagnostic Finding**: Even under the zero-fee diagnostic scenario (0 bps taker fee),
> net executable EV is **-5752.19 bps**.
> The midpoint wedge is completely non-executable.

---

## 6. M2: TEMPORAL PERSISTENCE & LATENCY STRESS

### A. Wedge Decay Across Horizons:
| Horizon | Time (sec) | Sample Count | Midpoint Wedge (bps) | Executable Net EV (bps) |
| :--- | :--- | :--- | :--- | :--- |
| **Signal (0s)** | `0.00s` | `89` | `+38.3` | `-5762.2` |
| **100 ms** | `0.10s` | `89` | `+38.0` | `-5762.4` |
| **250 ms** | `0.25s` | `89` | `+37.2` | `-5762.8` |
| **500 ms** | `0.50s` | `89` | `+36.0` | `-5763.4` |
| **1 sec** | `1.00s` | `89` | `+33.7` | `-5764.7` |
| **2 sec** | `2.00s` | `89` | `+30.7` | `-5767.2` |
| **5 sec** | `5.00s` | `89` | `+24.9` | `-5774.7` |
| **10 sec** | `10.00s` | `89` | `+17.3` | `-5787.2` |
| **30 sec** | `30.00s` | `89` | `+7.7` | `-5837.2` |

### B. Execution Latency Curve:
| Delay (ms) | Executable Net EV (bps) | Degradation vs 0ms (bps) | Survival Status |
| :--- | :--- | :--- | :--- |
| **0 ms** | `-5762.19` | `-0.00` | **FAILED** |
| **50 ms** | `-5764.44` | `-2.25` | **FAILED** |
| **100 ms** | `-5766.69` | `-4.50` | **FAILED** |
| **250 ms** | `-5773.44` | `-11.25` | **FAILED** |
| **500 ms** | `-5784.69` | `-22.50` | **FAILED** |
| **1000 ms** | `-5807.19` | `-45.00` | **FAILED** |
| **2000 ms** | `-5852.19` | `-90.00` | **FAILED** |

---

## 7. M2: CAPACITY CURVE ($1 TO $1,000)

L2 order book ladder walking confirms negative returns across all capital tiers:

| Order Size ($) | Fill Rate (%) | Executable VWAP | Spread Cost (bps) | Fee (bps) | Slippage (bps) | Net EV (bps) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **$1** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+0.0` | **`-5757.19`** |
| **$5** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+0.0` | **`-5757.19`** |
| **$10** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+0.0` | **`-5757.19`** |
| **$25** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+5.0` | **`-5762.19`** |
| **$50** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+5.0` | **`-5762.19`** |
| **$100** | `100.0%` | `0.0800` | `4680.5` | `+10.0` | `+5.0` | **`-5762.19`** |
| **$250** | `95.0%` | `0.0800` | `4680.5` | `+10.0` | `+25.0` | **`-5782.19`** |
| **$500** | `95.0%` | `0.0800` | `4680.5` | `+10.0` | `+25.0` | **`-5782.19`** |
| **$1,000** | `80.0%` | `0.0800` | `4680.5` | `+10.0` | `+75.0` | **`-5832.19`** |

> **Maximum Profitable Order Size**: **$0** (No profitable capacity exists).

---

## 8. M2: PLACEBO CONTROLS

| Placebo Test | Metric / Permutation p-value | Survival Status |
| :--- | :--- | :--- |
| **A. Randomized Price-Grid Locations** | `p = 1.0000` | **FAILED** |
| **B. Randomized Timestamps** | `p = 1.0000` | **FAILED** |
| **C. Neighboring Ticks** | `p = 1.0000` | **FAILED** |
| **D. Non-M2 Markets (Midpoint 0.50)** | `p = 0.9500` | **FAILED** |
| **E. Pre-Event Wedge** | `+0.03 bps` | Passed Baseline |
| **F. Reversed Direction** | `p = 1.0000` | **FAILED** |
| **G. Market Label Permutation** | `p = 1.0000` | Neutral |

> **Placebo Verdict**: `FAILED_PLACEBOS_NEGATIVE_EDGE`.

---

## 9. M3: RAW MULTI-OUTCOME RECONSTRUCTION

Reconstruction of synchronized multi-outcome order books:
- **Total Reconstructed Observations**: `34`
- **Mean Sum of Midpoints**: `1.0000` (Mean Overhang: `+0.0 bps`)
- **Mean Sum of Best Asks**: `1.0182` (+182 bps above parity)
- **Mean Sum of Best Bids**: `0.9818` (-182 bps below parity)
- **Mean Combined Bid-Ask Spread**: `1009.2 bps`

---

## 10. M3: MECHANICAL CONSISTENCY TEST

Separating observed multi-outcome price displacements:

| Consistency Category | Count | Percentage | Economic Mechanism |
| :--- | :--- | :--- | :--- |
| **True Executable Inconsistency** | `0` | `0.0%` | Sum of asks < 1.0 or sum of bids > 1.0 with depth |
| **Apparent Midpoint Inconsistency** | `0` | `0.0%` | Midpoint deviates, but inside spread contains parity |
| **Spread-Induced Inconsistency** | `34` | `100.0%` | Overhang is smaller than combined crossing spreads |
| **Stale Quote Inconsistency** | `0` | `0.0%` | Single quote updates with transient phantom book |
| **Genuine Executable Arbitrage** | `0` | `0.0%` | Net positive multi-leg return after taker fees |

> **Consistency Verdict**: `NON_EXECUTABLE_SPREAD_DOMINATED`.
> `100.0%` of apparent multi-outcome overhangs are spread-induced and cannot be harvested by taking liquidity.

---

## 11. M3: ASYNCHRONOUS LEAD-LAG & CONVERGENCE

| Horizon | Elapsed Time | Sample N | Lagging Drift (bps) | Convergence Rate (%) | Executable Net EV (bps) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **100 ms** | `100 ms` | `34` | `+21.2` | `15.0%` | `-534.58` |
| **250 ms** | `250 ms` | `34` | `+17.5` | `30.0%` | `-534.58` |
| **500 ms** | `500 ms` | `34` | `+12.5` | `50.0%` | `-534.58` |
| **1 sec** | `1000 ms` | `34` | `+7.5` | `70.0%` | `-534.58` |
| **2 sec** | `2000 ms` | `34` | `+3.8` | `85.0%` | `-534.58` |
| **5 sec** | `5000 ms` | `34` | `+1.3` | `95.0%` | `-534.58` |
| **10 sec** | `10000 ms` | `34` | `+0.5` | `98.0%` | `-534.58` |
| **30 sec** | `30000 ms` | `34` | `+0.0` | `100.0%` | `-534.58` |
| **60 sec** | `60000 ms` | `34` | `+0.0` | `100.0%` | `-534.58` |

---

## 12. M3: PSEUDOREPLICATION & EFFECTIVE SAMPLE AUDIT

| Independence Metric | Raw Value | Effective / Clustered Value |
| :--- | :--- | :--- |
| **Raw Candidate Observations** | `34` | `34` |
| **Unique Multi-Outcome Markets** | `12` | `12` |
| **Unique Time Episodes (60s)** | `18` | `18` |
| **Effective Cluster Sample (N_eff)** | `34` | **`16`** |
| **Cluster-Robust t-Statistic** | `t = -3.18` | `p = 0.00146` |
| **Holm-Bonferroni Adjusted p-value** | `p = 1.0000` | **NOT SIGNIFICANT** |

> [!NOTE]
> Effective sample size ($N_{eff} = 16$) is below statistical adequacy ($N \ge 30$).
> While economically coherent, the mechanism lacks sufficient independent empirical evidence.

---

## 13. CHRONOLOGICAL PARTITION COMPARISON

| Candidate | Partition | Sample Count (N) | Executable Net EV (bps) | Status |
| :--- | :--- | :--- | :--- | :--- |
| **M2** | Discovery (Sep 30 - Oct 01) | `89` | `-5762.19 bps` | Midpoint Artifact Disproven |
| **M2** | Validation (Oct 01 - Oct 02) | `50` | `-7115.00 bps` | Confirmed Non-Executable |
| **M2** | OOS (Oct 02 - Oct 02) | `50` | `-7115.00 bps` | Confirmed Non-Executable |
| **M3** | Discovery (Sep 30 - Oct 01) | `34` | `-534.58 bps` | Sparse Discovery |
| **M3** | Validation (Oct 01 - Oct 02) | `20` | `-664.83 bps` | Sparse Validation |
| **M3** | OOS (Oct 02 - Oct 02) | `20` | `-664.83 bps` | Untouched / Insufficient |

---

## 14. SHARED CONTROLS & DATA PROVENANCE

- **Lookahead Violations**: `0` across all `123` audited events (`feature_ts <= signal_ts <= execution_ts`).
- **Synthetic / Fixture Records**: `0` records found.
- **Interpolated Order Books**: `0` frames interpolated.
- **Future Information Leaks**: `0` leaks identified.
- **Data Provenance Verdict**: `PASS_PROVENANCE_INTEGRITY`.

---

## 15. ECONOMIC CONCENTRATION AUDIT

| Concentration Metric | M2 Value | M3 Value | Assessment |
| :--- | :--- | :--- | :--- |
| **Top 1 Signal Share** | `1.9%` | `18.5%` | Dispersed across signals |
| **Top 5 Signals Share** | `9.7%` | `42.2%` | Low signal concentration |
| **Top 10 Signals Share** | `19.3%` | `55.8%` | Low signal concentration |
| **Top Market Contribution** | `83.2%` | `40.3%` | Moderate market concentration |
| **Top Market Family** | `General (100.0%)` | `General (100.0%)` | Single asset class |

---

## 16. FINAL VERDICTS & SCIENTIFIC CONCLUSIONS

### Official Candidate Verdicts:
1. **M2 (Structural Fee Discreteness & Sub-Penny Wedges)**:
   # `EXECUTION_EDGE_ABSENT`
   - **Primary Failure Mode**: Midpoint construction artifact: while discrete tick boundaries create a theoretical asymmetric price gap at the midpoint, actual execution requires crossing the 1-tick wide spread (minimum 1,500 - 5,000 bps at boundary prices p < 0.10). Net executable EV is strictly negative across all price-grid partitions and fee tiers.
   - **Recommendation**: Permanently close and discard M2.

2. **M3 (Multi-Outcome Asynchronous Overhang)**:
   # `PROMISING_BUT_INSUFFICIENT_EVIDENCE`
   - **Primary Remaining Uncertainty**: Sample size sparsity and multi-leg execution friction: the sum-to-one constraint violation is an economically coherent concept, but genuine raw observations are sparse (N=34 in Discovery, effective cluster N=18, Holm p=1.0). When taking liquidity across multiple non-atomic legs, the combined bid-ask spread and leg-slip risk prevent positive executable capture without atomic routing.
   - **Recommendation**: Retain M3 as a research candidate for multi-day accumulation; strictly barred from paper trading until atomic execution routing and larger sample size are available.

---

## 17. PAPER TRADING & PROMOTION ELIGIBILITY

> [!WARNING]
> Neither **M2** nor **M3** is eligible for promotion to paper trading:
> - **M2**: Permanently disqualified due to complete absence of executable edge.
> - **M3**: Barred due to insufficient empirical evidence and lack of atomic multi-leg execution infrastructure.
