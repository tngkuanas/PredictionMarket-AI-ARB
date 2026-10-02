"""Deterministic Contract Relationship & Equivalence Engine for Phase 10A.9.

Identifies, formalizes, and deterministically validates candidate hedge relationships
from Polymarket market universe data without LLM hallucination or correlation estimates.
"""

from datetime import datetime, timezone
import hashlib
import re
from typing import Dict, Any, List, Optional, Tuple, Set
from collections import defaultdict

from src.phase10a9.schema import (
    RelationshipType,
    RelationshipValidationStatus,
    RelationshipRejectionReason,
    ContractRelationshipRecord,
    BasisRiskRecord,
)


class DeterministicRelationshipEngine:
    """Rigorous deterministic engine discovering and validating hedgeable contract pairs."""

    def __init__(self):
        self.rejection_counts: Dict[RelationshipRejectionReason, int] = defaultdict(int)
        self.rejection_details: List[Dict[str, Any]] = []

    def discover_and_validate_universe(
        self,
        market_universe_rows: List[Dict[str, Any]]
    ) -> Tuple[List[ContractRelationshipRecord], Dict[str, Any]]:
        """Processes raw market universe rows, discovering valid hedge relationships and logging rejections."""
        # 1. Group tokens by market_id
        markets_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in market_universe_rows:
            mid = str(row.get("market_id", ""))
            if mid:
                markets_map[mid].append(row)

        relationships: List[ContractRelationshipRecord] = []
        total_markets = len(markets_map)
        total_binary_markets = 0
        candidate_pairs_evaluated = 0

        # Pass 1: Intra-market Complementary Relationships (R1)
        for mid, tokens in markets_map.items():
            # Deduplicate tokens by token_id
            unique_tokens = {}
            for t in tokens:
                unique_tokens[t["token_id"]] = t
            token_list = list(unique_tokens.values())

            if len(token_list) == 2:
                total_binary_markets += 1
                candidate_pairs_evaluated += 1
                t_a = token_list[0]
                t_b = token_list[1]

                rel = self._evaluate_r1_pair(mid, t_a, t_b)
                if rel:
                    relationships.append(rel)

            elif len(token_list) > 2:
                # Multi-outcome market: evaluate R4
                candidate_pairs_evaluated += (len(token_list) * (len(token_list) - 1)) // 2
                r4_rels = self._evaluate_r4_set(mid, token_list)
                relationships.extend(r4_rels)

        # Pass 2: Cross-Market Nested (R3) and Complementary (R2)
        r2_r3_rels, cross_pairs_count = self._evaluate_cross_market_relationships(markets_map)
        candidate_pairs_evaluated += cross_pairs_count
        relationships.extend(r2_r3_rels)

        # Compile coverage metrics
        coverage = {
            "total_active_markets": total_markets,
            "total_binary_markets": total_binary_markets,
            "candidate_pairs_evaluated": candidate_pairs_evaluated,
            "exact_hedgeable_pairs": sum(1 for r in relationships if r.validation_status == RelationshipValidationStatus.EXACT_HEDGEABLE),
            "bounded_hedgeable_pairs": sum(1 for r in relationships if r.validation_status == RelationshipValidationStatus.BOUNDED_HEDGEABLE),
            "conditional_hedgeable_pairs": sum(1 for r in relationships if r.validation_status == RelationshipValidationStatus.CONDITIONALLY_HEDGEABLE),
            "total_accepted_relationships": len(relationships),
            "total_rejected_pairs": sum(self.rejection_counts.values()),
            "rejection_reasons_breakdown": {k.value: v for k, v in self.rejection_counts.items() if v > 0},
        }

        return relationships, coverage

    def _evaluate_r1_pair(
        self,
        market_id: str,
        token_a: Dict[str, Any],
        token_b: Dict[str, Any]
    ) -> Optional[ContractRelationshipRecord]:
        """Evaluates intra-market binary complement (YES/NO or Outcome 1 / Outcome 2)."""
        tok_id_a = str(token_a["token_id"])
        tok_id_b = str(token_b["token_id"])
        out_a = str(token_a.get("outcome", "")).strip().lower()
        out_b = str(token_b.get("outcome", "")).strip().lower()
        title = str(token_a.get("title", "")) or str(token_b.get("title", ""))

        # Check binary outcome exhaustiveness
        is_yes_no = (out_a in ("yes", "no") and out_b in ("yes", "no") and out_a != out_b)
        is_up_down = (out_a in ("up", "down") and out_b in ("up", "down") and out_a != out_b)
        is_head_to_head = (out_a != out_b and len(out_a) > 0 and len(out_b) > 0)

        if not (is_yes_no or is_up_down or is_head_to_head):
            self._record_rejection(
                tok_id_a, tok_id_b, RelationshipRejectionReason.SETTLEMENT_MISMATCH,
                f"Outcomes '{out_a}' and '{out_b}' do not form an exhaustive binary pair."
            )
            return None

        # Check if market has ambiguous resolution clauses
        if "provisional" in title.lower() or "unofficial" in title.lower():
            self._record_rejection(
                tok_id_a, tok_id_b, RelationshipRejectionReason.AMBIGUOUS,
                f"Market title contains provisional/unofficial clauses: {title}"
            )
            return None

        # Generate deterministic relationship ID
        rel_id = f"rel_r1_{market_id}_{tok_id_a[:8]}_{tok_id_b[:8]}"

        return ContractRelationshipRecord(
            relationship_id=rel_id,
            contract_a=tok_id_a,
            contract_b=tok_id_b,
            market_id_a=market_id,
            market_id_b=market_id,
            relationship_type=RelationshipType.R1_COMPLEMENTARY_BINARY,
            event_identity=f"mkt_{market_id}",
            variable="BINARY_OUTCOME",
            threshold=None,
            inequality=None,
            time_window=str(token_a.get("timestamp", "PERPETUAL")),
            timezone="UTC",
            geography="GLOBAL",
            resolution_source="POLYMARKET_ORACLE",
            resolution_date="RESOLUTION_EXPIRY",
            payout_formula="Payoff(A) + Payoff(B) == 1.0",
            hedge_ratio=1.0,
            relationship_confidence=1.0,
            validation_status=RelationshipValidationStatus.EXACT_HEDGEABLE,
            reason=f"Exhaustive binary complementary tokens in market '{title[:50]}'"
        )

    def _evaluate_r4_set(
        self,
        market_id: str,
        tokens: List[Dict[str, Any]]
    ) -> List[ContractRelationshipRecord]:
        """Evaluates mutually exclusive multi-outcome set where sum(P_i) == 1."""
        records = []
        n = len(tokens)
        for i in range(n):
            for j in range(i + 1, n):
                t_a = tokens[i]
                t_b = tokens[j]
                tok_a = str(t_a["token_id"])
                tok_b = str(t_b["token_id"])
                out_a = str(t_a.get("outcome", ""))
                out_b = str(t_b.get("outcome", ""))

                # For multi-outcome set, buying A and buying B is not a complete hedge;
                # but A and B are mutually exclusive: Payoff(A) * Payoff(B) == 0.
                # Hedging A with B alone leaves residual risk (another candidate C could win).
                rel_id = f"rel_r4_{market_id}_{tok_a[:8]}_{tok_b[:8]}"
                rec = ContractRelationshipRecord(
                    relationship_id=rel_id,
                    contract_a=tok_a,
                    contract_b=tok_b,
                    market_id_a=market_id,
                    market_id_b=market_id,
                    relationship_type=RelationshipType.R4_MUTUALLY_EXCLUSIVE_SET,
                    event_identity=f"mkt_{market_id}",
                    variable="MULTI_OUTCOME_PARTITION",
                    threshold=None,
                    inequality=None,
                    time_window="EXPIRY",
                    timezone="UTC",
                    geography="GLOBAL",
                    resolution_source="POLYMARKET_ORACLE",
                    resolution_date="EXPIRY",
                    payout_formula="Payoff(A) * Payoff(B) == 0.0 (Mutually Exclusive)",
                    hedge_ratio=1.0,
                    relationship_confidence=0.90,
                    validation_status=RelationshipValidationStatus.CONDITIONALLY_HEDGEABLE,
                    reason=f"Mutually exclusive outcomes in multi-outcome market ({out_a} vs {out_b})"
                )
                records.append(rec)
        return records

    def _evaluate_cross_market_relationships(
        self,
        markets_map: Dict[str, List[Dict[str, Any]]]
    ) -> Tuple[List[ContractRelationshipRecord], int]:
        """Evaluates cross-market candidate relationships (R2 complementary and R3 nested)."""
        records = []
        cross_pairs_count = 0
        market_ids = list(markets_map.keys())

        # Extract normalized features for each market
        market_features = {}
        for mid in market_ids:
            tokens = markets_map[mid]
            if not tokens:
                continue
            title = str(tokens[0].get("title", ""))
            market_features[mid] = {
                "title": title,
                "tokens": tokens,
                "strike_match": re.search(r"\$(\d+[\d,]*(\.\d+)?)", title),
                "date_match": re.search(r"(october|november|december|september)\s+\d+(,\s+\d{4})?", title, re.I),
                "asset_match": re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol|spx|s&p 500)\b", title, re.I),
            }

        # Compare pairs across markets
        n = len(market_ids)
        for i in range(min(n, 50)):  # Bounded deterministic check
            for j in range(i + 1, min(n, 50)):
                cross_pairs_count += 1
                mid_a = market_ids[i]
                mid_b = market_ids[j]
                feat_a = market_features[mid_a]
                feat_b = market_features[mid_b]

                # Check for R3: Nested strikes on same asset and same date
                if feat_a["asset_match"] and feat_b["asset_match"] and feat_a["date_match"] and feat_b["date_match"]:
                    asset_a = feat_a["asset_match"].group(1).lower()
                    asset_b = feat_b["asset_match"].group(1).lower()
                    date_a = feat_a["date_match"].group(1).lower()
                    date_b = feat_b["date_match"].group(1).lower()

                    if asset_a == asset_b and date_a == date_b and feat_a["strike_match"] and feat_b["strike_match"]:
                        s_a = float(feat_a["strike_match"].group(1).replace(",", ""))
                        s_b = float(feat_b["strike_match"].group(1).replace(",", ""))

                        if s_a != s_b:
                            # Valid R3 nested strike corridor
                            tok_a = str(feat_a["tokens"][0]["token_id"])
                            tok_b = str(feat_b["tokens"][0]["token_id"])
                            rel_id = f"rel_r3_{mid_a[:6]}_{mid_b[:6]}"
                            rec = ContractRelationshipRecord(
                                relationship_id=rel_id,
                                contract_a=tok_a,
                                contract_b=tok_b,
                                market_id_a=mid_a,
                                market_id_b=mid_b,
                                relationship_type=RelationshipType.R3_NESTED_MONOTONIC,
                                event_identity=f"strike_{asset_a}_{date_a}",
                                variable=f"{asset_a.upper()}_PRICE",
                                threshold=abs(s_b - s_a),
                                inequality="MONOTONIC_CORRIDOR",
                                time_window=date_a,
                                timezone="UTC",
                                geography="GLOBAL",
                                resolution_source="BINANCE_ORACLE",
                                resolution_date=date_a,
                                payout_formula=f"0 <= Payoff({min(s_a, s_b)}) - Payoff({max(s_a, s_b)}) <= 1.0",
                                hedge_ratio=1.0,
                                relationship_confidence=0.95,
                                validation_status=RelationshipValidationStatus.BOUNDED_HEDGEABLE,
                                reason=f"Monotonic strike corridor: ${min(s_a, s_b):,.0f} vs ${max(s_a, s_b):,.0f} on {asset_a.upper()}"
                            )
                            records.append(rec)
                            continue

                # Cross-market mismatch logging
                self._record_rejection(
                    mid_a, mid_b, RelationshipRejectionReason.EVENT_MISMATCH,
                    f"Different underlying events: '{feat_a['title'][:30]}' vs '{feat_b['title'][:30]}'"
                )

        return records, cross_pairs_count

    def _record_rejection(
        self,
        id_a: str,
        id_b: str,
        reason: RelationshipRejectionReason,
        details: str
    ) -> None:
        """Records a rejected candidate relationship with explicit audit reason."""
        self.rejection_counts[reason] += 1
        if len(self.rejection_details) < 1000:
            self.rejection_details.append({
                "contract_a": id_a,
                "contract_b": id_b,
                "reason": reason.value,
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

    @staticmethod
    def evaluate_basis_risk(record: ContractRelationshipRecord, notional_usd: float = 50.0) -> BasisRiskRecord:
        """Calculates explicit basis risk and residual payoff bounds for non-exact hedges."""
        if record.validation_status == RelationshipValidationStatus.EXACT_HEDGEABLE:
            return BasisRiskRecord(
                relationship_id=record.relationship_id,
                relationship_type=record.relationship_type,
                maximum_residual_payoff_usd=0.0,
                expected_residual_exposure_usd=0.0,
                worst_case_settlement_mismatch_bps=0.0,
                is_risk_acceptable=True
            )
        elif record.relationship_type == RelationshipType.R3_NESTED_MONOTONIC:
            # For strike corridor, max loss occurs when price settles between strikes
            max_payoff_mismatch = notional_usd
            return BasisRiskRecord(
                relationship_id=record.relationship_id,
                relationship_type=record.relationship_type,
                maximum_residual_payoff_usd=max_payoff_mismatch,
                expected_residual_exposure_usd=max_payoff_mismatch * 0.25,
                worst_case_settlement_mismatch_bps=10_000.0,
                is_risk_acceptable=True  # Bounded corridor
            )
        elif record.relationship_type == RelationshipType.R4_MUTUALLY_EXCLUSIVE_SET:
            # Unhedged third-party outcome risk
            return BasisRiskRecord(
                relationship_id=record.relationship_id,
                relationship_type=record.relationship_type,
                maximum_residual_payoff_usd=notional_usd,
                expected_residual_exposure_usd=notional_usd * 0.50,
                worst_case_settlement_mismatch_bps=10_000.0,
                is_risk_acceptable=False  # Requires full multi-outcome basket
            )
        else:
            return BasisRiskRecord(
                relationship_id=record.relationship_id,
                relationship_type=record.relationship_type,
                maximum_residual_payoff_usd=notional_usd,
                expected_residual_exposure_usd=notional_usd,
                worst_case_settlement_mismatch_bps=10_000.0,
                is_risk_acceptable=False
            )
