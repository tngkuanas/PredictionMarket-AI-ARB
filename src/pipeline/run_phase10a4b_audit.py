"""Pipeline Runner for Phase 10A.4b Anti-Leakage & Event-Universe Audit.

Executes all 12 audit analyses, logs complete verification details,
persists audit tables to DuckDB, and outputs full structured audit metrics.
"""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

from src.phase10.audit.anti_leakage_audit import AntiLeakageAuditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_phase10a4b_pipeline(
    db_path: str = "data/prediction_market.duckdb",
    output_json_path: str = "data/phase10a4b_audit_summary.json"
):
    """Executes the Phase 10A.4b audit pipeline."""
    logger.info("================================================================================")
    logger.info("PHASE 10A.4b ANTI-LEAKAGE & EVENT-UNIVERSE AUDIT")
    logger.info("================================================================================")

    auditor = AntiLeakageAuditor(db_path=db_path)
    audit_results = auditor.execute_complete_audit()

    # Persist audit tables to DuckDB
    conn = duckdb.connect(db_path)
    try:
        # 1. Audit records table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phase10a4b_provenance_records (
                event_id VARCHAR PRIMARY KEY,
                event_cluster_id VARCHAR,
                source VARCHAR,
                event_category VARCHAR,
                mapped_market_id VARCHAR,
                mapped_token_id VARCHAR,
                direction VARCHAR,
                is_real_token BOOLEAN,
                is_real_market BOOLEAN,
                has_raw_feed_provenance BOOLEAN,
                direction_knowability VARCHAR,
                timing_integrity VARCHAR,
                lookahead_detected BOOLEAN,
                data_source_type VARCHAR
            );
        """)

        events = auditor.dataset_loader.load_curated_events()
        prov_records = auditor.audit_event_provenance(events)
        
        rows = [
            (
                p.event_id, p.event_cluster_id, p.source, p.event_category,
                p.mapped_market_id, p.mapped_token_id, p.direction,
                bool(p.is_real_token), bool(p.is_real_market), bool(p.has_raw_feed_provenance),
                p.direction_knowability, p.timing_integrity, bool(p.lookahead_detected),
                p.data_source_type
            )
            for p in prov_records
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a4b_provenance_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        logger.info(f"Persisted {len(rows)} event provenance audit records to DuckDB.")

        # 2. Placebo summary table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phase10a4b_placebo_tests (
                test_name VARCHAR PRIMARY KEY,
                n_iterations INTEGER,
                mean_markout_bps DOUBLE,
                median_markout_bps DOUBLE,
                win_rate DOUBLE,
                p_value DOUBLE,
                ci_lower_95_bps DOUBLE,
                ci_upper_95_bps DOUBLE,
                empirical_separation VARCHAR
            );
        """)

        placebo_rows = [
            (
                v["test_name"], v["n_iterations"], v["mean_markout_bps"],
                v["median_markout_bps"], v["win_rate"], v["p_value"],
                v["ci_lower_95_bps"], v["ci_upper_95_bps"], v["empirical_separation"]
            )
            for v in audit_results["placebo_results"].values()
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO phase10a4b_placebo_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, placebo_rows)
        logger.info(f"Persisted {len(placebo_rows)} placebo test records to DuckDB.")

    finally:
        conn.close()

    # Save summary JSON
    out_path = Path(output_json_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2, default=str)
    logger.info(f"Saved Phase 10A.4b audit summary JSON to {output_json_path}")

    logger.info("================================================================================")
    logger.info("PHASE 10A.4b AUDIT COMPLETED")
    logger.info(f"Verdict: {audit_results['final_classification']['primary_classification']}")
    logger.info("================================================================================")

    print("\n" + "=" * 80)
    print("PHASE 10A.4b AUDIT SUMMARY")
    print("=" * 80)
    print(json.dumps(audit_results, indent=2, default=str))

    return audit_results


if __name__ == "__main__":
    run_phase10a4b_pipeline()
