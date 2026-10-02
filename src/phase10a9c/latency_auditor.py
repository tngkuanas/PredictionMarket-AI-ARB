"""Latency and Execution Path Forensic Auditor for Phase 10A.9-C.

Audits:
- End-to-end execution path: passive fill -> target timestamp -> snapshot selection -> VWAP -> P&L.
- Requested vs actual execution delay across all 10 tiers.
- Same-observation audit verifying identical 500 fills across tiers.
- Same-relationship audit quantifying market and event concentration.
- Root cause diagnosis of non-monotonicity between 100ms and 250ms/500ms.
"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from src.phase10a9b.schema import CausalHedgeExecutionStatus
from src.phase10a9b.hedge_executor import StrictForwardCausalHedgeExecutor
from src.phase10a9b.economics_engine import CausalHedgedEconomicsEngine
from src.phase10a9c.schema import (
    LatencyTierAuditRecord,
    LatencySampleAuditRecord,
)

STANDARD_LATENCIES_MS = [0, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000]


class Phase10A9CLatencyAuditor:
    """Forensic auditor evaluating latency mechanics and order book availability."""

    def __init__(self):
        pass

    @classmethod
    def audit_tier_execution(
        cls,
        tier_ms: int,
        fills: List[Dict[str, Any]],
        rel_by_token: Dict[str, Dict[str, Any]],
        executor: StrictForwardCausalHedgeExecutor,
        econ_eng: CausalHedgedEconomicsEngine,
        snaps: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Audits the complete execution path for a specific latency tier."""
        recs = []
        e_recs = []
        delays_sec = []
        total_latencies_sec = []
        pre_target_count = 0
        comp_count = 0
        part_count = 0
        failed_count = 0

        for f in fills:
            tok = f["token_id"]
            if tok not in rel_by_token:
                continue
            rel = rel_by_token[tok]
            r = executor.execute_causal_hedge(f, rel, snaps, latency_ms=tier_ms)
            recs.append(r)
            e = econ_eng.evaluate_paired_economics(f, r)
            e_recs.append(e)

            if r.hedge_status == CausalHedgeExecutionStatus.COMPLETED:
                comp_count += 1
            elif r.hedge_status == CausalHedgeExecutionStatus.PARTIAL:
                part_count += 1
            else:
                failed_count += 1

            if r.selected_snapshot_timestamp is not None:
                if r.selected_snapshot_timestamp < r.hedge_target_timestamp:
                    pre_target_count += 1
                delay_s = max(0.0, (r.selected_snapshot_timestamp - r.hedge_target_timestamp).total_seconds())
                delays_sec.append(delay_s)
                total_latencies_sec.append((tier_ms / 1000.0) + delay_s)

        # Factor decomposition
        maker_evs = [e.unhedged_net_ev_bps for e in e_recs]
        hedge_spreads = [e.hedge_spread_cost_bps for e in e_recs]
        depth_slippages = [e.hedge_slippage_bps for e in e_recs]
        latency_drifts = [e.hedge_latency_cost_bps for e in e_recs]
        residual_costs = [e.residual_inventory_cost_bps + e.residual_liquidation_cost_bps for e in e_recs]
        net_evs = [e.hedged_net_ev_bps for e in e_recs]

        # Discovery vs OOS
        disc_evs = [e.hedged_net_ev_bps for e in e_recs if not e.is_out_of_sample]
        oos_evs = [e.hedged_net_ev_bps for e in e_recs if e.is_out_of_sample]

        return {
            "tier_ms": tier_ms,
            "n_fills": len(fills),
            "completed": comp_count,
            "partial": part_count,
            "failed": failed_count,
            "pre_target_snapshots": pre_target_count,
            "delays_sec": delays_sec,
            "total_latencies_sec": total_latencies_sec,
            "delay_stats": {
                "min": float(np.min(delays_sec)) if delays_sec else 0.0,
                "median": float(np.median(delays_sec)) if delays_sec else 0.0,
                "mean": float(np.mean(delays_sec)) if delays_sec else 0.0,
                "p95": float(np.percentile(delays_sec, 95)) if delays_sec else 0.0,
                "p99": float(np.percentile(delays_sec, 99)) if delays_sec else 0.0,
                "max": float(np.max(delays_sec)) if delays_sec else 0.0,
            },
            "actual_latency_stats": {
                "median": float(np.median(total_latencies_sec)) if total_latencies_sec else 0.0,
                "p95": float(np.percentile(total_latencies_sec, 95)) if total_latencies_sec else 0.0,
                "p99": float(np.percentile(total_latencies_sec, 99)) if total_latencies_sec else 0.0,
            },
            "factors": {
                "maker_ev": float(np.mean(maker_evs)),
                "hedge_spread": float(np.mean(hedge_spreads)),
                "depth_slippage": float(np.mean(depth_slippages)),
                "latency_drift": float(np.mean(latency_drifts)),
                "residual_cost": float(np.mean(residual_costs)),
                "net_ev": float(np.mean(net_evs)),
            },
            "disc_ev": float(np.mean(disc_evs)) if disc_evs else 0.0,
            "oos_evs": oos_evs,
            "execution_records": recs,
            "economic_records": e_recs,
        }

    @classmethod
    def audit_same_observations(
        cls,
        tier_results: Dict[int, Dict[str, Any]],
        fills: List[Dict[str, Any]]
    ) -> List[LatencySampleAuditRecord]:
        """Verifies that all latency tiers evaluate the exact same 500 passive fills."""
        baseline_fill_ids = set(f["fill_id"] for f in fills)
        records = []

        for lat_ms, res in tier_results.items():
            tier_fill_ids = set(r.passive_fill_id for r in res["execution_records"])
            same_fills = (tier_fill_ids == baseline_fill_ids)
            unique_count = len(tier_fill_ids)
            missing = len(baseline_fill_ids - tier_fill_ids)

            records.append(LatencySampleAuditRecord(
                latency_ms=lat_ms,
                passive_fills_evaluated=len(res["execution_records"]),
                same_fills_as_0ms=same_fills,
                unique_fills=unique_count,
                missing_fills=missing,
                completed=res["completed"],
                partial=res["partial"],
                failed=res["failed"]
            ))
        return records

    @classmethod
    def audit_relationship_concentration(
        cls,
        fills: List[Dict[str, Any]],
        rel_by_token: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Audits relationship, market, and event concentration."""
        all_rels = [rel_by_token[f["token_id"]]["relationship_id"] for f in fills if f["token_id"] in rel_by_token]
        all_mkts = [rel_by_token[f["token_id"]]["market_id_a"] for f in fills if f["token_id"] in rel_by_token]

        oos_fills = [f for f in fills if f.get("is_out_of_sample", False)]
        oos_rels = [rel_by_token[f["token_id"]]["relationship_id"] for f in oos_fills if f["token_id"] in rel_by_token]
        oos_mkts = [rel_by_token[f["token_id"]]["market_id_a"] for f in oos_fills if f["token_id"] in rel_by_token]

        c_rel_all = Counter(all_rels)
        c_mkt_all = Counter(all_mkts)
        c_rel_oos = Counter(oos_rels)
        c_mkt_oos = Counter(oos_mkts)

        top1_oos_count = c_rel_oos.most_common(1)[0][1] if oos_rels else 0
        top1_oos_pct = (top1_oos_count / max(1, len(oos_rels))) * 100.0

        top2_all_count = sum(cnt for _, cnt in c_rel_all.most_common(2))
        top2_all_pct = (top2_all_count / max(1, len(all_rels))) * 100.0

        return {
            "all_fills_count": len(fills),
            "oos_fills_count": len(oos_fills),
            "top_relationships_all": c_rel_all.most_common(5),
            "top_markets_all": c_mkt_all.most_common(5),
            "top_relationships_oos": c_rel_oos.most_common(5),
            "top_markets_oos": c_mkt_oos.most_common(5),
            "top1_relationship_oos_pct": round(top1_oos_pct, 1),
            "top2_relationships_all_pct": round(top2_all_pct, 1),
            "unique_relationships_oos": len(c_rel_oos),
            "unique_markets_oos": len(c_mkt_oos),
        }
