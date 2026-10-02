"""Deduplication Engine for Phase 10A.10-D.

Resolves the 5,791 / 5,913 pseudoreplication problem by collapsing parameter-grid
and hypothesis permutations of the identical economic opportunity into canonical executions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Tuple, Set


@dataclass
class CanonicalExecution:
    """Canonical representation of an economic execution opportunity."""
    canonical_id: str
    event_id: str
    market_id: str
    token_id: str
    execution_timestamp: datetime
    entry_side: str
    execution_price: float  # VWAP
    quantity: float  # filled shares
    position_size_usd: float
    gross_pnl: float
    net_pnl: float
    net_return: float
    net_ev_bps: float
    settlement_value: float
    is_win: bool
    generating_candidate_ids: List[str] = field(default_factory=list)
    generating_hypotheses: List[str] = field(default_factory=list)
    generating_latencies: List[str] = field(default_factory=list)
    generating_thresholds: List[float] = field(default_factory=list)


class DeduplicationEngine:
    """Deduplicates raw executions into canonical executions."""

    @staticmethod
    def compute_identity(
        event_id: str,
        market_id: str,
        token_id: str,
        execution_timestamp: datetime,
        entry_side: str,
        execution_price: float,
        quantity: float,
        tolerance: float = 1e-4
    ) -> Tuple[str, str, str, str, str, float, float]:
        """Generates deterministic economic execution identity."""
        ts_str = execution_timestamp.isoformat()
        rounded_price = round(execution_price, 4)
        rounded_qty = round(quantity, 4)
        return (event_id, market_id, token_id, ts_str, entry_side.upper(), rounded_price, rounded_qty)

    @classmethod
    def deduplicate_executions(
        cls,
        raw_executions: List[Any],
        baseline_size_only: bool = False,
        baseline_size: float = 50.0
    ) -> Tuple[List[CanonicalExecution], Dict[str, List[str]], int]:
        """Collapses duplicate executions into canonical unique economic trades.

        Args:
            raw_executions: List of raw ExecutionRecord objects.
            baseline_size_only: If True, filters only to canonical trades of baseline size.
            baseline_size: The baseline position size in USD (default $50).

        Returns:
            canonical_executions: List of unique canonical executions.
            audit_trail: Mapping of canonical_id -> list of raw candidate_ids.
            duplicate_count: Number of redundant executions removed.
        """
        canonical_map: Dict[Tuple, CanonicalExecution] = {}
        audit_trail: Dict[str, List[str]] = {}

        for exec_rec in raw_executions:
            # Extract fields
            ev_id = getattr(exec_rec, "event_id", "")
            mkt_id = getattr(exec_rec, "market_id", "")
            tok_id = getattr(exec_rec, "token_id", "")
            ts = getattr(exec_rec, "execution_timestamp", datetime.min)
            side = getattr(exec_rec, "side", "BUY")
            vwap = getattr(exec_rec, "vwap", 0.0)
            qty = getattr(exec_rec, "filled_shares", 0.0)
            size = getattr(exec_rec, "position_size_usd", 0.0)
            cand_id = getattr(exec_rec, "candidate_id", "")

            # Optional filter to baseline size
            if baseline_size_only and abs(size - baseline_size) > 1e-3:
                continue

            ident = cls.compute_identity(
                event_id=ev_id,
                market_id=mkt_id,
                token_id=tok_id,
                execution_timestamp=ts,
                entry_side=side,
                execution_price=vwap,
                quantity=qty,
            )

            # Extract parameter metadata from cand_id if present
            # Format: exp_cand_{event}_{latency}_{threshold}_{size}
            parts = cand_id.split("_")
            hyp = "H1"
            lat = "500ms_1s"
            thresh = 10.0
            if len(parts) >= 4:
                lat = parts[-3] if "ms" in parts[-3] or "s" in parts[-3] else "500ms_1s"
                try:
                    thresh = float(parts[-2])
                except ValueError:
                    thresh = 10.0

            if ident not in canonical_map:
                c_id = f"canon_{ev_id}_{size:.0f}_{round(vwap*10000):.0f}"
                settlement_val = 1.0  # evaluated by settlement engine
                is_win = (getattr(exec_rec, "net_ev_bps", 0.0) > 0)

                canonical_exec = CanonicalExecution(
                    canonical_id=c_id,
                    event_id=ev_id,
                    market_id=mkt_id,
                    token_id=tok_id,
                    execution_timestamp=ts,
                    entry_side=side,
                    execution_price=vwap,
                    quantity=qty,
                    position_size_usd=size,
                    gross_pnl=getattr(exec_rec, "gross_deterministic_edge_bps", 0.0),
                    net_pnl=getattr(exec_rec, "net_ev_bps", 0.0),
                    net_return=getattr(exec_rec, "net_ev_bps", 0.0) / 10000.0,
                    net_ev_bps=getattr(exec_rec, "net_ev_bps", 0.0),
                    settlement_value=settlement_val,
                    is_win=is_win,
                    generating_candidate_ids=[cand_id],
                    generating_hypotheses=[hyp],
                    generating_latencies=[lat],
                    generating_thresholds=[thresh],
                )
                canonical_map[ident] = canonical_exec
                audit_trail[c_id] = [cand_id]
            else:
                canon = canonical_map[ident]
                canon.generating_candidate_ids.append(cand_id)
                if hyp not in canon.generating_hypotheses:
                    canon.generating_hypotheses.append(hyp)
                if lat not in canon.generating_latencies:
                    canon.generating_latencies.append(lat)
                if thresh not in canon.generating_thresholds:
                    canon.generating_thresholds.append(thresh)
                audit_trail[canon.canonical_id].append(cand_id)

        canonical_list = list(canonical_map.values())
        raw_count = len(raw_executions) if not baseline_size_only else sum(1 for x in raw_executions if abs(getattr(x, "position_size_usd", 0.0) - baseline_size) < 1e-3)
        duplicate_count = raw_count - len(canonical_list)

        return canonical_list, audit_trail, duplicate_count
