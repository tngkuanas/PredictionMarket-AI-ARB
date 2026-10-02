"""Pipeline Runner for Phase 10A.10 Deterministic Resolution-State Lag Research.

Usage:
    python -u src/pipeline/run_phase10a10_resolution_lag.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import subprocess
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a10.pipeline import Phase10A10Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Phase10A10Runner")


def check_live_recorder_pid(expected_pid: int = 70671) -> bool:
    """Verifies that the live recorder daemon is active."""
    try:
        res = subprocess.run(["ps", "-p", str(expected_pid), "-o", "pid,command"], capture_output=True, text=True)
        if str(expected_pid) in res.stdout:
            logger.info(f"Verified live recorder daemon PID {expected_pid} is ACTIVE.")
            return True
        else:
            logger.warning(f"Recorder PID {expected_pid} not found in process table.")
            # Check if any run_phase10a5e_daemon is running
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
    parser = argparse.ArgumentParser(description="Phase 10A.10 Deterministic Resolution-State Lag Research")
    parser.add_argument("--db-path", type=str, default="data/prediction_market.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()

    logger.info("================================================================================")
    logger.info("PHASE 10A.10 — DETERMINISTIC RESOLUTION-STATE LAG RESEARCH RUNNER")
    logger.info("================================================================================")

    # 1. Check live recorder daemon PID
    recorder_alive = check_live_recorder_pid(70671)
    if not recorder_alive:
        logger.warning("Live recorder daemon is NOT currently detected! Proceeding in read-only research mode.")

    # 2. Run Pipeline
    pipeline = Phase10A10Pipeline(db_path=args.db_path)
    t0 = time.time()
    results = pipeline.run()
    elapsed = time.time() - t0

    logger.info("================================================================================")
    logger.info(f"Phase 10A.10 Research Completed in {elapsed:.2f}s")
    logger.info(f"Primary Verdict: {results['verdict']}")
    logger.info(f"Raw Markets: {results['raw_markets']}")
    logger.info(f"Total Resolution Events: {results['total_events']}")
    logger.info(f"Candidates Generated: {results['total_candidates']}")
    logger.info(f"Executions Simulated: {results['total_executions']}")
    logger.info(f"OOS Executions: {results['oos_executions']}")
    logger.info(f"Report Generated: {results['report_path']}")
    logger.info("================================================================================")


if __name__ == "__main__":
    main()
