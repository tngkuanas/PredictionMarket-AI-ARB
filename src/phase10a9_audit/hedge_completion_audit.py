"""Hedge Completion and Timestamp Strictness Audit Engine for Phase 10A.9.

Audits:
- 500/500 hedge completion claim.
- Timestamp ordering and causality strictness: verifies whether book snapshots were strictly post-fill.
- Pre-target vs post-target snapshot selection in _find_active_snapshot.
- Re-evaluation of hedge depth and fill completion under strict forward causality (ts >= t_fill + latency).
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


class Phase10A9HedgeCompletionAuditor:
    """Audits hedge execution timestamp integrity, book depth, and fill completion rates."""

    @staticmethod
    def audit_timestamp_causality(
        fills: List[Dict[str, Any]],
        snapshots: List[Dict[str, Any]],
        rel_lookup: Dict[str, Any],
        latency_ms: int = 100
    ) -> Dict[str, Any]:
        """Audits snapshot selection against target hedge timestamps (t_fill + latency)."""
        pre_target_count = 0
        post_target_count = 0
        exact_count = 0
        delays_sec = []

        strict_completed = 0
        strict_partial = 0
        strict_failed = 0
        insufficient_depth = 0

        for f in fills:
            tok = f["token_id"]
            if tok not in rel_lookup:
                continue
            rel = rel_lookup[tok]
            c_a = rel.get("contract_a") if isinstance(rel, dict) else getattr(rel, "contract_a")
            c_b = rel.get("contract_b") if isinstance(rel, dict) else getattr(rel, "contract_b")
            hedge_tok = c_b if tok == c_a else c_a
            
            t_fill = f["fill_timestamp"]
            if isinstance(t_fill, str):
                t_fill = datetime.fromisoformat(t_fill)
            if t_fill.tzinfo is None:
                t_fill = t_fill.replace(tzinfo=timezone.utc)
            t_target = t_fill + timedelta(milliseconds=latency_ms)

            token_snaps = [s for s in snapshots if str(s.get("token_id", "")) == hedge_tok]
            if not token_snaps:
                strict_failed += 1
                continue

            # Original algorithm selection (closest abs diff in [-10s, +30s])
            valid_snaps = []
            for s in token_snaps:
                ts = s.get("timestamp")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                diff = (ts - t_target).total_seconds()
                if -10.0 <= diff <= 30.0:
                    valid_snaps.append((abs(diff), diff, s))

            if valid_snaps:
                valid_snaps.sort(key=lambda x: x[0])
                signed_diff = valid_snaps[0][1]
                delays_sec.append(signed_diff)
                if signed_diff < -1e-4:
                    pre_target_count += 1
                elif signed_diff > 1e-4:
                    post_target_count += 1
                else:
                    exact_count += 1

            # Strict causality selection: MUST be ts >= t_target
            forward_snaps = []
            for s in token_snaps:
                ts = s.get("timestamp")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                diff = (ts - t_target).total_seconds()
                if 0.0 <= diff <= 60.0:
                    forward_snaps.append((diff, s))

            if not forward_snaps:
                strict_failed += 1
            else:
                forward_snaps.sort(key=lambda x: x[0])
                strict_snap = forward_snaps[0][1]
                # Check depth
                asks = strict_snap.get("asks", [])
                total_ask_shares = sum([float(a.get("size", 0.0)) for a in asks])
                req_shares = float(f.get("fill_shares", 50.0))
                if total_ask_shares >= req_shares:
                    strict_completed += 1
                elif total_ask_shares > 0:
                    strict_partial += 1
                    insufficient_depth += 1
                else:
                    strict_failed += 1
                    insufficient_depth += 1

        n_audited = len(delays_sec)
        pre_pct = round((pre_target_count / max(1, n_audited)) * 100.0, 1)
        post_pct = round((post_target_count / max(1, n_audited)) * 100.0, 1)

        return {
            "total_fills_audited": n_audited,
            "reported_completion_count": n_audited,
            "reported_completion_rate_pct": 100.0,
            "pre_target_snapshots_used": pre_target_count,
            "pre_target_pct": pre_pct,
            "post_target_snapshots_used": post_target_count,
            "post_target_pct": post_pct,
            "exact_snapshots_used": exact_count,
            "mean_timestamp_error_sec": round(float(np.mean(delays_sec)), 4) if delays_sec else 0.0,
            "strict_causality_completed": strict_completed,
            "strict_causality_partial": strict_partial,
            "strict_causality_failed": strict_failed,
            "strict_causality_completion_rate_pct": round((strict_completed / max(1, n_audited)) * 100.0, 1),
            "is_100pct_completion_valid": (pre_target_count == 0),
            "verdict_reason": (
                f"METHODOLOGY ERROR: Phase 10A.9 _find_active_snapshot sorted by abs(diff), selecting "
                f"snapshots prior to t_target (t_fill + latency) in {pre_pct}% of evaluations. "
                f"Under strict forward causality (ts >= t_target), completion rate is {round((strict_completed / max(1, n_audited)) * 100.0, 1)}%."
            )
        }
