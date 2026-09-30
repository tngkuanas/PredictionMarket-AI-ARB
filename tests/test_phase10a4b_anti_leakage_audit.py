"""Unit and Integration Tests for Phase 10A.4b Anti-Leakage & Event-Universe Audit.

Validates:
1. Complete execution of the AntiLeakageAuditor and pipeline runner.
2. Detection of synthetic order book generator (`generate_high_frequency_book_tape`) and mathematical circularity.
3. Raw data provenance verification (detecting 0% genuine raw feed logs in data/raw_hf_messages).
4. Token authenticity audit (identifying placeholder token IDs like token_geopol_*).
5. Direction-free Monte Carlo placebo test (verifying collapse to null / negative net markout).
6. Reversed-direction test (verifying 0.0% win rate and steep negative markout).
7. Chronological out-of-sample invariance detection.
8. Category breakdown alignment with synthetic target_move parameters.
9. Complete sample attrition upon clean filtering (0 surviving clean events).
10. Final validity classification (rejecting Class A genuine alpha; assigning Class E / D).
"""

import pytest
import duckdb

from src.phase10.audit.anti_leakage_audit import AntiLeakageAuditor
from src.phase10.high_frequency.event_dataset import HighFrequencyEventDataset


@pytest.fixture
def auditor():
    return AntiLeakageAuditor(db_path="data/prediction_market.duckdb")


def test_synthetic_generator_detection(auditor):
    """Verifies that the audit detects the synthetic order book generator and circularity."""
    leakage = auditor.audit_simulation_pipeline_leakage()
    
    assert leakage["synthetic_generator_identified"] is True
    assert leakage["generator_function"] == "generate_high_frequency_book_tape"
    assert "dir_mult * target_delta" in leakage["generator_formula"]
    assert leakage["leakage_verdict"] == "FATAL_CIRCULAR_SYNTHESIS"
    assert leakage["signal_to_noise_ratio"] > 10.0


def test_raw_provenance_and_token_authenticity(auditor):
    """Verifies that raw feed provenance is 0% and placeholder tokens are identified."""
    events = auditor.dataset_loader.load_curated_events()
    records = auditor.audit_event_provenance(events)

    assert len(records) == 112
    # Zero raw exchange JSON logs exist on disk
    assert all(r.has_raw_feed_provenance is False for r in records)

    # 58 contracts use synthetic placeholder token strings
    placeholder_tokens = [r for r in records if not r.is_real_token]
    assert len(placeholder_tokens) == 58
    assert all(r.mapped_token_id.startswith("token_") for r in placeholder_tokens)


def test_direction_free_placebo_test(auditor):
    """Verifies that randomizing direction collapses net markout to negative due to friction."""
    events = auditor.dataset_loader.load_curated_events()
    placebo = auditor.run_direction_free_placebo(events, n_iterations=500, random_seed=42)

    assert placebo.test_name == "Direction-Free Placebo (T+15s)"
    assert placebo.n_iterations == 500
    assert placebo.mean_markout_bps < 0.0, "Expected negative net markout due to friction"
    assert abs(placebo.win_rate - 0.50) < 0.05, "Expected ~50% win rate under random direction"
    assert placebo.empirical_separation == "COLLAPSED_TO_NULL"


def test_reversed_direction_test(auditor):
    """Verifies that reversing trading direction inverts the captured move into severe losses."""
    rev = auditor.run_reversed_direction_test()

    assert rev.test_name == "Reversed-Direction Test (T+15s)"
    assert rev.win_rate == 0.0, "Reversed direction must produce 0% win rate"
    assert rev.mean_markout_bps < -100.0, "Expected severe negative markout"
    assert rev.empirical_separation == "REVERSED"


def test_temporal_invariance_detection(auditor):
    """Verifies that the synthetic data generator produced stationary responses across all periods."""
    temporal = auditor.run_temporal_out_of_sample_split()

    assert temporal["synthetic_invariance_detected"] is True
    # All tertiles exhibit 100% win rate because of synthetic data injection
    assert temporal["tertile_1_early"]["info_repricing_bps"]["win_rate"] == 1.0
    assert temporal["tertile_2_mid"]["info_repricing_bps"]["win_rate"] == 1.0
    assert temporal["tertile_3_late"]["info_repricing_bps"]["win_rate"] == 1.0


def test_category_breakdown_alignment(auditor):
    """Verifies that observed repricing in each category matches the synthetic target_move."""
    breakdown = auditor.run_event_category_breakdown()

    # Macro monetary: target_move was 0.025 (250 bps)
    assert abs(breakdown["macro_monetary"]["info_response_mean_bps"] - 250.0) < 15.0
    # Macro indicator: target_move was 0.015 (150 bps)
    assert abs(breakdown["macro_indicator"]["info_response_mean_bps"] - 150.0) < 15.0
    # Crypto milestone: target_move was 0.035 (350 bps)
    assert abs(breakdown["crypto_milestone"]["info_response_mean_bps"] - 350.0) < 15.0


def test_clean_filtered_sample_attrition(auditor):
    """Verifies that zero events survive clean empirical filtering."""
    clean = auditor.run_clean_filtered_recalculation()

    assert clean["initial_events_count"] == 112
    assert clean["events_with_raw_provenance"] == 0
    assert clean["surviving_clean_events_count"] == 0
    assert clean["verdict"] == "COMPLETE_SAMPLE_ATTRITION_WHEN_SYNTHETIC_DATA_EXCLUDED"


def test_final_classification_verdict(auditor):
    """Verifies that the audit definitively rejects Class A genuine alpha."""
    results = auditor.execute_complete_audit()
    classification = results["final_classification"]

    assert classification["genuine_ex_ante_alpha"] is False
    assert "E" in classification["primary_classification"]
    assert "D" in classification["primary_driver"]
