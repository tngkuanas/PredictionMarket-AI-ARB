"""Deterministic Settlement Normalizer & Cross-Venue Contract Equivalence Engine.

Phase 10A.6e Sections 2, 3, 4, 12:
Determines whether Polymarket and Kalshi contracts share provably identical settlement state spaces.

CRITICAL RULE:
Equivalence is decided purely by deterministic evaluation of canonical contracts,
NEVER by an LLM or unverified semantic similarity.
"""

import re
import logging
from typing import Optional, Tuple, List
from datetime import datetime

from src.cross_venue.schema import (
    CanonicalEconomicContract,
    ContractMappingResult,
    EquivalenceClass,
    MappingStatus,
)

logger = logging.getLogger(__name__)


class SettlementNormalizer:
    """Deterministic validator for cross-venue contract equivalence and settlement normalization."""

    # Canonical authoritative resolution sources that must match exactly
    STANDARDIZED_SOURCES = {
        "bls": "bureau of labor statistics",
        "bureau of labor statistics": "bureau of labor statistics",
        "fed": "federal reserve",
        "federal reserve": "federal reserve",
        "binance": "binance",
        "coinbase": "coinbase",
        "noaa": "national oceanic and atmospheric administration",
        "ap": "associated press",
        "associated press": "associated press",
    }

    @classmethod
    def normalize_source(cls, source_raw: str) -> str:
        s = source_raw.strip().lower()
        for k, v in cls.STANDARDIZED_SOURCES.items():
            if k in s:
                return v
        return s

    @classmethod
    def compare_contracts(
        cls,
        poly: CanonicalEconomicContract,
        kalshi: CanonicalEconomicContract,
    ) -> ContractMappingResult:
        """Determines the exact equivalence class and settlement parity between Polymarket and Kalshi contracts."""
        mapping_id = f"map_{poly.venue_contract_id[:8]}_{kalshi.venue_contract_id[:8]}"
        reasons: List[str] = []

        # 1. Verification of Basic Inputs
        if not poly.underlying_event or not kalshi.underlying_event:
            return cls._build_result(
                mapping_id, poly, kalshi,
                EquivalenceClass.NON_EQUIVALENT, False,
                MappingStatus.INSUFFICIENT_DATA,
                "INSUFFICIENT_DATA: Missing underlying event specification."
            )

        # 2. Geographic Scope Parity
        if poly.geographic_scope.strip().upper() != kalshi.geographic_scope.strip().upper():
            return cls._build_result(
                mapping_id, poly, kalshi,
                EquivalenceClass.NON_EQUIVALENT, False,
                MappingStatus.NON_EQUIVALENT,
                f"GEOGRAPHY_MISMATCH: Polymarket ({poly.geographic_scope}) != Kalshi ({kalshi.geographic_scope})."
            )

        # 3. Observation Variable / Metric Identity
        poly_metric = poly.observation_variable.strip().lower()
        kalshi_metric = kalshi.observation_variable.strip().lower()
        if poly_metric != kalshi_metric:
            # Check if metrics are completely distinct
            if not (poly_metric in kalshi_metric or kalshi_metric in poly_metric):
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.NON_EQUIVALENT, False,
                    MappingStatus.NON_EQUIVALENT,
                    f"METRIC_MISMATCH: Distinct observation metrics '{poly_metric}' vs '{kalshi_metric}'."
                )

        # 4. Temporal Scope / Resolution Date
        poly_temp = poly.temporal_scope.strip().lower()
        kalshi_temp = kalshi.temporal_scope.strip().lower()
        if poly_temp != kalshi_temp:
            return cls._build_result(
                mapping_id, poly, kalshi,
                EquivalenceClass.NON_EQUIVALENT, False,
                MappingStatus.NON_EQUIVALENT,
                f"DATE_MISMATCH: Temporal windows differ '{poly_temp}' vs '{kalshi_temp}'."
            )

        # Timestamp check if both provided
        if poly.resolution_timestamp and kalshi.resolution_timestamp:
            diff_sec = abs((poly.resolution_timestamp - kalshi.resolution_timestamp).total_seconds())
            if diff_sec > 3600.0:  # More than 1 hour divergence
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.NON_EQUIVALENT, False,
                    MappingStatus.NON_EQUIVALENT,
                    f"RESOLUTION_TIME_MISMATCH: Timestamp difference is {diff_sec/3600.0:.1f} hours."
                )

        # 5. Authoritative Resolution Source Match
        poly_src = cls.normalize_source(poly.source_of_resolution)
        kalshi_src = cls.normalize_source(kalshi.source_of_resolution)
        if poly_src != kalshi_src:
            return cls._build_result(
                mapping_id, poly, kalshi,
                EquivalenceClass.SEMANTIC_ONLY, False,
                MappingStatus.SEMANTIC_ONLY,
                f"RESOLUTION_SOURCE_MISMATCH: Polymarket uses '{poly.source_of_resolution}', Kalshi uses '{kalshi.source_of_resolution}'."
            )

        # 6. Direction & Complementarity Check
        poly_dir = (poly.inequality_direction or "").strip()
        kalshi_dir = (kalshi.inequality_direction or "").strip()

        # Complementary Check: e.g. >= vs < or > vs <=
        is_complementary = False
        if (poly_dir in (">=", ">") and kalshi_dir in ("<", "<=")) or \
           (poly_dir in ("<", "<=") and kalshi_dir in (">=", ">")):
            # If thresholds match, they are complementary
            if poly.threshold is not None and kalshi.threshold is not None and poly.threshold == kalshi.threshold:
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.COMPLEMENTARY, False,
                    MappingStatus.COMPLEMENTARY,
                    f"COMPLEMENTARY: Opposite inequality directions ({poly_dir} vs {kalshi_dir}) on identical strike {poly.threshold}."
                )

        # Direction Mismatch (strict)
        if poly_dir and kalshi_dir and poly_dir != kalshi_dir:
            # Subtle mismatch: >= vs >
            if (poly_dir == ">=" and kalshi_dir == ">") or (poly_dir == ">" and kalshi_dir == ">="):
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.NON_EQUIVALENT, False,
                    MappingStatus.AMBIGUOUS,
                    f"INEQUALITY_STRICTNESS_MISMATCH: Boundary condition divergence ('{poly_dir}' vs '{kalshi_dir}')."
                )

        # 7. Threshold & Strike Value Parity
        if poly.threshold is not None and kalshi.threshold is not None:
            if poly.threshold != kalshi.threshold:
                # Nested Check: same metric, same direction, differing strikes
                if poly_dir == kalshi_dir and poly_dir in (">=", ">"):
                    return cls._build_result(
                        mapping_id, poly, kalshi,
                        EquivalenceClass.NESTED, False,
                        MappingStatus.NESTED,
                        f"NESTED: Same direction ({poly_dir}) but nested strike thresholds ({poly.threshold} vs {kalshi.threshold})."
                    )
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.NON_EQUIVALENT, False,
                    MappingStatus.NON_EQUIVALENT,
                    f"THRESHOLD_MISMATCH: Numeric thresholds differ ({poly.threshold} != {kalshi.threshold})."
                )
        elif poly.strike_value and kalshi.strike_value:
            if poly.strike_value.strip().lower() != kalshi.strike_value.strip().lower():
                return cls._build_result(
                    mapping_id, poly, kalshi,
                    EquivalenceClass.NON_EQUIVALENT, False,
                    MappingStatus.NON_EQUIVALENT,
                    f"STRIKE_VALUE_MISMATCH: Discrete strike mismatch '{poly.strike_value}' vs '{kalshi.strike_value}'."
                )

        # 8. Resolution Rules & Edge-Case Defenses (Section 12)
        poly_rules = f"{poly.resolution_rules} {poly.invalidation_rules}".lower()
        kalshi_rules = f"{kalshi.resolution_rules} {kalshi.invalidation_rules}".lower()

        # Revisions / Preliminary vs Final data
        is_poly_prelim = any(w in poly_rules for w in ["preliminary", "first", "unrevised"])
        is_kalshi_prelim = any(w in kalshi_rules for w in ["preliminary", "first", "unrevised"])
        is_poly_final = any(w in poly_rules for w in ["final", "revised", "later"])
        is_kalshi_final = any(w in kalshi_rules for w in ["final", "revised", "later"])

        if (is_poly_prelim and is_kalshi_final) or (is_poly_final and is_kalshi_prelim):
            return cls._build_result(
                mapping_id, poly, kalshi,
                EquivalenceClass.SEMANTIC_ONLY, False,
                MappingStatus.SEMANTIC_ONLY,
                "REVISION_POLICY_MISMATCH: Preliminary vs revised settlement data definition divergence."
            )

        # Cancellation / Void rules mismatch
        if poly.cancellation_rules and kalshi.cancellation_rules:
            if poly.cancellation_rules.strip().lower() != kalshi.cancellation_rules.strip().lower():
                # If one cancels on delay and other extends
                if ("void" in poly.cancellation_rules.lower() and "delay" in kalshi.cancellation_rules.lower()):
                    return cls._build_result(
                        mapping_id, poly, kalshi,
                        EquivalenceClass.NON_EQUIVALENT, False,
                        MappingStatus.NON_EQUIVALENT,
                        "CANCELLATION_RULE_MISMATCH: Voiding vs postponement policy divergence."
                    )

        # 9. Full Parity Established
        reason = (
            f"EXACT_EQUIVALENT: Identical event '{poly.underlying_event}', metric '{poly_metric}', "
            f"geography '{poly.geographic_scope}', horizon '{poly_temp}', strike {poly.threshold}, "
            f"direction '{poly_dir}', and resolution source '{poly_src}'."
        )
        return cls._build_result(
            mapping_id, poly, kalshi,
            EquivalenceClass.EXACT_EQUIVALENT, True,
            MappingStatus.EXACT_EQUIVALENT,
            reason
        )

    @staticmethod
    def _build_result(
        mapping_id: str,
        poly: CanonicalEconomicContract,
        kalshi: CanonicalEconomicContract,
        eq_class: EquivalenceClass,
        settlement_eq: bool,
        status: MappingStatus,
        reason: str,
    ) -> ContractMappingResult:
        result = ContractMappingResult(
            mapping_id=mapping_id,
            polymarket_market_id=poly.venue_contract_id,
            polymarket_token_id=f"token_{poly.venue_contract_id}",
            kalshi_market_id=kalshi.venue_contract_id,
            kalshi_contract_id=kalshi.venue_contract_id,
            canonical_contract_id=f"canon_{poly.compute_contract_hash()[:12]}",
            equivalence_class=eq_class,
            settlement_equivalence=settlement_eq,
            mapping_status=status,
            mapping_reason=reason,
            resolution_source_polymarket=poly.source_of_resolution,
            resolution_source_kalshi=kalshi.source_of_resolution,
            resolution_time_polymarket=poly.resolution_timestamp.isoformat() if poly.resolution_timestamp else None,
            resolution_time_kalshi=kalshi.resolution_timestamp.isoformat() if kalshi.resolution_timestamp else None,
            threshold_polymarket=poly.threshold,
            threshold_kalshi=kalshi.threshold,
            direction_polymarket=poly.inequality_direction,
            direction_kalshi=kalshi.inequality_direction,
            currency_polymarket=poly.currency,
            currency_kalshi=kalshi.currency,
        )
        result.mapping_config_hash = result.compute_mapping_hash()
        return result
