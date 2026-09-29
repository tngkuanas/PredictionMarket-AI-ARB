"""Phase 6: Upgraded Relative-Value Statistical Arbitrage Model.
Models target market B as a multi-variate, state-conditional function of:
ΔA_t, realized volatility, order-book liquidity, bid-ask spread, time to expiry, catalyst impulse, and regime.
Analyzes the residual:
    epsilon_t = B_t - B_hat_t
and evaluates whether unusually large residuals (|epsilon_t| >= k * sigma) subsequently mean-revert.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import adfuller

from src.phase6.config import Phase6Config

logger = logging.getLogger(__name__)


@dataclass
class ResidualAnalysisResult:
    """Statistical summary of relative-value model residual and mean-reversion dynamics."""
    r_squared: float
    residual_std: float
    adf_statistic: float
    adf_pvalue: float
    is_stationary: bool
    ou_kappa: float
    reversion_half_life_hours: float
    ou_t_stat: float
    ou_pvalue: float
    n_total_observations: int
    n_large_residuals: int
    mean_reversion_hit_rate: float
    mean_reversion_recovery_pp: float
    recovery_t_stat: float
    recovery_pvalue: float
    is_statistically_mean_reverting: bool
    verdict: str
    rejection_reason: Optional[str] = None


class RelativeValueStatArbModel:
    """Upgraded relative-value statistical arbitrage engine.
    Constructs state-conditional pricing models, extracts residuals, and audits mean reversion.
    """

    def __init__(self, config: Optional[Phase6Config] = None):
        self.config = config or Phase6Config()
        self.fitted_beta: Optional[np.ndarray] = None
        self.feature_names: List[str] = []

    def build_feature_matrix(
        self,
        series_a: pd.Series,
        series_b: pd.Series,
        spread_b: Optional[pd.Series] = None,
        liquidity_b: Optional[pd.Series] = None,
        time_to_expiry_days: Optional[pd.Series] = None,
        catalyst_threshold: float = 0.04,
        lookback_steps: int = 1,
    ) -> pd.DataFrame:
        """Construct state-conditional feature matrix aligning leading A and target B."""
        # Deduplicate indices to prevent pandas reindexing errors
        sa = series_a[~series_a.index.duplicated(keep="last")]
        sb = series_b[~series_b.index.duplicated(keep="last")]

        df = pd.DataFrame({"pa": sa, "pb": sb}).dropna().sort_index()
        if len(df) < 50:
            return pd.DataFrame()

        # 1. Delta A (catalyst impulse)
        df["delta_a"] = df["pa"] - df["pa"].shift(lookback_steps)

        # 2. Realized Volatility of A (24-period rolling std)
        rolling_vol = df["pa"].diff().rolling(window=24, min_periods=6).std()
        df["volatility_a"] = rolling_vol.fillna(rolling_vol.median() or 0.01)

        # 3. Target Bid-Ask Spread
        if spread_b is not None:
            sp = spread_b[~spread_b.index.duplicated(keep="last")]
            df["spread_b"] = sp.reindex(df.index).ffill().fillna(0.015)
        else:
            df["spread_b"] = 0.015

        # 4. Target Liquidity (normalized log-liquidity)
        if liquidity_b is not None:
            lq = liquidity_b[~liquidity_b.index.duplicated(keep="last")]
            raw_liq = lq.reindex(df.index).ffill().fillna(50000.0)
            df["liquidity_b"] = np.log10(np.clip(raw_liq, 1000.0, 10_000_000.0))
        else:
            df["liquidity_b"] = 4.7 # log10(50,000)

        # 5. Time to Expiration (days)
        if time_to_expiry_days is not None:
            df["time_to_expiry"] = time_to_expiry_days.reindex(df.index).ffill().fillna(30.0)
        else:
            # Linear decay from 90 days to 0 over length of sample
            t_span = np.linspace(90.0, 1.0, len(df))
            df["time_to_expiry"] = t_span

        # 6. Catalyst Impulse Indicator (binary)
        df["is_catalyst"] = (df["delta_a"].abs() >= catalyst_threshold).astype(float)

        # 7. Regime Indicator (High-Vol Regime = 1.0, Low-Vol = 0.0)
        median_vol = df["volatility_a"].median()
        df["regime_high_vol"] = (df["volatility_a"] > median_vol).astype(float)

        # Drop initial NaN rows created by lags
        return df.dropna()

    def fit_relative_value_model(self, df_is: pd.DataFrame) -> Tuple[pd.Series, np.ndarray, float]:
        """Fit in-sample multi-variate state-conditional model:
        B_hat_t = beta_0 + beta_1 * A_t + beta_2 * Delta_A_t + beta_3 * vol_t +
                  beta_4 * spread_t + beta_5 * time_t + beta_6 * (Delta_A_t * regime_t)
        Returns: (b_hat_series, beta_coefficients, r_squared)
        """
        X = self._extract_design_matrix(df_is)
        y = df_is["pb"].values

        # Ordinary Least Squares with L2 ridge stabilization (lambda = 1e-4)
        n_features = X.shape[1]
        ridge_diag = np.eye(n_features) * 1e-4
        ridge_diag[0, 0] = 0.0 # Don't regularize intercept

        beta = np.linalg.solve(X.T @ X + ridge_diag, X.T @ y)
        self.fitted_beta = beta

        y_hat = X @ beta
        residuals = y - y_hat
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_sq = float(1.0 - (ss_res / (ss_tot + 1e-9)))

        b_hat_series = pd.Series(y_hat, index=df_is.index)
        return b_hat_series, beta, r_sq

    def predict_fair_value(self, df: pd.DataFrame) -> pd.Series:
        """Predict expected fair-value B_hat using fitted model parameters."""
        if self.fitted_beta is None:
            raise ValueError("Model must be fitted before predicting fair value.")
        X = self._extract_design_matrix(df)
        y_hat = np.clip(X @ self.fitted_beta, 0.01, 0.99)
        return pd.Series(y_hat, index=df.index)

    def analyze_residuals_and_mean_reversion(
        self,
        df: pd.DataFrame,
        horizon_steps: int = 1,
        z_threshold: float = 1.5,
    ) -> ResidualAnalysisResult:
        """Compute residual:
            epsilon_t = B_t - B_hat_t
        and evaluate ADF stationarity, Ornstein-Uhlenbeck mean-reversion speed,
        and directional recovery of large residuals (|epsilon_t| >= z_threshold * sigma).
        """
        b_hat = self.predict_fair_value(df)
        residuals = df["pb"] - b_hat
        n_obs = len(residuals)

        if n_obs < 30:
            return ResidualAnalysisResult(
                r_squared=0.0, residual_std=0.0, adf_statistic=0.0, adf_pvalue=1.0,
                is_stationary=False, ou_kappa=0.0, reversion_half_life_hours=999.0,
                ou_t_stat=0.0, ou_pvalue=1.0, n_total_observations=n_obs,
                n_large_residuals=0, mean_reversion_hit_rate=0.0,
                mean_reversion_recovery_pp=0.0, recovery_t_stat=0.0, recovery_pvalue=1.0,
                is_statistically_mean_reverting=False, verdict="REJECTED_UNDERPOWERED",
                rejection_reason="Insufficient time-series observations for residual stat-arb (N < 30)."
            )

        res_std = float(residuals.std())
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((df["pb"] - df["pb"].mean()) ** 2)
        r_sq = float(1.0 - (ss_res / (ss_tot + 1e-9)))

        # 1. ADF Stationarity Test on Residuals
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=FutureWarning)
                adf_out = adfuller(residuals.values, autolag="AIC")
            adf_stat = float(adf_out[0])
            adf_pval = float(adf_out[1])
        except Exception:
            adf_stat = 0.0
            adf_pval = 1.0

        is_stationary = (adf_pval <= self.config.stationarity_pvalue_hurdle)

        # 2. Ornstein-Uhlenbeck / AR(1) Mean-Reversion Estimation
        # Delta epsilon_t = -kappa * epsilon_{t-1} + eta_t
        eps_lag = residuals.shift(1).dropna()
        delta_eps = (residuals - residuals.shift(1)).dropna()

        # OLS of delta_eps on eps_lag
        slope, intercept, r_val, p_val, std_err = stats.linregress(eps_lag, delta_eps)
        kappa = float(-slope) # Reversion rate
        ou_t_stat = float(-slope / (std_err + 1e-9))
        ou_pval = float(p_val)

        if kappa > 0:
            half_life_hours = float(np.log(2.0) / kappa)
        else:
            half_life_hours = 999.0

        # 3. Test Mean-Reversion of Unusually Large Residuals (|epsilon| >= z_threshold * sigma)
        threshold_val = z_threshold * res_std
        large_pos = residuals[residuals >= threshold_val].index
        large_neg = residuals[residuals <= -threshold_val].index
        all_large = residuals[residuals.abs() >= threshold_val].index
        n_large = len(all_large)

        recoveries = []
        hits = 0

        for t in all_large:
            loc = df.index.get_loc(t)
            if loc + horizon_steps < len(df):
                future_t = df.index[loc + horizon_steps]
                eps_t = residuals.loc[t]
                eps_future = residuals.loc[future_t]
                # Normalized recovery: if eps_t > 0, we want eps_future < eps_t (recovery = eps_t - eps_future > 0)
                # If eps_t < 0, we want eps_future > eps_t (recovery = eps_future - eps_t > 0)
                if eps_t > 0:
                    rec = eps_t - eps_future
                else:
                    rec = eps_future - eps_t
                recoveries.append(rec)
                if rec > 0:
                    hits += 1

        if len(recoveries) >= 5:
            hit_rate = float(hits / len(recoveries))
            mean_rec = float(np.mean(recoveries))
            t_rec, p_rec = stats.ttest_1samp(recoveries, 0.0)
            t_rec = float(t_rec) if not np.isnan(t_rec) else 0.0
            p_rec = float(p_rec) if not np.isnan(p_rec) else 1.0
        else:
            hit_rate = 0.0
            mean_rec = 0.0
            t_rec = 0.0
            p_rec = 1.0

        # 4. Final Stat-Arb Verdict Determination
        is_stat_mr = (
            is_stationary
            and kappa >= self.config.min_mean_reversion_kappa
            and half_life_hours <= self.config.max_half_life_hours
            and mean_rec > 0
            and p_rec <= 0.05
        )

        if not is_stationary:
            verdict = "REJECTED_NON_STATIONARY"
            reason = f"Residuals are non-stationary (ADF stat={adf_stat:.2f}, p={adf_pval:.3f} > {self.config.stationarity_pvalue_hurdle})."
        elif kappa <= 0:
            verdict = "REJECTED_DIVERGENT"
            reason = f"Spread diverges: OU kappa={kappa:.4f} <= 0."
        elif half_life_hours > self.config.max_half_life_hours:
            verdict = "REJECTED_SLOW_REVERSION"
            reason = f"Mean reversion half-life ({half_life_hours:.1f}h) exceeds maximum allowed ({self.config.max_half_life_hours:.0f}h)."
        elif n_large < 5 or p_rec > 0.05:
            verdict = "REJECTED_STATISTICALLY_INSIGNIFICANT"
            reason = f"Large residual recovery (+{mean_rec*100:.2f}%) not statistically significant (p={p_rec:.3f}, N={len(recoveries)})."
        else:
            verdict = "VALIDATED_RELATIVE_VALUE"
            reason = None

        return ResidualAnalysisResult(
            r_squared=r_sq,
            residual_std=res_std,
            adf_statistic=adf_stat,
            adf_pvalue=adf_pval,
            is_stationary=is_stationary,
            ou_kappa=kappa,
            reversion_half_life_hours=half_life_hours,
            ou_t_stat=ou_t_stat,
            ou_pvalue=ou_pval,
            n_total_observations=n_obs,
            n_large_residuals=n_large,
            mean_reversion_hit_rate=hit_rate,
            mean_reversion_recovery_pp=mean_rec,
            recovery_t_stat=t_rec,
            recovery_pvalue=p_rec,
            is_statistically_mean_reverting=is_stat_mr,
            verdict=verdict,
            rejection_reason=reason
        )

    def _extract_design_matrix(self, df: pd.DataFrame) -> np.ndarray:
        """Extract columns into numpy design matrix with intercept."""
        intercept = np.ones((len(df), 1))
        pa = df["pa"].values.reshape(-1, 1)
        delta_a = df["delta_a"].values.reshape(-1, 1)
        vol = df["volatility_a"].values.reshape(-1, 1)
        spread = df["spread_b"].values.reshape(-1, 1)
        time_rem = df["time_to_expiry"].values.reshape(-1, 1)
        regime_interaction = (df["delta_a"] * df["regime_high_vol"]).values.reshape(-1, 1)

        self.feature_names = [
            "intercept", "price_a", "delta_a", "volatility_a",
            "spread_b", "time_to_expiry", "delta_a_x_regime"
        ]
        return np.hstack([intercept, pa, delta_a, vol, spread, time_rem, regime_interaction])
