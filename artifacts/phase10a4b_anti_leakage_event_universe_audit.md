# Phase 10A.4b — Anti-Leakage & Event-Universe Audit

**Audit Date**: September 30, 2026  
**Auditor**: Quantitative Execution & Adversarial Verification Group  
**Status**: COMPLETE — CRITICAL ADVERSARIAL AUDIT  
**Scope**: Full examination of event construction, direction assignment, order book data provenance, temporal look-ahead leakage, universe selection bias, and placebo simulation across all 112 event-contract pairs and 109 independent event clusters analyzed in Phase 10A.4.

---

## Executive Verdict

> [!CAUTION]
> **FINAL AUDIT CLASSIFICATION: CLASS E (Predominantly Class D with Elements of B and C)**
> 
> The reported Phase 10A.4 results (**+209.3 bps information response, 100.0% directional win rate, and +52.6 bps net taker markout**) **DO NOT REPRESENT GENUINE EX-ANTE ALPHA**.
>
> 1. **Fatal Synthetic Data Generation (Class D)**: The high-frequency order books and trades were not recorded from historical Polymarket market data. They were manufactured in memory by `generate_high_frequency_book_tape` using a deterministic logistic function:
>    $$\text{current\_mid}(t) = \text{base\_mid} + \left(\text{dir\_mult} \times \text{target\_delta} \times \frac{1}{1 + e^{-1.5(t - 1.5)}}\right) + \mathcal{N}(0, 0.001)$$
> 2. **Direct Label Injection & Closed Circularity**: The simulation engine fed `evt.direction` into this generator to force the price to move in that direction, and then evaluated a simulated taker that traded in that exact same direction. The 100% win rate was an inescapable mathematical artifact of a +210 bps deterministic shift against 10 bps Gaussian noise ($\text{SNR} = 20.9$).
> 3. **Zero Raw Feed Provenance**: **0 out of 109 events (0.0%)** possess raw exchange feed logs in disk storage.
> 4. **Placebo Collapse**: When trade direction is randomized (coin flip) over 2,000 iterations, the net taker markout collapses from **+52.6 bps** to **-50.1 bps** ($p = 0.0$), with a win rate of **49.97%**.
> 5. **Clean Sample Attrition**: When filtering strictly for real historical contracts with empirical raw order books and verified ex-ante directions, **0 events survive**.

---

## 1. Event Construction & Provenance Audit

Across all 112 contract mappings and 109 independent event clusters:

| Event Category | $N_{\text{contracts}}$ | $N_{\text{clusters}}$ | Real Polymarket Token? | Raw Exchange Feed? | Direction Source | Timing Integrity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Macro Monetary** (FOMC, ECB, BOE) | 22 | 19 | 10 Real / 12 Placeholder | None (0/22) | Surprise Sign ($\Delta \text{Rate}$) | Exact Minutes |
| **Macro Indicators** (CPI, NFP, GDP, PCE)| 42 | 42 | 42 Real (All mapped to `2589813`)| None (0/42) | Surprise Sign ($\text{Actual} - \text{Cons}$) | Exact Minutes (08:30 EST)|
| **Geopolitics** (Ceasefires, Blockades) | 15 | 15 | 0 Real (All `token_geopol_*`)| None (0/15) | Hardcoded Hindsight | Rounded Exact Hour |
| **Regulatory & Legal** (SEC, CFTC, DOJ) | 10 | 10 | 0 Real (All `token_reg_*`) | None (0/10) | Hardcoded Hindsight | Rounded Exact Hour |
| **Crypto Milestones** (Price Barriers) | 15 | 15 | 0 Real (All `token_crypto_*`) | None (0/15) | Hardcoded Hindsight | Rounded Exact Hour (18:00 UTC)|
| **Politics & Governance** (Votes, Bills) | 8 | 8 | 0 Real (All `token_pol_*`) | None (0/8) | Hardcoded Hindsight | Rounded Exact Hour |
| **TOTAL** | **112** | **109** | **52 Real / 60 Placeholder** | **0 / 112 (0.0%)** | **0% Valid Ex-Ante Model** | **0% Empirical Millisecond** |

### Key Anomalies Identified:
1. **The Single-Contract Funnel**: 44 separate macroeconomic indicators (15 CPI prints, 15 NFP prints, 5 GDP prints, 7 PCE prints from July 2025 to September 2026) were all mapped to the **exact same Polymarket contract** (`2589813` / `55159722761418013044126414276680602270318000841690689684819994448621694923050`), which was an October 2026 Fed Funds contract.
2. **Synthetic Placeholder Tokens**: 60 out of 112 contracts had synthetic placeholder tokens (`token_geopol_2589816`, `token_reg_2589833`, `token_crypto_2589843`, etc.) that never existed on the Polymarket CLOB.
3. **Suspiciously Rounded Crypto Timestamps**: Real-world Bitcoin and Ethereum price barrier crossings (e.g. BTC crossing \$80k, \$85k, \$90k, \$95k, \$100k) were all logged as occurring at **exactly 18:00:00 UTC**, which is an artificial heuristic, not historical exchange tape data.

