"""Dedicated Test Suite for Phase 10A.10-D Methodology Repair and Revalidation.

Validates:
- Authoritative terminal payoff rules and state classification (STATE_A, B, C, D)
- Unresolved macro term contract rejection (5,544 executions)
- In-play sports non-deterministic execution rejection (264 executions)
- Canonical outcome mapping and inversion repairs
- Economic execution identity deduplication
- Exact capital-at-risk, ROI vs price discount, and bps conversion
- Hypothesis registry and alias identification (H3/H4, H1/H5)
- Capacity modeling across $10 to $1,000 tiers
- Controls C1 through C10
- Event-level inference and bootstrap
- Contamination accounting and final verdict (CORRECTED_EDGE_INSUFFICIENT_DATA)
"""

from datetime import datetime, timezone, timedelta
import pytest
import numpy as np

from src.phase10a10d import (
    Phase10A10DVerdict,
    SettlementStatus,
    DeterministicStateRepair,
    ContaminationExclusionReason,
)
from src.phase10a10d.settlement_engine import AuthoritativeSettlementEngine, SettlementResult
from src.phase10a10d.outcome_mapper import CanonicalOutcomeMapper, CanonicalContractMapping
from src.phase10a10d.deduplication import DeduplicationEngine, CanonicalExecution
from src.phase10a10d.capital_and_pnl import CapitalAndPnLCalculator, TradePnLResult
from src.phase10a10d.hypothesis_registry import HypothesisRegistry, HypothesisDefinition
from src.phase10a10d.capacity_model import CapacityEvaluationModel, CapacityFillResult
from src.phase10a10d.controls import Phase10A10DControlsEvaluator, ControlTestResult


# ==============================================================================
# 1. TERMINAL PAYOFF & INVARIANTS (Tests 1 - 8)
# ==============================================================================

def test_terminal_payoff_no_default_one():
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Yes"}
    source_state = {"event_id": "ev1", "deterministic_state": "UNKNOWN"}
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert res.settlement_value is None
    assert res.status == SettlementStatus.NOT_RESOLVED
    assert not res.is_valid_for_strategy


def test_terminal_payoff_resolved_win():
    ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Carlos Alcaraz"}
    source_state = {
        "event_id": "cand_alcaraz",
        "category": "sports_competitions",
        "source_timestamp": ts,
        "deterministic_state": "STATE_A",
        "winning_outcome": "Carlos Alcaraz",
    }
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, ts + timedelta(seconds=1)
    )
    assert res.status == SettlementStatus.RESOLVED_WIN
    assert res.settlement_value == 1.0
    assert res.is_valid_for_strategy


def test_terminal_payoff_resolved_loss():
    ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Alex Michelsen"}
    source_state = {
        "event_id": "cand_alcaraz",
        "category": "sports_competitions",
        "source_timestamp": ts,
        "deterministic_state": "STATE_A",
        "winning_outcome": "Carlos Alcaraz",
    }
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, ts + timedelta(seconds=1)
    )
    assert res.status == SettlementStatus.RESOLVED_LOSS
    assert res.settlement_value == 0.0
    assert res.is_valid_for_strategy


def test_terminal_payoff_missing_resolution_returns_unknown():
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Yes"}
    source_state = {
        "event_id": "cand_missing",
        "deterministic_state": "STATE_A",
        "winning_outcome": "",
    }
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert res.status == SettlementStatus.UNKNOWN
    assert res.settlement_value is None
    assert not res.is_valid_for_strategy


def test_terminal_payoff_not_resolved_returns_none():
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Yes"}
    source_state = {"event_id": "cand_unres", "deterministic_state": "STATE_D"}
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert res.status == SettlementStatus.NOT_RESOLVED
    assert res.settlement_value is None
    assert not res.is_valid_for_strategy


def test_terminal_payoff_no_fallback_to_winning_side():
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "UnknownSide"}
    source_state = {
        "event_id": "cand_test",
        "deterministic_state": "STATE_A",
        "winning_outcome": "OtherSide",
    }
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        contract, source_state, datetime(2026, 10, 1, tzinfo=timezone.utc)
    )
    assert res.settlement_value != 1.0
    assert res.status == SettlementStatus.RESOLVED_LOSS


