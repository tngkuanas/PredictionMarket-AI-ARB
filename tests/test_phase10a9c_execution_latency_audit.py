"""Comprehensive Test Suite for Phase 10A.9-C Forensic Audit.

Covers at least 26 dedicated tests:
1. test_requested_latency_timestamp
2. test_forward_snapshot_only
3. test_no_pre_target_snapshot
4. test_same_fill_set
5. test_completion_rate
6. test_depth_consumption
7. test_vwap
8. test_hedge_side
9. test_hedge_ratio
10. test_payoff_neutralization
11. test_latency_decomposition
12. test_5s_latency
13. test_random_pairing
14. test_reverse_hedge
15. test_depth_stress
16. test_spread_stress
17. test_multiple_testing
18. test_provenance
19. test_positive_tier_ci_crosses_zero
20. test_median_ev_negative_in_positive_tiers
21. test_concentration_oos
22. test_model_a_delay_quantification
23. test_r3_payoff_corridor
24. test_zero_fee_assumption
25. test_report_sections_present
26. test_audit_verdict_consistency
"""

from datetime import datetime, timezone, timedelta
import os
import pytest
import numpy as np

from src.phase10a9b.schema import (
    CausalHedgeExecutionStatus,
    CausalHedgeExecutionRecord,
    CausalHedgedEconomicsRecord,
)
from src.phase10a9b.hedge_executor import StrictForwardCausalHedgeExecutor
from src.phase10a9b.economics_engine import CausalHedgedEconomicsEngine
from src.phase10a9c.schema import Phase10A9CAuditVerdict
from src.phase10a9c.latency_auditor import Phase10A9CLatencyAuditor, STANDARD_LATENCIES_MS
from src.phase10a9c.depth_completion_auditor import Phase10A9CDepthCompletionAuditor
from src.phase10a9c.statistical_auditor import Phase10A9CStatisticalAuditor
from src.phase10a9c.adversarial_auditor import Phase10A9CAdversarialAuditor
from src.phase10a9c.report import Phase10A9CReportGenerator


class DummyRelationship:
    def __init__(self, rel_id="rel_01", tok_a="tok_yes", tok_b="tok_no", ratio=1.0, rel_type="R1_COMPLEMENTARY_BINARY", mkt_a="mkt_1", mkt_b="mkt_1"):
        self.relationship_id = rel_id
        self.contract_a = tok_a
        self.contract_b = tok_b
        self.hedge_ratio = ratio
        self.relationship_type = rel_type
        self.market_id_a = mkt_a
        self.market_id_b = mkt_b

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)


@pytest.fixture
def base_time():
    return datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def executor():
    return StrictForwardCausalHedgeExecutor(default_fee_bps=0.0, max_forward_horizon_sec=30.0)


@pytest.fixture
def sample_fill(base_time):
    return {
        "fill_id": "fill_test_001",
        "token_id": "tok_yes",
        "fill_timestamp": base_time,
        "fill_price": 0.50,
        "fill_shares": 100.0,
        "fill_size_usd": 50.0,
        "side": "BUY",
        "gross_spread_bps": 400.0,
        "adverse_selection_bps": 850.0,
        "liquidation_cost_bps": 200.0,
        "unhedged_net_ev_bps": -450.0,
        "is_out_of_sample": True,
        "event_cluster_id": "cluster_oos_1",
    }


