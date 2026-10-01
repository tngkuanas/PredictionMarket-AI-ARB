"""Deterministic Statistical Arbitrage Framework for Prediction Markets.

Implements:
1. Spread formulation (Y_t - beta * X_t) with in-sample beta estimation.
2. Rolling hedge ratio with zero-lookahead.
3. Standard and Robust (MAD) rolling z-scores.
4. Ornstein-Uhlenbeck mean-reversion half-life.
5. Stationarity diagnostics (ADF test).
6. Engle-Granger cointegration testing.
7. Residual autocorrelation (ACF lag 1, Ljung-Box).
8. Lead-lag cross-correlation profile.
9. Conditional impulse response functions.
10. Regime segmentation (volatility and spread regimes).
"""

import logging
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.stats.diagnostic import acorr_ljungbox

from src.statarb.schema import (
    SpreadModelConfig,
    StatArbMetrics,
)

logger = logging.getLogger(__name__)


class DeterministicStatArbEngine:
    """Rigorous mathematical engine for statistical arbitrage modeling."""

    def __init__(self, config: Optional[SpreadModelConfig] = None):
        self.config = config or SpreadModelConfig()

    # =========================================================================
    # 1. HEDGE RATIO ESTIMATION (STRICTLY IN-SAMPLE)
    # =========================================================================

    def estimate_hedge_ratio(
        self,
        series_x: pd.Series,
        series_y: pd.Series,
        method: Optional[str] = None
    ) -> Tuple[float, float]:
        """Estimates hedge ratio beta and intercept alpha strictly from historical data.
        
        Model: Y_t = alpha + beta * X_t + epsilon_t
        Returns: (beta, alpha)
        """
        valid = pd.DataFrame({"x": series_x, "y": series_y}).dropna()
        if len(valid) < self.config.min_observations:
            return 1.0, 0.0

        est_method = method or self.config.estimation_method
        x_vals = valid["x"].values
        y_vals = valid["y"].values

        if est_method == "theil_sen":
            res = stats.theilslopes(y_vals, x_vals)
            beta = float(res.slope)
            alpha = float(res.intercept)
        elif est_method == "huber":
            # Iterative reweighted Huber regression
            beta, alpha = self._fit_huber(x_vals, y_vals)
        else:
            # Standard Ordinary Least Squares (OLS)
            cov_xy = np.cov(x_vals, y_vals)[0, 1]
            var_x = np.var(x_vals, ddof=1)
            if var_x < 1e-12:
                beta = 1.0
                alpha = float(np.mean(y_vals) - np.mean(x_vals))
            else:
                beta = float(cov_xy / var_x)
                alpha = float(np.mean(y_vals) - beta * np.mean(x_vals))

        return beta, alpha

    def _fit_huber(self, x: np.ndarray, y: np.ndarray, c: float = 1.345, max_iter: int = 30) -> Tuple[float, float]:
        """Robust M-estimator regression using Huber loss."""
        # Initial OLS fit
        cov_xy = np.cov(x, y)[0, 1]
        var_x = np.var(x, ddof=1)
        beta = cov_xy / var_x if var_x > 1e-12 else 1.0
        alpha = np.mean(y) - beta * np.mean(x)

        for _ in range(max_iter):
            residuals = y - (alpha + beta * x)
            scale = 1.4826 * np.median(np.abs(residuals - np.median(residuals)))
            if scale < 1e-8:
                break
            r = residuals / scale
            # Huber weights
            weights = np.where(np.abs(r) <= c, 1.0, c / np.maximum(np.abs(r), 1e-8))
            
            w_sum = np.sum(weights)
            x_wmean = np.sum(weights * x) / w_sum
            y_wmean = np.sum(weights * y) / w_sum
            
            denom = np.sum(weights * (x - x_wmean) ** 2)
            if denom < 1e-12:
                break
            new_beta = np.sum(weights * (x - x_wmean) * (y - y_wmean)) / denom
            new_alpha = y_wmean - new_beta * x_wmean

            if abs(new_beta - beta) < 1e-6 and abs(new_alpha - alpha) < 1e-6:
                beta, alpha = new_beta, new_alpha
                break
            beta, alpha = new_beta, new_alpha

        return float(beta), float(alpha)

    # =========================================================================
    # 2. SPREAD CONSTRUCTION & ROLLING HEDGE RATIO
    # =========================================================================

    def compute_spread(
        self,
        series_x: pd.Series,
        series_y: pd.Series,
        beta: float,
        alpha: float = 0.0
    ) -> pd.Series:
        """Constructs residual spread: spread_t = Y_t - (alpha + beta * X_t)."""
        df = pd.DataFrame({"x": series_x, "y": series_y})
        if self.config.spread_type == "log":
            spread = np.log(df["y"].clip(lower=1e-4)) - beta * np.log(df["x"].clip(lower=1e-4)) - alpha
        else:
            spread = df["y"] - beta * df["x"] - alpha
        return spread

    def compute_rolling_hedge_ratio(
        self,
        series_x: pd.Series,
        series_y: pd.Series,
        window: Optional[int] = None
    ) -> pd.Series:
        """Computes rolling hedge ratio beta_t = Cov(X, Y) / Var(X) strictly using past observations."""
        win = window or self.config.rolling_window
        df = pd.DataFrame({"x": series_x, "y": series_y}).dropna()
        rolling_cov = df["x"].rolling(window=win, min_periods=self.config.min_observations).cov(df["y"])
        rolling_var = df["x"].rolling(window=win, min_periods=self.config.min_observations).var()
        rolling_beta = rolling_cov / rolling_var.replace(0.0, np.nan)
        return rolling_beta.fillna(1.0)

    # =========================================================================
    # 3. Z-SCORE & ROBUST MAD Z-SCORE
    # =========================================================================

    def compute_z_score(
        self,
        spread: pd.Series,
        window: Optional[int] = None
    ) -> pd.Series:
        """Standard rolling z-score: z_t = (spread_t - mean_t) / std_t (zero-lookahead)."""
        win = window or self.config.rolling_window
        rolling_mean = spread.rolling(window=win, min_periods=self.config.min_observations).mean()
        rolling_std = spread.rolling(window=win, min_periods=self.config.min_observations).std()
        z_score = (spread - rolling_mean) / rolling_std.replace(0.0, np.nan)
        return z_score.fillna(0.0)

    def compute_robust_mad_z_score(
        self,
        spread: pd.Series,
        window: Optional[int] = None
    ) -> pd.Series:
        """Robust rolling z-score using Median and Median Absolute Deviation (MAD).
        
        z_t^robust = (spread_t - median_t) / (1.4826 * MAD_t)
        Resistant to fat tails, flash jumps, and single outlier book quotes.
        """
        win = window or self.config.rolling_window
        min_p = self.config.min_observations

        def calc_mad(window_vals: np.ndarray) -> float:
            med = np.median(window_vals)
            mad = np.median(np.abs(window_vals - med))
            return 1.4826 * mad

        rolling_median = spread.rolling(window=win, min_periods=min_p).median()
        rolling_mad = spread.rolling(window=win, min_periods=min_p).apply(calc_mad, raw=True)
        
        robust_z = (spread - rolling_median) / rolling_mad.replace(0.0, np.nan)
        return robust_z.fillna(0.0)

    # =========================================================================
    # 4. ORNSTEIN-UHLENBECK MEAN-REVERSION HALF-LIFE
    # =========================================================================
    # 4. ORNSTEIN-UHLENBECK MEAN-REVERSION HALF-LIFE (AUDITED & HARDENED)
    # =========================================================================

    def estimate_half_life(self, spread: pd.Series, dt: float = 1.0) -> Tuple[float, float, float]:
        """Estimates mean-reversion half-life via AR(1) Ornstein-Uhlenbeck regression:
        
        Δs_t = α + θ s_{t-1} + ε_t
        AR(1): φ = 1 + θ
        Continuous rate: λ = -ln(φ) / dt = -ln(1 + θ) / dt (for 0 < φ < 1)
        Half-life: t_{1/2} = ln(2) / λ
        
        Guarantees: Never returns a false positive half-life if φ <= 0 or φ >= 1.
        Returns: (half_life_steps, theta, p_value)
        """
        from src.statarb.ou_validator import OUModelValidator, OUProcessStatus
        validator = OUModelValidator(min_observations=self.config.min_observations)
        res = validator.validate_and_estimate_ou(spread, dt=dt, check_bounded=False)

        if res.status == OUProcessStatus.VALID_MEAN_REVERSION:
            return res.half_life_steps, res.theta, res.regression_pvalue
        elif res.status in (OUProcessStatus.NO_MEAN_REVERSION, OUProcessStatus.EXPLOSIVE, OUProcessStatus.ZERO_VARIANCE):
            return float("inf"), res.theta, res.regression_pvalue
        elif res.status == OUProcessStatus.ZERO_MEMORY_WHITE_NOISE:
            return 0.0, res.theta, res.regression_pvalue
        elif res.status == OUProcessStatus.INVALID_PARAMETER:
            return float("nan"), res.theta, res.regression_pvalue
        else: # INSUFFICIENT_DATA
            return float("inf"), 0.0, 1.0

    def audit_ou_dynamics(
        self,
        series: pd.Series,
        dt: float = 1.0,
        check_bounded: bool = True
    ):
        """Conducts full audited continuous-time OU validation with bounded price diagnostics."""
        from src.statarb.ou_validator import OUModelValidator
        validator = OUModelValidator(min_observations=self.config.min_observations)
        return validator.validate_and_estimate_ou(series, dt=dt, check_bounded=check_bounded)

    # =========================================================================
    # 5. STATIONARITY & COINTEGRATION
    # =========================================================================

    def test_stationarity_adf(self, spread: pd.Series) -> Tuple[bool, float, float]:
        """Augmented Dickey-Fuller test on spread. Returns (is_stationary, adf_stat, p_val)."""
        s = spread.dropna()
        if len(s) < self.config.min_observations:
            return False, 0.0, 1.0

        try:
            res = adfuller(s, autolag="AIC")
            adf_stat = float(res[0])
            p_val = float(res[1])
            is_stat = p_val < 0.05
            return is_stat, adf_stat, p_val
        except Exception as e:
            logger.warning(f"ADF test failed: {e}")
            return False, 0.0, 1.0

    def test_cointegration_engle_granger(
        self,
        series_x: pd.Series,
        series_y: pd.Series
    ) -> Tuple[bool, float, float]:
        """Engle-Granger two-step cointegration test. Returns (is_cointegrated, test_stat, p_val)."""
        df = pd.DataFrame({"x": series_x, "y": series_y}).dropna()
        if len(df) < self.config.min_observations:
            return False, 0.0, 1.0

        try:
            score, p_val, _ = coint(df["y"].values, df["x"].values)
            is_coint = p_val < 0.05
            return is_coint, float(score), float(p_val)
        except Exception as e:
            logger.warning(f"Cointegration test failed: {e}")
            return False, 0.0, 1.0

    # =========================================================================
    # 6. RESIDUAL AUTOCORRELATION & LJUNG-BOX
    # =========================================================================

    def test_residual_autocorrelation(self, residuals: pd.Series, lags: int = 5) -> Tuple[float, float]:
        """Computes lag-1 autocorrelation and Ljung-Box test p-value."""
        r = residuals.dropna().values
        if len(r) < self.config.min_observations:
            return 0.0, 1.0

        acf_1 = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if len(r) > 1 else 0.0
        try:
            lb_res = acorr_ljungbox(r, lags=[min(lags, len(r) // 5)], return_df=True)
            lb_pvalue = float(lb_res["lb_pvalue"].iloc[0])
        except Exception:
            lb_pvalue = 1.0

        return acf_1, lb_pvalue

    # =========================================================================
    # 7. LEAD-LAG CROSS-CORRELATION
    # =========================================================================

    def compute_lead_lag_profile(
        self,
        returns_x: pd.Series,
        returns_y: pd.Series,
        max_lag: int = 10
    ) -> Dict[str, Any]:
        """Computes cross-correlation function Corr(X_t, Y_{t+tau}) for tau in [-max_lag, +max_lag].
        
        tau > 0: X leads Y (X moves first, Y responds later).
        tau < 0: Y leads X.
        tau = 0: Contemporaneous correlation.
        """
        df = pd.DataFrame({"x": returns_x, "y": returns_y}).dropna()
        if len(df) < self.config.min_observations:
            return {"lags": list(range(-max_lag, max_lag + 1)), "correlations": [0.0] * (2 * max_lag + 1), "optimal_lag": 0, "max_correlation": 0.0}

        lags = list(range(-max_lag, max_lag + 1))
        correlations = []

        for tau in lags:
            if tau != 0:
                c = df["x"].corr(df["y"].shift(-tau))
            else:
                c = df["x"].corr(df["y"])
            correlations.append(float(c) if not np.isnan(c) else 0.0)

        # Optimal leading lag
        opt_idx = int(np.argmax(np.abs(correlations)))
        optimal_lag = lags[opt_idx]
        max_corr = correlations[opt_idx]

        return {
            "lags": lags,
            "correlations": correlations,
            "optimal_lag": optimal_lag,
            "max_correlation": round(max_corr, 4),
            "x_leads_y": bool(optimal_lag > 0 and abs(max_corr) > 0.15)
        }

    # =========================================================================
    # 8. REGIME SEGMENTATION & CONDITIONAL RESPONSE
    # =========================================================================

    def segment_regimes(
        self,
        series: pd.Series,
        window: int = 30
    ) -> pd.Series:
        """Classifies observations into volatility regimes: LOW (0), MEDIUM (1), HIGH (2)."""
        rolling_vol = series.diff().rolling(window=window, min_periods=10).std()
        p33 = rolling_vol.quantile(0.33)
        p67 = rolling_vol.quantile(0.67)

        regimes = pd.Series(1, index=series.index) # default MEDIUM
        regimes[rolling_vol <= p33] = 0            # LOW
        regimes[rolling_vol > p67] = 2             # HIGH
        return regimes

    def evaluate_conditional_response(
        self,
        leading_delta: pd.Series,
        target_delta: pd.Series,
        threshold: float = 0.02,
        horizon_steps: int = 5
    ) -> Dict[str, Any]:
        """Calculates conditional expected move E[Delta Y_{t+h} | Delta X_t >= threshold] vs unconditional baseline."""
        df = pd.DataFrame({"dx": leading_delta, "dy": target_delta}).dropna()
        if len(df) < self.config.min_observations:
            return {"conditional_mean": 0.0, "baseline_mean": 0.0, "difference": 0.0, "p_value": 1.0, "sample_size": 0}

        # Forward target move
        fwd_target = df["dy"].rolling(window=horizon_steps).sum().shift(-horizon_steps)
        df["fwd_target"] = fwd_target
        df = df.dropna()

        # Impulse condition
        impulse_mask = df["dx"] >= threshold
        sample_size = int(np.sum(impulse_mask))

        if sample_size < 5:
            return {"conditional_mean": 0.0, "baseline_mean": 0.0, "difference": 0.0, "p_value": 1.0, "sample_size": sample_size}

        cond_moves = df.loc[impulse_mask, "fwd_target"].values
        base_moves = df.loc[~impulse_mask, "fwd_target"].values

        cond_mean = float(np.mean(cond_moves))
        base_mean = float(np.mean(base_moves))
        diff = cond_mean - base_mean

        t_stat, p_val = stats.ttest_ind(cond_moves, base_moves, equal_var=False)

        return {
            "conditional_mean": round(cond_mean, 6),
            "baseline_mean": round(base_mean, 6),
            "difference": round(diff, 6),
            "p_value": round(float(p_val) if not np.isnan(p_val) else 1.0, 4),
            "sample_size": sample_size,
        }

    # =========================================================================
    # 9. FULL STAT-ARB SUMMARY EVALUATION
    # =========================================================================

    def evaluate_stat_arb_candidate(
        self,
        train_x: pd.Series,
        train_y: pd.Series,
        test_x: Optional[pd.Series] = None,
        test_y: Optional[pd.Series] = None,
    ) -> StatArbMetrics:
        """Executes full deterministic stat-arb analysis estimating parameters strictly in-sample."""
        # 1. Estimate beta strictly in-sample
        beta, alpha = self.estimate_hedge_ratio(train_x, train_y)

        # 2. Spread calculation
        eval_x = test_x if test_x is not None else train_x
        eval_y = test_y if test_y is not None else train_y
        spread = self.compute_spread(eval_x, eval_y, beta, alpha)

        # 3. Mean reversion half-life
        half_life, theta, hl_pval = self.estimate_half_life(spread)

        # 4. ADF stationarity
        is_stat, adf_stat, adf_pval = self.test_stationarity_adf(spread)

        # 5. Cointegration
        is_coint, coint_stat, coint_pval = self.test_cointegration_engle_granger(eval_x, eval_y)

        # 6. Autocorrelation
        acf1, lb_pval = self.test_residual_autocorrelation(spread)

        # 7. Lead-lag profile
        ret_x = eval_x.diff().dropna()
        ret_y = eval_y.diff().dropna()
        lead_lag = self.compute_lead_lag_profile(ret_x, ret_y, max_lag=10)

        # 8. Spread capture simulation (Z-score mean reversion)
        z = self.compute_robust_mad_z_score(spread) if self.config.use_robust_mad else self.compute_z_score(spread)
        
        # Simple threshold entry/exit simulation
        gross_bps, net_bps, hit_rate, turnover, max_dd = self._simulate_spread_capture(spread, z)

        return StatArbMetrics(
            sample_size=len(spread),
            mean_spread=round(float(spread.mean()), 6),
            std_spread=round(float(spread.std()), 6),
            beta=round(beta, 4),
            half_life_steps=round(half_life, 2) if np.isfinite(half_life) else 9999.0,
            is_stationary=is_stat,
            adf_statistic=round(adf_stat, 4),
            adf_pvalue=round(adf_pval, 4),
            is_cointegrated=is_coint,
            cointegration_pvalue=round(coint_pval, 4),
            autocorrelation_lag1=round(acf1, 4),
            lead_lag_optimal_lag=lead_lag["optimal_lag"],
            lead_lag_max_correlation=lead_lag["max_correlation"],
            gross_spread_capture_bps=round(gross_bps, 2),
            net_spread_capture_bps=round(net_bps, 2),
            hit_rate=round(hit_rate, 4),
            turnover=round(turnover, 2),
            max_drawdown_bps=round(max_dd, 2),
            capacity_limit_usd=1000.0 # Default baseline before L2 book execution
        )

    def _simulate_spread_capture(
        self,
        spread: pd.Series,
        z_score: pd.Series
    ) -> Tuple[float, float, float, float, float]:
        """Simulates conservative z-score entry/exit on spread to measure capture and drawdown."""
        z_arr = z_score.values
        s_arr = spread.values
        n = len(z_arr)
        
        position = 0.0 # +1 (long spread), -1 (short spread)
        entry_spread = 0.0
        trades_pnl_bps = []
        equity = [0.0]

        for t in range(n):
            z_t = z_arr[t]
            s_t = s_arr[t]

            # Entry
            if position == 0.0:
                if z_t <= -self.config.z_score_threshold:
                    position = 1.0 # Long spread: expect spread to rise
                    entry_spread = s_t
                elif z_t >= self.config.z_score_threshold:
                    position = -1.0 # Short spread: expect spread to fall
                    entry_spread = s_t
            # Exit
            elif position == 1.0:
                if z_t >= -self.config.exit_z_score or z_t <= -self.config.stop_loss_z_score:
                    pnl = (s_t - entry_spread) * 10000.0 # in bps
                    trades_pnl_bps.append(pnl)
                    equity.append(equity[-1] + pnl)
                    position = 0.0
            elif position == -1.0:
                if z_t <= self.config.exit_z_score or z_t >= self.config.stop_loss_z_score:
                    pnl = (entry_spread - s_t) * 10000.0 # in bps
                    trades_pnl_bps.append(pnl)
                    equity.append(equity[-1] + pnl)
                    position = 0.0

        if not trades_pnl_bps:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        pnl_arr = np.array(trades_pnl_bps)
        gross_mean = float(np.mean(pnl_arr))
        # Conservative 2-leg round-trip friction ~ 30 bps
        net_mean = gross_mean - 30.0
        hit_rate = float(np.mean(pnl_arr > 0))
        turnover = float(len(trades_pnl_bps))

        # Max drawdown
        eq_arr = np.array(equity)
        peaks = np.maximum.accumulate(eq_arr)
        dds = peaks - eq_arr
        max_dd = float(np.max(dds)) if len(dds) > 0 else 0.0

        return gross_mean, net_mean, hit_rate, turnover, max_dd