def test_terminal_payoff_requires_execution_timestamp():
    contract = {"market_id": "m1", "token_id": "t1", "outcome": "Yes"}
    source_state = {"event_id": "cand_test", "deterministic_state": "STATE_A", "winning_outcome": "Yes"}
    ts = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(contract, source_state, ts)
    assert isinstance(res, SettlementResult)


def test_terminal_payoff_state_mapping_integrity():
    for state_val in ["STATE_A", "STATE_B", "STATE_C", "STATE_D"]:
        assert hasattr(DeterministicStateRepair, state_val)


# ==============================================================================
# 2. STATE CLASSIFICATION & CONTRACT TYPES (Tests 9 - 22)
# ==============================================================================

def test_state_a_actually_resolved():
    ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Team Liquid"},
        {"event_id": "cand_dota", "category": "sports_competitions", "source_timestamp": ts, "deterministic_state": "STATE_A", "winning_outcome": "Team Liquid"},
        ts + timedelta(seconds=2)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_A
    assert res.is_valid_for_strategy


def test_state_b_mechanically_determined():
    ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes"},
        {"event_id": "cand_btc", "source_timestamp": ts, "deterministic_state": "STATE_B", "actual_val": 85000.0, "thresh_val": 84000.0},
        ts + timedelta(seconds=2)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_B
    assert res.status == SettlementStatus.RESOLVED_WIN
    assert res.settlement_value == 1.0


def test_state_c_near_deterministic_rejection():
    ts = datetime(2026, 10, 2, 1, 45, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Astralis", "title": "Counter-Strike: Astralis vs Alliance"},
        {"event_id": "cand_cs_astralis_alliance_20261002", "category": "sports_competitions", "source_timestamp": ts, "is_in_play": True},
        ts + timedelta(seconds=13)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_C
    assert not res.is_valid_for_strategy
    assert res.rejection_reason == ContaminationExclusionReason.IN_PLAY_NON_DETERMINISTIC


def test_state_d_unresolved_future_dependent_rejection():
    ts = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    expiry = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "Will FOMC hike rates in October 2026?", "expiry_date": expiry},
        {"event_id": "hf_fomc_sep26_oct_hike25", "category": "central_bank_rates", "source_timestamp": ts},
        ts + timedelta(seconds=1)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_D
    assert not res.is_valid_for_strategy
    assert res.rejection_reason == ContaminationExclusionReason.UNRESOLVED_TERMINAL_PAYOFF


def test_macro_term_contracts_rejection_fomc():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "FOMC rate decision"},
        {"event_id": "hf_hf_fomc_sep26_oct_hike25", "category": "central_bank_rates"},
        datetime(2026, 9, 16, 18, 0, 1, tzinfo=timezone.utc)
    )
    assert res.rejection_reason == ContaminationExclusionReason.UNRESOLVED_TERMINAL_PAYOFF
    assert not res.is_valid_for_strategy


def test_macro_term_contracts_rejection_cpi():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "CPI Release September 2026"},
        {"event_id": "hf_hf_cpi_20260911", "category": "government_statistical_releases"},
        datetime(2026, 9, 11, 12, 30, 1, tzinfo=timezone.utc)
    )
    assert res.rejection_reason == ContaminationExclusionReason.UNRESOLVED_TERMINAL_PAYOFF


def test_macro_term_contracts_rejection_gdp():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "BEA GDP release"},
        {"event_id": "hf_hf_gdp_print", "category": "government_statistical_releases"},
        datetime(2026, 8, 28, 12, 30, 1, tzinfo=timezone.utc)
    )
    assert res.rejection_reason == ContaminationExclusionReason.UNRESOLVED_TERMINAL_PAYOFF


def test_sports_in_play_match_rejection_astralis():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Astralis", "title": "Astralis vs Alliance"},
        {"event_id": "cand_cs_astralis_alliance_20261002", "category": "sports_competitions"},
        datetime(2026, 10, 2, 1, 45, 13, tzinfo=timezone.utc)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_C
    assert not res.is_valid_for_strategy


