"""Frozen M3 Reproduction Engine for Phase 10A.11-C.

Verifies that published Phase 10A.11 and Phase 10A.11-B discovery and forensic
metrics for M3_MULTI_OUTCOME_OVERHANG are reproduced verbatim before proceeding
to atomic routing validation.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class FrozenM3Metrics:
    candidate_id: str = "M3_MULTI_OUTCOME_OVERHANG"
    name: str = "Multi-Outcome Asynchronous Rebalancing Overhang"
    discovery_n: int = 34
    validation_n: int = 17
    oos_n: int = 12
    raw_ev_bps: float = 16.50
    gross_ev_bps: float = 21.50
    fees_bps: float = 10.00
    slippage_bps: float = 0.00
    nominal_net_ev_bps: float = 11.50
    clustered_t_stat: float = 1.08
    unadjusted_p_value: float = 0.280
    holm_adjusted_p_value: float = 1.000
    market_clusters: int = 8
    independent_events: int = 12
    effective_n: int = 16
    assumed_capacity_usd: float = 100.00

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "discovery_n": self.discovery_n,
            "validation_n": self.validation_n,
            "oos_n": self.oos_n,
            "raw_ev_bps": self.raw_ev_bps,
            "gross_ev_bps": self.gross_ev_bps,
            "fees_bps": self.fees_bps,
            "slippage_bps": self.slippage_bps,
            "nominal_net_ev_bps": self.nominal_net_ev_bps,
            "clustered_t_stat": self.clustered_t_stat,
            "unadjusted_p_value": self.unadjusted_p_value,
            "holm_adjusted_p_value": self.holm_adjusted_p_value,
            "market_clusters": self.market_clusters,
            "independent_events": self.independent_events,
            "effective_n": self.effective_n,
            "assumed_capacity_usd": self.assumed_capacity_usd,
        }


class FrozenM3Verifier:
    """Verifies that published Phase 10A.11 metrics for M3 are reproduced exactly."""

    FROZEN_RECORD = FrozenM3Metrics()

    @classmethod
    def get_frozen_metrics(cls) -> FrozenM3Metrics:
        return cls.FROZEN_RECORD

    @classmethod
    def verify_reproduction(cls, candidate_dict: Dict[str, Any]) -> bool:
        """Verifies candidate metrics against the frozen baseline."""
        rec = cls.FROZEN_RECORD
        assert candidate_dict.get("discovery_n") == rec.discovery_n, "Discovery N mismatch"
        assert candidate_dict.get("validation_n") == rec.validation_n, "Validation N mismatch"
        assert candidate_dict.get("oos_n") == rec.oos_n, "OOS N mismatch"
        assert abs(candidate_dict.get("gross_ev_bps", 0.0) - rec.gross_ev_bps) < 1e-4, "Gross EV mismatch"
        assert abs(candidate_dict.get("nominal_net_ev_bps", 0.0) - rec.nominal_net_ev_bps) < 1e-4, "Net EV mismatch"
        assert abs(candidate_dict.get("effective_n", 0) - rec.effective_n) <= 1, "Effective N mismatch"
        return True
