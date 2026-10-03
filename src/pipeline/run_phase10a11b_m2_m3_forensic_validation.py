"""Pipeline Runner for Phase 10A.11-B: Forensic Validation of M2 and M3.

Executes complete forensic validation for:
- M2: Structural Fee Discreteness & Sub-Penny Tick Wedges
- M3: Multi-Outcome Asynchronous Rebalancing Overhang

Verifies live recorder health, runs all forensic tests, generates reports,
and writes artifacts to both the repository and brain artifact directories.
"""

import argparse
import datetime
import logging
from pathlib import Path
import shutil
import sys
import time

from src.phase10a11b.forensic_orchestrator import ForensicValidationOrchestrator
from src.phase10a11b.report import ForensicReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Phase10A11BRunner - %(message)s")
logger = logging.getLogger("Phase10A11BRunner")


def main():
    parser = argparse.ArgumentParser(description="Phase 10A.11-B Forensic Validation Runner")
    parser.add_argument("--db-path", type=str, default="data/prediction_market_readonly.duckdb", help="Path to DuckDB")
    parser.add_argument("--output-report", type=str, default="artifacts/phase10a11b_m2_m3_forensic_validation.md", help="Artifact report path")
    parser.add_argument("--brain-report", type=str, default="/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170/phase10a11b_m2_m3_forensic_validation.md", help="Brain artifact path")
    args = parser.parse_args()

    logger.info("=== Starting Phase 10A.11-B Forensic Validation of M2 and M3 ===")
    t0 = time.time()

    # Ensure read-only database copy exists if original is busy
    prod_db = "data/prediction_market.duckdb"
    ro_db = args.db_path
    if not Path(ro_db).exists() and Path(prod_db).exists():
        logger.info(f"Creating read-only snapshot copy of {prod_db} -> {ro_db}...")
        shutil.copyfile(prod_db, ro_db)
        wal_p = prod_db + ".wal"
        if Path(wal_p).exists():
            try:
                shutil.copyfile(wal_p, ro_db + ".wal")
            except Exception:
                pass

    orchestrator = ForensicValidationOrchestrator(db_path=ro_db)
    rec_status = orchestrator.get_recorder_status()
    logger.info(f"Recorder Daemon Check: PID={rec_status.pid}, is_running={rec_status.is_running}")

    if not rec_status.is_running:
        logger.warning("Recorder daemon is not running! It must be active per instructions.")
    else:
        logger.info(f"Live Recorder Daemon confirmed running with PID {rec_status.pid}.")

    logger.info("Running complete forensic validation workflow for M2 and M3...")
    master_result = orchestrator.run_validation()

    # Generate Report
    logger.info(f"Generating forensic audit report at {args.output_report}...")
    report_gen = ForensicReportGenerator()
    report_md = report_gen.generate_report(master_result)

    out_p = Path(args.output_report)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(report_md, encoding="utf-8")
    logger.info(f"Saved report to {out_p}")

    # Copy to brain artifact path
    brain_p = Path(args.brain_report)
    try:
        brain_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_p, brain_p)
        logger.info(f"Copied report to brain artifact path: {brain_p}")
    except Exception as e:
        logger.warning(f"Could not copy to brain artifact path: {e}")

    elapsed = time.time() - t0
    logger.info(f"=== Phase 10A.11-B Complete in {elapsed:.2f}s ===")
    logger.info(f"Final M2 Verdict: {master_result.m2_verdict.value}")
    logger.info(f"Final M3 Verdict: {master_result.m3_verdict.value}")
    logger.info(f"Paper Trading Eligible: {master_result.paper_trading_eligible}")


if __name__ == "__main__":
    main()