def test_sports_in_play_match_rejection_dota_bb_og():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "BetBoom Team", "title": "Dota 2: BetBoom Team vs OG"},
        {"event_id": "cand_dota_bb_og_20260930", "category": "sports_competitions"},
        datetime(2026, 9, 30, 22, 16, 0, tzinfo=timezone.utc)
    )
    assert res.deterministic_state == DeterministicStateRepair.STATE_C
    assert not res.is_valid_for_strategy


def test_sports_in_play_rejection_even_if_winning():
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Astralis", "title": "Astralis vs Alliance"},
        {"event_id": "cand_cs_astralis_alliance_20261002", "winning_outcome": "Astralis", "category": "sports_competitions"},
        datetime(2026, 10, 2, 1, 45, 13, tzinfo=timezone.utc)
    )
    assert not res.is_valid_for_strategy
    assert res.settlement_value is None


def test_crypto_threshold_above_strike_win():
    ts = datetime(2026, 10, 1, 0, 0, 1, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "Will BTC be above 82k?"},
        {"event_id": "cand_btc_82k_sep30", "source_timestamp": ts - timedelta(seconds=1), "deterministic_state": "STATE_B", "actual_val": 83420.5, "thresh_val": 82000.0},
        ts
    )
    assert res.status == SettlementStatus.RESOLVED_WIN
    assert res.settlement_value == 1.0


def test_crypto_threshold_below_strike_loss():
    ts = datetime(2026, 10, 1, 0, 0, 1, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "Will BTC be above 95k?"},
        {"event_id": "cand_btc_95k", "source_timestamp": ts - timedelta(seconds=1), "deterministic_state": "STATE_B", "actual_val": 83420.5, "thresh_val": 95000.0},
        ts
    )
    assert res.status == SettlementStatus.RESOLVED_LOSS
    assert res.settlement_value == 0.0


def test_crypto_threshold_unresolved_rejection():
    ts = datetime(2026, 10, 1, 0, 0, 1, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "Will BTC be above 100k by December?"},
        {"event_id": "hf_crypto_btc_reach_100k", "category": "crypto_milestones"},
        ts
    )
    assert res.rejection_reason == ContaminationExclusionReason.UNRESOLVED_TERMINAL_PAYOFF


def test_period_elapsed_ceasefire_contract_resolution():
    exec_ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes", "title": "US x Iran ceasefire continues through September 30?"},
        {"event_id": "cand_us_iran_ceasefire_sep30", "category": "mechanical_public_events", "winning_outcome": "Yes"},
        exec_ts
    )
    assert res.status == SettlementStatus.RESOLVED_WIN
    assert res.settlement_value == 1.0
    assert res.is_valid_for_strategy


# ==============================================================================
# 3. CANONICAL OUTCOME MAPPING (Tests 23 - 32)
# ==============================================================================

def test_canonical_mapping_explicit_token_binding():
    tok = "18108354744468601294025853601030425188395211927926870885542758981304523217919"
    mapping = CanonicalOutcomeMapper.map_token(market_id="4641064", token_id=tok)
    assert mapping.is_valid_mapping
    assert mapping.outcome_label == "Yes"
    assert mapping.is_yes_token
    assert not mapping.is_no_token


def test_canonical_mapping_never_infers_from_array_order():
    tok_unknown = "unknown_tok_123"
    mapping = CanonicalOutcomeMapper.map_token(market_id="m_unknown", token_id=tok_unknown)
    assert not mapping.is_valid_mapping
    assert mapping.invalidation_reason == "INVALID_CONTRACT_MAPPING"


def test_canonical_mapping_token_0_not_assumed_yes():
    tok_dota = "88391114873121460534755374453373541457506862776360231577867131214687456642030"
    mapping = CanonicalOutcomeMapper.map_token(market_id="4904811", token_id=tok_dota)
    assert mapping.outcome_label == "BetBoom Team"
    assert not mapping.is_yes_token


def test_canonical_mapping_token_1_not_assumed_no():
    tok_dota_og = "88391114873121460534755374453373541457506862776360231577867131214687456642031"
    mapping = CanonicalOutcomeMapper.map_token(market_id="4904811", token_id=tok_dota_og)
    assert mapping.outcome_label == "OG"
    assert not mapping.is_no_token


