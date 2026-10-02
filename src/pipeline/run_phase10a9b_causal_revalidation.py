"""Runner script for Phase 10A.9-B Strict Forward-Causal Hedge Revalidation.

Executes:
1. Master research pipeline under strict forward causality.
2. Generates comprehensive phase10a9b_causal_revalidation.md report.
3. Syncs report to artifact directory.
4. Outputs key performance and validation metrics.
"""

import json
import logging
import os
import shutil
import sys

from src.phase10a9b.pipeline import Phase10A9BResearchPipeline
from src.phase10a9b.report import Phase10A9BReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("phase10a9b_runner")

ARTIFACT_DIR = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170"


def main():
    logger.info("Initializing Phase 10A.9-B Research Pipeline...")
    pipeline = Phase10A9BResearchPipeline(db_path="data/prediction_market.duckdb")

    summary = pipeline.run_pipeline(max_fills_to_evaluate=500, primary_latency_ms=100)

    report_path = "phase10a9b_causal_revalidation.md"
    report_content = Phase10A9BReportGenerator.generate_report(summary, output_path=report_path)
    logger.info(f"Report generated successfully at {report_path}")

    # Sync to artifact directory
    if os.path.exists(ARTIFACT_DIR):
        artifact_path = os.path.join(ARTIFACT_DIR, "phase10a9b_causal_revalidation.md")
        shutil.copyfile(report_path, artifact_path)
        logger.info(f"Synced report to artifact directory: {artifact_path}")

    print("\n" + "=" * 60)
    print("PHASE 10A.9-B REVALIDATION COMPLETE")
    print(f"Verdict: {summary['verdict']}")
    print(f"Pre-target snapshots used: {summary['pre_target_snapshots_used']}")
    print(f"Pre-target snapshots rejected: {summary['pre_target_snapshots_rejected']}")
    print(f"Completed hedges: {summary['completed_hedges']} / {summary['passive_fills_count']} ({summary['completion_rate_pct']}%)")
    print(f"OOS Mean EV: {summary['oos_stat']['mean_ev_bps']} bps/fill (t={summary['oos_stat']['t_stat']}, p={summary['oos_stat']['p_value']:.2e})")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
