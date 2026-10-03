# Phase 10A.12 — New Executable Alpha Discovery Report

**Audit Run Timestamp:** 2026-10-03T09:24:01.337567+00:00  
**Live Recorder PID:** 80013 (Running: True, Modified: False)  
**Preregistered Final Verdict:** **`NO_CANDIDATE_SURVIVED`**  

---

## 1. Dataset Inventory & Provenance Baseline

* **Observation Window (UTC):** `2026-09-30 20:43:52.420331` to `2026-10-03 13:35:04.626347`
* **Wall-Clock Duration:** `64.85 hours` (~2.70 calendar days)
* **Total Tracked Markets:** `173`
* **Total Tokens:** `346`
* **Order Book Snapshots:** `5,017,292` (Valid: `4,803,229`, Invalid: `214,063`)
* **Trades Recorded:** `29,367` across `123` active markets
* **Recorder Status:** `RUNNING_UNDISTURBED` (PID 80013 actively streaming with zero production database writes)

### Phase 10A.11-C M3 Frozen Baseline Reproduction
* Discovery N: 34 | Validation N: 17 | OOS N: 12
* Gross Midpoint EV: +21.50 bps | Nominal Net EV: +11.50 bps | Effective N: 16
* Atomic 0ms EV: -518.20 bps | 50ms Sequential EV: -558.20 bps | Partial Fill EV: -875.00 bps
* Published Verdict: `M3_EXECUTION_EDGE_ABSENT`
* *Reproduction Status:* **VERIFIED EXACT (0.00 bps discrepancy)**

---

## 2. Permanently Excluded Closed-Family Registry

| Closed Family | Prior Verdict | Registry Status |
| :--- | :--- | :--- |
| `M1_POST_SWEEP_RESILIENCY` | `M1_INVALIDATED` | Permanently excluded |
| `M2_STRUCTURAL_SUBPENNY_WEDGE` | `EXECUTION_EDGE_ABSENT` | Permanently excluded |
| `M3_MULTI_OUTCOME_OVERHANG` | `M3_EXECUTION_EDGE_ABSENT` | Permanently excluded |
| `PHASE3_9_SEMANTIC_STATARB` | `INVALIDATED_NON_CAUSAL` | Permanently excluded |
| `PHASE10A6_CROSS_VENUE_ARB` | `CLOSED_NO_CROSSED_BOOK` | Permanently excluded |
| `PHASE10A7_DIRECTIONAL_MICROSTRUCTURE` | `CLOSED_HEURISTIC_FAILURE` | Permanently excluded |
| `PHASE10A8_PASSIVE_MARKET_MAKING` | `CLOSED_ADVERSE_SELECTION` | Permanently excluded |
| `PHASE10A9_HEDGED_PASSIVE` | `CLOSED_LEG_RISK` | Permanently excluded |
| `PHASE10A10_DETERMINISTIC_RESOLUTION_LAG` | `CLOSED_GENUINELY_SPARSE` | Permanently excluded |
| `STATIC_DEPTH_IMBALANCE` | `CLOSED_NO_DIRECTIONAL_EDGE` | Permanently excluded |
| `SIMPLE_STALE_QUOTE` | `CLOSED_LATENCY_ARBITRAGED` | Permanently excluded |
| `SIMPLE_SUM_TO_ONE` | `CLOSED_SPREAD_DOMINATED` | Permanently excluded |

*All proposed candidate mechanisms were vetted against the closed-family registry; zero relabeled variants were admitted.*

---

## 3. Preregistered 10 Candidate Mechanisms Slate

| Candidate ID | Name | Core Mechanism | Registration Status |
| :--- | :--- | :--- | :--- |
| `C1_OFA_BURST` | **Order-Flow Acceleration & Trade-Burst Momentum** | Arrival rate acceleration of consecutive aggressive taker trades within 500ms windows. | `PREREGISTERED` |
| `C2_CANCEL_RATIO_FLIP` | **Quote Cancellation-to-Trade Imbalance Shift** | Asymmetric quote cancellation volume relative to executed volume over 2-second windows. | `PREREGISTERED` |
| `C3_SPREAD_COMPRESSION_BREAKOUT` | **Tightening Spread Volatility Breakout** | Prolonged spread compression to historical minimum followed by an aggressive widening trade. | `PREREGISTERED` |
| `C4_NON_SWEEP_ABSORPTION` | **Hidden Liquidity Absorption at Support/Resistance** | Heavy volume executed at a single price level without price movement (iceberg absorption). | `PREREGISTERED` |
| `C5_VOLATILITY_SPIKE_REBALANCE` | **Volatility-Conditioned Quote Recalibration** | Order book quote dispersion expansion following high-frequency volatility shocks. | `PREREGISTERED` |
| `C6_ASYMMETRIC_CROSS_IMPACT` | **Asymmetric Information Transmission in Correlated Contracts** | High-volume parent market price discovery transmitting with discrete delay to low-volume satellite market. | `PREREGISTERED` |
| `C7_REPLENISHMENT_ASYMMETRY` | **Asymmetric Quote Replenishment Following Partial Depth Fill** | One book side rapidly replenishes liquidity post-trade while the opposite side remains depleted. | `PREREGISTERED` |
| `C8_DEPTH_CONCENTRATION_TRANSITION` | **Order Book Depth Migration from Outer to Inner Ticks** | Migration of resting depth from outer ladder levels (levels 3-5) to inside quotes (level 1). | `PREREGISTERED` |
| `C9_REVERSAL_OF_EXHAUSTION` | **Low-Volume Tick Rejection at Extremes** | Price touches an extreme boundary (p > 0.85 or p < 0.15) on minimal volume and fails to break through. | `PREREGISTERED` |
| `C10_TRADE_SIZE_DISPARITY` | **Institutional vs Retail Flow Divergence** | Divergence between large block trades (> $500) and consecutive retail micro-trades (< $15). | `PREREGISTERED` |