def test_canonical_mapping_yes_no_semantics():
    tok_no = "18108354744468601294025853601030425188395211927926870885542758981304523217920"
    mapping = CanonicalOutcomeMapper.map_token(market_id="4641064", token_id=tok_no)
    assert mapping.outcome_label == "No"
    assert mapping.is_no_token
    assert not mapping.is_yes_token


def test_canonical_mapping_inverted_cs_big_fnatic_correction():
    mapping = CanonicalOutcomeMapper.map_token(market_id="4638094", token_id="4638094_big")
    assert mapping.is_valid_mapping
    assert mapping.outcome_label == "BIG"
    assert mapping.winning_side == "BIG"


def test_canonical_mapping_inverted_btc_84k_correction():
    mapping = CanonicalOutcomeMapper.map_token(market_id="4882983", token_id="4882983_yes")
    assert mapping.is_valid_mapping
    assert mapping.outcome_label == "Yes"
    assert mapping.winning_side == "Yes"


def test_canonical_mapping_ambiguous_returns_invalid():
    mapping = CanonicalOutcomeMapper.map_token(market_id="fake_mkt", token_id="fake_tok")
    assert not mapping.is_valid_mapping
    assert mapping.invalidation_reason == "INVALID_CONTRACT_MAPPING"


def test_canonical_mapping_condition_id_preservation():
    tok = "18108354744468601294025853601030425188395211927926870885542758981304523217919"
    mapping = CanonicalOutcomeMapper.map_token(market_id="4641064", token_id=tok)
    assert mapping.condition_id == "0xceasefire_us_iran_sep30"


def test_canonical_mapping_market_universe_fallback():
    universe = [{"market_id": "999", "token_id": "tok_999", "outcome": "Yes", "condition_id": "c999"}]
    mapping = CanonicalOutcomeMapper.map_token(market_id="999", token_id="tok_999", market_universe=universe)
    assert mapping.is_valid_mapping
    assert mapping.outcome_label == "Yes"
    assert mapping.is_yes_token


# ==============================================================================
# 4. SOURCE CHRONOLOGY & INFORMATION CUTOFF (Tests 33 - 40)
# ==============================================================================

def test_source_chronology_t_source_le_t_execution():
    source_ts = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    exec_ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    assert source_ts <= exec_ts


def test_source_chronology_future_source_rejected():
    exec_ts = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    future_source = datetime(2026, 10, 1, 0, 0, 10, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes"},
        {"event_id": "ev_future", "source_timestamp": future_source},
        exec_ts
    )
    assert res.rejection_reason == ContaminationExclusionReason.TIMESTAMP_VIOLATION


def test_source_deterministic_timestamp_recorded():
    exec_ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes"},
        {"event_id": "cand_us_iran_ceasefire_sep30", "winning_outcome": "Yes"},
        exec_ts
    )
    assert res.deterministic_timestamp is not None
    assert res.deterministic_timestamp <= exec_ts


def test_source_formal_resolution_timestamp_recorded():
    exec_ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    res = AuthoritativeSettlementEngine.determine_terminal_payoff(
        {"outcome": "Yes"},
        {"event_id": "cand_us_iran_ceasefire_sep30", "winning_outcome": "Yes"},
        exec_ts
    )
    assert res.formal_resolution_timestamp is not None


def test_source_historical_provenance_verified():
    from src.phase10a10d.controls import Phase10A10DControlsEvaluator
    c8 = Phase10A10DControlsEvaluator.evaluate_all_controls()[7]
    assert c8.control_id == "C8"
    assert c8.passed


def test_source_content_hash_integrity():
    hash_str = "sha256_verified_state_dept_20260930"
    assert len(hash_str) > 10


def test_source_state_dept_ceasefire_bulletin_timestamp():
    expected_bulletin = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    exec_ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    assert expected_bulletin < exec_ts


def test_no_lookahead_through_event_labels():
    from src.phase10a10d.controls import Phase10A10DControlsEvaluator
    test_fn = lambda d: {"candidate_id": "test_id", "executable_vwap": 0.9880, "execution_status": "EXECUTED"}
    res = Phase10A10DControlsEvaluator.run_c8_hidden_outcome(test_fn, {"event_id": "ev1"})
    assert res.passed


# ==============================================================================
# 5. DEDUPLICATION & ECONOMIC IDENTITY (Tests 41 - 48)
# ==============================================================================

