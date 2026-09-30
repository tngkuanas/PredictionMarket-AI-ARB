"""Microstructure Adversarial Engine:
1. Alternative Fill Models (Conservative Trade-Through vs Moderate Brownian Bridge vs Adversarial Volume-Depth).
2. Dynamic Queue Depletion Mechanics (Q_rem = Q_ahead + Q_new - Q_cancels - V_exec).
3. Partial Fill Modeling (depth-constrained fractional execution).
4. Market Impact & Inventory Capacity Curve ($10 -> $1,000).
5. Multi-Dimensional Cost Stress Matrix & Break-Even Analysis.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd

from src.phase9.config import Phase9Config, FillModel, CostRegime


@dataclass
class FillModelComparisonResult:
    model_name: str
    orders_n: int
    fills_n: int
    fill_rate_pct: float
    toxic_rate_pct: float
    mean_markout_pp: float
    unconditional_pnl_pp: float
    cumulative_pnl_usd: float
    annualized_sharpe: float
    verdict: str


@dataclass
class DynamicQueueResult:
    orders_n: int
    queue_exhausted_fills: int
    fill_rate_pct: float
    mean_queue_duration_sec: float
    toxic_fills_count: int
    mean_markout_pp: float
    cumulative_pnl_usd: float
    annualized_sharpe: float


@dataclass
class PartialFillResult:
    orders_n: int
    unfilled_count: int
    partial_fill_count: int
    full_fill_count: int
    mean_fill_fraction_pct: float
    total_volume_executed_usd: float
    cumulative_pnl_usd: float
    effective_pnl_per_dollar: float


@dataclass
class CapacityCurvePoint:
    order_size_usd: float
    fill_probability_pct: float
    market_impact_bps: float
    realized_spread_pp: float
    mean_markout_pp: float
    total_pnl_usd: float
    pnl_per_dollar_deployed: float
    annualized_sharpe: float
    max_capital_deployed_usd: float
    is_viable: bool


@dataclass
class CostStressResult:
    cost_regime: str
    half_spread_pp: float
    maker_fee_pp: float
    slippage_drag_pp: float
    latency_ms: float
    net_mean_markout_pp: float
    unconditional_pnl_pp: float
    cumulative_pnl_usd: float
    annualized_sharpe: float
    verdict: str


class MicrostructureAdversaryEngine:
    def __init__(self, config: Phase9Config):
        self.config = config

    def _resolve_snapshot(
        self, market_id: str, token_snapshots: Dict[str, pd.DataFrame], market_to_token: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        tkn = market_to_token.get(market_id, market_id) if market_to_token else market_id
        df = token_snapshots.get(tkn)
        if df is None:
            df = token_snapshots.get(market_id)
        return df

    def evaluate_fill_models(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        quote_distance_d: int = 1
    ) -> List[FillModelComparisonResult]:
        """Compare Conservative Trade-Through, Moderate Brownian Bridge, and Adversarial Volume-Depth."""
        results = []

        for model in [FillModel.CONSERVATIVE_TRADE_THROUGH, FillModel.MODERATE_BROWNIAN_BRIDGE, FillModel.ADVERSARIAL_VOLUME_DEPTH]:
            orders_total = len(events)
            fills = []
            trade_pnls = []
            toxic_count = 0

            for evt in events:
                t0 = evt["timestamp"]
                m_b = evt["market_b_id"]
                df_b = self._resolve_snapshot(m_b, token_snapshots, market_to_token)
                if df_b is None:
                    continue
                prices = df_b["yes_mid"].dropna().sort_index()
                future = prices[prices.index > t0]
                if future.empty:
                    continue

                past = prices[prices.index <= t0]
                p0 = float(past.iloc[-1]) if not past.empty else float(prices.iloc[0])
                p_next = float(future.iloc[0])
                pred_delta = evt["predicted_delta_15m"]
                side_buy = (pred_delta >= 0)

                quote_p = round(p0 - 0.0075 - (quote_distance_d * self.config.tick_size), 4) if side_buy else round(p0 + 0.0075 + (quote_distance_d * self.config.tick_size), 4)

                # 1. Fill Logic based on Model
                is_filled = False
                if model == FillModel.CONSERVATIVE_TRADE_THROUGH:
                    # Must strictly trade THROUGH the quote price
                    if side_buy:
                        is_filled = (p_next < quote_p)
                    else:
                        is_filled = (p_next > quote_p)

                elif model == FillModel.MODERATE_BROWNIAN_BRIDGE:
                    # Phase 7/8 standard barrier touch
                    dt = max(0.25, (future.index[0] - t0).total_seconds() / 3600.0)
                    vol = 0.025
                    if side_buy:
                        if p_next <= quote_p:
                            is_filled = True
                        else:
                            dist_0 = max(0.001, p0 - quote_p)
                            dist_1 = max(0.001, p_next - quote_p)
                            exponent = - (2.0 * dist_0 * dist_1) / ((vol ** 2) * dt)
                            p_touch = float(np.exp(np.clip(exponent, -25.0, 0.0))) * 0.70
                            # Deterministic pseudo-randomness
                            seed = int(pd.Timestamp(t0).timestamp()) + int(quote_p * 1000)
                            is_filled = (np.random.default_rng(seed).random() <= p_touch)
                    else:
                        if p_next >= quote_p:
                            is_filled = True
                        else:
                            dist_0 = max(0.001, quote_p - p0)
                            dist_1 = max(0.001, quote_p - p_next)
                            exponent = - (2.0 * dist_0 * dist_1) / ((vol ** 2) * dt)
                            p_touch = float(np.exp(np.clip(exponent, -25.0, 0.0))) * 0.70
                            seed = int(pd.Timestamp(t0).timestamp()) + int(quote_p * 1000)
                            is_filled = (np.random.default_rng(seed).random() <= p_touch)

                elif model == FillModel.ADVERSARIAL_VOLUME_DEPTH:
                    # Requires price touch AND adverse market excursion indicating substantial volume cleared the level
                    touch = (p_next <= quote_p) if side_buy else (p_next >= quote_p)
                    excursion_depth = abs(p_next - quote_p)
                    # Volume barrier: needs at least 0.2 cents penetration to assume fill
                    is_filled = touch and (excursion_depth >= 0.0020)

                if is_filled:
                    raw_markout = (p_next - quote_p) if side_buy else (quote_p - p_next)
                    # Deduct latency drag (150ms)
                    lat_drag = 0.0010
                    eff_markout = raw_markout - lat_drag
                    pnl_usd = eff_markout * self.config.order_size_usd
                    fills.append(eff_markout)
                    trade_pnls.append(pnl_usd)
                    if eff_markout < -0.005:
                        toxic_count += 1

            n_fills = len(fills)
            fill_p = float(n_fills / orders_total) if orders_total > 0 else 0.0
            if n_fills > 0:
                mean_m = float(np.mean(fills))
                tot_pnl = float(np.sum(trade_pnls))
                toxic_rate = float(toxic_count / n_fills)
                std_m = float(np.std(fills)) if len(fills) > 1 else 0.01
                sharpe = float((mean_m / (std_m + 1e-9)) * np.sqrt(252 * 4))
                uncond = fill_p * mean_m
            else:
                mean_m = 0.0
                tot_pnl = 0.0
                toxic_rate = 0.0
                sharpe = 0.0
                uncond = 0.0

            verdict = "SURVIVES_ADVERSARIAL_FILL" if tot_pnl > 0 and sharpe >= 1.0 else "FAILS_UNDER_STRICT_FILL"

            results.append(FillModelComparisonResult(
                model_name=model.value,
                orders_n=orders_total,
                fills_n=n_fills,
                fill_rate_pct=fill_p * 100.0,
                toxic_rate_pct=toxic_rate * 100.0,
                mean_markout_pp=mean_m,
                unconditional_pnl_pp=uncond,
                cumulative_pnl_usd=tot_pnl,
                annualized_sharpe=sharpe,
                verdict=verdict
            ))

        return results

    def simulate_dynamic_queue_depletion(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        quote_distance_d: int = 1
    ) -> DynamicQueueResult:
        """Simulate queue mechanics: Q_rem = Q_ahead + Q_new - Q_cancels - V_exec over 15 minutes."""
        orders_total = len(events)
        filled_records = []
        toxic_count = 0

        for evt in events:
            t0 = evt["timestamp"]
            m_b = evt["market_b_id"]
            df_b = self._resolve_snapshot(m_b, token_snapshots, market_to_token)
            if df_b is None:
                continue
            prices = df_b["yes_mid"].dropna().sort_index()
            future = prices[prices.index > t0]
            if future.empty:
                continue

            past = prices[prices.index <= t0]
            p0 = float(past.iloc[-1]) if not past.empty else float(prices.iloc[0])
            p_next = float(future.iloc[0])
            pred_delta = evt["predicted_delta_15m"]
            side_buy = (pred_delta >= 0)

            # Starting queue ahead at d=1: ~2,500 shares typical depth
            q_ahead = 2500.0
            quote_p = round(p0 - 0.0075 - (quote_distance_d * self.config.tick_size), 4) if side_buy else round(p0 + 0.0075 + (quote_distance_d * self.config.tick_size), 4)

            # 15 minute horizon in 1-minute steps
            # Q_rem = Q_ahead + arrivals - cancellations - executions
            is_exhausted = False
            exhaustion_time_sec = 900.0

            for sec in range(60, 901, 60):
                # Executed volume arriving at price level: proportional to move magnitude
                price_pressure = abs(p_next - p0) / 0.01  # Normalized to 1 cent
                exec_vol = self.config.queue_depletion_velocity * price_pressure * (sec / 900.0)
                cancels = q_ahead * self.config.queue_cancellation_rate * (sec / 900.0)
                new_arrivals = q_ahead * self.config.queue_new_arrival_rate * (sec / 900.0)

                q_rem = q_ahead + new_arrivals - cancels - exec_vol
                if q_rem <= 0:
                    is_exhausted = True
                    exhaustion_time_sec = sec
                    break

            if is_exhausted:
                raw_markout = (p_next - quote_p) if side_buy else (quote_p - p_next)
                eff_markout = raw_markout - 0.0010
                pnl_usd = eff_markout * self.config.order_size_usd
                filled_records.append({
                    "markout": eff_markout,
                    "pnl": pnl_usd,
                    "duration": exhaustion_time_sec
                })
                if eff_markout < -0.005:
                    toxic_count += 1

        n_f = len(filled_records)
        fill_p = float(n_f / orders_total) if orders_total > 0 else 0.0
        if n_f > 0:
            m_list = [r["markout"] for r in filled_records]
            dur_list = [r["duration"] for r in filled_records]
            mean_m = float(np.mean(m_list))
            std_m = float(np.std(m_list)) if len(m_list) > 1 else 0.01
            tot_pnl = float(sum(r["pnl"] for r in filled_records))
            sharpe = float((mean_m / (std_m + 1e-9)) * np.sqrt(252 * 4))
            mean_dur = float(np.mean(dur_list))
        else:
            mean_m = 0.0
            tot_pnl = 0.0
            sharpe = 0.0
            mean_dur = 0.0

        return DynamicQueueResult(
            orders_n=orders_total,
            queue_exhausted_fills=n_f,
            fill_rate_pct=fill_p * 100.0,
            mean_queue_duration_sec=mean_dur,
            toxic_fills_count=toxic_count,
            mean_markout_pp=mean_m,
            cumulative_pnl_usd=tot_pnl,
            annualized_sharpe=sharpe
        )

    def evaluate_partial_fills(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str],
        quote_distance_d: int = 1
    ) -> PartialFillResult:
        """Model realistic partial fills: size execution constrained by available CLOB depth."""
        orders_total = len(events)
        fill_fractions = []
        executed_volumes = []
        pnls = []

        unfilled = 0
        partial = 0
        full = 0

        for evt in events:
            t0 = evt["timestamp"]
            m_b = evt["market_b_id"]
            df_b = self._resolve_snapshot(m_b, token_snapshots, market_to_token)
            if df_b is None:
                continue
            prices = df_b["yes_mid"].dropna().sort_index()
            future = prices[prices.index > t0]
            if future.empty:
                continue

            past = prices[prices.index <= t0]
            p0 = float(past.iloc[-1]) if not past.empty else float(prices.iloc[0])
            p_next = float(future.iloc[0])
            pred_delta = evt["predicted_delta_15m"]
            side_buy = (pred_delta >= 0)

            quote_p = round(p0 - 0.0075 - (quote_distance_d * self.config.tick_size), 4) if side_buy else round(p0 + 0.0075 + (quote_distance_d * self.config.tick_size), 4)

            # Check if excursion touches quote
            is_touch = (p_next <= quote_p) if side_buy else (p_next >= quote_p)
            if not is_touch:
                unfilled += 1
                fill_fractions.append(0.0)
                continue

            # Fractional depth: depth available depends on excursion penetration
            penetration = abs(p_next - quote_p)
            if penetration < 0.001:
                fraction = 0.25
                partial += 1
            elif penetration < 0.003:
                fraction = 0.65
                partial += 1
            else:
                fraction = 1.0
                full += 1

            raw_markout = (p_next - quote_p) if side_buy else (quote_p - p_next)
            eff_markout = raw_markout - 0.0010
            exec_usd = self.config.order_size_usd * fraction
            pnl_usd = eff_markout * exec_usd

            fill_fractions.append(fraction)
            executed_volumes.append(exec_usd)
            pnls.append(pnl_usd)

        tot_pnl = float(sum(pnls))
        tot_vol = float(sum(executed_volumes))
        mean_frac = float(np.mean(fill_fractions)) * 100.0 if fill_fractions else 0.0
        pnl_per_dollar = float(tot_pnl / tot_vol) if tot_vol > 0 else 0.0

        return PartialFillResult(
            orders_n=orders_total,
            unfilled_count=unfilled,
            partial_fill_count=partial,
            full_fill_count=full,
            mean_fill_fraction_pct=mean_frac,
            total_volume_executed_usd=tot_vol,
            cumulative_pnl_usd=tot_pnl,
            effective_pnl_per_dollar=pnl_per_dollar
        )

    def evaluate_capacity_curve(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str]
    ) -> List[CapacityCurvePoint]:
        """Trace capacity curve: evaluate order sizes from $10 to $1,000 to find alpha exhaustion point."""
        curve_points = []
        base_depth_usd = 2500.0  # Average Polymarket top-tier level depth

        for size in self.config.capacity_curve_sizes_usd:
            # Sqrt price impact: Impact_bps = 15.0 * sqrt(Size / BaseDepth)
            impact_bps = 15.0 * np.sqrt(size / base_depth_usd)
            impact_pp = impact_bps / 10000.0

            filled_records = []
            for evt in events:
                t0 = evt["timestamp"]
                m_b = evt["market_b_id"]
                df_b = self._resolve_snapshot(m_b, token_snapshots, market_to_token)
                if df_b is None:
                    continue
                prices = df_b["yes_mid"].dropna().sort_index()
                future = prices[prices.index > t0]
                if future.empty:
                    continue

                past = prices[prices.index <= t0]
                p0 = float(past.iloc[-1]) if not past.empty else float(prices.iloc[0])
                p_next = float(future.iloc[0])
                pred_delta = evt["predicted_delta_15m"]
                side_buy = (pred_delta >= 0)

                quote_p = round(p0 - 0.0075 - 0.005, 4) if side_buy else round(p0 + 0.0075 + 0.005, 4)
                touch = (p_next <= quote_p) if side_buy else (p_next >= quote_p)

                # Fill probability attenuates as order size grows relative to depth
                size_fill_penalty = min(0.60, 0.40 * (size / base_depth_usd))
                p_fill = 0.55 * (1.0 - size_fill_penalty)

                seed = int(pd.Timestamp(t0).timestamp()) + int(size)
                is_filled = touch and (np.random.default_rng(seed).random() <= p_fill)

                if is_filled:
                    raw_markout = (p_next - quote_p) if side_buy else (quote_p - p_next)
                    # Markout degrades under market impact
                    net_markout = raw_markout - 0.0010 - impact_pp
                    pnl_usd = net_markout * size
                    filled_records.append({
                        "markout": net_markout,
                        "pnl": pnl_usd
                    })

            n_f = len(filled_records)
            fill_p = float(n_f / len(events)) if events else 0.0
            if n_f > 0:
                m_arr = [r["markout"] for r in filled_records]
                mean_m = float(np.mean(m_arr))
                std_m = float(np.std(m_arr)) if len(m_arr) > 1 else 0.01
                tot_pnl = float(sum(r["pnl"] for r in filled_records))
                sharpe = float((mean_m / (std_m + 1e-9)) * np.sqrt(252 * 4))
                pnl_per_dollar = float(tot_pnl / (size * n_f))
            else:
                mean_m = 0.0
                tot_pnl = 0.0
                sharpe = 0.0
                pnl_per_dollar = 0.0

            is_viable = (tot_pnl > 0 and sharpe >= 1.0)

            curve_points.append(CapacityCurvePoint(
                order_size_usd=size,
                fill_probability_pct=fill_p * 100.0,
                market_impact_bps=impact_bps,
                realized_spread_pp=0.0075,
                mean_markout_pp=mean_m,
                total_pnl_usd=tot_pnl,
                pnl_per_dollar_deployed=pnl_per_dollar,
                annualized_sharpe=sharpe,
                max_capital_deployed_usd=min(2500.0, size * n_f),
                is_viable=is_viable
            ))

        return curve_points

    def evaluate_cost_stress_matrix(
        self,
        events: List[Dict[str, Any]],
        token_snapshots: Dict[str, pd.DataFrame],
        market_to_token: Dict[str, str]
    ) -> List[CostStressResult]:
        """Stress every cost assumption: Optimistic, Base, Conservative, Severe."""
        results = []

        for regime_name, params in self.config.cost_regimes.items():
            half_spread = params["half_spread"]
            fee_rate = params["maker_fee_rate"]
            slippage = params["slippage_drag"]
            lat_ms = params["latency_ms"]

            filled_records = []
            orders_total = len(events)

            for evt in events:
                t0 = evt["timestamp"]
                m_b = evt["market_b_id"]
                df_b = self._resolve_snapshot(m_b, token_snapshots, market_to_token)
                if df_b is None:
                    continue
                prices = df_b["yes_mid"].dropna().sort_index()
                future = prices[prices.index > t0]
                if future.empty:
                    continue

                past = prices[prices.index <= t0]
                p0 = float(past.iloc[-1]) if not past.empty else float(prices.iloc[0])
                p_next = float(future.iloc[0])
                pred_delta = evt["predicted_delta_15m"]
                side_buy = (pred_delta >= 0)

                quote_p = round(p0 - half_spread - 0.005, 4) if side_buy else round(p0 + half_spread + 0.005, 4)
                touch = (p_next <= quote_p) if side_buy else (p_next >= quote_p)

                # Latency adverse drift
                lat_drift = 0.025 * np.sqrt(lat_ms / (3600.0 * 1000.0)) * 1.5
                seed = int(pd.Timestamp(t0).timestamp()) + int(lat_ms)
                is_filled = touch and (np.random.default_rng(seed).random() <= 0.50)

                if is_filled:
                    raw_markout = (p_next - quote_p) if side_buy else (quote_p - p_next)
                    net_markout = raw_markout - fee_rate - slippage - lat_drift
                    pnl_usd = net_markout * self.config.order_size_usd
                    filled_records.append(net_markout)

            n_f = len(filled_records)
            fill_p = float(n_f / orders_total) if orders_total > 0 else 0.0
            if n_f > 0:
                mean_m = float(np.mean(filled_records))
                std_m = float(np.std(filled_records)) if len(filled_records) > 1 else 0.01
                tot_pnl = float(mean_m * self.config.order_size_usd * n_f)
                sharpe = float((mean_m / (std_m + 1e-9)) * np.sqrt(252 * 4))
                uncond = fill_p * mean_m
            else:
                mean_m = 0.0
                tot_pnl = 0.0
                sharpe = 0.0
                uncond = 0.0

            verdict = "NET_PROFITABLE" if tot_pnl > 0 and sharpe >= 1.0 else "FRICTION_BREACH"

            results.append(CostStressResult(
                cost_regime=regime_name,
                half_spread_pp=half_spread,
                maker_fee_pp=fee_rate,
                slippage_drag_pp=slippage,
                latency_ms=lat_ms,
                net_mean_markout_pp=mean_m,
                unconditional_pnl_pp=uncond,
                cumulative_pnl_usd=tot_pnl,
                annualized_sharpe=sharpe,
                verdict=verdict
            ))

        return results
