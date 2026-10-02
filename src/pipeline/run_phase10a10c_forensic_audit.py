"""Pipeline Runner for Phase 10A.10-C Forensic Audit.

Usage:
    python -u src/pipeline/run_phase10a10c_forensic_audit.py --db-path data/prediction_market.duckdb
"""

import argparse
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.phase10a10c.audit_runner import Phase10A10CAuditRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Phase10A10CAudit")


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
    parser = argparse.ArgumentParser(description="Phase 10A.10-C Forensic Audit")
    parser.add_argument("--db-path", type=str, default="data/prediction_market.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()

    logger.info("================================================================================")
    logger.info("PHASE 10A.10-C — FORENSIC AUDIT OF PHASE 10A.10-B RUNNER")
    logger.info("================================================================================")

    recorder_alive = check_live_recorder_pid(70671)
    if not recorder_alive:
        logger.warning("Live recorder daemon is NOT currently detected! Running in read-only audit mode.")

    audit_runner = Phase10A10CAuditRunner(db_path=args.db_path)
    t0 = time.time()
    results = audit_runner.run_full_audit()
    elapsed = time.time() - t0

    reproduction = results["reproduction"]
    logger.info("================================================================================")
    logger.info(f"Phase 10A.10-C Forensic Audit Completed in {elapsed:.2f}s")
    logger.info(f"Final Audit Verdict: {results['verdict']}")
    logger.info(f"Reported OOS Net EV: {reproduction['reported_mean_net_ev']:.2f} bps")
    logger.info(f"Independent OOS Net EV: {reproduction['independent_mean_net_ev']:.2f} bps")
    logger.info(f"Reported OOS Executions: {reproduction['reported_n_oos']}")
    logger.info(f"Independent OOS Executions: {reproduction['independent_n_oos']}")
    logger.info(f"Mathematical Reproduction: {'EXACT PASS' if reproduction['reproduced'] else 'FAIL'}")
    logger.info(f"Report: {results['report_path']}")
    logger.info("================================================================================")


if __name__ == "__main__":
    main()