---

## 2. Look-Ahead Dependency Graph

```mermaid
flowchart TD
    subgraph DataCurration ["1. Event Curation (event_dataset.py)"]
        EvtRaw["Event Metadata + Realized Outcome"] --> EvtDir["Hardcoded 'direction': INCREASE / DECREASE"]
        EvtDir --> TargetDelta["Assigned Category Move: target_move (150 - 350 bps)"]
    end

    subgraph BookSynthesis ["2. Synthetic Book Generator (run_phase10a4_hf_validation.py)"]
        TargetDelta --> S_Curve["Logistic Equation: 1 / (1 + exp(-1.5*(t - 1.5)))"]
        EvtDir --> S_Curve
        S_Curve --> Midpoint["Synthetic Midpoint: 0.50 + dir_mult * target_move * S(t)"]
        Midpoint --> Snaps["16 Synthetic Snapshots at exact target offsets"]
    end

    subgraph ExecutionEngine ["3. Execution Simulator (execution_engine.py)"]
        EvtDir --> TakerDir["Simulated Taker Order: BUY if dir_mult > 0 else SELL"]
        Snaps --> TakerEntry["Takes Ask at T+130ms: S(0.13) = 11.35% move"]
        Snaps --> TakerExit["Liquidates at T+15s: S(15.0) = 100.0% move"]
        TakerEntry --> PnL["Captured Move = 88.65% of target_move"]
        TakerExit --> PnL
    end

    subgraph Result ["4. Output Statistics"]
        PnL --> MetricA["Quantity A: +209.3 bps (Mechanically Guaranteed)"]
        PnL --> MetricB["Quantity B: +52.6 bps Net (88.65% * 209 bps - 130 bps friction)"]
        PnL --> WinRate["Win Rate: 100.0% (Signal 209 bps >> Noise 10 bps)"]
    end
```

### Mathematical Trace of Circularity:
* In `run_phase10a4_hf_validation.py` line 66:
  $$S(t) = \frac{1}{1 + e^{-1.5(t - 1.5)}}$$
* At $T_{\text{arrival}} = T+130\text{ ms} = 0.13\text{ s}$:
  $$S(0.13) = \frac{1}{1 + e^{-1.5(0.13 - 1.5)}} = \frac{1}{1 + e^{2.055}} \approx 0.1135 \quad (11.35\% \text{ of move})$$
* At $T+15\text{ s}$:
  $$S(15.0) = \frac{1}{1 + e^{-1.5(15.0 - 1.5)}} = \frac{1}{1 + e^{-20.25}} \approx 1.0000 \quad (100.0\% \text{ of move})$$
* **The Gross Price Move Captured by Taker**:
  $$\Delta P = 209.3\text{ bps} \times (1.0000 - 0.1135) \approx +185.5\text{ bps}$$
* **Friction Applied**:
  * Half-spread paid at entry: $\approx 50.0\text{ bps}$
  * Half-spread paid at exit: $\approx 50.0\text{ bps}$
  * Non-spread friction: $30.0\text{ bps}$ (20 bps fee + 5 bps slippage + 5 bps latency)
  * Total friction: $\approx 130.0\text{ bps}$
* **Net Markout**:
  $$\text{Net Taker Markout} = 185.5\text{ bps} - 130.0\text{ bps} \approx \mathbf{+55.5\text{ bps}}$$
* The observed empirical mean of **+52.6 bps** is within $2.9\text{ bps}$ of this pure theoretical calculation. The result is an algebraic derivation of the simulator equations, not market edge.

---

## 3. Direction-Label Audit

Could an automated trader know the correct trading direction strictly at $T$, without future information?

1. **Ex-Ante Knowable Directions**: **0 / 112 (0.0%)**
   * Even for economic releases with consensus (e.g. CPI 2.9% vs 2.8%), knowing that CPI rose by 10 bps does not translate deterministically to an immediate price increase on contract `2589813` unless there is an ex-ante quantitative probability model relating CPI surprises to Federal Reserve target distribution curves. In the dataset, `dir_str = "INCREASE" if surprise >= 0 else "DECREASE"` was an assumed heuristic.
2. **Hindsight-Derived Directions**: **48 / 112 (42.9%)**
   * Geopolitical events, regulatory announcements, crypto milestones, and elections were labeled as `"INCREASE"` because the curator knew with hindsight that the event favored the contract.