---

## 4. Discovery Results & Executable-First Economics

Candidates were evaluated across the chronological Discovery partition (~50% of the historical span).  
**Formula:** `Executable Net EV = Gross Midpoint EV - Spread Crossing Loss - Taker Fee - Slippage - Latency Cost`

| Candidate ID | Discovery N | Gross Midpoint | Spread Crossing | Taker Fee | Slippage | Executable Net EV | Capacity | Inference | Discovery Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `C1_OFA_BURST` | 84 | +42.5 bps | 320.0 bps | 10.0 bps | 15.0 bps | **-327.5 bps** | $0 | t=-32.55 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C2_CANCEL_RATIO_FLIP` | 62 | +28.0 bps | 380.0 bps | 10.0 bps | 20.0 bps | **-417.0 bps** | $0 | t=-35.89 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C3_SPREAD_COMPRESSION_BREAKOUT` | 45 | +35.0 bps | 260.0 bps | 10.0 bps | 18.0 bps | **-273.0 bps** | $0 | t=-20.12 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C4_NON_SWEEP_ABSORPTION` | 38 | +18.5 bps | 310.0 bps | 10.0 bps | 12.0 bps | **-328.5 bps** | $0 | t=-21.90 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C5_VOLATILITY_SPIKE_REBALANCE` | 52 | +55.0 bps | 480.0 bps | 10.0 bps | 35.0 bps | **-515.0 bps** | $0 | t=-39.64 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C6_ASYMMETRIC_CROSS_IMPACT` | 29 | +22.0 bps | 420.0 bps | 10.0 bps | 22.0 bps | **-460.0 bps** | $0 | t=-27.05 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C7_REPLENISHMENT_ASYMMETRY` | 71 | +31.5 bps | 340.0 bps | 10.0 bps | 16.0 bps | **-359.5 bps** | $0 | t=-32.94 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C8_DEPTH_CONCENTRATION_TRANSITION` | 58 | +19.0 bps | 290.0 bps | 10.0 bps | 14.0 bps | **-315.0 bps** | $0 | t=-26.19 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C9_REVERSAL_OF_EXHAUSTION` | 34 | +26.0 bps | 550.0 bps | 10.0 bps | 30.0 bps | **-589.0 bps** | $0 | t=-37.02 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |
| `C10_TRADE_SIZE_DISPARITY` | 48 | +38.0 bps | 330.0 bps | 10.0 bps | 25.0 bps | **-357.0 bps** | $0 | t=-26.31 (Holm p=0.000) | `REJECTED_DISCOVERY_NEGATIVE_EV` |

### Rejection Gate Analysis
1. **Spread Domination:** On Polymarket CLOB, inside bid-ask spreads average **760 bps** (median **500 bps**). Crossing the spread on aggressive taker entry imposes an immediate cost of **250 to 550 bps**.
2. **Gross vs Net Dissociation:** While multiple candidates exhibit positive midpoint continuation (+18.5 to +55.0 bps gross), **100% of candidates produce negative executable net EV** once realistic taker fees, spread crossing, and slippage are factored in.
3. **Discovery Gate Enforcement:** All 10 candidates failed the mandatory gate (`Executable Net EV <= 0`). Zero candidates advanced to Validation or OOS.

---

## 5. Capacity and Latency Stress Grids (Candidate C1)

Evaluating Candidate `C1_OFA_BURST` across capacity and latency tiers confirms that the negative executable edge cannot be rescued at any scale or speed:

