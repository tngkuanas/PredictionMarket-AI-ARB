"""Capital-at-Risk and P&L Calculation Module for Phase 10A.10-D.

Enforces mathematically exact accounting:
- capital_at_risk = entry_price * quantity + fees + slippage_cost
- if win: gross_pnl = quantity * (1.0 - entry_price)
- if loss: gross_pnl = -quantity * entry_price
- net_pnl = gross_pnl - fees - slippage_cost - lockup_cost
- net_return = net_pnl / capital_at_risk
- net_ev_bps = net_return * 10,000

Strictly distinguishes between dollar price discount ($1 - p) and percentage ROI ((1 - p) / p).
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class TradePnLResult:
    """Exact financial accounting result for a single execution."""
    entry_price: float
    quantity: float
    notional_usd: float
    capital_at_risk_usd: float
    settlement_value: float
    is_win: bool
    gross_pnl_usd: float
    gross_return: float
    gross_bps: float
    fee_usd: float
    fee_bps: float
    slippage_usd: float
    slippage_bps: float
    lockup_cost_usd: float
    lockup_bps: float
    net_pnl_usd: float
    net_return: float
    net_ev_bps: float
    price_discount_cents: float
    price_discount_bps: float


class CapitalAndPnLCalculator:
    """Computes exact capital at risk, net P&L, ROI, and bps."""

    @classmethod
    def compute_trade_pnl(
        cls,
        entry_price: float,
        quantity: float,
        settlement_value: float,
        fee_bps: float = 5.0,
        slippage_bps: float = 0.0,
        lockup_bps: float = 2.0,
    ) -> TradePnLResult:
        """Computes exact trade economics.

        Args:
            entry_price: Executable VWAP per share (0 < entry_price < 1).
            quantity: Number of token shares purchased.
            settlement_value: Terminal settlement value per share (1.0 for WIN, 0.0 for LOSS).
            fee_bps: Exchange fee in basis points (default 5.0 bps).
            slippage_bps: Execution slippage in basis points.
            lockup_bps: Capital lockup cost in basis points (default 2.0 bps).

        Returns:
            TradePnLResult dataclass with exact financial metrics.
        """
        if entry_price <= 0.0 or entry_price >= 1.0:
            raise ValueError(f"Entry price must be strictly between 0 and 1, got {entry_price}")
        if quantity <= 0.0:
            raise ValueError(f"Quantity must be strictly positive, got {quantity}")

        notional_usd = entry_price * quantity
        fee_usd = notional_usd * (fee_bps / 10000.0)
        slippage_usd = notional_usd * (slippage_bps / 10000.0)
        lockup_cost_usd = notional_usd * (lockup_bps / 10000.0)

        capital_at_risk_usd = notional_usd + fee_usd + slippage_usd

        is_win = (settlement_value >= 0.5)

        if is_win:
            gross_pnl_usd = quantity * (1.0 - entry_price)
        else:
            gross_pnl_usd = -quantity * entry_price

        gross_return = gross_pnl_usd / notional_usd
        gross_bps = gross_return * 10000.0

        net_pnl_usd = gross_pnl_usd - fee_usd - slippage_usd - lockup_cost_usd
        net_return = net_pnl_usd / capital_at_risk_usd
        net_ev_bps = net_return * 10000.0

        price_discount_cents = (1.0 - entry_price) * 100.0
        price_discount_bps = (1.0 - entry_price) * 10000.0

        return TradePnLResult(
            entry_price=entry_price,
            quantity=quantity,
            notional_usd=notional_usd,
            capital_at_risk_usd=capital_at_risk_usd,
            settlement_value=settlement_value,
            is_win=is_win,
            gross_pnl_usd=gross_pnl_usd,
            gross_return=gross_return,
            gross_bps=gross_bps,
            fee_usd=fee_usd,
            fee_bps=fee_bps,
            slippage_usd=slippage_usd,
            slippage_bps=slippage_bps,
            lockup_cost_usd=lockup_cost_usd,
            lockup_bps=lockup_bps,
            net_pnl_usd=net_pnl_usd,
            net_return=net_return,
            net_ev_bps=net_ev_bps,
            price_discount_cents=price_discount_cents,
            price_discount_bps=price_discount_bps,
        )
