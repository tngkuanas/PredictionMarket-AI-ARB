"""Unit tests for Phase 10A.3b Execution Cost and Data Integrity Audit."""
import pytest
from src.phase10.audit.execution_integrity_audit import ExecutionDataIntegrityAuditor


@pytest.fixture
def audit_engine():
    return ExecutionDataIntegrityAuditor(db_path="data/prediction_market.duckdb")


def test_audit_pipeline_execution(audit_engine):
    """Verifies that the audit pipeline runs end-to-end and returns complete results."""
    results = audit_engine.run_full_audit()
    
    assert results["total_events_audited"] == 35
    assert results["valid_1h_observations"] == 21
    
    # 1. Friction decomposition verification
    decomp = results["friction_decomposition"]
    assert decomp["double_counting_identified"] is True
    assert decomp["granular_breakdown_bps"]["exchange_fee_bps"] == 20.0
    assert abs(decomp["granular_breakdown_bps"]["total_cost_applied_in_10a_bps"] - 273.3) < 1.0

    # 2. Quantities separation
    quantities = results["quantities_comparison"]
    qa = quantities["quantity_a_info_response"]
    qb = quantities["quantity_b_obs_market_response"]
    assert abs(qa["mean_pct"] - 1.1643) < 0.01
    assert abs(qb["mean_pct"] - 0.0310) < 0.01

    # 3. FOMC subgroup audit
    fomc = results["fomc_subgroup_audit"]
    assert fomc["sample_size"] == 5
    assert "FATALLY COMPROMISED" in fomc["catalyst_independence"]
    assert abs(fomc["gross_stats"]["mean_pct"] - 2.15) < 0.01
    assert abs(fomc["net_160bps_stats"]["mean_pct"] - 0.55) < 0.01

    # 4. Break-even thresholds
    cost_grid = results["cost_sensitivity_grid"]
    assert abs(cost_grid["aggregate_break_even_non_spread_bps"] - 3.1) < 0.1
    assert abs(cost_grid["aggregate_break_even_all_in_bps"] - 116.4) < 1.0

    # 5. Venue and liquidity verification
    venues = results["venue_breakdown"]
    assert venues["polymarket"]["event_count"] == 21
    assert venues["kalshi"]["event_count"] == 0

    liq = results["liquidity_breakdown"]
    assert "HIGH_LIQUIDITY" in liq
    assert liq["HIGH_LIQUIDITY"]["count"] == 12
    assert liq["HIGH_LIQUIDITY"]["mean_obs_market_response_pct"] > 0