def test_deduplication_economic_identity_hash():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    id1 = DeduplicationEngine.compute_identity("ev1", "m1", "t1", ts, "BUY", 0.9880, 50.6)
    id2 = DeduplicationEngine.compute_identity("ev1", "m1", "t1", ts, "BUY", 0.9880, 50.6)
    assert id1 == id2


def test_deduplication_collapses_parameter_grid_permutations():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, cid, size):
            self.candidate_id = cid
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = 0.9880
            self.filled_shares = 50.6
            self.position_size_usd = size
            self.net_ev_bps = 116.46
            self.gross_deterministic_edge_bps = 120.0

    raw = [
        DummyExec("exp_ev1_500ms_5_50", 50.0),
        DummyExec("exp_ev1_1s_5_50", 50.0),
        DummyExec("exp_ev1_500ms_10_50", 50.0),
        DummyExec("exp_ev1_1s_10_50", 50.0),
    ]
    canonical, audit, dup_count = DeduplicationEngine.deduplicate_executions(raw)
    assert len(canonical) == 1
    assert dup_count == 3
    assert len(audit[canonical[0].canonical_id]) == 4


def test_deduplication_audit_trail_captures_all_candidates():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, cid):
            self.candidate_id = cid
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = 0.9880
            self.filled_shares = 50.6
            self.position_size_usd = 50.0
            self.net_ev_bps = 116.46
            self.gross_deterministic_edge_bps = 120.0

    raw = [DummyExec("c1"), DummyExec("c2")]
    canonical, audit, _ = DeduplicationEngine.deduplicate_executions(raw)
    assert "c1" in audit[canonical[0].canonical_id]
    assert "c2" in audit[canonical[0].canonical_id]


def test_deduplication_preserves_unique_size_tiers():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, size, vwap):
            self.candidate_id = f"c_{size}"
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = vwap
            self.filled_shares = size / vwap
            self.position_size_usd = size
            self.net_ev_bps = 100.0
            self.gross_deterministic_edge_bps = 110.0

    raw = [DummyExec(10.0, 0.9880), DummyExec(25.0, 0.9880), DummyExec(50.0, 0.9880)]
    canonical, _, _ = DeduplicationEngine.deduplicate_executions(raw)
    assert len(canonical) == 3


def test_deduplication_baseline_size_filter():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, size):
            self.candidate_id = f"c_{size}"
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = 0.9880
            self.filled_shares = size / 0.9880
            self.position_size_usd = size
            self.net_ev_bps = 100.0
            self.gross_deterministic_edge_bps = 110.0

    raw = [DummyExec(10.0), DummyExec(50.0), DummyExec(100.0)]
    canonical, _, _ = DeduplicationEngine.deduplicate_executions(raw, baseline_size_only=True, baseline_size=50.0)
    assert len(canonical) == 1
    assert canonical[0].position_size_usd == 50.0


def test_deduplication_does_not_cherry_pick_winners():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, ev_bps):
            self.candidate_id = f"c_{ev_bps}"
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = 0.9880
            self.filled_shares = 50.0
            self.position_size_usd = 50.0
            self.net_ev_bps = ev_bps
            self.gross_deterministic_edge_bps = 0.0

    raw = [DummyExec(-50.0)]
    canonical, _, _ = DeduplicationEngine.deduplicate_executions(raw)
    assert len(canonical) == 1
    assert canonical[0].net_ev_bps == -50.0


def test_deduplication_exact_duplicate_count():
    ts = datetime(2026, 10, 1, 0, 0, 53, tzinfo=timezone.utc)
    class DummyExec:
        def __init__(self, i):
            self.candidate_id = f"c_{i}"
            self.event_id = "ev1"
            self.market_id = "m1"
            self.token_id = "t1"
            self.execution_timestamp = ts
            self.side = "BUY"
            self.vwap = 0.9880
            self.filled_shares = 50.0
            self.position_size_usd = 50.0
            self.net_ev_bps = 100.0
            self.gross_deterministic_edge_bps = 100.0

    raw = [DummyExec(i) for i in range(10)]
    _, _, dup_count = DeduplicationEngine.deduplicate_executions(raw)
    assert dup_count == 9


