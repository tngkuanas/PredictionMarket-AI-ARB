"""Pipeline Runner for Phase 10A.11 Executable Alpha Discovery.

Usage:
    python -u src/pipeline/run_phase10a11_alpha_discovery.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a11.discovery_pipeline import DiscoveryPipeline
from src.phase10a11.report import Phase10A11ReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("Phase10A11Runner")


def check_recorder_status() -> bool:
    """Verifies that the live recorder daemon is NOT running."""
    try:
        res = subprocess.run(
            ["pgrep", "-f", "run_phase10a5e_daemon.py"],
            capture_output=True,
            text=True,
        )
        pids = res.stdout.strip().split()
        if pids:
            logger.warning(f"Recorder daemon process detected with PID(s): {pids}")
            return True
        return False
    except Exception as e:
        logger.warning(f"Error checking recorder process: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Phase 10A.11 New Executable Alpha Discovery")
    parser.add_argument("--db-path", default="data/prediction_market.duckdb", help="Path to DuckDB database")
    parser.add_argument("--output-path", default="artifacts/phase10a11_alpha_discovery.md", help="Output path for report")
    args = parser.parse_args()

    logger.info("=== Starting Phase 10A.11 New Executable Alpha Discovery ===")
    start_time = time.time()

    # Step 1: Live Recorder Check
    is_running = check_recorder_status()
    if is_running:
        logger.warning("Recorder daemon is currently running. Accessing DB strictly in READ-ONLY mode.")
    else:
        logger.info("Live recorder daemon is NOT running (PID 70671 stopped as reported). Read-only DB access safe.")

    # Step 2: Initialize Discovery Pipeline
    pipeline = DiscoveryPipeline(db_path=args.db_path)

    # Step 3: Execute Discovery Pipeline
    logger.info("Executing Discovery Pipeline...")
    summary = pipeline.execute_discovery()

    # Step 4: Generate Report
    logger.info(f"Generating Phase 10A.11 discovery report at {args.output_path}...")
    report_gen = Phase10A11ReportGenerator(summary=summary)
    report_gen.generate_report(output_path=args.output_path)

    # Also copy report to brain artifacts directory if it exists
    brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170")
    if os.path.isdir(brain_dir):
        brain_report = os.path.join(brain_dir, "phase10a11_alpha_discovery.md")
        try:
            shutil.copyfile(args.output_path, brain_report)
            logger.info(f"Copied report to brain artifact path: {brain_report}")
        except Exception as e:
            logger.warning(f"Could not copy report to brain dir: {e}")

    elapsed = time.time() - start_time
    logger.info(f"=== Phase 10A.11 Discovery Complete in {elapsed:.2f}s ===")
    logger.info(f"Total Candidates: {summary.total_candidates}")
    logger.info(f"Novel Mechanisms: {summary.novel_candidates_count}")
    logger.info(f"Duplicate Rejected: {summary.duplicate_rejected_count}")
    logger.info(f"Promising Candidates: {summary.promising_candidates_count}")
    logger.info(f"Most Promising: {summary.most_promising_candidate_id}")


if __name__ == "__main__":
    main()
