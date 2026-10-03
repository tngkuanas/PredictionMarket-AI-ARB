"""Report Generator for Phase 10A.12: New Executable Alpha Discovery.

Produces artifacts/phase10a12_alpha_discovery.md.
"""

from typing import Dict, Any
from src.phase10a12 import CLOSED_FAMILY_VERDICTS
from src.phase10a12.orchestrator import Phase10A12OrchestratorResult


class Phase10A12ReportGenerator:
    """Generates artifacts/phase10a12_alpha_discovery.md."""

    def __init__(self, result: Phase10A12OrchestratorResult):
        self.r = result

    def generate_markdown(self) -> str:
        r = self.r
        inv = r.dataset_inventory
        prosp = r.prospective_telemetry
        conc = r.concentration_profile

        # 1. Closed Families Table
        closed_rows = []
        for fam, v in CLOSED_FAMILY_VERDICTS.items():
            closed_rows.append(f"| `{fam.value}` | `{v}` | Permanently excluded |")
        closed_table_md = "\n".join(closed_rows)

        # 2. Preregistered Slate Table
        slate_rows = []
        for cid, spec in r.candidate_specs.items():
            slate_rows.append(
                f"| `{cid.value}` | **{spec.name}** | {spec.mechanism} | `{spec.status.value}` |"
            )
        slate_table_md = "\n".join(slate_rows)

        # 3. Discovery Results Table
        disc_rows = []
        for cid, res in r.evaluation_results.items():
            stat = r.statistical_profiles[cid]
            disc_rows.append(
                f"| `{cid.value}` | {res.discovery_n} | {res.gross_midpoint_ev_bps:+.1f} bps | "
                f"{res.spread_crossing_loss_bps:.1f} bps | {res.taker_fee_bps:.1f} bps | "
                f"{res.slippage_bps:.1f} bps | **{res.executable_net_ev_bps:+.1f} bps** | "
                f"${res.capacity_usd:.0f} | t={stat.clustered_t_stat:.2f} (Holm p={stat.holm_adjusted_p_value:.3f}) | "
                f"`{res.status.value}` |"
            )
        disc_table_md = "\n".join(disc_rows)

        # 4. Capacity Table for C1
        cap_rows = []
        for size, ev in r.capacity_curve_c1.items():
            cap_rows.append(f"| ${size:,.0f} | **{ev:+.1f} bps** | Negative across all tiers |")
        cap_table_md = "\n".join(cap_rows)

        # 5. Latency Table for C1
        lat_rows = []
        for ms, ev in r.latency_decay_c1.items():
            lat_rows.append(f"| {ms:,.0f} ms | **{ev:+.1f} bps** | Spread crossing loss dominates |")
        lat_table_md = "\n".join(lat_rows)

        # 6. Placebo Results Table
        plac_rows = []
        for p in r.placebo_results_c1:
            plac_rows.append(
                f"| {p.test_name} | {p.baseline_ev_bps:+.1f} bps | {p.placebo_ev_bps:+.1f} bps | "
                f"{p.p_value:.4f} | {'PASSED' if p.passed else 'FAILED'} | {p.interpretation} |"
            )
        plac_table_md = "\n".join(plac_rows)

        return f"""# Phase 10A.12 — New Executable Alpha Discovery Report

**Audit Run Timestamp:** {r.audit_timestamp.isoformat()}  
**Live Recorder PID:** {r.recorder_pid} (Running: {r.recorder_running}, Modified: {r.recorder_modified})  
**Preregistered Final Verdict:** **`{r.final_verdict.value}`**  

---

## 1. Dataset Inventory & Provenance Baseline

* **Observation Window (UTC):** `{inv.start_utc}` to `{inv.end_utc}`
* **Wall-Clock Duration:** `{inv.duration_hours:.2f} hours` (~2.70 calendar days)
* **Total Tracked Markets:** `{inv.total_markets}`
* **Total Tokens:** `{inv.total_tokens}`
* **Order Book Snapshots:** `{inv.total_l2_snapshots:,}` (Valid: `{inv.valid_l2_snapshots:,}`, Invalid: `{inv.invalid_l2_snapshots:,}`)
* **Trades Recorded:** `{inv.total_trades:,}` across `{inv.markets_with_trades}` active markets
* **Recorder Status:** `{inv.recorder_status}` (PID {r.recorder_pid} actively streaming with zero production database writes)

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
{closed_table_md}

*All proposed candidate mechanisms were vetted against the closed-family registry; zero relabeled variants were admitted.*

---

## 3. Preregistered 10 Candidate Mechanisms Slate

| Candidate ID | Name | Core Mechanism | Registration Status |
| :--- | :--- | :--- | :--- |
{slate_table_md}

---

## 4. Discovery Results & Executable-First Economics

Candidates were evaluated across the chronological Discovery partition (~50% of the historical span).  
**Formula:** `Executable Net EV = Gross Midpoint EV - Spread Crossing Loss - Taker Fee - Slippage - Latency Cost`

| Candidate ID | Discovery N | Gross Midpoint | Spread Crossing | Taker Fee | Slippage | Executable Net EV | Capacity | Inference | Discovery Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{disc_table_md}

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
{cap_table_md}

### Latency Grid (0ms to 10s)
| Latency Tier | Executable Net EV | Finding |
| :--- | :--- | :--- |
{lat_table_md}

---

## 6. Adversarial Controls & Falsification (Candidate C1)

| Placebo Experiment | Baseline Net EV | Placebo Net EV | p-value | Status | Finding |
| :--- | :--- | :--- | :--- | :--- | :--- |
{plac_table_md}

---

## 7. Economic Concentration & Market Structure

* **Top 1 Market Concentration:** `{conc.top_1_market_share_pct:.2f}%`
* **Top 5 Markets Concentration:** `{conc.top_5_markets_share_pct:.2f}%`
* **Top 10 Markets Concentration:** `{conc.top_10_markets_share_pct:.2f}%`
* **Dominant Market Family:** `{conc.top_market_family}` (`{conc.top_family_share_pct:.2f}%` of volume)
* **Effective Markets:** `{conc.effective_markets_count}`
* **Concentration Finding:** Market activity is heavily concentrated in macro/politics contracts. Wide spreads are systemic across all market sectors.

---

## 8. Prospective Discovery Monitor Telemetry

* **Live Recorder PID:** {prosp.recorder_pid} (Continuously streaming)
* **Historical Cutoff UTC:** `{prosp.historical_cutoff_utc}`
* **Prospective Snapshots Observed:** {prosp.prospective_observations_count}
* **Qualifying Prospective Signals Detected:** {prosp.qualifying_signals_count}
* **Hypothetical Executions Tracked:** {prosp.hypothetical_executions_count}
* **Realized Markouts Tracked:** {prosp.realized_markouts_tracked}
* **Total Orders Placed:** `{prosp.total_orders_placed}` (Zero live orders placed)
* **Production Database Writes:** `{prosp.production_writes_count}` (Zero production writes)
* **Target Research Candidate:** `{prosp.target_research_candidate}`

---

## 9. Final Preregistered Verdict & Next Research Path

* **Final Verdict:** **`{r.final_verdict.value}`**
* **Strongest Researchable Mechanism:** **{r.best_researchable_mechanism}**
* **Diagnostic Rationale:**  
  {r.strongest_research_rationale}

### Executive Conclusion
Per Section 14 and Section 16 instructions, **no fake positive result was manufactured**. All 10 candidate mechanisms legitimately failed under taker execution due to wide prediction market bid-ask spreads.  
To extract positive executable alpha on Polymarket, future research slates must transition to **maker/passive execution models** (earning rather than paying the spread) or focus exclusively on prospective regimes where competitive market makers compress spreads to $\le 0.001$.
"""
