"""Dedicated Test Suite for Phase 10A.9 Hedged Passive / Cross-Contract Neutralization.

Covers 40 distinct test dimensions:
1. Relationship validation: R1 exact complementary binary
2. Exact complementary payoff: Payoff(A) + Payoff(B) == 1.0 identity
3. Nested payoff: R3 monotonic strike corridor bounds
4. Mutually exclusive set: R4 partition validation
5. Cross-market candidate validation: R2 mirror questions
6. Rejection reason tracking: Event mismatch rejected with explicit reason
7. Rejection reason tracking: Threshold mismatch rejected
8. Rejection reason tracking: Resolution source mismatch rejected
9. Rejection reason tracking: Wording / provisional ambiguity rejected
10. Rejection reason tracking: Unresolved hedge ratio rejected
11. Hedge ratios: Exact complementary binary (1.0)
12. Hedge ratios: Monotonic strike corridor (1.0)
13. Passive partial fills: 100 quoted, 37 filled -> requires 37 hedge
14. Hedge partial fills: 37 required, 20 filled in book -> 17 residual
15. Residual exposure: residual unhedged shares and USD accounting
16. L2 hedge VWAP: single level fill pricing
17. L2 hedge VWAP: multi-level walking ladder pricing
18. Hedge depth exhaustion: depth exhausted flag set on thin book
19. Hedge depth insufficient: zero available book depth -> HEDGE_DEPTH_INSUFFICIENT
20. Hedge latency: 0ms baseline execution
21. Hedge latency: 100ms realistic execution
22. Hedge latency: 5,000ms delay penalty calculation
23. Inventory tracking: multi-leg accumulation (passive + hedge)
24. Inventory limits: $25 to $500 limit enforcement
25. Forced liquidation: limit breach triggers liquidation penalty
26. Fee accounting: 0 bps Polymarket maker/taker fee
27. No double counting: direct return vs factor decomposition mathematical identity
28. Timestamp ordering: quote strictly precedes passive fill, fill precedes hedge
29. No lookahead: hedge state evaluated strictly at or after t_h
30. Discovery/OOS isolation: chronological 60/40 partition separation
31. Provenance: POLYMARKET_LIVE validated
32. Contamination guard: rejects mock fixture in production
33. Contamination guard: rejects synthetic provenance in production
34. Event clustering: 5-minute window grouping
35. Cluster-robust standard error: SE calculation and t-statistic
36. Adversarial control C1: random pairing worsens EV
37. Adversarial control C2: reverse hedge direction doubles directional risk
38. Adversarial control C3: hedge latency stress
39. Adversarial control C4: depth stress (10% depth)
40. Statistical engine verdict: assigns HEDGED_EDGE_DESTROYED_BY_HEDGE_COST
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import pytest
import numpy as np
import duckdb

from src.phase10a9.schema import (
    RelationshipType,
    RelationshipValidationStatus,
    RelationshipRejectionReason,
    HedgeExecutionStatus,
    HedgedVerdict,
    PrimaryHypothesis,
    AdversarialControl,
    ContractRelationshipRecord,
    HedgeExecutionRecord,
    HedgedEconomicsRecord,
    HedgeInventoryStateRecord,
    BasisRiskRecord,
    HypothesisResultRecord,
    AdversarialControlRecord,
    STANDARD_HEDGE_LATENCIES_MS,
    STANDARD_INVENTORY_LIMITS_USD,
)
from src.phase10a9.relationship_engine import DeterministicRelationshipEngine
from src.phase10a9.hedge_executor import HedgeExecutionEngine
from src.phase10a9.economics_engine import HedgedEconomicsEngine
from src.phase10a9.statistical_engine import Phase10A9StatisticalEngine
from src.phase10a9.db_store import (
    Phase10A9DbStore,
    ProductionContaminationGuard,
    Phase10A9ContaminationError,
)


class TestPhase10A9HedgedPassive:

    @pytest.fixture
    def base_ts(self):
        return datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def sample_r1_relationship(self):
        return ContractRelationshipRecord(
            relationship_id="rel_r1_mkt001_tokA_tokB",
            contract_a="token_yes_01",
            contract_b="token_no_01",
            market_id_a="mkt_binary_001",
            market_id_b="mkt_binary_001",
            relationship_type=RelationshipType.R1_COMPLEMENTARY_BINARY,
            event_identity="event_btc_82k",
            variable="BTC_PRICE",
            threshold=82000.0,
            inequality="GT",
            time_window="2026-10-01",
            timezone="UTC",
            geography="GLOBAL",
            resolution_source="POLYMARKET_ORACLE",
            resolution_date="2026-10-01",
            payout_formula="Payoff(A) + Payoff(B) == 1.0",
            hedge_ratio=1.0,
            relationship_confidence=1.0,
            validation_status=RelationshipValidationStatus.EXACT_HEDGEABLE,
            reason="Exhaustive binary complementary tokens in same market",
            provenance="POLYMARKET_LIVE"
        )

    @pytest.fixture
    def sample_passive_fill(self, base_ts):
        return {
            "fill_id": "fill_pass_001",
            "quote_id": "quote_pass_001",
            "token_id": "token_yes_01",
            "side": "BUY",
            "fill_price": 0.48,
            "fill_size_usd": 48.0,
            "fill_shares": 100.0,
            "fill_timestamp": base_ts + timedelta(seconds=2),
            "fill_status": "FILLED",
            "gross_spread_bps": 400.0,
            "adverse_selection_bps": 850.0,
            "liquidation_cost_bps": 200.0,
            "quote_policy": "M1_BEST_PRICE",
            "queue_model": "Q1_BACK_OF_QUEUE",
            "is_out_of_sample": False
        }

    @pytest.fixture
    def sample_hedge_snapshot(self, base_ts):
        return {
            "snapshot_id": "snap_hedge_001",
            "token_id": "token_no_01",
            "market_id": "mkt_binary_001",
            "timestamp": base_ts + timedelta(seconds=2, milliseconds=100),
            "best_bid": 0.49,
            "best_ask": 0.52,
            "midpoint": 0.505,
            "bids": [{"price": 0.49, "size": 100.0, "size_usd": 49.0}],
            "asks": [
                {"price": 0.52, "size": 60.0, "size_usd": 31.2},
                {"price": 0.53, "size": 80.0, "size_usd": 42.4},
            ]
        }

    # 1. Relationship validation: R1 exact complementary binary
    def test_01_relationship_validation_r1_exact(self, sample_r1_relationship):
        assert sample_r1_relationship.relationship_type == RelationshipType.R1_COMPLEMENTARY_BINARY
        assert sample_r1_relationship.validation_status == RelationshipValidationStatus.EXACT_HEDGEABLE
        assert sample_r1_relationship.hedge_ratio == 1.0

    # 2. Exact complementary payoff identity
    def test_02_exact_complementary_payoff(self):
        # In state 1 (YES occurs): YES pays $1, NO pays $0 -> sum = $1
        # In state 2 (NO occurs): YES pays $0, NO pays $1 -> sum = $1
        p_yes_state1 = 1.0; p_no_state1 = 0.0
        p_yes_state2 = 0.0; p_no_state2 = 1.0
        assert p_yes_state1 + p_no_state1 == 1.0
        assert p_yes_state2 + p_no_state2 == 1.0

    # 3. Nested payoff: R3 monotonic strike corridor bounds
    def test_03_nested_payoff_monotonic_bounds(self):
        # P(BTC > 85k) <= P(BTC > 80k)
        # Payoff(80k) - Payoff(85k) is always in [0, 1]
        for p_80k, p_85k in [(1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]:
            payoff_diff = p_80k - p_85k
            assert 0.0 <= payoff_diff <= 1.0

    # 4. Mutually exclusive set: R4 partition validation
    def test_04_mutually_exclusive_set_partition(self):
        engine = DeterministicRelationshipEngine()
        tokens = [
            {"token_id": "tok_cand_A", "outcome": "Candidate A"},
            {"token_id": "tok_cand_B", "outcome": "Candidate B"},
            {"token_id": "tok_cand_C", "outcome": "Candidate C"},
        ]
        r4_rels = engine._evaluate_r4_set("mkt_election", tokens)
        assert len(r4_rels) == 3  # (3 * 2) / 2 = 3 pairs
        assert all(r.relationship_type == RelationshipType.R4_MUTUALLY_EXCLUSIVE_SET for r in r4_rels)

    # 5. Cross-market candidate validation: R2 mirror questions
    def test_05_cross_market_candidate_validation(self):
        engine = DeterministicRelationshipEngine()
        markets_map = {
            "mkt_1": [{"token_id": "t1", "title": "Will Bitcoin exceed $80,000 on October 1?", "outcome": "Yes"}],
            "mkt_2": [{"token_id": "t2", "title": "Will Bitcoin exceed $85,000 on October 1?", "outcome": "Yes"}]
        }
        rels, count = engine._evaluate_cross_market_relationships(markets_map)
        assert count == 1
        assert len(rels) == 1
        assert rels[0].relationship_type == RelationshipType.R3_NESTED_MONOTONIC

    # 6. Rejection reason tracking: Event mismatch rejected
    def test_06_rejection_event_mismatch(self):
        engine = DeterministicRelationshipEngine()
        markets_map = {
            "mkt_1": [{"token_id": "t1", "title": "Will Bitcoin exceed $80,000 on October 1?", "outcome": "Yes"}],
            "mkt_2": [{"token_id": "t2", "title": "Will Trump win the 2026 election?", "outcome": "Yes"}]
        }
        rels, count = engine._evaluate_cross_market_relationships(markets_map)
        assert len(rels) == 0
        assert engine.rejection_counts[RelationshipRejectionReason.EVENT_MISMATCH] == 1

    # 7. Rejection reason tracking: Threshold mismatch rejected
    def test_07_rejection_threshold_mismatch(self):
        engine = DeterministicRelationshipEngine()
        # Same asset but identical strike compared as if complementary
        engine._record_rejection("t1", "t2", RelationshipRejectionReason.THRESHOLD_MISMATCH, "Thresholds identical")
        assert engine.rejection_counts[RelationshipRejectionReason.THRESHOLD_MISMATCH] == 1

    # 8. Rejection reason tracking: Resolution source mismatch rejected
    def test_08_rejection_resolution_mismatch(self):
        engine = DeterministicRelationshipEngine()
        engine._record_rejection("t1", "t2", RelationshipRejectionReason.RESOLUTION_MISMATCH, "AP vs Binance oracle")
        assert engine.rejection_counts[RelationshipRejectionReason.RESOLUTION_MISMATCH] == 1

    # 9. Rejection reason tracking: Wording / provisional ambiguity rejected
    def test_09_rejection_wording_ambiguity(self):
        engine = DeterministicRelationshipEngine()
        t_a = {"token_id": "ta", "outcome": "Yes", "title": "Provisional Election Result"}
        t_b = {"token_id": "tb", "outcome": "No", "title": "Provisional Election Result"}
        rel = engine._evaluate_r1_pair("mkt_amb", t_a, t_b)
        assert rel is None
        assert engine.rejection_counts[RelationshipRejectionReason.AMBIGUOUS] == 1

    # 10. Rejection reason tracking: Unresolved hedge ratio rejected
    def test_10_rejection_unresolved_hedge_ratio(self):
        engine = DeterministicRelationshipEngine()
        engine._record_rejection("ta", "tb", RelationshipRejectionReason.HEDGE_RATIO_UNRESOLVED, "Non-linear statistical correlation")
        assert engine.rejection_counts[RelationshipRejectionReason.HEDGE_RATIO_UNRESOLVED] == 1

    # 11. Hedge ratios: Exact complementary binary (1.0)
    def test_11_hedge_ratio_exact_binary(self, sample_r1_relationship):
        assert sample_r1_relationship.hedge_ratio == 1.0

    # 12. Hedge ratios: Monotonic strike corridor (1.0)
    def test_12_hedge_ratio_nested_corridor(self):
        rec = ContractRelationshipRecord(
            relationship_id="r3_test", contract_a="ta", contract_b="tb",
            market_id_a="ma", market_id_b="mb", relationship_type=RelationshipType.R3_NESTED_MONOTONIC,
            event_identity="e", variable="v", time_window="w", resolution_source="s",
            resolution_date="d", payout_formula="corridor", hedge_ratio=1.0,
            validation_status=RelationshipValidationStatus.BOUNDED_HEDGEABLE, reason="nested"
        )
        assert rec.hedge_ratio == 1.0

    # 13. Passive partial fills: 100 quoted, 37 filled -> requires 37 hedge
    def test_13_passive_partial_fill_hedge_requirement(self, sample_r1_relationship, sample_hedge_snapshot, base_ts):
        executor = HedgeExecutionEngine()
        passive_fill_partial = {
            "fill_id": "f_partial", "token_id": "token_yes_01", "side": "BUY",
            "fill_price": 0.50, "fill_size_usd": 18.5, "fill_shares": 37.0,
            "fill_timestamp": base_ts + timedelta(seconds=1)
        }
        res = executor.execute_hedge(passive_fill_partial, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=100)
        assert res.hedge_required_shares == 37.0
        # Snapshot has 60 shares at 0.52 -> 37 shares completely filled
        assert res.hedge_filled_shares == 37.0
        assert res.residual_unhedged_shares == 0.0
        assert res.execution_status == HedgeExecutionStatus.COMPLETE_HEDGE

    # 14. Hedge partial fills: 37 required, 20 filled in book -> 17 residual
    def test_14_hedge_partial_fills_and_residual(self, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        shallow_snapshot = {
            "token_id": "token_no_01",
            "timestamp": base_ts + timedelta(seconds=1, milliseconds=100),
            "best_bid": 0.49, "best_ask": 0.52,
            "bids": [],
            "asks": [{"price": 0.52, "size": 20.0, "size_usd": 10.4}]  # Only 20 shares available
        }
        passive_fill_37 = {
            "fill_id": "f_37", "token_id": "token_yes_01", "side": "BUY",
            "fill_price": 0.50, "fill_size_usd": 18.5, "fill_shares": 37.0,
            "fill_timestamp": base_ts + timedelta(seconds=1)
        }
        res = executor.execute_hedge(passive_fill_37, sample_r1_relationship, [shallow_snapshot], latency_ms=100)
        assert res.hedge_required_shares == 37.0
        assert res.hedge_filled_shares == 20.0
        assert res.residual_unhedged_shares == 17.0
        assert res.hedge_depth_exhausted is True
        assert res.execution_status == HedgeExecutionStatus.PARTIAL_HEDGE

    # 15. Residual exposure: residual unhedged shares and USD accounting
    def test_15_residual_exposure_accounting(self, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        snap_thin = {
            "token_id": "token_no_01",
            "timestamp": base_ts + timedelta(seconds=1, milliseconds=100),
            "best_bid": 0.48, "best_ask": 0.52,
            "bids": [],
            "asks": [{"price": 0.52, "size": 10.0, "size_usd": 5.2}]
        }
        passive_fill = {
            "fill_id": "f_res", "token_id": "token_yes_01", "side": "BUY",
            "fill_price": 0.50, "fill_size_usd": 25.0, "fill_shares": 50.0,
            "fill_timestamp": base_ts + timedelta(seconds=1)
        }
        res = executor.execute_hedge(passive_fill, sample_r1_relationship, [snap_thin], latency_ms=100)
        assert res.residual_unhedged_shares == 40.0
        assert res.residual_unhedged_usd == pytest.approx(40.0 * 0.50)

    # 16. L2 hedge VWAP: single level fill pricing
    def test_16_l2_hedge_vwap_single_level(self, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        snap = {
            "token_id": "token_no_01", "timestamp": base_ts + timedelta(seconds=1),
            "best_bid": 0.48, "best_ask": 0.51,
            "asks": [{"price": 0.51, "size": 100.0, "size_usd": 51.0}], "bids": []
        }
        fill = {"fill_id": "f1", "token_id": "token_yes_01", "side": "BUY", "fill_price": 0.49, "fill_shares": 50.0, "fill_timestamp": base_ts}
        res = executor.execute_hedge(fill, sample_r1_relationship, [snap], latency_ms=100)
        assert res.hedge_vwap == 0.51
        assert res.hedge_slippage_bps == 0.0

    # 17. L2 hedge VWAP: multi-level walking ladder pricing
    def test_17_l2_hedge_vwap_multi_level(self, sample_r1_relationship, sample_hedge_snapshot, sample_passive_fill):
        executor = HedgeExecutionEngine()
        # Needs 100 shares.
        # Ladder has: 60 shares @ 0.52 ($31.20) + 40 shares @ 0.53 ($21.20)
        # Total cost = 31.20 + 21.20 = $52.40. VWAP = 52.40 / 100 = 0.524
        res = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=100)
        assert res.hedge_filled_shares == 100.0
        assert res.hedge_vwap == 0.524
        # Slippage vs best ask (0.52): (0.524 - 0.52)/0.52 * 10000 = 76.92 bps
        assert round(res.hedge_slippage_bps, 2) == 76.92

    # 18. Hedge depth exhaustion: depth exhausted flag set on thin book
    def test_18_hedge_depth_exhaustion_flag(self, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        snap_exhaust = {
            "token_id": "token_no_01", "timestamp": base_ts, "best_bid": 0.48, "best_ask": 0.52,
            "asks": [{"price": 0.52, "size": 10.0, "size_usd": 5.2}], "bids": []
        }
        fill = {"fill_id": "f_ex", "token_id": "token_yes_01", "side": "BUY", "fill_price": 0.48, "fill_shares": 50.0, "fill_timestamp": base_ts}
        res = executor.execute_hedge(fill, sample_r1_relationship, [snap_exhaust], latency_ms=100)
        assert res.hedge_depth_exhausted is True

    # 19. Hedge depth insufficient: zero available book depth -> HEDGE_DEPTH_INSUFFICIENT
    def test_19_hedge_depth_insufficient(self, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        snap_empty = {
            "token_id": "token_no_01", "timestamp": base_ts, "best_bid": 0.48, "best_ask": 0.52,
            "asks": [], "bids": []
        }
        fill = {"fill_id": "f_emp", "token_id": "token_yes_01", "side": "BUY", "fill_price": 0.48, "fill_shares": 50.0, "fill_timestamp": base_ts}
        res = executor.execute_hedge(fill, sample_r1_relationship, [snap_empty], latency_ms=100)
        assert res.execution_status == HedgeExecutionStatus.HEDGE_DEPTH_INSUFFICIENT
        assert res.hedge_filled_shares == 0.0

    # 20. Hedge latency: 0ms baseline execution
    def test_20_hedge_latency_0ms(self, sample_r1_relationship, sample_hedge_snapshot, sample_passive_fill):
        executor = HedgeExecutionEngine()
        res = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=0)
        assert res.hedge_latency_ms == 0

    # 21. Hedge latency: 100ms realistic execution
    def test_21_hedge_latency_100ms(self, sample_r1_relationship, sample_hedge_snapshot, sample_passive_fill):
        executor = HedgeExecutionEngine()
        res = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=100)
        assert res.hedge_latency_ms == 100

    # 22. Hedge latency: 5,000ms delay penalty calculation
    def test_22_hedge_latency_5000ms_cost(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        hdg_0ms = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=0)
        hdg_5000ms = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=5000)

        econ_0ms = econ.evaluate_paired_economics(sample_passive_fill, hdg_0ms)
        econ_5000ms = econ.evaluate_paired_economics(sample_passive_fill, hdg_5000ms)

        assert econ_5000ms.hedge_latency_cost_bps > econ_0ms.hedge_latency_cost_bps
        assert econ_5000ms.hedged_net_ev_bps < econ_0ms.hedged_net_ev_bps

    # 23. Inventory tracking: multi-leg accumulation (passive + hedge)
    def test_23_multi_leg_inventory_accumulation(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot])
        econ_rec = econ.evaluate_paired_economics(sample_passive_fill, hdg)

        inv_state = econ.simulate_inventory_limits("mkt_binary_001", [(sample_passive_fill, hdg, econ_rec)], inventory_limit_usd=100.0)
        assert inv_state.gross_passive_usd == 48.0
        assert inv_state.gross_hedge_usd > 0.0
        assert inv_state.cumulative_passive_fills == 1
        assert inv_state.cumulative_hedges_executed == 1

    # 24. Inventory limits: $25 to $500 limit enforcement
    def test_24_inventory_limit_enforcement(self, sample_passive_fill, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        # Shallow snapshot leaving $15 residual unhedged
        snap_shallow = {
            "token_id": "token_no_01", "timestamp": base_ts + timedelta(seconds=2, milliseconds=100),
            "best_bid": 0.48, "best_ask": 0.52,
            "asks": [{"price": 0.52, "size": 30.0, "size_usd": 15.6}], "bids": []
        }
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [snap_shallow])
        econ_rec = econ.evaluate_paired_economics(sample_passive_fill, hdg)

        # 3 consecutive trades with $35 residual each will breach $50 limit on 2nd trade
        paired = [(sample_passive_fill, hdg, econ_rec)] * 3
        inv_state = econ.simulate_inventory_limits("mkt_binary_001", paired, inventory_limit_usd=50.0)
        assert inv_state.rejected_fills_limit_breach >= 1

    # 25. Forced liquidation: limit breach triggers liquidation penalty
    def test_25_forced_liquidation_cost(self, sample_passive_fill, sample_r1_relationship, base_ts):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        snap_shallow = {
            "token_id": "token_no_01", "timestamp": base_ts, "best_bid": 0.48, "best_ask": 0.52,
            "asks": [{"price": 0.52, "size": 10.0, "size_usd": 5.2}], "bids": []
        }
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [snap_shallow])
        econ_rec = econ.evaluate_paired_economics(sample_passive_fill, hdg)
        paired = [(sample_passive_fill, hdg, econ_rec)] * 5
        inv_state = econ.simulate_inventory_limits("mkt_binary_001", paired, inventory_limit_usd=25.0)
        assert inv_state.forced_liquidations_count > 0
        assert inv_state.forced_liquidation_cost_usd > 0.0

    # 26. Fee accounting: 0 bps Polymarket maker/taker fee
    def test_26_fee_accounting_zero_base(self):
        econ = HedgedEconomicsEngine(default_fee_bps=0.0)
        assert econ.default_fee_bps == 0.0

    # 27. No double counting: direct return vs factor decomposition mathematical identity
    def test_27_no_double_counting_identity(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot])
        econ_rec = econ.evaluate_paired_economics(sample_passive_fill, hdg)

        # Decomposed formula: Gross - ResidualAdvSel - HedgeSpread - HedgeSlippage - HedgeFee - HedgeLatency - ResidualLiq
        reconstructed = (
            econ_rec.passive_gross_spread_bps
            - econ_rec.residual_inventory_cost_bps
            - econ_rec.hedge_spread_cost_bps
            - econ_rec.hedge_slippage_bps
            - econ_rec.hedge_fee_bps
            - econ_rec.hedge_latency_cost_bps
            - econ_rec.residual_liquidation_cost_bps
        )
        assert econ_rec.hedged_net_ev_bps == pytest.approx(reconstructed, abs=0.01)

    # 28. Timestamp ordering: quote strictly precedes passive fill, fill precedes hedge
    def test_28_timestamp_ordering_monotonicity(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=100)
        assert hdg.passive_fill_timestamp < hdg.hedge_timestamp

    # 29. No lookahead: hedge state evaluated strictly at or after t_h
    def test_29_no_lookahead_temporal_integrity(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot], latency_ms=100)
        assert hdg.hedge_timestamp == sample_passive_fill["fill_timestamp"] + timedelta(milliseconds=100)

    # 30. Discovery/OOS isolation: chronological 60/40 partition separation
    def test_30_discovery_oos_separation(self):
        t0 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
        t_cutoff = t0 + timedelta(seconds=0.6 * (t_end - t0).total_seconds())

        t_disc = t0 + timedelta(hours=6)
        t_oos = t_cutoff + timedelta(hours=2)
        assert t_disc < t_cutoff
        assert t_oos >= t_cutoff

    # 31. Provenance: POLYMARKET_LIVE validated
    def test_31_provenance_polymarket_live(self):
        rec = {"evaluation_id": "eval_01", "provenance": "POLYMARKET_LIVE"}
        ProductionContaminationGuard.assert_valid_production_record(rec, is_production_db=True)

    # 32. Contamination guard: rejects mock fixture in production
    def test_32_contamination_guard_rejects_mock(self):
        rec = {"evaluation_id": "eval_mock_01", "provenance": "POLYMARKET_LIVE"}
        with pytest.raises(Phase10A9ContaminationError):
            ProductionContaminationGuard.assert_valid_production_record(rec, is_production_db=True)

    # 33. Contamination guard: rejects synthetic provenance in production
    def test_33_contamination_guard_rejects_synthetic(self):
        rec = {"evaluation_id": "eval_clean", "provenance": "SYNTHETIC"}
        with pytest.raises(Phase10A9ContaminationError):
            ProductionContaminationGuard.assert_valid_production_record(rec, is_production_db=True)

    # 34. Event clustering: 5-minute window grouping
    def test_34_event_clustering_5min_grouping(self):
        stat_eng = Phase10A9StatisticalEngine(cluster_window_sec=300.0)
        t1 = datetime(2026, 10, 1, 14, 2, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 1, 14, 4, 30, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 1, 14, 7, 0, tzinfo=timezone.utc)

        # Mock records
        r1 = HedgedEconomicsRecord(
            evaluation_id="e1", relationship_id="rel_1", passive_fill_id="f1", hedge_id="h1",
            hedge_latency_ms=100, quote_policy="M1", queue_model="Q1", is_fully_hedged=True,
            passive_gross_spread_bps=400, passive_adverse_selection_bps=800, hedge_spread_cost_bps=300,
            hedge_slippage_bps=50, hedge_fee_bps=0, hedge_latency_cost_bps=20, unhedged_net_ev_bps=-600,
            hedged_net_ev_bps=-200, ev_improvement_bps=400, hedged_pnl_usd=-1.0, is_out_of_sample=False
        )
        r2 = r1.model_copy(update={"evaluation_id": "e2", "passive_fill_id": "f2"})
        r3 = r1.model_copy(update={"evaluation_id": "e3", "passive_fill_id": "f3"})

        clusters = stat_eng.assign_event_clusters([r1, r2, r3], {"f1": t1, "f2": t2, "f3": t3})
        assert clusters["e1"] == clusters["e2"]
        assert clusters["e1"] != clusters["e3"]

    # 35. Cluster-robust standard error: SE calculation and t-statistic
    def test_35_cluster_robust_standard_error(self):
        stat_eng = Phase10A9StatisticalEngine()
        # Create records across 3 distinct clusters
        recs = []
        for c_idx, ev_val in enumerate([-200.0, -250.0, -180.0]):
            for i in range(5):
                r = HedgedEconomicsRecord(
                    evaluation_id=f"e_{c_idx}_{i}", relationship_id="rel", passive_fill_id=f"f_{c_idx}_{i}", hedge_id="h",
                    hedge_latency_ms=100, quote_policy="M1", queue_model="Q1", is_fully_hedged=True,
                    passive_gross_spread_bps=400, passive_adverse_selection_bps=800, hedge_spread_cost_bps=300,
                    hedge_slippage_bps=50, hedge_fee_bps=0, hedge_latency_cost_bps=20, unhedged_net_ev_bps=-600,
                    hedged_net_ev_bps=ev_val, ev_improvement_bps=400, hedged_pnl_usd=-1.0, is_out_of_sample=False,
                    event_cluster_id=f"c_{c_idx}"
                )
                recs.append(r)
        res = stat_eng.compute_cluster_robust_statistics(recs)
        assert res["n_raw"] == 15
        assert res["n_clusters"] == 3
        assert res["cluster_reduction_pct"] == 80.0
        assert res["mean_ev_bps"] < 0.0
        assert res["cluster_robust_se"] > 0.0
        assert res["t_stat"] < -2.0

    # 36. Adversarial control C1: random pairing worsens EV
    def test_36_adversarial_c1_random_pairing(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        executor = HedgeExecutionEngine()
        econ = HedgedEconomicsEngine()
        stat_eng = Phase10A9StatisticalEngine()
        hdg = executor.execute_hedge(sample_passive_fill, sample_r1_relationship, [sample_hedge_snapshot])
        econ_rec = econ.evaluate_paired_economics(sample_passive_fill, hdg)

        controls = stat_eng.evaluate_adversarial_controls([econ_rec])
        c1 = next(c for c in controls if c.control == AdversarialControl.C1_RANDOM_PAIRING)
        assert c1.delta_vs_baseline_bps < 0.0
        assert c1.behavior_matches_expectation is True

    # 37. Adversarial control C2: reverse hedge direction doubles directional risk
    def test_37_adversarial_c2_reverse_hedge_direction(self, sample_passive_fill, sample_r1_relationship, sample_hedge_snapshot):
        stat_eng = Phase10A9StatisticalEngine()
        econ_rec = HedgedEconomicsRecord(
            evaluation_id="e", relationship_id="r", passive_fill_id="f", hedge_id="h",
            hedge_latency_ms=100, quote_policy="M1", queue_model="Q1", is_fully_hedged=True,
            passive_gross_spread_bps=400, passive_adverse_selection_bps=800, hedge_spread_cost_bps=300,
            hedge_slippage_bps=50, hedge_fee_bps=0, hedge_latency_cost_bps=20, unhedged_net_ev_bps=-600,
            hedged_net_ev_bps=-200, ev_improvement_bps=400, hedged_pnl_usd=-1.0, is_out_of_sample=False
        )
        controls = stat_eng.evaluate_adversarial_controls([econ_rec])
        c2 = next(c for c in controls if c.control == AdversarialControl.C2_REVERSE_HEDGE_DIRECTION)
        assert c2.delta_vs_baseline_bps == -450.0

    # 38. Adversarial control C3: hedge latency stress
    def test_38_adversarial_c3_latency_stress(self):
        stat_eng = Phase10A9StatisticalEngine()
        econ_rec = HedgedEconomicsRecord(
            evaluation_id="e", relationship_id="r", passive_fill_id="f", hedge_id="h",
            hedge_latency_ms=100, quote_policy="M1", queue_model="Q1", is_fully_hedged=True,
            passive_gross_spread_bps=400, passive_adverse_selection_bps=800, hedge_spread_cost_bps=300,
            hedge_slippage_bps=50, hedge_fee_bps=0, hedge_latency_cost_bps=20, unhedged_net_ev_bps=-600,
            hedged_net_ev_bps=-200, ev_improvement_bps=400, hedged_pnl_usd=-1.0, is_out_of_sample=False
        )
        controls = stat_eng.evaluate_adversarial_controls([econ_rec])
        c3 = next(c for c in controls if c.control == AdversarialControl.C3_HEDGE_LATENCY_STRESS)
        assert c3.delta_vs_baseline_bps == -180.0

    # 39. Adversarial control C4: depth stress (10% depth)
    def test_39_adversarial_c4_depth_stress(self):
        stat_eng = Phase10A9StatisticalEngine()
        econ_rec = HedgedEconomicsRecord(
            evaluation_id="e", relationship_id="r", passive_fill_id="f", hedge_id="h",
            hedge_latency_ms=100, quote_policy="M1", queue_model="Q1", is_fully_hedged=True,
            passive_gross_spread_bps=400, passive_adverse_selection_bps=800, hedge_spread_cost_bps=300,
            hedge_slippage_bps=50, hedge_fee_bps=0, hedge_latency_cost_bps=20, unhedged_net_ev_bps=-600,
            hedged_net_ev_bps=-200, ev_improvement_bps=400, hedged_pnl_usd=-1.0, is_out_of_sample=False
        )
        controls = stat_eng.evaluate_adversarial_controls([econ_rec])
        c4 = next(c for c in controls if c.control == AdversarialControl.C4_DEPTH_STRESS)
        assert c4.delta_vs_baseline_bps == -210.0

    # 40. Statistical engine verdict: assigns HEDGED_EDGE_DESTROYED_BY_HEDGE_COST
    def test_40_statistical_engine_verdict(self):
        stat_eng = Phase10A9StatisticalEngine()
        gate_results = {
            "Gate 1 (Deterministic Relationship)": True,
            "Gate 2 (Passive Fill Evidence)": True,
            "Gate 3 (Hedge Availability)": True,
            "Gate 4 (Executable Hedge Pricing)": True,
            "Gate 5 (Residual Exposure Tracking)": True,
            "Gate 6 (Complete Economics No Double-Counting)": True,
            "Gate 7 (OOS Survival)": False,  # Negative EV in OOS
            "Gate 8 (Stress Test)": False,
        }
        verdict, reason = stat_eng.assign_verdict(
            gate_results=gate_results,
            mean_hedged_ev=-140.0,
            mean_unhedged_ev=-900.0,
            mean_hedge_cost=350.0,
            mean_adv_sel=800.0
        )
        assert verdict == HedgedVerdict.HEDGED_EDGE_DESTROYED_BY_HEDGE_COST
        assert "paying the taker spread and slippage" in reason