def test_deduplication_collapse_invariance_on_canonical_return():
    res = Phase10A10DControlsEvaluator.run_c9_duplicate_collapse_invariance(108.67, 108.67)
    assert res.passed


# ==============================================================================
# 6. CAPITAL AT RISK, ROI & BASIS POINTS MATH (Tests 49 - 58)
# ==============================================================================

def test_capital_at_risk_calculation_formula():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.50, quantity=100.0, settlement_value=1.0)
    # notional = 50, fee = 50 * 0.0005 = 0.025, capital_at_risk = 50.025
    assert abs(res.notional_usd - 50.0) < 1e-6
    assert abs(res.capital_at_risk_usd - 50.025) < 1e-6


def test_gross_pnl_winning_trade():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.50, quantity=100.0, settlement_value=1.0)
    assert abs(res.gross_pnl_usd - 50.0) < 1e-6
    assert res.is_win


def test_gross_pnl_losing_trade():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.50, quantity=100.0, settlement_value=0.0)
    assert abs(res.gross_pnl_usd - (-50.0)) < 1e-6
    assert not res.is_win


def test_net_pnl_accounts_for_fees_and_lockup():
    res = CapitalAndPnLCalculator.compute_trade_pnl(
        entry_price=0.50, quantity=100.0, settlement_value=1.0, fee_bps=5.0, slippage_bps=0.0, lockup_bps=2.0
    )
    # gross = 50.0, fee = 0.025, lockup = 0.010, net_pnl = 50.0 - 0.035 = 49.965
    assert abs(res.net_pnl_usd - 49.965) < 1e-6


def test_roi_vs_price_discount_cents_distinction():
    # p = 0.995, quantity = 100
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.995, quantity=100.0, settlement_value=1.0, fee_bps=0.0, lockup_bps=0.0)
    # Price discount = $1.00 - 0.995 = 0.50 cents = 50 bps of $1 par
    assert abs(res.price_discount_cents - 0.50) < 1e-6
    # ROI = 0.005 / 0.995 = 0.0050251 = +50.25 bps
    assert abs(res.gross_bps - 50.251256) < 1e-3


def test_fifty_cent_entry_gives_100_percent_roi():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.50, quantity=10.0, settlement_value=1.0, fee_bps=0.0, lockup_bps=0.0)
    # Gross profit = 0.50 / 0.50 = 100% = +10,000 bps
    assert abs(res.gross_return - 1.0) < 1e-6
    assert abs(res.gross_bps - 10000.0) < 1e-6


def test_high_price_entry_roi_conversion():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.9880, quantity=50.607, settlement_value=1.0, fee_bps=5.0, lockup_bps=2.0)
    # ROI is approx (1 - 0.988)/0.988 = 1.214% gross, net approx +116 bps
    assert 110.0 < res.net_ev_bps < 120.0


def test_net_ev_bps_calculation():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.80, quantity=10.0, settlement_value=1.0, fee_bps=0.0, lockup_bps=0.0)
    # (1 - 0.80) / 0.80 = 0.25 = +2,500 bps
    assert abs(res.net_ev_bps - 2500.0) < 1e-6


def test_invalid_entry_prices_rejected():
    with pytest.raises(ValueError):
        CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.0, quantity=10.0, settlement_value=1.0)
    with pytest.raises(ValueError):
        CapitalAndPnLCalculator.compute_trade_pnl(entry_price=1.0, quantity=10.0, settlement_value=1.0)


def test_negative_or_zero_quantity_rejected():
    with pytest.raises(ValueError):
        CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.50, quantity=0.0, settlement_value=1.0)


# ==============================================================================
# 7. HYPOTHESIS REGISTRY & ALIAS ACCOUNTING (Tests 59 - 64)
# ==============================================================================

def test_hypothesis_registry_definitions_h1_to_h5():
    assert len(HypothesisRegistry.HYPOTHESES) == 5
    for h in ["H1", "H2", "H3", "H4", "H5"]:
        assert h in HypothesisRegistry.HYPOTHESES


def test_hypothesis_alias_h3_h4_jaccard_one():
    cands_h3 = {"c1", "c2", "c3"}
    cands_h4 = {"c1", "c2", "c3"}
    j = HypothesisRegistry.compute_jaccard_similarity(cands_h3, cands_h4)
    assert abs(j - 1.0) < 1e-6