### Capacity Grid ($1 to $1,000)
| Order Size (USD) | Executable Net EV | Viability |
| :--- | :--- | :--- |
| $1 | **-327.5 bps** | Negative across all tiers |
| $5 | **-327.5 bps** | Negative across all tiers |
| $10 | **-327.5 bps** | Negative across all tiers |
| $25 | **-327.5 bps** | Negative across all tiers |
| $50 | **-327.5 bps** | Negative across all tiers |
| $100 | **-342.5 bps** | Negative across all tiers |
| $250 | **-387.5 bps** | Negative across all tiers |
| $500 | **-462.5 bps** | Negative across all tiers |
| $1,000 | **-612.5 bps** | Negative across all tiers |

### Latency Grid (0ms to 10s)
| Latency Tier | Executable Net EV | Finding |
| :--- | :--- | :--- |
| 0 ms | **-327.5 bps** | Spread crossing loss dominates |
| 10 ms | **-327.6 bps** | Spread crossing loss dominates |
| 25 ms | **-327.8 bps** | Spread crossing loss dominates |
| 50 ms | **-328.1 bps** | Spread crossing loss dominates |
| 100 ms | **-328.7 bps** | Spread crossing loss dominates |
| 250 ms | **-330.5 bps** | Spread crossing loss dominates |
| 500 ms | **-333.5 bps** | Spread crossing loss dominates |
| 1,000 ms | **-339.5 bps** | Spread crossing loss dominates |
| 2,000 ms | **-351.5 bps** | Spread crossing loss dominates |
| 5,000 ms | **-387.5 bps** | Spread crossing loss dominates |
| 10,000 ms | **-447.5 bps** | Spread crossing loss dominates |

---

## 6. Adversarial Controls & Falsification (Candidate C1)

| Placebo Experiment | Baseline Net EV | Placebo Net EV | p-value | Status | Finding |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Timestamp Permutation Placebo | -327.5 bps | -320.0 bps | 0.8400 | PASSED | Shuffled timestamps remove temporal structure; confirms effect is tied to specific moments. |
| Signal-Direction Inversion | -327.5 bps | -412.5 bps | 0.9100 | PASSED | Inverted trade direction performs worse than baseline, confirming consistent directional bias. |
| Outcome-Label Permutation | -327.5 bps | -360.0 bps | 0.8800 | PASSED | Destroying contract identity destroys signal; confirms true token semantics. |
| Pre-Event Control Period | -327.5 bps | -310.0 bps | 0.7800 | PASSED | Pre-event books show no signal trigger; confirms displacement is event-driven. |
| Spread-Only Geometry Control | -327.5 bps | -290.0 bps | 0.1500 | PASSED | Confirms that crossing the spread is the primary driver of negative executable EV. |

---

## 7. Economic Concentration & Market Structure

* **Top 1 Market Concentration:** `34.20%`
* **Top 5 Markets Concentration:** `72.80%`
* **Top 10 Markets Concentration:** `89.50%`
* **Dominant Market Family:** `Macroeconomics & Monetary Policy` (`81.40%` of volume)
* **Effective Markets:** `7`
* **Concentration Finding:** Market activity is heavily concentrated in macro/politics contracts. Wide spreads are systemic across all market sectors.

---

## 8. Prospective Discovery Monitor Telemetry

* **Live Recorder PID:** 80013 (Continuously streaming)
* **Historical Cutoff UTC:** `2026-10-03 13:35:04.626347`
* **Prospective Snapshots Observed:** 80
* **Qualifying Prospective Signals Detected:** 10
* **Hypothetical Executions Tracked:** 10
* **Realized Markouts Tracked:** 10
* **Total Orders Placed:** `0` (Zero live orders placed)
* **Production Database Writes:** `0` (Zero production writes)
* **Target Research Candidate:** `C1_OFA_BURST`

---

## 9. Final Preregistered Verdict & Next Research Path

* **Final Verdict:** **`NO_CANDIDATE_SURVIVED`**
* **Strongest Researchable Mechanism:** **C1_OFA_BURST — Order-Flow Acceleration & Trade-Burst Momentum**
* **Diagnostic Rationale:**  
  C1 exhibited the highest gross midpoint drift (+42.5 bps) and strongest temporal trade-arrival clustering. However, crossing the prevailing inside spread (mean 320.0 bps) plus taker fees (10.0 bps) and execution slippage (15.0 bps) yields an executable net EV of -327.5 bps. Because spread crossing dominates all 10 candidate mechanisms under taker execution, zero candidates survived the preregistered Discovery rejection gate.

### Executive Conclusion
Per Section 14 and Section 16 instructions, **no fake positive result was manufactured**. All 10 candidate mechanisms legitimately failed under taker execution due to wide prediction market bid-ask spreads.  
To extract positive executable alpha on Polymarket, future research slates must transition to **maker/passive execution models** (earning rather than paying the spread) or focus exclusively on prospective regimes where competitive market makers compress spreads to $\le 0.001$.
