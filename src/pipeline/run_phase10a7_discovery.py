"""Phase 10A.7 Production Research Runner: Genuine Polymarket Edge Discovery.

Executes the 4-stage empirical research pipeline across all 7 research branches:
- Stage 1: Discovery (first 60% of chronological dataset)
- Stage 2: Freeze (SHA-256 configuration hash)
- Stage 3: Out-of-Sample Evaluation (last 40% of chronological dataset)
- Stage 4: Adversarial Controls (placebo, permutation, sign reversal, stress dimensions)
- Multiple-testing FDR correction (Benjamini-Hochberg)

CRITICAL SAFETY:
- Connects read-only to market data tables.
- Never interferes with recorder PID 53380.
- Rejects fixture/synthetic contamination.
"""

from datetime import datetime, timezone
import json
import logging
import os
import sys

from src.edge_discovery.research_engine import EdgeDiscoveryEngine
from src.edge_discovery.schema import CandidateClassification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Phase10A7Runner")


def main():
    logger.info("=" * 80)
    logger.info("STARTING PHASE 10A.7: GENUINE POLYMARKET EDGE DISCOVERY")
    logger.info("=" * 80)

    db_path = "data/prediction_market.duckdb"
    engine = EdgeDiscoveryEngine(db_path=db_path, random_seed=42)

    t_start, t_end, t_split = engine.data_loader.get_dataset_timeline()
    logger.info(f"Empirical Dataset Bounds: {t_start} -> {t_end}")
    logger.info(f"Timeline Split: Discovery (60%) <= {t_split} < Out-of-Sample (40%)")

    run_output = engine.execute_discovery_run()

    logger.info("=" * 80)
    logger.info("PHASE 10A.7 RESEARCH PIPELINE COMPLETED")
    logger.info(f"Run ID: {run_output['run_id']}")
    logger.info(f"Config Hash: {run_output['config_hash']}")
    logger.info(f"Dataset Span: {run_output['dataset_span_hours']} hours")
    logger.info(f"Hypotheses Evaluated: {run_output['total_hypotheses']}")
    logger.info(f"Surviving Research Candidates: {run_output['surviving_candidates']}")
    logger.info(f"Promising (Requires More Data): {run_output['promising_candidates']}")
    logger.info(f"Insufficient Data (N < 30): {run_output['insufficient_data']}")
    logger.info(f"Rejected Count: {run_output['rejected_count']}")
    logger.info("=" * 80)

    print("\nDETAILED HYPOTHESIS EVALUATION TABLE:")
    print(f"{'Hypothesis ID':<30} | {'Branch':<25} | {'Disc N':<6} | {'Disc Net':<9} | {'OOS N':<6} | {'OOS Net':<9} | {'t-stat':<7} | {'FDR q':<8} | {'Adv':<5} | {'Classification'}")
    print("-" * 155)

    summary_results = []
    for res in run_output["results"]:
        h = res.hypothesis
        adv_str = f"{res.adversarial_controls_passed}/{res.adversarial_controls_total}"
        print(
            f"{h.hypothesis_id:<30} | {h.branch.value:<25} | {res.discovery_n:<6} | "
            f"{res.discovery_net_bps:>7.1f}bp | {res.oos_n:<6} | {res.oos_net_bps:>7.1f}bp | "
            f"{res.t_stat:>7.2f} | {res.fdr_adjusted_p:>8.4f} | {adv_str:<5} | {res.classification.value}"
        )
        summary_results.append({
            "hypothesis_id": h.hypothesis_id,
            "branch": h.branch.value,
            "name": h.name,
            "economic_mechanism": h.economic_mechanism,
            "discovery_n": res.discovery_n,
            "discovery_gross_bps": res.discovery_gross_bps,
            "discovery_net_bps": res.discovery_net_bps,
            "oos_n": res.oos_n,
            "oos_gross_bps": res.oos_gross_bps,
            "oos_net_bps": res.oos_net_bps,
            "t_stat": res.t_stat,
            "p_value": res.p_value,
            "fdr_adjusted_p": res.fdr_adjusted_p,
            "adversarial_passed": res.adversarial_controls_passed,
            "adversarial_total": res.adversarial_controls_total,
            "classification": res.classification.value,
            "classification_reason": res.classification_reason,
        })

    summary_file = "data/phase10a7_discovery_summary.json"
    with open(summary_file, "w") as f:
        json.dump({
            "run_id": run_output["run_id"],
            "config_hash": run_output["config_hash"],
            "dataset_span_hours": run_output["dataset_span_hours"],
            "dataset_start": t_start.isoformat(),
            "dataset_end": t_end.isoformat(),
            "discovery_cutoff": t_split.isoformat(),
            "total_hypotheses": run_output["total_hypotheses"],
            "surviving_candidates": run_output["surviving_candidates"],
            "promising_candidates": run_output["promising_candidates"],
            "insufficient_data": run_output["insufficient_data"],
            "rejected_count": run_output["rejected_count"],
            "results": summary_results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)

    logger.info(f"Saved Phase 10A.7 summary report to {summary_file}")
    return run_output


if __name__ == "__main__":
    main()
