"""Capital Lockup and Opportunity Cost Model for Phase 10A.10.

Evaluates:
- Entry capital requirement.
- Expected resolution delay (contract scheduled end) vs actual resolution delay (UMA oracle settlement).
- Opportunity cost of capital (annualized risk-free benchmark, e.g. 5.0% USD Treasury yield).
- Annualized return: (net_return / capital) * (8760 / delay_hours).
- Capital utilization impact on small deterministic edges.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, Any, Optional

from src.phase10a10.schema import CapitalLockupRecord

logger = logging.getLogger(__name__)


class CapitalLockupModel:
    """Models capital lockup duration and opportunity costs."""

    # Annual risk-free rate assumption (5.00% annualized)
    RISK_FREE_ANNUAL_PCT = 5.0
    RISK_FREE_HOURLY_BPS = (RISK_FREE_ANNUAL_PCT / 8760.0) * 100.0

    @classmethod
    def calculate_lockup(
        cls,
        event_id: str,
        market_id: str,
        position_size_usd: float,
        entry_ts: datetime,
        scheduled_end_ts: datetime,
        actual_settlement_ts: datetime,
        gross_pnl_usd: float,
        trading_fees_usd: float = 0.0,
    ) -> CapitalLockupRecord:
        """Computes capital lockup metrics and annualized performance."""
        def to_utc(dt: datetime) -> datetime:
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

        t_entry = to_utc(entry_ts)
        t_sched = to_utc(scheduled_end_ts)
        t_settle = to_utc(actual_settlement_ts)

        expected_delay_hours = max(0.1, (t_sched - t_entry).total_seconds() / 3600.0)
        actual_delay_hours = max(0.1, (t_settle - t_entry).total_seconds() / 3600.0)

        # Opportunity cost of capital over the holding period
        cost_of_capital_bps = actual_delay_hours * cls.RISK_FREE_HOURLY_BPS
        capital_cost_usd = position_size_usd * (cost_of_capital_bps / 10000.0)

        net_pnl_usd = gross_pnl_usd - trading_fees_usd - capital_cost_usd

        # Annualized return
        simple_return = net_pnl_usd / position_size_usd if position_size_usd > 0 else 0.0
        annualized_return_pct = (simple_return * (8760.0 / actual_delay_hours)) * 100.0

        return CapitalLockupRecord(
            lockup_id=f"lockup_{event_id}_{int(position_size_usd)}",
            event_id=event_id,
            market_id=market_id,
            position_size_usd=position_size_usd,
            entry_timestamp=t_entry,
            resolution_timestamp=t_settle,
            expected_delay_hours=expected_delay_hours,
            actual_delay_hours=actual_delay_hours,
            cost_of_capital_bps=cost_of_capital_bps,
            gross_pnl_usd=gross_pnl_usd,
            net_pnl_usd=net_pnl_usd,
            annualized_return_pct=annualized_return_pct
        )
