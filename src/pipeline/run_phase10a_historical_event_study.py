"""Phase 10A.3 Pipeline Runner: Historical Information-Latency Event Study.
Executes end-to-end historical information latency study across 452-day Polymarket dataset.
Analyzes Questions Q1-Q8, runs 4 null controls, saves DuckDB tables, and evaluates Decision Gate.
"""
import os
import shutil
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from src.phase10.events.historical_events import create_historical_event_dataset
from src.phase10.events.event_study_engine import HistoricalEventStudyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_historical_event_study(db_path: str = "data/prediction_market.duckdb") -> Dict[str, Any]:
    """Runs the full Phase 10A.3 historical event study pipeline."""
    logger.info("Initializing Phase 10A.3 Historical Event Study Engine...")
    engine = HistoricalEventStudyEngine(db_path=db_path)
    
    conn = duckdb.connect(db_path, read_only=False)
    
    # 1. Load Canonical Universe & Historical Events
    universe = engine.load_canonical_universe(conn)
    events = create_historical_event_dataset()
    logger.info(f"Loaded canonical universe ({len(universe)} markets) and event dataset ({len(events)} events).")

    # 2. Stage B Deterministic Contract Mapping
    mappings, accepted_pairs = engine.evaluate_mappings(events, universe)
    n_total = len(mappings)
    n_accepted = sum(1 for m in mappings if m.mapping_decision.value == "accepted")
    n_ambiguous = sum(1 for m in mappings if m.mapping_decision.value == "ambiguous")
    n_rejected = sum(1 for m in mappings if m.mapping_decision.value == "rejected")
    logger.info(f"Contract Mapping evaluated {n_total} pairs: {n_accepted} Accepted, {n_ambiguous} Ambiguous, {n_rejected} Rejected.")
    logger.info(f"Unique events with primary Accepted target contract: {len(accepted_pairs)}")

    # 3. High-Resolution Price Response Measurement
    observations = []
    for evt, cm, token, liq, vol, mapping in accepted_pairs:
        obs = engine.measure_event_response(conn, evt, cm, token, liq, mapping)
        if obs:
            observations.append(obs)
    logger.info(f"Measured high-resolution market responses for {len(observations)} accepted events.")

    # 4. Run Null Controls
    sports_tokens = [tok for mid, (cm, tok, liq, vol) in universe.items() if cm.event_type == 'sports_championship']
    placebos = engine.run_null_controls(conn, accepted_pairs, sports_tokens)
    logger.info(f"Completed 4 null control batteries (Random TS: {len(placebos['placebo_a_random_ts'])}, Time-Shift: {len(placebos['placebo_b_timeshift'])}, Wrong Market: {len(placebos['placebo_c_wrong_market'])}, Direction: {len(placebos['placebo_d_direction'])}).")

    # 5. Persist Normalized DuckDB Tables
    engine.persist_to_duckdb(conn, events, mappings, observations, placebos)
    logger.info("Persisted tables: phase10a_information_events, phase10a_contract_mappings, phase10a_event_study, phase10a_placebos.")

    # 6. Analytical Slices & Metrics
    gate = engine.evaluate_decision_gate(observations, placebos)
    logger.info(f"Decision Gate Classification: {gate['classification']}")
    logger.info(f"Decision Rationale: {gate['rationale']}")

    # Surprise vs Repricing Regression (Q1)
    obs_surprise = [o for o in observations if o.measurable_surprise is not None and abs(o.measurable_surprise) > 1e-4 and o.horizons.get("1h") and o.horizons["1h"].is_available]
    if len(obs_surprise) >= 3:
        x_surp = np.array([o.measurable_surprise for o in obs_surprise])
        y_ret = np.array([o.horizons["1h"].dir_delta_mid for o in obs_surprise])
        slope, intercept, r_value, p_value, std_err = stats.linregress(x_surp, y_ret)
        surprise_reg = {
            "n": len(obs_surprise),
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": float(r_value ** 2),
            "p_value": float(p_value),
            "std_err": float(std_err)
        }
    else:
        surprise_reg = {"n": len(obs_surprise), "slope": 0.0, "intercept": 0.0, "r_squared": 0.0, "p_value": 1.0, "std_err": 0.0}

    # Horizon Availability & Repricing Speed (Q2)
    horizon_summary = {}
    for h_name, _, _ in engine.HORIZONS_CONFIG:
        avail_obs = [o for o in observations if o.horizons.get(h_name) and o.horizons[h_name].is_available]
        count = len(avail_obs)
        mean_dir_delta = float(np.mean([o.horizons[h_name].dir_delta_mid for o in avail_obs])) if count > 0 else None
        mean_exec = float(np.mean([o.horizons[h_name].exec_markout for o in avail_obs])) if count > 0 else None
        horizon_summary[h_name] = {
            "count": count,
            "pct_available": float(count / len(observations) * 100.0) if observations else 0.0,
            "mean_dir_delta": mean_dir_delta,
            "mean_exec_markout": mean_exec
        }

    # Liquidity Slicing (Q5)
    obs_1h = [o for o in observations if o.horizons.get("1h") and o.horizons["1h"].is_available]
    high_liq = [o for o in obs_1h if o.depth_minus >= 15000.0] # >= $100k total liquidity
    low_liq = [o for o in obs_1h if o.depth_minus < 15000.0]
    
    liq_slice = {
        "high_liq_n": len(high_liq),
        "high_liq_mean_spread": float(np.mean([o.spread_minus for o in high_liq])) if high_liq else 0.0,
        "high_liq_mean_exec": float(np.mean([o.horizons["1h"].exec_markout for o in high_liq])) if high_liq else 0.0,
        "high_liq_mean_net": float(np.mean([o.horizons["1h"].net_markout_160bps for o in high_liq])) if high_liq else 0.0,
        "low_liq_n": len(low_liq),
        "low_liq_mean_spread": float(np.mean([o.spread_minus for o in low_liq])) if low_liq else 0.0,
        "low_liq_mean_exec": float(np.mean([o.horizons["1h"].exec_markout for o in low_liq])) if low_liq else 0.0,
        "low_liq_mean_net": float(np.mean([o.horizons["1h"].net_markout_160bps for o in low_liq])) if low_liq else 0.0,
    }

    # Event Type Slicing (Q6)
    type_slice = {}
    for etype in set(o.event_type for o in obs_1h):
        subset = [o for o in obs_1h if o.event_type == etype]
        type_slice[etype] = {
            "n": len(subset),
            "mean_dir_delta": float(np.mean([o.horizons["1h"].dir_delta_mid for o in subset])),
            "mean_exec_markout": float(np.mean([o.horizons["1h"].exec_markout for o in subset])),
            "mean_net_markout": float(np.mean([o.horizons["1h"].net_markout_160bps for o in subset])),
            "win_rate": float((np.array([o.horizons["1h"].exec_markout for o in subset]) > 0).mean())
        }

    # Persistence Ratio (Q3)
    valid_pers = [o.persistence_ratio_24h_1h for o in observations if o.persistence_ratio_24h_1h is not None]
    mean_pers = float(np.median(valid_pers)) if valid_pers else 0.0

    conn.close()

    summary_results = {
        "mapping_stats": {
            "total_pairs": n_total,
            "accepted": n_accepted,
            "ambiguous": n_ambiguous,
            "rejected": n_rejected,
            "unique_accepted_events": len(accepted_pairs)
        },
        "gate": gate,
        "surprise_regression": surprise_reg,
        "horizon_summary": horizon_summary,
        "liquidity_slice": liq_slice,
        "type_slice": type_slice,
        "median_persistence_ratio": mean_pers,
        "observations_count": len(observations)
    }

    return summary_results


if __name__ == "__main__":
    results = run_historical_event_study()
    print("\n" + "="*80)
    print("PHASE 10A.3 HISTORICAL INFORMATION-LATENCY EVENT STUDY COMPLETED")
    print("="*80)
    print(json.dumps(results, indent=2, default=str))
