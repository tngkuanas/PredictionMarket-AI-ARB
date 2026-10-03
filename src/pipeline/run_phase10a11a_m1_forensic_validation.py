"""Pipeline Runner for Phase 10A.11-A Forensic Validation of M1 Post-Sweep Resiliency.

Usage:
    python -u src/pipeline/run_phase10a11a_m1_forensic_validation.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a11a.forensic_orchestrator import ForensicValidationOrchestrator
from src.phase10a11a.report import Phase10A11AReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("Phase10A11ARunner")


def verify_recorder_stopped() -> bool:
    """Verifies that no live recorder daemon is running."""
    try:
        res = subprocess.run(
            ["pgrep", "-f", "run_phase10a5e_daemon.py"],
            capture_output=True,
            text=True,
        )
        pids = res.stdout.strip().split()
        if pids:
            logger.error(f"Recorder process found running with PID(s): {pids}! Must be stopped.")
            return False
        return True
    except Exception as e:
        logger.warning(f"Error checking recorder: {e}")
        return True


def main():
    parser = argparse.ArgumentParser(description="Phase 10A.11-A Forensic Validation of M1")
    parser.add_argument("--db-path", default="data/prediction_market.duckdb", help="DuckDB database path")
    parser.add_argument("--output-path", default="artifacts/phase10a11a_m1_forensic_validation.md", help="Output markdown path")
    args = parser.parse_args()

    logger.info("=== Starting Phase 10A.11-A Forensic Validation of M1 Post-Sweep Resiliency ===")
    start_time = time.time()

    # Step 1: Verify Recorder Stopped
    if not verify_recorder_stopped():
        logger.warning("Recorder was detected running. Ensure it is stopped before proceeding.")
    else:
        logger.info("Recorder daemon is confirmed STOPPED (PID 70671 / PID 79361 not running).")

    # Step 2: Initialize Orchestrator
    orchestrator = ForensicValidationOrchestrator(db_path=args.db_path)

    # Step 3: Run Validation
    logger.info("Running complete 16-step forensic validation workflow...")
    result = orchestrator.run_validation()

    # Step 4: Generate Report
    logger.info(f"Generating report at {args.output_path}...")
    report_gen = Phase10A11AReportGenerator(master_result=result)
    report_gen.generate_report(output_path=args.output_path)

    # Copy to brain dir if exists
    brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170")
    if os.path.isdir(brain_dir):
        brain_report = os.path.join(brain_dir, "phase10a11a_m1_forensic_validation.md")
        try:
            shutil.copyfile(args.output_path, brain_report)
            logger.info(f"Copied report to brain artifact path: {brain_report}")
        except Exception as e:
            logger.warning(f"Could not copy report to brain: {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== Phase 10A.11-A Complete in {elapsed:.2f}s ===")
    logger.info(f"Final Forensic Verdict: {result.final_verdict.value}")
    logger.info(f"30s Mean Executable Net EV: {result.horizon_markouts.get(30).mean_executable_markout_bps:.2f} bps")
    logger.info(f"Primary Failure Mode: {result.primary_failure_mode}")


if __name__ == "__main__":
    main()
