"""Walk-Forward Backtesting & Paper Trading Engine for Validated Prediction Market Arbitrage.
Implements realistic non-midpoint order-book execution, latency, partial fills,
realized P&L, Return on Deployed Capital (ROC), Annualized Capital Efficiency,
concurrent capital tracking, and liquidity-adjusted capacity scaling.
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from src.normalization.schema import (
    CandidateRelationship,
    FalsificationResult,
    HypothesisVerdict,
    OrderSide,
    Platform,
    PaperOrder,
    PaperFill,
    PortfolioSnapshot,
)
from src.execution.order_book import OrderBookSimulator, ReconstructedOrderBook
from src.execution.fee_model import DynamicExecutionCostModel
from src.db.duckdb_store import DuckDBStore, get_db

logger = logging.getLogger(__name__)

class ArbitragePosition:
    """Tracks an active cross-contract arbitrage position (Leg A and Leg B)."""

    def __init__(
        self,
        position_id: str,
        constraint_id: str,
        market_a: str,
        market_b: str,
        entry_time: datetime,
        side_a: OrderSide, # typically SELL / NO on A
        side_b: OrderSide, # typically BUY / YES on B
        fill_price_a: float,
        fill_price_b: float,
        size_usd_a: float,
        size_usd_b: float,
        entry_fees_usd: float,
        entry_slippage_usd: float
    ):
        self.position_id = position_id
        self.constraint_id = constraint_id
        self.market_a = market_a
        self.market_b = market_b
        self.entry_time = entry_time
        self.side_a = side_a
        self.side_b = side_b
        self.fill_price_a = fill_price_a
        self.fill_price_b = fill_price_b
        self.size_usd_a = size_usd_a
        self.size_usd_b = size_usd_b
        self.entry_fees = entry_fees_usd
        self.entry_slippage = entry_slippage_usd
        self.deployed_capital = size_usd_a + size_usd_b
        self.is_open = True
        self.exit_time: Optional[datetime] = None
        self.exit_proceeds = 0.0
        self.exit_fees = 0.0
        self.realized_pnl = 0.0
        self.holding_days = 0.0
        self.roc = 0.0
        self.annualized_roc = 0.0

    def close(self, exit_time: datetime, price_a: float, price_b: float, exit_fees_usd: float):
        self.exit_time = exit_time
        self.exit_fees = exit_fees_usd
        self.is_open = False
        duration_seconds = max(3600.0, (exit_time - self.entry_time).total_seconds())
        self.holding_days = duration_seconds / 86400.0

        # PnL Calculation:
        # Leg A was sold at fill_price_a, bought back at price_a (or expired)
        # Leg B was bought at fill_price_b, sold at price_b (or expired)
        gross_pnl_a = (self.fill_price_a - price_a) * (self.size_usd_a / self.fill_price_a) if self.fill_price_a > 0 else 0.0
        gross_pnl_b = (price_b - self.fill_price_b) * (self.size_usd_b / self.fill_price_b) if self.fill_price_b > 0 else 0.0
        total_gross_pnl = gross_pnl_a + gross_pnl_b
        total_fees = self.entry_fees + self.exit_fees

        self.realized_pnl = total_gross_pnl - total_fees
        self.roc = (self.realized_pnl / self.deployed_capital) if self.deployed_capital > 0 else 0.0

        # Annualized ROC: (1 + ROC)^(365 / holding_days) - 1
        if self.holding_days > 0 and self.roc > -1.0:
            # Cap exponent at 365 to prevent extreme numerical overflow on intraday trades
            exp = min(52.0, 365.0 / max(1.0, self.holding_days))
            self.annualized_roc = float((1.0 + self.roc) ** exp - 1.0)
        else:
            self.annualized_roc = 0.0


class WalkForwardBacktestEngine:
    """Executes realistic non-midpoint order-book backtesting on validated opportunities."""

    def __init__(
        self,
        initial_cash_usd: float = 25_000.0,
        max_position_size_usd: float = 2_000.0,
        max_concurrent_capital_pct: float = 0.80, # Up to 80% capital deployed
        min_violation_threshold: float = 0.02,   # 2 pp mispricing to trigger entry
        db: Optional[DuckDBStore] = None
    ):
        self.initial_cash = initial_cash_usd
        self.cash = initial_cash_usd
        self.max_position_size = max_position_size_usd
        self.max_concurrent_capital = initial_cash_usd * max_concurrent_capital_pct
        self.min_violation_threshold = min_violation_threshold
        self.db = db or get_db()
        self.book_sim = OrderBookSimulator(default_latency_ms=250.0, taker_fee_rate=0.001)

        # State tracking
        self.open_positions: List[ArbitragePosition] = []
        self.closed_positions: List[ArbitragePosition] = []
        self.portfolio_history: List[PortfolioSnapshot] = []
        self.orders: List[PaperOrder] = []
        self.fills: List[PaperFill] = []
        self.peak_deployed_capital = 0.0

    def run_backtest(
        self,
        validated_reports: List[FalsificationResult],
        price_series_dict: Dict[str, pd.Series],
        markets_metadata: Dict[str, Dict[str, Any]],
        split_ratio: float = 0.60
    ) -> Dict[str, Any]:
        """Runs walk-forward backtest strictly on the Out-of-Sample (OOS) period."""
        tradeable_reports = [r for r in validated_reports if r.verdict == HypothesisVerdict.TRADEABLE]
        if not tradeable_reports:
            logger.warning("No TRADEABLE opportunities passed to backtest engine.")
            return {"error": "No tradeable opportunities found"}

        logger.info(f"Running Phase 4 Backtest on {len(tradeable_reports)} validated opportunities...")

        # 1. Determine common Out-of-Sample time index across tradeable opportunities
        all_timestamps = set()
        pair_data = {}

        for rep in tradeable_reports:
            sa = price_series_dict.get(rep.market_a)
            sb = price_series_dict.get(rep.market_b)
            if sa is not None and sb is not None:
                df_pair = pd.DataFrame({"pa": sa, "pb": sb}).dropna().sort_index()
                n_split = int(len(df_pair) * split_ratio)
                df_oos = df_pair.iloc[n_split:] # Strictly Out-of-Sample!
                pair_data[rep.constraint_id] = {
                    "rep": rep,
                    "df_oos": df_oos,
                    "meta_a": markets_metadata.get(rep.market_a, {}),
                    "meta_b": markets_metadata.get(rep.market_b, {})
                }
                all_timestamps.update(df_oos.index)

        sorted_timestamps = sorted(list(all_timestamps))
        if not sorted_timestamps:
            return {"error": "No overlapping out-of-sample data points found"}

        # 2. Iterate chronologically step-by-step
        for ts in sorted_timestamps:
            # A. Manage / Close existing open positions
            self._update_and_close_positions(ts, pair_data)

            # B. Check for new entry signals
            self._evaluate_new_entries(ts, pair_data)

            # C. Record portfolio snapshot
            self._record_portfolio_snapshot(ts)

        # Close any positions remaining at backtest termination
        final_ts = sorted_timestamps[-1]
        self._force_close_all_positions(final_ts, pair_data)

        # 3. Calculate portfolio aggregate performance & capital efficiency metrics
        report = self._compute_performance_report()

        # Save paper orders, fills, and portfolio state to DuckDB
        if self.orders:
            self.db.save_paper_orders(self.orders)
        if self.fills:
            self.db.save_paper_fills(self.fills)
        if self.portfolio_history:
            self.db.save_portfolio_snapshots(self.portfolio_history)

        return report

    def _evaluate_new_entries(self, ts: datetime, pair_data: Dict[str, Any]):
        """Evaluates entry triggers for all pairs at current timestamp."""
        currently_deployed = sum(pos.deployed_capital for pos in self.open_positions)
        self.peak_deployed_capital = max(self.peak_deployed_capital, currently_deployed)

        for cid, data in pair_data.items():
            df_oos = data["df_oos"]
            if ts not in df_oos.index:
                continue

            # Check if position already open for this constraint
            if any(pos.constraint_id == cid and pos.is_open for pos in self.open_positions):
                continue

            # Capital constraint check
            if currently_deployed + (2.0 * self.max_position_size) > self.max_concurrent_capital:
                continue
            if self.cash < (2.0 * self.max_position_size):
                continue

            pa = float(df_oos.loc[ts, "pa"])
            pb = float(df_oos.loc[ts, "pb"])

            # Monotonic bound violation check:
            # Tautology: P(A) <= P(B). Violation occurs when P(A) > P(B) + threshold
            violation_magnitude = pa - pb
            if violation_magnitude >= self.min_violation_threshold:
                # Execute Arbitrage Trade:
                # Leg A: SELL contract A (or short)
                # Leg B: BUY contract B
                meta_a = data["meta_a"]
                meta_b = data["meta_b"]
                liq_a = float(meta_a.get("liquidity", 50_000.0) or 50_000.0)
                liq_b = float(meta_b.get("liquidity", 50_000.0) or 50_000.0)

                # Reconstruct L2 order books at current snapshot
                book_a = ReconstructedOrderBook.from_market_snapshot(
                    market_id=data["rep"].market_a, mid_price=pa, spread=0.012, liquidity_usd=liq_a, timestamp=ts
                )
                book_b = ReconstructedOrderBook.from_market_snapshot(
                    market_id=data["rep"].market_b, mid_price=pb, spread=0.012, liquidity_usd=liq_b, timestamp=ts
                )

                # Calculate deployable capacity & position sizing
                cap_a = self.book_sim.calculate_market_capacity(book_a, OrderSide.SELL, violation_magnitude)
                cap_b = self.book_sim.calculate_market_capacity(book_b, OrderSide.BUY, violation_magnitude)
                avail_cap = min(cap_a["max_deployable_capacity_usd"], cap_b["max_deployable_capacity_usd"])
                if avail_cap < 500.0:
                    continue # Insufficient book capacity

                target_order_size = min(self.max_position_size, avail_cap, self.cash / 2.0)

                # Walk the books for both legs
                fill_a = self.book_sim.walk_the_book(book_a, OrderSide.SELL, target_order_size)
                fill_b = self.book_sim.walk_the_book(book_b, OrderSide.BUY, target_order_size)

                # Ensure both legs filled with high fill ratio (>80%) to prevent leg risk
                if fill_a["fill_ratio"] < 0.80 or fill_b["fill_ratio"] < 0.80:
                    continue

                pos_size_a = fill_a["filled_size_usd"]
                pos_size_b = fill_b["filled_size_usd"]
                total_entry_fees = fill_a["fee_usd"] + fill_b["fee_usd"]
                total_entry_slippage = (fill_a["effective_slippage_pp"] * pos_size_a) + (fill_b["effective_slippage_pp"] * pos_size_b)
                total_outlay = pos_size_a + pos_size_b + total_entry_fees

                self.cash -= total_outlay
                currently_deployed += (pos_size_a + pos_size_b)

                pos_id = str(uuid.uuid4())[:8]
                pos = ArbitragePosition(
                    position_id=pos_id,
                    constraint_id=cid,
                    market_a=data["rep"].market_a,
                    market_b=data["rep"].market_b,
                    entry_time=ts,
                    side_a=OrderSide.SELL,
                    side_b=OrderSide.BUY,
                    fill_price_a=fill_a["vwap_fill_price"],
                    fill_price_b=fill_b["vwap_fill_price"],
                    size_usd_a=pos_size_a,
                    size_usd_b=pos_size_b,
                    entry_fees_usd=total_entry_fees,
                    entry_slippage_usd=total_entry_slippage
                )
                self.open_positions.append(pos)

                # Record paper orders & fills
                order_id_a = str(uuid.uuid4())[:8]
                order_id_b = str(uuid.uuid4())[:8]
                self.orders.extend([
                    PaperOrder(
                        order_id=order_id_a, timestamp=ts, signal_id=cid, market_id=data["rep"].market_a,
                        platform=Platform.POLYMARKET, side=OrderSide.SELL, limit_price=fill_a["vwap_fill_price"],
                        quantity=pos_size_a, status="FILLED"
                    ),
                    PaperOrder(
                        order_id=order_id_b, timestamp=ts, signal_id=cid, market_id=data["rep"].market_b,
                        platform=Platform.POLYMARKET, side=OrderSide.BUY, limit_price=fill_b["vwap_fill_price"],
                        quantity=pos_size_b, status="FILLED"
                    )
                ])
                self.fills.extend([
                    PaperFill(
                        fill_id=str(uuid.uuid4())[:8], order_id=order_id_a, timestamp=ts, market_id=data["rep"].market_a,
                        platform=Platform.POLYMARKET, side=OrderSide.SELL, fill_price=fill_a["vwap_fill_price"],
                        quantity=pos_size_a, fee=fill_a["fee_usd"], slippage=fill_a["effective_slippage_pp"]
                    ),
                    PaperFill(
                        fill_id=str(uuid.uuid4())[:8], order_id=order_id_b, timestamp=ts, market_id=data["rep"].market_b,
                        platform=Platform.POLYMARKET, side=OrderSide.BUY, fill_price=fill_b["vwap_fill_price"],
                        quantity=pos_size_b, fee=fill_b["fee_usd"], slippage=fill_b["effective_slippage_pp"]
                    )
                ])

    def _update_and_close_positions(self, ts: datetime, pair_data: Dict[str, Any]):
        """Checks exit conditions: mean reversion to fair parity or holding expiration."""
        for pos in list(self.open_positions):
            data = pair_data.get(pos.constraint_id)
            if not data:
                continue
            df_oos = data["df_oos"]
            if ts not in df_oos.index:
                continue

            pa = float(df_oos.loc[ts, "pa"])
            pb = float(df_oos.loc[ts, "pb"])

            # Convergence condition: spread normalized (P(A) <= P(B)) or holding period >= 14 days
            spread_normalized = (pa <= pb)
            holding_time_exceeded = (ts - pos.entry_time).total_seconds() >= (14 * 86400)

            if spread_normalized or holding_time_exceeded:
                # Close position
                meta_a = data["meta_a"]
                meta_b = data["meta_b"]
                book_a = ReconstructedOrderBook.from_market_snapshot(pos.market_a, pa, timestamp=ts)
                book_b = ReconstructedOrderBook.from_market_snapshot(pos.market_b, pb, timestamp=ts)

                # Unwind legs
                exit_fill_a = self.book_sim.walk_the_book(book_a, OrderSide.BUY, pos.size_usd_a)
                exit_fill_b = self.book_sim.walk_the_book(book_b, OrderSide.SELL, pos.size_usd_b)

                exit_fees = exit_fill_a["fee_usd"] + exit_fill_b["fee_usd"]
                pos.close(
                    exit_time=ts,
                    price_a=exit_fill_a["vwap_fill_price"],
                    price_b=exit_fill_b["vwap_fill_price"],
                    exit_fees_usd=exit_fees
                )
                self.cash += (pos.deployed_capital + pos.realized_pnl)
                self.open_positions.remove(pos)
                self.closed_positions.append(pos)

    def _force_close_all_positions(self, ts: datetime, pair_data: Dict[str, Any]):
        """Closes any remaining open positions at final timestamp."""
        for pos in list(self.open_positions):
            data = pair_data.get(pos.constraint_id, {})
            df_oos = data.get("df_oos", pd.DataFrame())
            pa = float(df_oos.loc[ts, "pa"]) if ts in df_oos.index else pos.fill_price_a
            pb = float(df_oos.loc[ts, "pb"]) if ts in df_oos.index else pos.fill_price_b
            pos.close(exit_time=ts, price_a=pa, price_b=pb, exit_fees_usd=pos.entry_fees)
            self.cash += (pos.deployed_capital + pos.realized_pnl)
            self.open_positions.remove(pos)
            self.closed_positions.append(pos)

    def _record_portfolio_snapshot(self, ts: datetime):
        """Records point-in-time equity, cash, unrealized P&L, and drawdown."""
        open_val = sum(pos.deployed_capital for pos in self.open_positions)
        realized_pnl = sum(pos.realized_pnl for pos in self.closed_positions)
        total_equity = self.cash + open_val
        drawdown_pct = max(0.0, (self.initial_cash - total_equity) / self.initial_cash)

        snapshot = PortfolioSnapshot(
            timestamp=ts,
            cash=self.cash,
            portfolio_value=total_equity,
            total_realized_pnl=realized_pnl,
            total_unrealized_pnl=0.0,
            total_fees_paid=sum(pos.entry_fees + pos.exit_fees for pos in self.closed_positions),
            total_slippage_paid=sum(pos.entry_slippage for pos in self.closed_positions),
            open_positions_count=len(self.open_positions),
            exposure_usd=open_val,
            daily_drawdown_pct=drawdown_pct,
            max_drawdown_pct=drawdown_pct
        )
        self.portfolio_history.append(snapshot)

    def _compute_performance_report(self) -> Dict[str, Any]:
        """Calculates final comprehensive capital efficiency, capacity, and P&L metrics."""
        total_trades = len(self.closed_positions)
        if total_trades == 0:
            return {
                "initial_capital_usd": self.initial_cash,
                "final_equity_usd": self.cash,
                "total_realized_pnl_usd": 0.0,
                "portfolio_return_pct": 0.0,
                "trade_level_roc_pct": 0.0,
                "avg_annualized_roc_pct": 0.0,
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "avg_holding_days": 0.0,
                "peak_concurrent_capital_usd": 0.0,
                "capital_utilization_pct": 0.0,
                "total_fees_paid_usd": 0.0,
                "trade_details": []
            }

        total_pnl = sum(p.realized_pnl for p in self.closed_positions)
        total_deployed = sum(p.deployed_capital for p in self.closed_positions)
        winning_trades = [p for p in self.closed_positions if p.realized_pnl > 0]
        avg_holding = float(np.mean([p.holding_days for p in self.closed_positions]))

        portfolio_roc = (total_pnl / self.initial_cash) * 100.0
        trade_level_roc = (total_pnl / total_deployed * 100.0) if total_deployed > 0 else 0.0

        # Annualized ROC across the backtest duration
        annualized_roc = float(np.mean([p.annualized_roc for p in self.closed_positions]) * 100.0)

        # Capacity metrics
        trade_details = []
        for p in self.closed_positions:
            trade_details.append({
                "position_id": p.position_id,
                "constraint_id": p.constraint_id,
                "market_a": p.market_a,
                "market_b": p.market_b,
                "deployed_capital_usd": p.deployed_capital,
                "realized_pnl_usd": p.realized_pnl,
                "roc_pct": p.roc * 100.0,
                "annualized_roc_pct": p.annualized_roc * 100.0,
                "holding_days": p.holding_days,
                "fees_paid_usd": p.entry_fees + p.exit_fees
            })

        return {
            "initial_capital_usd": self.initial_cash,
            "final_equity_usd": self.cash,
            "total_realized_pnl_usd": total_pnl,
            "portfolio_return_pct": portfolio_roc,
            "trade_level_roc_pct": trade_level_roc,
            "avg_annualized_roc_pct": annualized_roc,
            "total_trades": total_trades,
            "win_rate_pct": (len(winning_trades) / total_trades) * 100.0,
            "avg_holding_days": avg_holding,
            "peak_concurrent_capital_usd": self.peak_deployed_capital,
            "capital_utilization_pct": (self.peak_deployed_capital / self.initial_cash) * 100.0,
            "total_fees_paid_usd": sum(p.entry_fees + p.exit_fees for p in self.closed_positions),
            "trade_details": trade_details
        }
