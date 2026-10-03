#!/usr/bin/env python3
"""Pipeline runner for Phase 10A.12: New Executable Alpha Discovery."""

import os
import shutil
import sys
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.phase10a12.orchestrator import Phase10A12Orchestrator
from src.phase10a12.report import Phase10A12ReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Initializing Phase 10A.12 Discovery Orchestrator...")
    orchestrator = Phase10A12Orchestrator()
    result = orchestrator.run_discovery_pipeline()

    logger.info(f"Phase 10A.12 Completed. Final Verdict: {result.final_verdict.value}")
    logger.info(f"Strongest Research Mechanism: {result.best_researchable_mechanism}")

    # Generate Report
    report_gen = Phase10A12ReportGenerator(result)
    report_content = report_gen.generate_markdown()

    # Save to artifacts directory
    artifacts_dir = PROJECT_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    report_path = artifacts_dir / "phase10a12_alpha_discovery.md"
    report_path.write_text(report_content)
    logger.info(f"Audit report saved to: {report_path}")

    # Copy to brain artifact directory if present
    brain_dir = Path("/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170")
    if brain_dir.exists():
        dest = brain_dir / "phase10a12_alpha_discovery.md"
        shutil.copyfile(report_path, dest)
        logger.info(f"Report mirrored to brain artifact directory: {dest}")


if __name__ == "__main__":
    main()
