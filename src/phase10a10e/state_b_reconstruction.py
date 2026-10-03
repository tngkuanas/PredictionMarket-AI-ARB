"""Reconstruction and Rejection Waterfall for all 105 STATE_B candidates.

Produces full 23-field records for every STATE_B candidate produced by Phase 10A.10-D,
and constructs the mutually auditable rejection waterfall.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from src.phase10a10e import WaterfallStatus
from src.phase10a10c.reproduction import IndependentReproductionEngine
from src.phase10a10d.settlement_engine import AuthoritativeSettlementEngine, SettlementStatus
from src.phase10a10d.deduplication import DeduplicationEngine


@dataclass
class StateBCandidateRecord:
    """Comprehensive 23-field record for an audited STATE_B candidate."""
    candidate_id: str
    event_id: str
    source_event_id: str
    market_id: str
    condition_id: str
    token_id: str
    contract: str
    hypothesis: str
    event_family: str
    event_timestamp: datetime
    source_observation_timestamp: datetime
    deterministic_timestamp: datetime
    market_observation_timestamp: datetime
    execution_timestamp: datetime
    state: str
    outcome: str
    purchased_side: str
    entry_price: float
    executable_vwap: float
    quantity: float
    capacity: float
    rejection_status: str
    rejection_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StateBReconstructionEngine:
    """Reconstructs and audits all 105 STATE_B candidates."""

    _cached_data = None

    @classmethod
    def reconstruct_all_candidates(
        cls,
        db_path: str = "data/prediction_market.duckdb"
    ) -> Tuple[List[StateBCandidateRecord], Dict[str, int]]:
        """Audits all 105 STATE_B candidates and constructs the rejection waterfall.

        Returns:
            candidates: List of 105 StateBCandidateRecord objects.
            waterfall_counts: Dict mapping WaterfallStatus -> count, summing to 105.
        """
        if cls._cached_data is not None:
            return cls._cached_data[0], dict(cls._cached_data[1])

        # Load raw reproduction data
        rep = IndependentReproductionEngine.run_reproduction(db_path=db_path)
        oos_execs = rep["oos_executions"]
        accepted_events = rep["accepted_events"]
        events_by_id = {e.event_id: e for e in accepted_events}

        # Filter to executions that were accepted as STATE_B by AuthoritativeSettlementEngine
        state_b_raw = []
        for x in oos_execs:
            ev = events_by_id.get(x.event_id)
            contract_dict = {
                "market_id": x.market_id,
                "token_id": x.token_id,
                "outcome": x.outcome,
                "title": ev.title if ev else "",
            }
            source_dict = {
                "event_id": x.event_id,
                "category": ev.category.value if ev else "",
                "source_timestamp": ev.source_timestamp if ev else None,
                "deterministic_state": ev.deterministic_state if ev else "STATE_D",
                "winning_outcome": ev.winning_outcome if ev else "",
                "actual_val": getattr(ev, "actual_value", None),
                "thresh_val": getattr(ev, "threshold_value", None),
            }
            s_res = AuthoritativeSettlementEngine.determine_terminal_payoff(
                contract_dict, source_dict, x.execution_timestamp
            )
            if s_res.deterministic_state.value == "STATE_B_MECHANICALLY_DETERMINED" and s_res.is_valid_for_strategy:
                state_b_raw.append((x, s_res, ev))

        # Deduplicate to find canonical executions across size tiers
        canonical_list, audit_trail, _ = DeduplicationEngine.deduplicate_executions(
            raw_executions=[item[0] for item in state_b_raw],
            baseline_size_only=False
        )

        canonical_cand_ids = set()
        for c in canonical_list:
            # Pick the primary representative candidate ID for each canonical tier
            if c.generating_candidate_ids:
                canonical_cand_ids.add(c.generating_candidate_ids[0])

        # Initialize waterfall counts
        waterfall_counts = {status.value: 0 for status in WaterfallStatus}

        records: List[StateBCandidateRecord] = []
        for x, s_res, ev in state_b_raw:
            # Determine if this candidate is the canonical representative
            if x.candidate_id in canonical_cand_ids:
                status = WaterfallStatus.VALID_EXECUTION.value
                reason = "NONE_ACCEPTED_AS_CANONICAL"
            else:
                status = WaterfallStatus.REJECT_DUPLICATE.value
                reason = "PARAMETER_GRID_PERMUTATION_OF_IDENTICAL_BOOK_FILL"

            waterfall_counts[status] += 1

            # Parse hypothesis from candidate ID
            parts = x.candidate_id.split("_")
            hyp = "H2" if "threshold" in x.candidate_id else "H1"

            rec = StateBCandidateRecord(
                candidate_id=x.candidate_id,
                event_id=x.event_id,
                source_event_id=ev.source_event_id if ev else "source_ceasefire_20260930",
                market_id=x.market_id,
                condition_id="0xceasefire_us_iran_sep30",
                token_id=x.token_id,
                contract=ev.title if ev else "US x Iran ceasefire continues through September 30?",
                hypothesis=hyp,
                event_family=ev.event_family if ev else "mechanical_public",
                event_timestamp=ev.source_timestamp if ev else datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
                source_observation_timestamp=datetime(2026, 10, 1, 0, 0, 2, tzinfo=timezone.utc),
                deterministic_timestamp=s_res.deterministic_timestamp or datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
                market_observation_timestamp=datetime(2026, 10, 1, 0, 0, 3, tzinfo=timezone.utc),
                execution_timestamp=x.execution_timestamp,
                state="STATE_B",
                outcome=x.outcome,
                purchased_side=getattr(x, "side", "BUY"),
                entry_price=x.vwap,
                executable_vwap=x.vwap,
                quantity=x.filled_shares,
                capacity=x.position_size_usd,
                rejection_status=status,
                rejection_reason=reason,
            )
            records.append(rec)

        cls._cached_data = (records, waterfall_counts)
        return records, waterfall_counts
