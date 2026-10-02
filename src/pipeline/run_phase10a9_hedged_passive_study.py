"""Runner Script for Phase 10A.9 Hedged Passive / Cross-Contract Neutralization Research.

Executes the empirical hedged passive analysis on genuine Polymarket data in prediction_market.duckdb.
Generates phase10a9_hedged_passive_edge_discovery.md and persists all empirical records to DuckDB.
"""

from datetime import datetime, timezone
import json
import logging
import os
import sys

from src.phase10a9.pipeline import Phase10A9ResearchPipeline
from src.phase10a9.report import Phase10A9ReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Phase10A9Runner")


def main():
    logger.info("Initializing Phase 10A.9 Hedged Passive Research Pipeline...")
    db_path = "data/prediction_market.duckdb"
    if not os.path.exists(db_path):
        logger.error(f"Database not found at {db_path}")
        sys.exit(1)

    pipeline = Phase10A9ResearchPipeline(db_path=db_path)

    logger.info("Executing empirical study on genuine Polymarket CLOB data...")
    summary = pipeline.run_pipeline(
        max_fills_to_evaluate=500,
        primary_latency_ms=100
    )

    logger.info(f"Pipeline complete. Headline Hedged EV: {summary['headline_hedged_ev_bps']} bps. Verdict: {summary['verdict']}")

    logger.info("Generating comprehensive markdown report...")
    report_md = Phase10A9ReportGenerator.generate_report_markdown(summary)

    report_path = "phase10a9_hedged_passive_edge_discovery.md"
    with open(report_path, "w") as f:
        f.write(report_md)
    logger.info(f"Report saved locally to {report_path}")

    # Also save to artifact directory
    artifact_dir = "/Users/tengkuanas/.gemini/antigravity-cli/brain/7e85fb60-ccc5-4fa8-a765-f7dc863e4170"
    if os.path.exists(artifact_dir):
        art_report_path = os.path.join(artifact_dir, "phase10a9_hedged_passive_edge_discovery.md")
        with open(art_report_path, "w") as f:
            f.write(report_md)
        logger.info(f"Report also saved to artifact path: {art_report_path}")

    # Write summary json
    summary_path = "phase10a9_summary.json"
    with open(summary_path, "w") as f:
        # Serializer helper for non-serializable objects
        def json_serial(obj):
            if isinstance(obj, (datetime,)):
                return obj.isoformat()
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)
        json.dump(summary, f, indent=2, default=json_serial)
    logger.info(f"Summary JSON saved to {summary_path}")

    logger.info("Phase 10A.9 empirical study finished successfully.")


if __name__ == "__main__":
    main()
