"""Runner script for Phase 10A.9-C Hedge Execution / Latency Forensic Audit.

Executes:
1. Complete forensic audit of latency tiers, depth, payoff, and statistics.
2. Generates phase10a9c_execution_latency_audit.md.
3. Syncs report to conversation artifact directory.
4. Outputs key audit conclusions.
"""

import logging
import os
import shutil

from src.phase10a9c.pipeline import Phase10A9CForensicAuditPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("phase10a9c_runner")

ARTIFACT_DIR = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170"


def main():
    logger.info("Initializing Phase 10A.9-C Forensic Audit Pipeline...")
    pipeline = Phase10A9CForensicAuditPipeline(db_path="data/prediction_market.duckdb")
    summary = pipeline.run_audit(max_fills=500)

    report_path = "phase10a9c_execution_latency_audit.md"
    logger.info(f"Report generated successfully at {report_path}")

    if os.path.exists(ARTIFACT_DIR):
        artifact_path = os.path.join(ARTIFACT_DIR, "phase10a9c_execution_latency_audit.md")
        shutil.copyfile(report_path, artifact_path)
        logger.info(f"Synced report to artifact directory: {artifact_path}")

    print("\n" + "=" * 60)
    print("PHASE 10A.9-C FORENSIC AUDIT COMPLETE")
    print(f"Audit Verdict: {summary['verdict']}")
    print(f"Hedge Sides Correct: {summary['sides_correct']}")
    print(f"Payoff Neutralization: {summary['payoff_audit'].neutralized_count} / {summary['payoff_audit'].total_hedges} ({summary['payoff_audit'].neutralization_rate_pct}%)")
    print(f"Depth Ratio Min: {summary['depth_audit'].min_ratio}x, Median: {summary['depth_audit'].med_ratio}x, P95: {summary['depth_audit'].p95_ratio}x")
    print(f"Levels Consumed: Median: {summary['depth_audit'].med_levels_consumed}, P95: {summary['depth_audit'].p95_levels_consumed}")
    print(f"250ms OOS EV: {summary['positive_tier_audit'][250]['mean_ev_bps']} bps (CI crosses zero: {summary['positive_tier_audit'][250]['ci_crosses_zero']})")
    print(f"500ms OOS EV: {summary['positive_tier_audit'][500]['mean_ev_bps']} bps (CI crosses zero: {summary['positive_tier_audit'][500]['ci_crosses_zero']})")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