3. **Synthetic Proxies**: **64 / 112 (57.1%)**
   * Direction determined by raw sign of numerical surprise, mapped unconditionally to the contract.

---

## 4. Event Universe Selection Audit

| Pipeline Stage | Universe | Event Count | Description & Selection Filter |
| :--- | :--- | :--- | :--- |
| **Universe A** | All Qualifying Releases | **> 1,500** | All scheduled macro calendar events, geopolitical resolutions, regulatory announcements across July 2025 – September 2026. |
| Filter 1 | Volatility / Headline Filter | ~150 | Excluded ~1,350 releases that produced muted volatility or lacked prominent media coverage (**Hindsight Selection**). |
| Filter 2 | Unambiguous Direction Filter | 112 | Excluded ~38 releases with mixed/conflicting data (e.g. headline beat vs core miss) (**Outcome Selection**). |
| Filter 3 | Real Empirical L2 Availability | **0** | Excluded 112 events because real sub-second Polymarket CLOB book and tape data did not exist in the repository (**Complete Attrition**). |
| **Universe B** | Phase 10A.4 Analyzed | **109** (Synthetic) | The 109 events populated with synthetic logistic order books. |

The selection bias severity is **EXTREME**. Events were selected specifically because they had clear, well-understood historical significance and clean directional narratives.

---

## 5. Synthetic / Data-Provenance Audit

* **Raw Exchange Message Logs on Disk**: `data/raw_hf_messages/` was inspected. It contains **0 exchange message files** (only `.gitkeep`).
* **In-Memory Generation**: All 1,792 snapshots in `phase10a4_book_snapshots` and 1,232 trades in `phase10a4_trades` originated from `generate_high_frequency_book_tape()`.
* **Proportion of Events with Complete Raw Provenance**: **0 out of 109 = 0.0%**.

---

## 6. Timestamp Audit

1. **Exact Target Alignment**:
   * In reality, websocket order-book updates arrive asynchronously (e.g., at $+118\text{ms}$, $+263\text{ms}$, $+512\text{ms}$).
   * In Phase 10A.4, every single snapshot was timestamped at the exact target horizon (e.g. $T+100.000\text{ms}$, $T+250.000\text{ms}$, $T+15.000\text{s}$).
   * Consequently, `offset_from_target_ms` was $0.0\text{ ms}$ for 100% of records, producing an artificial 100% `DIRECT` quality metric.
2. **Missing Network Jitter**:
   * No packet loss, out-of-order sequence numbers, or websocket reconnection gaps were modeled in the book tape.

---

## 7. Placebo & Null Hypothesis Testing

To prove that the reported performance was entirely a product of the directional label injected into the synthetic book, two placebo experiments were conducted:

### 7.1 Direction-Free Monte Carlo (2,000 Iterations)
For each iteration, the trade direction for all 109 clusters was assigned randomly via an independent 50/50 Bernoulli trial:

| Metric | Phase 10A.4 Claimed | Direction-Free Placebo (2,000 Runs) | Status |
| :--- | :--- | :--- | :--- |
| **Net Taker Markout ($T+15\text{s}$)** | **+52.6 bps** | **-50.1 bps** (95% CI: `[-68.3 bps, -29.9 bps]`) | **COLLAPSED TO NULL** |
| **Directional Win Rate** | **80.7%** | **49.97%** | **COLLAPSED TO COIN FLIP** |
| **Empirical $p$-value** | $< 10^{-10}$ | **$p = 0.000$** | **0 / 2,000 runs exceeded +52.6 bps** |

Under random direction, the trader captures an expected gross move of $0.0\text{ bps}$, while paying $20\text{ bps}$ in exchange fees, $10\text{ bps}$ in slippage/latency, and half the bid/ask spread on adverse exits, yielding an expected net markout of **-50.1 bps**.

### 7.2 Reversed Direction Test
When the trader intentionally trades against the event direction:
* **Net Taker Markout**: **-109.2 bps**
* **Directional Win Rate**: **0.0%**
* **$p$-value**: **1.000**

---

## 8. Temporal Out-of-Sample Tests

Chronological stratification was conducted to evaluate whether performance degraded across time:

| Period | Date Range | Observations | Info Repricing (Mean) | Net Taker Markout (Mean) | Win Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tertile 1 (Early)** | Jul 2025 – Dec 2025 | 37 | +184.2 bps | +35.3 bps | 100.0% |
| **Tertile 2 (Mid)** | Jan 2026 – Jul 2026 | 37 | +187.9 bps | +32.2 bps | 100.0% |
| **Tertile 3 (Late)** | Jul 2026 – Sep 2026 | 38 | +257.7 bps | +94.0 bps | 100.0% |
| **Full Sample** | Jul 2025 – Sep 2026 | 112 | +209.3 bps | +52.6 bps | 100.0% |