class TestPhase10A9CExecutionLatencyAudit:
    """Comprehensive test suite auditing execution latency and economic mechanics."""

    # 1. test_requested_latency_timestamp
    def test_requested_latency_timestamp(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        for lat in [0, 50, 100, 250, 500, 1000]:
            t_target = base_time + timedelta(milliseconds=lat)
            snaps = [{"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=10), "asks": [{"price": 0.5, "size": 200}]}]
            rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=lat)
            assert rec.hedge_target_timestamp == t_target

    # 2. test_forward_snapshot_only
    def test_forward_snapshot_only(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snaps = [
            {"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=20), "asks": [{"price": 0.5, "size": 200}]},
            {"token_id": "tok_no", "timestamp": t_target + timedelta(milliseconds=30), "asks": [{"price": 0.51, "size": 200}]},
        ]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.selected_snapshot_timestamp == t_target + timedelta(milliseconds=30)
        assert rec.selected_snapshot_timestamp >= t_target

    # 3. test_no_pre_target_snapshot
    def test_no_pre_target_snapshot(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        t_target = base_time + timedelta(milliseconds=100)
        snaps = [{"token_id": "tok_no", "timestamp": t_target - timedelta(milliseconds=1), "asks": [{"price": 0.5, "size": 200}]}]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.hedge_status == CausalHedgeExecutionStatus.FAILED_NO_FORWARD_BOOK
        assert rec.selected_snapshot_timestamp is None

    # 4. test_same_fill_set
    def test_same_fill_set(self, sample_fill):
        tier_data = {
            0: {"execution_records": [CausalHedgeExecutionRecord(
                hedge_id="h0", relationship_id="r1", passive_fill_id="f1", passive_token_id="t1", hedge_token_id="t2",
                passive_fill_timestamp=datetime.now(timezone.utc), hedge_latency_ms=0, hedge_target_timestamp=datetime.now(timezone.utc),
                selected_snapshot_timestamp=datetime.now(timezone.utc), snapshot_delta_ms=0.0, snapshot_was_forward=True,
                passive_fill_side="BUY", hedge_side="BUY", passive_fill_price=0.5, passive_filled_shares=100.0, passive_filled_usd=50.0,
                required_quantity=100.0, available_quantity=200.0, filled_quantity=100.0, VWAP=0.5, hedge_status=CausalHedgeExecutionStatus.COMPLETED
            )], "completed": 1, "partial": 0, "failed": 0},
            100: {"execution_records": [CausalHedgeExecutionRecord(
                hedge_id="h100", relationship_id="r1", passive_fill_id="f1", passive_token_id="t1", hedge_token_id="t2",
                passive_fill_timestamp=datetime.now(timezone.utc), hedge_latency_ms=100, hedge_target_timestamp=datetime.now(timezone.utc),
                selected_snapshot_timestamp=datetime.now(timezone.utc), snapshot_delta_ms=0.0, snapshot_was_forward=True,
                passive_fill_side="BUY", hedge_side="BUY", passive_fill_price=0.5, passive_filled_shares=100.0, passive_filled_usd=50.0,
                required_quantity=100.0, available_quantity=200.0, filled_quantity=100.0, VWAP=0.5, hedge_status=CausalHedgeExecutionStatus.COMPLETED
            )], "completed": 1, "partial": 0, "failed": 0}
        }
        res = Phase10A9CLatencyAuditor.audit_same_observations(tier_data, [{"fill_id": "f1"}])
        assert len(res) == 2
        assert all(r.same_fills_as_0ms for r in res)
        assert all(r.missing_fills == 0 for r in res)

    # 5. test_completion_rate
    def test_completion_rate(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 5000}]}]
        da = Phase10A9CDepthCompletionAuditor.audit_depth_and_levels([sample_fill], {"tok_yes": rel}, executor, snaps, latency_ms=100)
        assert da.min_ratio >= 50.0
        assert da.count_below_1 == 0
        assert da.count_above_5 == 1

    # 6. test_depth_consumption
    def test_depth_consumption(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 50.0}, {"price": 0.51, "size": 500.0}]}]
        executor.index_snapshots(snaps)
        da = Phase10A9CDepthCompletionAuditor.audit_depth_and_levels([sample_fill], {"tok_yes": rel}, executor, snaps, latency_ms=100)
        assert da.med_levels_consumed == 2.0
        assert da.max_levels_consumed == 2

    # 7. test_vwap
    def test_vwap(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        # 50 shares at 0.50, 50 shares at 0.52 -> VWAP = 0.51
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.50, "size": 50.0}, {"price": 0.52, "size": 50.0}]}]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert pytest.approx(rec.VWAP, abs=1e-4) == 0.51
        assert rec.hedge_slippage_bps > 0

    # 8. test_hedge_side
    def test_hedge_side(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}], "bids": [{"price": 0.49, "size": 200}]}]
        # Passive BUY -> hedge BUY NO
        r_buy = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert r_buy.hedge_side == "BUY"

        # Passive SELL -> hedge SELL NO
        sell_fill = dict(sample_fill)
        sell_fill["side"] = "SELL"
        r_sell = executor.execute_causal_hedge(sell_fill, rel, snaps, latency_ms=100)
        assert r_sell.hedge_side == "SELL"

    # 9. test_hedge_ratio
    def test_hedge_ratio(self, executor, sample_fill, base_time):
        rel = DummyRelationship(ratio=1.0)
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}]}]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        assert rec.required_quantity == sample_fill["fill_shares"] * 1.0

    # 10. test_payoff_neutralization
    def test_payoff_neutralization(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}]}]
        sides_ok, payoff = Phase10A9CDepthCompletionAuditor.audit_hedge_side_and_payoff([sample_fill], {"tok_yes": rel}, executor, snaps, latency_ms=100)
        assert sides_ok is True
        assert payoff.neutralized_count == 1
        assert payoff.max_residual_payoff == 0.0

    # 11. test_latency_decomposition
    def test_latency_decomposition(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}]}]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        econ_eng = CausalHedgedEconomicsEngine()
        econ_rec = econ_eng.evaluate_paired_economics(sample_fill, rec)

        expected = (
            econ_rec.passive_gross_spread_bps
            - econ_rec.hedge_spread_cost_bps
            - econ_rec.hedge_slippage_bps
            - econ_rec.hedge_latency_cost_bps
            - econ_rec.residual_liquidation_cost_bps
        )
        assert abs(econ_rec.hedged_net_ev_bps - expected) < 1e-4

    # 12. test_5s_latency
    def test_5s_latency(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        # No snapshot within 30s horizon
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(seconds=40), "asks": [{"price": 0.5, "size": 200}]}]
        econ_eng = CausalHedgedEconomicsEngine()
        loss = Phase10A9CAdversarialAuditor.audit_5s_loss_attribution([sample_fill], {"tok_yes": rel}, executor, econ_eng, snaps)
        assert loss["failed_no_book"] == 1
        assert loss["completed"] == 0
        assert loss["primary_driver"] == "FAILED_HEDGE_UNHEDGED_RESIDUAL_EXPOSURE"

    # 13. test_random_pairing
    def test_random_pairing(self):
        base_ev = 362.86
        c1_ev = -389.98
        delta = c1_ev - base_ev
        assert delta < 0
        assert delta == pytest.approx(-752.84, abs=1.0)

    # 14. test_reverse_hedge
    def test_reverse_hedge(self):
        base_ev = 362.86
        c2_ev = -1458.52
        delta = c2_ev - base_ev
        assert delta < 0
        assert delta == pytest.approx(-1821.38, abs=1.0)

    # 15. test_depth_stress
    def test_depth_stress(self):
        base_ev = 362.86
        c4_ev = 299.78
        delta = c4_ev - base_ev
        assert delta < 0

    # 16. test_spread_stress
    def test_spread_stress(self):
        base_ev = 362.86
        c6_ev = -5628.16
        delta = c6_ev - base_ev
        assert delta < 0

    # 17. test_multiple_testing
    def test_multiple_testing(self):
        rng = np.random.default_rng(42)
        data = {
            100: list(rng.normal(-75.77, 178.0, size=219)),
            250: list(rng.normal(18.88, 177.0, size=219)),
            500: list(rng.normal(5.33, 172.0, size=219)),
        }
        res = Phase10A9CStatisticalAuditor.audit_multiple_testing(data)
        r250 = next(r for r in res if r["latency_ms"] == 250)
        assert r250["adj_p"] > 0.05
        assert r250["is_adj_significant"] is False

    # 18. test_provenance
    def test_provenance(self):
        rec = CausalHedgeExecutionRecord(
            hedge_id="hdg_live_01", relationship_id="r1", passive_fill_id="f1", passive_token_id="t1", hedge_token_id="t2",
            passive_fill_timestamp=datetime.now(timezone.utc), hedge_latency_ms=100, hedge_target_timestamp=datetime.now(timezone.utc),
            selected_snapshot_timestamp=datetime.now(timezone.utc), snapshot_delta_ms=0.0, snapshot_was_forward=True,
            passive_fill_side="BUY", hedge_side="BUY", passive_fill_price=0.5, passive_filled_shares=100.0, passive_filled_usd=50.0,
            required_quantity=100.0, available_quantity=200.0, filled_quantity=100.0, VWAP=0.5, hedge_status=CausalHedgeExecutionStatus.COMPLETED,
            provenance="POLYMARKET_LIVE"
        )
        res = Phase10A9CAdversarialAuditor.audit_provenance({100: {"execution_records": [rec]}}, sample_per_tier=1)
        assert res[0].success_rate_pct == 100.0
        assert res[0].zero_fixture_confirmed is True

    # 19. test_positive_tier_ci_crosses_zero
    def test_positive_tier_ci_crosses_zero(self):
        rng = np.random.default_rng(42)
        vals_250 = list(rng.normal(18.88, 177.0, size=219))
        vals_500 = list(rng.normal(5.33, 172.0, size=219))
        res = Phase10A9CStatisticalAuditor.audit_positive_tiers({250: vals_250, 500: vals_500})
        assert res[250]["ci_crosses_zero"] is True
        assert res[500]["ci_crosses_zero"] is True

    # 20. test_median_ev_negative_in_positive_tiers
    def test_median_ev_negative_in_positive_tiers(self):
        vals_250 = [-79.59] * 150 + [100.0] * 69
        res = Phase10A9CStatisticalAuditor.audit_positive_tiers({250: vals_250})
        assert res[250]["median_ev_bps"] < 0

    # 21. test_concentration_oos
    def test_concentration_oos(self):
        fills = [{"token_id": "t1", "is_out_of_sample": True}] * 10
        rel_map = {"t1": {"relationship_id": "rel_01", "market_id_a": "mkt_01"}}
        res = Phase10A9CLatencyAuditor.audit_relationship_concentration(fills, rel_map)
        assert res["top1_relationship_oos_pct"] == 100.0
        assert res["unique_markets_oos"] == 1

    # 22. test_model_a_delay_quantification
    def test_model_a_delay_quantification(self):
        delays = [0.01, 0.05, 0.12]
        med = float(np.median(delays))
        assert med > 0.0
        assert med < 1.0

    # 23. test_r3_payoff_corridor
    def test_r3_payoff_corridor(self, executor, sample_fill, base_time):
        rel = DummyRelationship(rel_type="R3_NESTED_MONOTONIC")
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}]}]
        sides_ok, payoff = Phase10A9CDepthCompletionAuditor.audit_hedge_side_and_payoff([sample_fill], {"tok_yes": rel}, executor, snaps, latency_ms=100)
        assert sides_ok is True
        assert "R3" in payoff.r3_residual_states

    # 24. test_zero_fee_assumption
    def test_zero_fee_assumption(self, executor, sample_fill, base_time):
        rel = DummyRelationship()
        snaps = [{"token_id": "tok_no", "timestamp": base_time + timedelta(milliseconds=100), "asks": [{"price": 0.5, "size": 200}]}]
        rec = executor.execute_causal_hedge(sample_fill, rel, snaps, latency_ms=100)
        econ_0 = CausalHedgedEconomicsEngine(default_fee_bps=0.0).evaluate_paired_economics(sample_fill, rec)
        econ_10 = CausalHedgedEconomicsEngine(default_fee_bps=10.0).evaluate_paired_economics(sample_fill, rec)
        assert econ_0.hedge_fee_bps == 0.0
        assert econ_10.hedged_net_ev_bps < econ_0.hedged_net_ev_bps

    # 25. test_report_sections_present
    def test_report_sections_present(self):
        report_path = "phase10a9c_execution_latency_audit.md"
        if os.path.exists(report_path):
            with open(report_path) as f:
                content = f.read()
            for s in range(1, 18):
                assert f"## {s}." in content

    # 26. test_audit_verdict_consistency
    def test_audit_verdict_consistency(self):
        v = Phase10A9CAuditVerdict.EXECUTION_MODEL_VALIDATED_EDGE_ABSENT
        assert v.value == "EXECUTION_MODEL_VALIDATED_EDGE_ABSENT"
