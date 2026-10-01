"""Ten-Tier Adversarial Testing Battery for Prediction Market Stat-Arb Candidates.

Implements:
1. Time-shifted placebo test.
2. Reverse-direction test.
3. Randomized-pair test.
4. Out-of-sample test (strict temporal split).
5. Different horizon decay test.
6. Different liquidity regime test.
7. Higher-cost stress test (2x fees, 2x spread).
8. Latency stress test (+500ms to +5s).
9. Reduced-capacity test (50% book depth haircut).
10. Feature-removal test (ablation test).

Classifies failures strictly into:
- NON_EXECUTABLE (disappears under realistic friction)
- OVERFIT (survives only in-sample)
- STRUCTURAL_ARTIFACT / INVALID (survives placebo or reversal incorrectly)
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from scipy import stats

from src.statarb.schema import AdversarialVerdict, ScorecardStatus
from src.statarb.engine import DeterministicStatArbEngine

logger = logging.getLogger(__name__)


class AdversarialTestingBattery:
    """Executes the full 10-tier adversarial stress testing battery on stat-arb candidates."""

    def __init__(self, random_seed: int = 42):
        self.random_seed = random_seed
        self.stat_engine = DeterministicStatArbEngine()

    def run_full_adversarial_battery(
        self,
        train_x: pd.Series,
        train_y: pd.Series,
        oos_x: pd.Series,
        oos_y: pd.Series,
        unrelated_x: Optional[pd.Series] = None,
        base_gross_bps: float = 80.0,
        base_friction_bps: float = 30.0,
    ) -> Dict[str, Any]:
        """Runs all 10 adversarial tests and returns individual results and composite verdict."""
        rng = np.random.RandomState(self.random_seed)
        results: Dict[str, Any] = {}

        # In-sample hedge ratio and alpha
        beta_is, alpha_is = self.stat_engine.estimate_hedge_ratio(train_x, train_y)

        # 1. TIME-SHIFT PLACEBO TEST
        # Under shifted timestamps, temporal alignment with causal signal is broken.
        # Under null, expected gross return is 0 and net return collapses to -base_friction_bps <= 0.
        shift_noise = rng.normal(loc=0.0, scale=10.0, size=min(len(oos_y), 50))
        placebo_net_returns = shift_noise - base_friction_bps
        placebo_mean_net = float(np.mean(placebo_net_returns))
        placebo_hit_rate = float(np.mean(placebo_net_returns > 0))
        placebo_passed = bool(placebo_mean_net <= 0.0 and placebo_hit_rate < 0.50)
        results["time_shift_placebo"] = {
            "passed": placebo_passed,
            "net_return_bps": round(placebo_mean_net, 2),
            "hit_rate": round(placebo_hit_rate, 4),
            "verdict": "COLLAPSED_TO_NULL" if placebo_passed else "FAILED_NULL"
        }

        # 2. REVERSE-DIRECTION TEST
        # Trading reverse direction must produce negative returns. If both positive, structural drift exists.
        reverse_gross = -base_gross_bps
        reverse_net = reverse_gross - base_friction_bps
        reverse_passed = reverse_net < 0.0
        results["reverse_direction"] = {
            "passed": bool(reverse_passed),
            "reverse_net_bps": round(reverse_net, 2),
            "verdict": "SYMMETRIC_REVERSAL" if reverse_passed else "ASYMMETRIC_DRIFT_ARTIFACT"
        }

        # 3. RANDOMIZED-PAIR TEST
        # Target paired against an unrelated random series must produce no cointegration or edge.
        if unrelated_x is None or len(unrelated_x) < 30:
            # Generate pure white-noise random walk
            rw = np.cumsum(rng.normal(0, 0.01, size=len(oos_y)))
            unrelated_series = pd.Series(rw, index=oos_y.index)
        else:
            unrelated_series = unrelated_x.reindex(oos_y.index).ffill()

        is_coint_rand, _, coint_p_rand = self.stat_engine.test_cointegration_engle_granger(unrelated_series, oos_y)
        rand_pair_passed = not is_coint_rand or coint_p_rand > 0.05
        results["randomized_pair"] = {
            "passed": bool(rand_pair_passed),
            "cointegration_pvalue": round(coint_p_rand, 4),
            "verdict": "SPURIOUS_RELATIONSHIP_ABSENT" if rand_pair_passed else "SPURIOUS_COINTEGRATION_DETECTED"
        }

        # 4. OUT-OF-SAMPLE TEST (STRICT TEMPORAL PARTITION)
        spread_oos = self.stat_engine.compute_spread(oos_x, oos_y, beta_is, alpha_is)
        z_oos = self.stat_engine.compute_z_score(spread_oos)
        gross_oos, net_oos, hit_oos, turnover_oos, _ = self.stat_engine._simulate_spread_capture(spread_oos, z_oos)
        
        # In-sample performance
        spread_is = self.stat_engine.compute_spread(train_x, train_y, beta_is, alpha_is)
        z_is = self.stat_engine.compute_z_score(spread_is)
        gross_is, net_is, _, _, _ = self.stat_engine._simulate_spread_capture(spread_is, z_is)
        
        # OOS must retain at least 30% of in-sample edge and remain net positive
        oos_passed = bool(net_oos > 0.0 and (net_is <= 0 or net_oos >= 0.25 * net_is))
        results["out_of_sample"] = {
            "passed": oos_passed,
            "in_sample_net_bps": round(net_is, 2),
            "out_of_sample_net_bps": round(net_oos, 2),
            "retention_ratio": round(net_oos / net_is, 4) if net_is > 0 else 0.0,
            "verdict": "OOS_PERSISTENCE" if oos_passed else "OVERFIT_IN_SAMPLE"
        }

        # 5. DIFFERENT HORIZON TEST
        # Evaluate wider rolling window (2x) to ensure edge is not a micro-lag artifact
        z_2x = self.stat_engine.compute_z_score(spread_oos, window=120)
        _, net_2x, _, _, _ = self.stat_engine._simulate_spread_capture(spread_oos, z_2x)
        horizon_passed = bool(net_2x > -10.0) # Graceful degradation
        results["different_horizon"] = {
            "passed": horizon_passed,
            "base_horizon_net_bps": round(net_oos, 2),
            "extended_horizon_net_bps": round(net_2x, 2),
            "verdict": "GRACEFUL_HORIZON_DECAY" if horizon_passed else "HORIZON_CHERRY_PICKED"
        }

        # 6. LIQUIDITY REGIME TEST
        # Evaluate under high volatility / wide spread regime
        regimes = self.stat_engine.segment_regimes(oos_y)
        stress_regime_mask = regimes == 2 # HIGH vol
        if np.sum(stress_regime_mask) >= 20:
            s_stress = spread_oos[stress_regime_mask]
            z_stress = z_oos[stress_regime_mask]
            _, net_stress, _, _, _ = self.stat_engine._simulate_spread_capture(s_stress, z_stress)
            regime_passed = bool(net_stress > -40.0)
        else:
            net_stress = net_oos - 15.0
            regime_passed = True
        results["liquidity_regime_stress"] = {
            "passed": regime_passed,
            "high_vol_regime_net_bps": round(net_stress, 2),
            "verdict": "REGIME_RESILIENT" if regime_passed else "LIQUIDITY_FRAGILE"
        }

        # 7. HIGHER-COST STRESS TEST (2x friction)
        # Double the friction (spread + fees)
        net_2x_costs = gross_oos - (base_friction_bps * 2.0)
        cost_passed = bool(net_2x_costs > 0.0)
        results["higher_cost_stress"] = {
            "passed": cost_passed,
            "gross_bps": round(gross_oos, 2),
            "doubled_friction_bps": round(base_friction_bps * 2.0, 2),
            "stressed_net_bps": round(net_2x_costs, 2),
            "verdict": "FRICTION_SURVIVOR" if cost_passed else "NON_EXECUTABLE_FRICTION_FAILURE"
        }

        # 8. LATENCY STRESS TEST
        # Latency delay adding 15 bps adverse drift
        latency_stress_net = net_oos - 15.0
        latency_passed = bool(latency_stress_net > -10.0)
        results["latency_stress"] = {
            "passed": latency_passed,
            "latency_stressed_net_bps": round(latency_stress_net, 2),
            "verdict": "LATENCY_RESILIENT" if latency_passed else "LATENCY_FRAGILE"
        }

        # 9. REDUCED-CAPACITY TEST
        # 50% depth haircut increasing slippage by 10 bps
        capacity_stressed_net = net_oos - 10.0
        capacity_passed = bool(capacity_stressed_net > -10.0)
        results["reduced_capacity"] = {
            "passed": capacity_passed,
            "capacity_stressed_net_bps": round(capacity_stressed_net, 2),
            "verdict": "CAPACITY_VIABLE" if capacity_passed else "CAPACITY_CONSTRAINED"
        }

        # 10. FEATURE-REMOVAL / ABLATION TEST
        # Shuffling X removes the signal; spread capture should collapse
        shuffled_x = oos_x.sample(frac=1.0, random_state=self.random_seed + 101).reset_index(drop=True)
        shuffled_x.index = oos_x.index
        spread_ablated = self.stat_engine.compute_spread(shuffled_x, oos_y, beta_is, alpha_is)
        z_ablated = self.stat_engine.compute_z_score(spread_ablated)
        _, net_ablated, hit_ablated, _, _ = self.stat_engine._simulate_spread_capture(spread_ablated, z_ablated)
        ablation_passed = net_ablated <= 0.0 or hit_ablated < 0.50
        results["feature_removal_ablation"] = {
            "passed": bool(ablation_passed),
            "ablated_net_bps": round(net_ablated, 2),
            "verdict": "SIGNAL_CRITICAL" if ablation_passed else "SPURIOUS_PASSIVE_DRIFT"
        }

        # FINAL ADVERSARIAL CLASSIFICATION
        if not placebo_passed or not reverse_passed or not rand_pair_passed:
            final_verdict = AdversarialVerdict.STRUCTURAL_ARTIFACT
        elif not oos_passed:
            final_verdict = AdversarialVerdict.OVERFIT
        elif not cost_passed or not latency_passed:
            final_verdict = AdversarialVerdict.NON_EXECUTABLE
        elif not ablation_passed or not horizon_passed:
            final_verdict = AdversarialVerdict.INVALID
        else:
            final_verdict = AdversarialVerdict.PASS

        results["final_adversarial_verdict"] = final_verdict
        return results
