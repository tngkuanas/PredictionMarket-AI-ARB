"""Phase 10A.10 Strategy Configuration Freeze & Hash Verification.

Demonstrates that all Phase 10A.10 trading strategy parameters remain 100% frozen:
- Entry thresholds (bps): [5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
- Position sizes (USD): [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]
- Latency buckets: 12 discrete buckets
- Base network & execution fee: 5.0 bps
- Convergence epsilon grid (bps): [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]
- Annualized risk-free rate for capital lockup: 5.0%
- Minimum independent sample size threshold: N >= 30
- Multiple testing procedure: Holm-Bonferroni (alpha = 0.05)
"""

import hashlib
import json
from typing import Dict, Any, List


FROZEN_PHASE10A10_CONFIG: Dict[str, Any] = {
    "version": "10A.10-FROZEN",
    "entry_thresholds_bps": [5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0],
    "position_sizes_usd": [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0],
    "latency_buckets": [
        "0_100ms", "100_250ms", "250_500ms", "500ms_1s",
        "1_2s", "2_5s", "5_10s", "10_30s", "30s_1m",
        "1_5m", "5_15m", "15m_plus"
    ],
    "base_fee_bps": 5.0,
    "convergence_epsilons_bps": [1.0, 5.0, 10.0, 25.0, 50.0, 100.0],
    "risk_free_annual_rate_pct": 5.0,
    "source_tiers": ["TIER_1_OFFICIAL", "TIER_2_PRIMARY", "TIER_3_SECONDARY"],
    "accepted_primary_tiers": ["TIER_1_OFFICIAL", "TIER_2_PRIMARY"],
    "deterministic_states": ["STATE_A", "STATE_B", "STATE_C", "STATE_D"],
    "accepted_primary_states": ["STATE_A", "STATE_B"],
    "min_sample_size_threshold": 30,
    "multiple_testing": "Holm-Bonferroni",
    "family_alpha": 0.05,
    "reconstruction_offsets_sec": [-3600.0, -1800.0, -600.0, -300.0, -60.0, -30.0, -10.0, -5.0, 0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0],
}


def compute_config_hash(config: Dict[str, Any] = FROZEN_PHASE10A10_CONFIG) -> str:
    """Computes deterministic SHA-256 hash of the strategy configuration."""
    canonical_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


PHASE10A10B_CONFIG_HASH = compute_config_hash()


def assert_config_unmodified(candidate_config: Dict[str, Any]) -> None:
    """Verifies that the provided configuration matches the frozen configuration exactly."""
    cand_hash = compute_config_hash(candidate_config)
    if cand_hash != PHASE10A10B_CONFIG_HASH:
        raise ValueError(
            f"Strategy configuration modified! Expected hash {PHASE10A10B_CONFIG_HASH}, got {cand_hash}."
        )
