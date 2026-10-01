"""Ornstein-Uhlenbeck (OU) Mean-Reversion and Half-Life Audit Engine.

Phase 10A.6c Mathematical Hardening:
1. Exact parameterization derivation:
   Regression: ΔX_t = α + θ X_{t-1} + ε_t
   Equivalent AR(1): X_t = α + φ X_{t-1} + ε_t where φ = 1 + θ.
   Continuous OU mapping: φ = exp(-λ Δt) => λ = -ln(φ) / Δt = -ln(1 + θ) / Δt
   Continuous half-life: t_{1/2} = ln(2) / λ = -ln(2) Δt / ln(1 + θ) for 0 < φ < 1.

2. Exhaustive edge case handling:
   - φ <= 0 (θ <= -1): Oscillatory / invalid continuous diffusion (INVALID_PARAMETER)
   - φ = 0 (θ = -1): Immediate memoryless reversion / white noise (ZERO_MEMORY_WHITE_NOISE)
   - 0 < φ < 1 (-1 < θ < 0): Valid mean-reversion (VALID_MEAN_REVERSION)
   - φ = 1 (θ = 0): Pure random walk / unit root (NO_MEAN_REVERSION)
   - φ > 1 (θ > 0): Explosive process (EXPLOSIVE)
   - Zero variance: (ZERO_VARIANCE)
   - Insufficient sample: (INSUFFICIENT_DATA)

3. Bounded prediction-market price diagnostics:
   - Prices p_t in [0, 1]
   - Boundary proximity detection (distance to 0 and 1)
   - Logit transformation diagnostic: logit(p) = ln(p* / (1 - p*))
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


class OUProcessStatus(str, Enum):
    VALID_MEAN_REVERSION = "VALID_MEAN_REVERSION"
    NO_MEAN_REVERSION = "NO_MEAN_REVERSION"
    EXPLOSIVE = "EXPLOSIVE"
    ZERO_MEMORY_WHITE_NOISE = "ZERO_MEMORY_WHITE_NOISE"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class OUValidationResult:
    status: OUProcessStatus
    theta: float                                      # Regression slope: ΔX ~ θ X_{t-1}
    phi: float                                        # AR(1) coefficient: φ = 1 + θ
    continuous_lambda: float                          # Mean-reversion rate: λ = -ln(φ) / Δt
    half_life_steps: float                            # Continuous half-life: ln(2) / λ
    regression_pvalue: float                          # OLS p-value of slope
    r_squared: float
    sample_size: int
    is_mean_reverting: bool
    is_bounded_price: bool = False
    is_near_boundary: bool = False
    dist_lower_boundary: Optional[float] = None
    dist_upper_boundary: Optional[float] = None
    logit_half_life_steps: Optional[float] = None
    logit_status: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class OUModelValidator:
    """Rigorous mathematical engine for OU parameterization, half-life estimation,
    edge-case classification, and bounded price diagnostics.
    """

    def __init__(
        self,
        min_observations: int = 15,
        boundary_threshold: float = 0.05,
        logit_epsilon: float = 1e-4,
    ):
        self.min_observations = min_observations
        self.boundary_threshold = boundary_threshold
        self.logit_epsilon = logit_epsilon

    def validate_and_estimate_ou(
        self,
        series: pd.Series,
        dt: float = 1.0,
        check_bounded: bool = True
    ) -> OUValidationResult:
        """Audits, parameterizes, and estimates continuous OU dynamics with strict edge-case gating."""
        clean_s = series.dropna().values
        n = len(clean_s)

        # Edge Case 1: Insufficient observations
        if n < self.min_observations:
            return OUValidationResult(
                status=OUProcessStatus.INSUFFICIENT_DATA,
                theta=0.0,
                phi=1.0,
                continuous_lambda=0.0,
                half_life_steps=float("inf"),
                regression_pvalue=1.0,
                r_squared=0.0,
                sample_size=n,
                is_mean_reverting=False,
                notes=f"Sample size {n} < required {self.min_observations}."
            )

        # Edge Case 2: Zero variance (constant series)
        series_var = float(np.var(clean_s))
        if series_var < 1e-12:
            return OUValidationResult(
                status=OUProcessStatus.ZERO_VARIANCE,
                theta=0.0,
                phi=1.0,
                continuous_lambda=0.0,
                half_life_steps=float("inf"),
                regression_pvalue=1.0,
                r_squared=0.0,
                sample_size=n,
                is_mean_reverting=False,
                notes="Series has zero variance (constant values)."
            )

        # Regress: ΔX_t = α + θ X_{t-1} + ε_t
        s_prev = clean_s[:-1]
        delta_s = clean_s[1:] - s_prev

        # Linear regression
        slope, intercept, r_value, p_value, std_err = stats.linregress(s_prev, delta_s)
        theta = float(slope)
        phi = 1.0 + theta
        r_sq = float(r_value ** 2)
        p_val = float(p_value)

        # Boundary diagnostics for bounded prediction-market series
        is_bounded = False
        is_near_bound = False
        dist_lower = None
        dist_upper = None
        logit_hl = None
        logit_stat = None

        min_val = float(np.min(clean_s))
        max_val = float(np.max(clean_s))

        if check_bounded and 0.0 <= min_val and max_val <= 1.0:
            is_bounded = True
            dist_lower = round(min_val - 0.0, 4)
            dist_upper = round(1.0 - max_val, 4)
            is_near_bound = bool(min_val < self.boundary_threshold or max_val > (1.0 - self.boundary_threshold))

            # Logit diagnostic
            logit_hl, logit_stat = self._evaluate_logit_ou(clean_s, dt)

        # Edge Case 3: Explosive (φ > 1.0 => θ > 0.0)
        if theta > 1e-7:
            return OUValidationResult(
                status=OUProcessStatus.EXPLOSIVE,
                theta=round(theta, 6),
                phi=round(phi, 6),
                continuous_lambda=0.0,
                half_life_steps=float("inf"),
                regression_pvalue=round(p_val, 4),
                r_squared=round(r_sq, 4),
                sample_size=n,
                is_mean_reverting=False,
                is_bounded_price=is_bounded,
                is_near_boundary=is_near_bound,
                dist_lower_boundary=dist_lower,
                dist_upper_boundary=dist_upper,
                logit_half_life_steps=logit_hl,
                logit_status=logit_stat,
                notes=f"Explosive process (θ={theta:.4f} > 0, φ={phi:.4f} > 1). Variance diverges exponentially."
            )

        # Edge Case 4: Pure Unit Root / No Mean Reversion (θ == 0.0 => φ == 1.0)
        if abs(theta) <= 1e-7:
            return OUValidationResult(
                status=OUProcessStatus.NO_MEAN_REVERSION,
                theta=round(theta, 6),
                phi=round(phi, 6),
                continuous_lambda=0.0,
                half_life_steps=float("inf"),
                regression_pvalue=round(p_val, 4),
                r_squared=round(r_sq, 4),
                sample_size=n,
                is_mean_reverting=False,
                is_bounded_price=is_bounded,
                is_near_boundary=is_near_bound,
                dist_lower_boundary=dist_lower,
                dist_upper_boundary=dist_upper,
                logit_half_life_steps=logit_hl,
                logit_status=logit_stat,
                notes="Unit root process (θ ≈ 0, φ ≈ 1). No mean reversion."
            )

        # Edge Case 5: Zero-Memory White Noise (φ == 0.0 => θ == -1.0)
        if abs(phi) <= 1e-6:
            return OUValidationResult(
                status=OUProcessStatus.ZERO_MEMORY_WHITE_NOISE,
                theta=round(theta, 6),
                phi=0.0,
                continuous_lambda=float("inf"),
                half_life_steps=0.0,
                regression_pvalue=round(p_val, 4),
                r_squared=round(r_sq, 4),
                sample_size=n,
                is_mean_reverting=True,
                is_bounded_price=is_bounded,
                is_near_boundary=is_near_bound,
                dist_lower_boundary=dist_lower,
                dist_upper_boundary=dist_upper,
                logit_half_life_steps=logit_hl,
                logit_status=logit_stat,
                notes="Memoryless white noise (φ=0). Deviations vanish in exactly 1 discrete step."
            )

        # Edge Case 6: Oscillating / Negative φ (φ < 0.0 => θ < -1.0)
        if phi < 0.0:
            return OUValidationResult(
                status=OUProcessStatus.INVALID_PARAMETER,
                theta=round(theta, 6),
                phi=round(phi, 6),
                continuous_lambda=float("nan"),
                half_life_steps=float("nan"),
                regression_pvalue=round(p_val, 4),
                r_squared=round(r_sq, 4),
                sample_size=n,
                is_mean_reverting=False,
                is_bounded_price=is_bounded,
                is_near_boundary=is_near_bound,
                dist_lower_boundary=dist_lower,
                dist_upper_boundary=dist_upper,
                logit_half_life_steps=logit_hl,
                logit_status=logit_stat,
                notes=f"Oscillatory process with negative AR(1) coefficient (φ={phi:.4f} < 0). Not a valid continuous OU diffusion."
            )

        # Valid continuous Ornstein-Uhlenbeck: 0 < φ < 1 (-1 < θ < 0)
        rate_lambda = -np.log(phi) / dt
        if rate_lambda <= 1e-12:
            return OUValidationResult(
                status=OUProcessStatus.NO_MEAN_REVERSION,
                theta=round(theta, 6),
                phi=round(phi, 6),
                continuous_lambda=0.0,
                half_life_steps=float("inf"),
                regression_pvalue=round(p_val, 4),
                r_squared=round(r_sq, 4),
                sample_size=n,
                is_mean_reverting=False,
                notes="Reversion rate too small to establish meaningful half-life."
            )

        half_life = np.log(2.0) / rate_lambda

        # Flag statistical significance
        is_stat_mr = bool(p_val < 0.05 and 0.0 < phi < 1.0)

        return OUValidationResult(
            status=OUProcessStatus.VALID_MEAN_REVERSION,
            theta=round(theta, 6),
            phi=round(phi, 6),
            continuous_lambda=round(rate_lambda, 6),
            half_life_steps=round(half_life, 2),
            regression_pvalue=round(p_val, 4),
            r_squared=round(r_sq, 4),
            sample_size=n,
            is_mean_reverting=is_stat_mr,
            is_bounded_price=is_bounded,
            is_near_boundary=is_near_bound,
            dist_lower_boundary=dist_lower,
            dist_upper_boundary=dist_upper,
            logit_half_life_steps=logit_hl,
            logit_status=logit_stat,
            notes=f"Valid OU mean-reversion (half-life={half_life:.2f} steps, λ={rate_lambda:.4f}, p={p_val:.4f})."
        )

    def _evaluate_logit_ou(self, raw_prices: np.ndarray, dt: float) -> Tuple[Optional[float], Optional[str]]:
        """Evaluates OU half-life on logit-transformed bounded prices: logit(p) = ln(p* / (1 - p*))."""
        try:
            clipped = np.clip(raw_prices, self.logit_epsilon, 1.0 - self.logit_epsilon)
            logit_p = np.log(clipped / (1.0 - clipped))
            prev_l = logit_p[:-1]
            delta_l = logit_p[1:] - prev_l

            slope, _, _, p_val, _ = stats.linregress(prev_l, delta_l)
            theta_l = float(slope)
            phi_l = 1.0 + theta_l

            if 0.0 < phi_l < 1.0:
                lam_l = -np.log(phi_l) / dt
                hl_l = np.log(2.0) / lam_l
                return round(hl_l, 2), "VALID_LOGIT_OU"
            elif theta_l >= 0.0:
                return float("inf"), "NO_MEAN_REVERSION_LOGIT"
            else:
                return float("nan"), "INVALID_LOGIT_PARAMETER"
        except Exception as e:
            return None, f"LOGIT_ERROR: {e}"