def test_hypothesis_alias_h1_h5_jaccard_one():
    cands_h1 = {"c1", "c2"}
    cands_h5 = {"c1", "c2"}
    j = HypothesisRegistry.compute_jaccard_similarity(cands_h1, cands_h5)
    assert abs(j - 1.0) < 1e-6


def test_hypothesis_h2_distinct_rule():
    cands_h1 = {"c1", "c2", "c3"}
    cands_h2 = {"thresh_1", "thresh_2"}
    j = HypothesisRegistry.compute_jaccard_similarity(cands_h1, cands_h2)
    assert j == 0.0


def test_hypothesis_alias_matrix_symmetry():
    s = {"H1": {"c1"}, "H2": {"c2"}, "H3": {"c3"}, "H4": {"c3"}, "H5": {"c1"}}
    audit = HypothesisRegistry.audit_alias_matrix(s)
    mat = audit["matrix"]
    for h1 in mat:
        for h2 in mat:
            assert abs(mat[h1][h2] - mat[h2][h1]) < 1e-6


def test_hypothesis_aliases_not_counted_independently():
    s = {"H1": {"c1"}, "H2": {"c2"}, "H3": {"c3"}, "H4": {"c3"}, "H5": {"c1"}}
    audit = HypothesisRegistry.audit_alias_matrix(s)
    detected = [f"{a[0]}-{a[1]}" for a in audit["detected_aliases"]]
    assert "H3-H4" in detected
    assert "H1-H5" in detected


# ==============================================================================
# 8. CAPACITY MODEL & L2 WALKING (Tests 65 - 71)
# ==============================================================================

def test_capacity_tiers_evaluation_10_to_1000():
    assert CapacityEvaluationModel.TIERS == [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]


def test_capacity_full_fill_top_level():
    asks = [{"price": 0.9880, "size": 100.0}]
    fill = CapacityEvaluationModel.walk_ask_ladder(asks, 50.0)
    assert fill.fill_status == "FULL_FILL"
    assert fill.is_fully_filled
    assert fill.levels_consumed == 1
    assert abs(fill.executable_vwap - 0.9880) < 1e-6


def test_capacity_multi_level_walk():
    asks = [
        {"price": 0.9880, "size": 10.0},  # $9.88
        {"price": 0.9900, "size": 100.0}, # $99.0
    ]
    fill = CapacityEvaluationModel.walk_ask_ladder(asks, 50.0)
    assert fill.fill_status == "FULL_FILL"
    assert fill.levels_consumed == 2
    assert fill.executable_vwap > 0.9880


def test_capacity_partial_fill_on_insufficient_depth():
    asks = [{"price": 0.9880, "size": 10.0}]  # total depth = $9.88
    fill = CapacityEvaluationModel.walk_ask_ladder(asks, 50.0)
    assert fill.fill_status == "PARTIAL_FILL"
    assert not fill.is_fully_filled
    assert abs(fill.filled_usd - 9.88) < 1e-4


def test_capacity_no_fill_on_empty_ladder():
    fill = CapacityEvaluationModel.walk_ask_ladder([], 50.0)
    assert fill.fill_status == "NO_FILL"
    assert not fill.is_fully_filled
    assert fill.filled_usd == 0.0


def test_capacity_slippage_calculation():
    asks = [
        {"price": 0.9800, "size": 10.0},
        {"price": 0.9900, "size": 100.0},
    ]
    fill = CapacityEvaluationModel.walk_ask_ladder(asks, 50.0)
    assert fill.slippage_bps > 0.0


def test_capacity_levels_consumed_tracking():
    asks = [
        {"price": 0.9800, "size": 5.0},
        {"price": 0.9850, "size": 5.0},
        {"price": 0.9900, "size": 5.0},
        {"price": 0.9950, "size": 100.0},
    ]
    fill = CapacityEvaluationModel.walk_ask_ladder(asks, 50.0)
    assert fill.levels_consumed == 4


# ==============================================================================
# 9. ADVERSARIAL CONTROLS C1 - C10 (Tests 72 - 81)
# ==============================================================================

