"""Runner Script for Phase 10A.8 Passive Maker Edge Discovery.

Executes the empirical passive maker analysis on genuine live Polymarket data in prediction_market.duckdb.
Generates phase10a8_passive_maker_edge_discovery.md and records all findings.
"""

from datetime import datetime, timezone
import json
import logging
import os
import sys

from src.phase10a8.discovery_engine import PassiveMakerDiscoveryEngine
from src.phase10a8.report import Phase10A8ReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Phase10A8Runner")


def main():
    logger.info("Initializing Phase 10A.8 Passive Maker Discovery Engine...")
    db_path = "data/prediction_market.duckdb"
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}")
        sys.exit(1)

    engine = PassiveMakerDiscoveryEngine(
        db_path=db_path,
        quote_size_usd=50.0,
        evaluation_horizon_ms=5000,
    )

    logger.info("Running empirical discovery pipeline across active liquid markets...")
    results = engine.run_discovery_pipeline(
        market_limit=15,
        snapshots_per_market=1000,
        sample_step=5,
    )

    logger.info("Pipeline complete. Generating comprehensive markdown report...")
    report_md = Phase10A8ReportGenerator.generate_report_markdown(results)

    report_path = "phase10a8_passive_maker_edge_discovery.md"
    with open(report_path, "w") as f:
        f.write(report_md)
    logger.info(f"Report saved to {report_path}")

    # Also save to artifact directory if present
    artifact_dir = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170"
    if os.path.exists(artifact_dir):
        art_report_path = os.path.join(artifact_dir, "phase10a8_passive_maker_edge_discovery.md")
        with open(art_report_path, "w") as f:
            f.write(report_md)
        logger.info(f"Report also saved to artifact path: {art_report_path}")

    logger.info("Execution finished successfully.")


if __name__ == "__main__":
    main()
