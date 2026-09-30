"""Harmless Infrastructure Dry-Run for Phase 10A.6 Event-Study Engine.

Runs the deterministic event-study engine against currently accumulated genuine
Phase 10A.5 data to verify pipeline wiring and execution mechanics without modifying
or interfering with the live recording daemon.
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.phase10.acquisition.dns_resolver import enable_polymarket_edge_resolver
enable_polymarket_edge_resolver()

from src.phase10.response_study.event_study_engine import DeterministicEventStudyEngine
from src.phase10.response_study.schema import EventStudyConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run_dry_run():
    config = EventStudyConfig(
        min_depth_usd=50.0,
        max_spread=0.25,
        fee_rate_bps=20.0
    )
    engine = DeterministicEventStudyEngine(
        db_path="data/prediction_market.duckdb",
        config=config,
        git_commit="04c720e"
    )

    print("\nExecuting Phase 10A.6 Infrastructure Dry-Run against production DuckDB...")
    summary = engine.run_study(persist_results=False, is_dry_run=True)

    print("\n" + "=" * 80)
    print("PHASE 10A.6 INCOMPLETE / INFRASTRUCTURE DRY-RUN RESULTS")
    print("=" * 80)
    print(json.dumps(summary, indent=2, default=str))
    print("=" * 80)


if __name__ == "__main__":
    run_dry_run()