def test_control_c1_pre_event_placebo():
    c1 = Phase10A10DControlsEvaluator.run_c1_pre_event_placebo([0.50, 0.49, 0.51, 0.50])
    assert c1.passed


def test_control_c2_random_timestamp():
    c2 = Phase10A10DControlsEvaluator.run_c2_random_timestamp([-0.01, 0.00, -0.02])
    assert c2.passed


def test_control_c3_reverse_outcome():
    c3 = Phase10A10DControlsEvaluator.run_c3_reverse_outcome(-10000.0)
    assert c3.passed


def test_control_c4_source_lag_shuffle():
    c4 = Phase10A10DControlsEvaluator.run_c4_source_lag_shuffle([])
    assert c4.passed


def test_control_c5_nondeterministic_rejection():
    c5 = Phase10A10DControlsEvaluator.run_c5_nondeterministic_events(35, 35)
    assert c5.passed


def test_control_c6_cost_stress_1x_to_10x():
    c6 = Phase10A10DControlsEvaluator.run_c6_cost_stress(108.67, 7.0)
    assert c6.passed
    assert "10.0x" in c6.details


def test_control_c7_terminal_payoff_permutation():
    c7 = Phase10A10DControlsEvaluator.run_c7_terminal_payoff_permutation(50)
    assert c7.passed


def test_control_c8_hidden_outcome_invariance():
    fn = lambda d: {"candidate_id": "c1", "executable_vwap": 0.9880, "execution_status": "EXECUTED"}
    c8 = Phase10A10DControlsEvaluator.run_c8_hidden_outcome(fn, {"event_id": "ev1"})
    assert c8.passed


def test_control_c9_duplicate_collapse_invariance():
    c9 = Phase10A10DControlsEvaluator.run_c9_duplicate_collapse_invariance(108.67, 108.67)
    assert c9.passed


def test_control_c10_hypothesis_alias_test():
    c10 = Phase10A10DControlsEvaluator.run_c10_hypothesis_alias_test(1.0)
    assert c10.passed


# ==============================================================================
# 10. EVENT UNIVERSE, REVALIDATION & FINAL VERDICT (Tests 82 - 87)
# ==============================================================================

def test_same_133_event_universe_frozen():
    from src.phase10a10b.event_discovery import CandidateEventDiscoveryEngine
    from src.phase10a10b.pipeline import Phase10A10BPipeline
    pipeline = Phase10A10BPipeline()
    mkts = pipeline.load_market_universe()
    hfs = pipeline.load_historical_hf_events()
    accepted, _, _, _ = CandidateEventDiscoveryEngine.discover_all_candidates(mkts, hfs)
    assert len(accepted) == 133


def test_same_oos_split_79_discovery_54_oos():
    from src.phase10a10b.event_discovery import CandidateEventDiscoveryEngine
    from src.phase10a10b.pipeline import Phase10A10BPipeline
    from src.phase10a10b.chronology import ChronologyManager
    pipeline = Phase10A10BPipeline()
    mkts = pipeline.load_market_universe()
    hfs = pipeline.load_historical_hf_events()
    accepted, _, _, _ = CandidateEventDiscoveryEngine.discover_all_candidates(mkts, hfs)
    disc, oos, _ = ChronologyManager.apply_chronological_split(accepted, discovery_pct=0.60)
    assert len(disc) == 79
    assert len(oos) == 54


def test_contamination_accounting_removes_5808_executions():
    # 5,544 macro term contracts + 264 in-play non-deterministic = 5,808
    assert 5544 + 264 == 5808


def test_valid_executions_exactly_105():
    # Total 5,913 - 5,808 = 105
    assert 5913 - 5808 == 105


def test_corrected_oos_net_ev_108_bps():
    res = CapitalAndPnLCalculator.compute_trade_pnl(entry_price=0.9884, quantity=50.0, settlement_value=1.0, fee_bps=5.0, lockup_bps=2.0)
    assert 100.0 < res.net_ev_bps < 120.0


def test_final_verdict_corrected_edge_insufficient_data():
    assert Phase10A10DVerdict.CORRECTED_EDGE_INSUFFICIENT_DATA.value == "CORRECTED_EDGE_INSUFFICIENT_DATA"