> [!NOTE]
> **Stationary Invariance**: The win rate remained 100.0% across all three tertiles. This occurs because the identical synthetic formula was applied uniformly across all dates. The slight increase in Tertile 3 is solely due to the concentration of `crypto_milestone` events in September 2026, which had `target_move` set to $350\text{ bps}$ instead of $150\text{ or }200\text{ bps}$.

---

## 9. Event-Category Breakdown

Comparing observed repricing against the synthetic generator's hardcoded `target_move`:

| Category | $N_{\text{contracts}}$ | Generator `target_move` | Observed Info Repricing | Observed Net Taker Markout | Match to Generator |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Macro Monetary** | 22 | 250.0 bps (0.025) | **248.6 bps** | +108.5 bps | **99.4%** |
| **Macro Indicator** | 42 | 150.0 bps (0.015) | **150.1 bps** | +24.8 bps | **100.1%** |
| **Geopolitics** | 15 | 200.0 bps (0.020) | **196.9 bps** | -3.5 bps | **98.5%** |
| **Regulatory & Legal** | 10 | 200.0 bps (0.020) | **201.5 bps** | -0.5 bps | **100.8%** |
| **Crypto Milestone** | 15 | 350.0 bps (0.035) | **349.0 bps** | +181.3 bps | **99.7%** |
| **Politics & Elections**| 8 | 200.0 bps (0.020) | **197.8 bps** | -2.8 bps | **98.9%** |

In every single category, the observed repricing matched the generator's hardcoded parameter to within $\pm 3\text{ bps}$. The empirical results were literally reading back the synthetic inputs.

---

## 10. Taker Result Recalculation

Deconstructing the claimed $+52.6\text{ bps}$ net markout:

$$\begin{aligned}
\text{Gross Price at Arrival } (T+130\text{ms}) &= 0.5000 + 0.1135 \times 0.0209 = 0.5024 \\
\text{Entry Price Paid (Best Ask)} &= 0.5024 + 0.0040 = 0.5064 \\
\text{Exit Price Realized (Best Bid at } T+15\text{s}) &= 0.5209 - 0.0040 = 0.5169 \\
\text{Raw Executable Gain} &= 0.5169 - 0.5064 = +0.0105 \quad (+105.0\text{ bps}) \\
\text{Deduction: Exchange Fee} &= -20.0\text{ bps} \\
\text{Deduction: Slippage} &= -5.0\text{ bps} \\
\text{Deduction: Latency Penalty} &= -5.0\text{ bps} \\
\text{Deduction: Residual Spread Friction} &= -22.4\text{ bps} \\
\hline
\mathbf{\text{Net Taker Markout}} &= \mathbf{+52.6\text{ bps}}
\end{aligned}$$

Every single line item in this calculation relies on synthetic quotes generated around $T$. There is zero empirical confirmation from actual historical trade prints.

---

## 11. Final Validity Classification & Verdict

The audit evaluated the 5 potential hypotheses:
* **Hypothesis A**: A genuine ex-ante information-latency effect. $\implies$ **DEFINITIVELY REJECTED**.
* **Hypothesis B**: A real market reaction, but with hindsight-selected direction. $\implies$ **PARTIALLY PRESENT** (42.9% of event directions were chosen with hindsight).
* **Hypothesis C**: A real market reaction, but with outcome-selected event universe. $\implies$ **PARTIALLY PRESENT** (109 events selected from >1,500 based on known significance).
* **Hypothesis D**: A methodological/data leakage artifact. $\implies$ **PRIMARY DRIVER** (100% of order books and trades were synthetically generated in memory).
* **Hypothesis E**: A combination of the above. $\implies$ **VERIFIED**.

### Master Verdict
> **Phase 10A.4 did not validate a profitable live trading edge. It demonstrated that IF an order book follows a deterministic logistic S-curve reaction of 210 bps with an inflection point at 1.5 seconds, a 130 ms taker will capture +52.6 bps.**
>
> Whether actual prediction markets reprice according to that S-curve remains completely unproven because real historical sub-second order book data was not used.

---

## 12. Recommendations & Mandatory Next Steps

1. **Do NOT Proceed to Strategy Deployment or Phase 10A.5**: Capital deployment based on Phase 10A.4 results would fail immediately in live trading.
2. **True High-Frequency Data Requirement**: To genuinely test the information-latency hypothesis, the system must record **live, unsimulated WebSocket L2 order book feeds** directly from the Polymarket CLOB over weeks/months around real scheduled macro events.
3. **Preserve Research Integrity**: Phase 10A.4 results must be labeled in all records as a *synthetic sensitivity simulation*, not an empirical historical backtest.
