#!/usr/bin/env python3
"""Pipeline runner for Phase 10A.11-C: M3 Atomic Multi-Outcome Routing & Prospective Validation."""

import os
import shutil
import sys
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.phase10a11c.orchestrator import Phase10A11COrchestrator
from src.phase10a11c.report import Phase10A11CReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Initializing Phase 10A.11-C M3 Atomic Routing Orchestrator...")
    orchestrator = Phase10A11COrchestrator()
    result = orchestrator.run_validation()

    logger.info(f"Phase 10A.11-C Completed. Final Verdict: {result.final_verdict.value}")
    logger.info(f"Paper-Trading Eligibility: {result.paper_trading_eligibility.value}")

    # Generate Report
    report_gen = Phase10A11CReportGenerator(result)
    report_content = report_gen.generate_markdown()

    # Save to artifacts directory
    artifacts_dir = PROJECT_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    report_path = artifacts_dir / "phase10a11c_m3_atomic_routing.md"
    report_path.write_text(report_content)
    logger.info(f"Audit report saved to: {report_path}")

    # Copy to app data directory if available
    brain_dir = Path("/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170")
    if brain_dir.exists():
        dest = brain_dir / "phase10a11c_m3_atomic_routing.md"
        shutil.copyfile(report_path, dest)
        logger.info(f"Report mirrored to brain artifact directory: {dest}")


if __name__ == "__main__":
    main()
