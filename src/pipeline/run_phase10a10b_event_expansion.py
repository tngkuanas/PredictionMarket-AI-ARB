"""Pipeline Runner for Phase 10A.10-B Genuine Event-Universe Expansion.

Usage:
    python -u src/pipeline/run_phase10a10b_event_expansion.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a10b.pipeline import Phase10A10BPipeline
from src.phase10a10b.config_freeze import PHASE10A10B_CONFIG_HASH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Phase10A10BRunner")


def check_live_recorder_pid(expected_pid: int = 70671) -> bool:
    """Verifies that the live recorder daemon is active."""
    try:
        res = subprocess.run(["ps", "-p", str(expected_pid), "-o", "pid,command"], capture_output=True, text=True)
        if str(expected_pid) in res.stdout:
            logger.info(f"Verified live recorder daemon PID {expected_pid} is ACTIVE.")
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
    parser = argparse.ArgumentParser(description="Phase 10A.10-B Event Universe Expansion")
    parser.add_argument("--db-path", type=str, default="data/prediction_market.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()

    logger.info("================================================================================")
    logger.info("PHASE 10A.10-B — GENUINE EVENT-UNIVERSE EXPANSION RUNNER")
    logger.info("================================================================================")
    logger.info(f"Frozen Phase 10A.10 Config Hash: {PHASE10A10B_CONFIG_HASH}")

    recorder_alive = check_live_recorder_pid(70671)
    if not recorder_alive:
        logger.warning("Live recorder daemon is NOT currently detected! Running in read-only research mode.")

    pipeline = Phase10A10BPipeline(db_path=args.db_path)
    t0 = time.time()
    results = pipeline.run()
    elapsed = time.time() - t0

    logger.info("================================================================================")
    logger.info(f"Phase 10A.10-B Expansion Completed in {elapsed:.2f}s")
    logger.info(f"Primary Verdict: {results['verdict']}")
    logger.info(f"Raw Candidate Events: {results['raw_candidates']}")
    logger.info(f"Accepted Independent Events: {results['total_events']}")
    logger.info(f"Independent OOS Events: {results['oos_events']}")
    logger.info(f"Rejected Candidates: {results['rejections_count']}")
    logger.info(f"Total Candidates: {results['total_candidates']}")
    logger.info(f"Total Executions: {results['total_executions']}")
    logger.info(f"OOS Executions: {results['oos_executions']}")
    logger.info(f"Mean OOS Net EV: {results['mean_oos_net_ev']:.2f} bps")
    logger.info(f"Report: {results['report_path']}")
    logger.info("================================================================================")


if __name__ == "__main__":
    main()
