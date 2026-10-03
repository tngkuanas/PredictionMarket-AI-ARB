"""Unit and Integration Tests for Phase 10A.6 Genuine High-Frequency Information-Response Study.

Verifies:
1. Mandatory Data-Span Check accurately computes exchange/receive spans and flags non-multi-day data.
2. Causal Gate Enforcement: Engine refuses to calculate event alpha when temporal span is insufficient.
3. Database isolation and schema creation for all 6 required Phase 10A.6 tables.
4. Audit trail preservation in phase10a6_data_quality and phase10a6_analysis_config.
5. Anti-synthetic zero-tolerance verification across all Phase 10A.5 and 10A.6 production tables.
6. Absolute anti-leakage invariants: zero synthetic price paths, zero fabricated events.
"""

from datetime import datetime, timezone
import pytest
import duckdb

from src.phase10.response_study.data_span_auditor import DataSpanAuditor, DataSpanCheckResult
from src.phase10.response_study.study_engine import GenuineResponseStudyEngine
from src.phase10.response_study.db_store import Phase10A6DbStore
from src.phase10.acquisition.anti_synthetic_guard import AntiSyntheticGuard


import os
import shutil
import tempfile

@pytest.fixture
def db_path():
    src_path = "data/prediction_market.duckdb"
    tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
    tmp_path = tmp.name
    tmp.close()
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    shutil.copyfile(src_path, tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


def test_mandatory_data_span_auditor(db_path):
    """Verifies that DataSpanAuditor inspects stored timestamps and detects the 15-minute span."""
    auditor = DataSpanAuditor(db_path=db_path)
    res = auditor.inspect_dataset_span()

    assert res.dataset_first_exchange_timestamp is not None
    assert res.dataset_last_exchange_timestamp is not None
    assert res.dataset_first_receive_timestamp is not None
    assert res.dataset_last_receive_timestamp is not None

    # Verify span is under 72 hours or spans multiple calendar days
    assert 60.0 < res.wall_clock_span_seconds
    assert 1 <= res.calendar_days_spanned <= 10

    assert res.is_multi_day is False
    assert res.gate_passed is False
    assert res.gate_verdict == "INSUFFICIENT_TEMPORAL_COVERAGE"
    assert "Per Section 0 critical rule: MUST NOT proceed with event study" in res.reason


def test_study_engine_causal_gate_enforcement(db_path):
    """Verifies that the engine halts calculation and marks study INCONCLUSIVE."""
    engine = GenuineResponseStudyEngine(db_path=db_path, git_commit="a7b61d6")
    summary = engine.run_study()

    assert summary["data_span_check"]["status"] == "FAILED"
    assert summary["decision_gate"]["classification"] == "B — INCONCLUSIVE"
    assert summary["decision_gate"]["execution_research_permitted"] is False
    assert summary["events_metrics"]["accepted_mappings"] == 0
    assert summary["primary_response"]["+100ms"].startswith("N/A")
    assert summary["anti_leakage_certification"]["status"] == "PASS"
    assert summary["anti_leakage_certification"]["data_span_fabrication_attempted"] == "NONE (Refused to simulate multi-day span)"


def test_phase10a6_db_tables_and_config(db_path):
    """Verifies that all 6 required output tables exist and contain valid audit records."""
    conn = duckdb.connect(db_path)
    try:
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        required_tables = [
            "phase10a6_event_study",
            "phase10a6_event_clusters",
            "phase10a6_contract_mappings",
            "phase10a6_placebos",
            "phase10a6_data_quality",
            "phase10a6_analysis_config",
        ]
        for tbl in required_tables:
            assert tbl in tables, f"Missing required table {tbl}"

        # Verify analysis config record
        config_rows = conn.execute("SELECT config_id, classification, execution_permitted, git_commit FROM phase10a6_analysis_config").fetchall()
        assert len(config_rows) >= 1
        assert config_rows[0][1] == "B"
        assert config_rows[0][2] is False
        assert config_rows[0][3] == "a7b61d6"

        # Verify data quality audit records
        dq_rows = conn.execute("SELECT check_name, status FROM phase10a6_data_quality WHERE check_name = 'MANDATORY_DATA_SPAN_CHECK'").fetchall()
        assert len(dq_rows) >= 1
        assert dq_rows[0][1] == "FAIL"

    finally:
        conn.close()


def test_anti_synthetic_guard_production_tables(db_path):
    """Verifies zero synthetic records in production database."""
    conn = duckdb.connect(db_path)
    try:
        scan = AntiSyntheticGuard.scan_production_tables(conn)
        assert scan["clean"] is True
        assert scan["violations"] == []
    finally:
        conn.close()
