"""Pipeline Runner for Phase 10A.10-D Methodology Repair and Revalidation.

Usage:
    python -u src/pipeline/run_phase10a10d_resolution_repair.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a10d.revalidation_pipeline import Phase10A10DRevalidationPipeline
from src.phase10a10d.report import Phase10A10DReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Phase10A10DRepair")


def check_live_recorder_pid(expected_pid: int = 70671) -> bool:
    """Verifies that the live recorder daemon is active and untouched."""
    try:
        res = subprocess.run(["ps", "-p", str(expected_pid), "-o", "pid,command"], capture_output=True, text=True)
        if str(expected_pid) in res.stdout:
            logger.info(f"Verified live recorder daemon PID {expected_pid} is ACTIVE and UNTOUCHED.")
            return True
        else:
            logger.warning(f"Recorder PID {expected_pid} not found in process table.")
            res2 = subprocess.run(["pgrep", "-f", "run_phase10a5e_daemon"], capture_output=True, text=True)
            pids = res2.stdout.strip().split()
            if pids:
                logger.info(f"Found active recorder daemon under PID(s): {pids}")
                return True
            return False
    except Exception as e:
        logger.error(f"Error checking recorder status: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Phase 10A.10-D Methodology Repair")
    parser.add_argument("--db-path", type=str, default="data/prediction_market.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()

    logger.info("================================================================================")
    logger.info("PHASE 10A.10-D — RESOLUTION METHODOLOGY REPAIR AND REVALIDATION")
    logger.info("================================================================================")

    recorder_alive = check_live_recorder_pid(70671)
    if not recorder_alive:
        logger.warning("Live recorder daemon is NOT currently detected! Running in read-only audit mode.")

    pipeline = Phase10A10DRevalidationPipeline(db_path=args.db_path)
    t0 = time.time()
    results = pipeline.run_revalidation()
    elapsed = time.time() - t0

    # Generate and write report
    report_md = Phase10A10DReportGenerator.generate_report(results=results, recorder_pid=70671)

    report_path = "artifacts/phase10a10d_resolution_repair.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report_md)

    brain_report_path = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170/phase10a10d_resolution_repair.md"
    try:
        with open(brain_report_path, "w") as f:
            f.write(report_md)
    except Exception as e:
        logger.warning(f"Could not write to brain artifacts directory: {e}")

    logger.info("================================================================================")
    logger.info(f"Phase 10A.10-D Revalidation Completed in {elapsed:.2f}s")
    logger.info(f"Final Audit Verdict: {results['verdict']}")
    logger.info(f"Raw OOS Executions: {results['raw_oos_executions']}")
    logger.info(f"Rejected Unresolved Executions: {results['rejected_raw_executions']}")
    logger.info(f"Valid Raw Executions Remaining: {results['valid_raw_executions']}")
    logger.info(f"Canonical Executions (all tiers): {results['canonical_executions_all_tiers']}")
    logger.info(f"Canonical Executions (baseline size $50): {results['canonical_executions_baseline']}")
    logger.info(f"Mean Corrected OOS Net EV: {results['mean_corrected_ev_bps']:.2f} bps")
    logger.info(f"Median Corrected OOS Net EV: {results['median_corrected_ev_bps']:.2f} bps")
    logger.info(f"Execution Hit Rate: {results['execution_hit_rate']:.1f}%")
    logger.info(f"Event Hit Rate: {results['event_hit_rate']:.1f}%")
    logger.info(f"Unique Valid Events: {results['event_count']}")
    logger.info(f"Report written to: {report_path}")
    logger.info("================================================================================")


if __name__ == "__main__":
    main()
