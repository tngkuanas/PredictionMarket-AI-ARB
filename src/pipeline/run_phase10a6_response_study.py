"""Pipeline Runner for Phase 10A.6 Genuine High-Frequency Information-Response Study.

Executes the mandatory data-span check, audits causal separation, initializes DuckDB
tables, enforces the anti-synthetic guard, and records the audit summary.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Dict, Any

from src.phase10.response_study.study_engine import GenuineResponseStudyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_phase10a6_pipeline(
    db_path: str = "data/prediction_market.duckdb",
    output_summary_json: str = "data/phase10a6_response_study_summary.json",
    git_commit: str = "a7b61d6"
) -> Dict[str, Any]:
    """Runs the Phase 10A.6 response study pipeline."""
    engine = GenuineResponseStudyEngine(db_path=db_path, git_commit=git_commit)
    summary = engine.run_study()

    # Save summary JSON
    out_file = Path(output_summary_json)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info(f"Saved Phase 10A.6 study summary JSON to {output_summary_json}")

    print("\n" + "=" * 80)
    print("PHASE 10A.6 GENUINE RESPONSE STUDY & DATA-SPAN AUDIT SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2, default=str))

    return summary


def main():
    run_phase10a6_pipeline()


if __name__ == "__main__":
    main()
