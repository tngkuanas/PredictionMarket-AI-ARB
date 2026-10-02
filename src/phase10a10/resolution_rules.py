"""Deterministic Contract Resolution Rule Parser and Evaluator for Phase 10A.10.

Parses contract conditions, variables, inequalities, thresholds, and expiry dates.
Performs deterministic evaluation of whether an authoritative release or event satisfies
the contract's exact resolution language without ambiguity.
"""

from datetime import datetime, timezone
import re
from typing import Dict, Any, Optional, Tuple

from src.phase10a10.schema import ContractResolutionRules, DeterministicState


class ResolutionRulesParser:
    """Parses and validates prediction market resolution criteria."""

    @classmethod
    def parse_market_rules(
        cls,
        market_id: str,
        token_id: str,
        title: str,
        outcome: str,
        category: str = "General",
        description: str = "",
    ) -> ContractResolutionRules:
        """Deterministically extracts condition parameters from market title and metadata."""
        norm_title = title.strip()
        outcome_clean = outcome.strip()

        threshold: Optional[float] = None
        inequality: Optional[str] = None
        variable: Optional[str] = None
        unit: Optional[str] = None
        measurement_date: Optional[str] = None
        measurement_tz: str = "UTC"
        resolution_source: Optional[str] = None

        # 1. Price Threshold Markets: "Will the price of Bitcoin be above $82,000 on September 30?"
        btc_match = re.search(r"price of Bitcoin be (above|below|over|under)\s*\$([0-9,]+)\s*(?:on|by)\s*([A-Za-z0-9\s,]+)\??", norm_title, re.IGNORECASE)
        if btc_match:
            ineq_str = btc_match.group(1).lower()
            inequality = "GT" if ineq_str in ("above", "over") else "LT"
            threshold = float(btc_match.group(2).replace(",", ""))
            measurement_date = btc_match.group(3).strip()
            variable = "BTC_USD_PRICE"
            unit = "USD"
            resolution_source = "binance_coinbase_fix"

        # 2. Daily Price Move: "Bitcoin Up or Down on September 30?" / "S&P 500 (SPX) Opens Up or Down on October 1?"
        up_down_match = re.search(r"(Bitcoin|S&P 500 \(SPX\))\s*(Opens\s+)?(Up or Down)\s*(?:on|by)\s*([A-Za-z0-9\s,]+)\??", norm_title, re.IGNORECASE)
        if up_down_match:
            asset = up_down_match.group(1)
            is_open = bool(up_down_match.group(2))
            variable = f"{asset.upper()}_OPEN_DIRECTION" if is_open else f"{asset.upper()}_DAILY_DIRECTION"
            threshold = 0.0
            inequality = "GT" if outcome_clean.lower() == "up" else "LT"
            measurement_date = up_down_match.group(4).strip()
            resolution_source = "cboe_nyse" if "spx" in asset.lower() else "exchange_index"

        # 3. Ceasefire / Status Markets: "US x Iran ceasefire continues through September 30?"
        ceasefire_match = re.search(r"(.*ceasefire continues through)\s*([A-Za-z0-9\s,]+)\??", norm_title, re.IGNORECASE)
        if ceasefire_match:
            variable = "CEASEFIRE_INTACT"
            measurement_date = ceasefire_match.group(2).strip()
            resolution_source = "state_dept_un"

        # 4. Scheduled Action / Release: "Gemini 4.0 released by September 30, 2026?"
        release_match = re.search(r"(.*)\s+released by\s+([A-Za-z0-9\s,]+)\??", norm_title, re.IGNORECASE)
        if release_match:
            variable = "PRODUCT_RELEASE_OCCURRED"
            measurement_date = release_match.group(2).strip()
            resolution_source = "official_publisher"

        # 5. Sports / Esports Match Winners: "Counter-Strike: BIG vs fnatic - Map 1 Winner" / "Dota 2: BetBoom Team vs OG (BO3)"
        match_winner = re.search(r"(LoL|Dota 2|Counter-Strike|Valorant|China Open|Japan Open):\s*([^-]+)(?:-\s*(.*Winner))?", norm_title, re.IGNORECASE)
        if match_winner:
            variable = "MATCH_WINNER"
            resolution_source = "league_official"

        # 6. Interest Rate Decisions: "Will the Fed decrease interest rates by 25 bps after the October 2026 meeting?"
        fomc_match = re.search(r"Will the Fed (decrease|increase|hold|no change).*after the ([A-Za-z0-9\s]+ meeting)\??", norm_title, re.IGNORECASE)
        if fomc_match:
            variable = "FOMC_RATE_DECISION"
            resolution_source = "federal_reserve"

        rules = ContractResolutionRules(
            market_id=market_id,
            token_id=token_id,
            condition=norm_title,
            outcome=outcome_clean,
            threshold=threshold,
            inequality=inequality,
            measurement_variable=variable,
            measurement_unit=unit,
            measurement_date=measurement_date,
            measurement_timezone=measurement_tz,
            resolution_source=resolution_source,
            is_deterministic_eligible=True,
        )

        # Check for ambiguous wording or missing variables
        if not variable:
            rules.is_deterministic_eligible = False
            rules.rejection_reason = "Unrecognized non-standard contract condition pattern"

        return rules

    @classmethod
    def evaluate_numerical_condition(
        cls,
        actual_value: float,
        threshold: float,
        inequality: str,
        outcome_name: str
    ) -> Tuple[bool, float]:
        """Evaluates whether an authoritative numerical measurement deterministically satisfies the outcome.
        
        Returns: (is_satisfied, deterministic_settlement_value: 1.0 or 0.0)
        """
        is_met = False
        ineq = inequality.upper()
        if ineq == "GT":
            is_met = (actual_value > threshold)
        elif ineq == "GTE":
            is_met = (actual_value >= threshold)
        elif ineq == "LT":
            is_met = (actual_value < threshold)
        elif ineq == "LTE":
            is_met = (actual_value <= threshold)
        elif ineq == "EQ":
            is_met = (actual_value == threshold)

        outcome_norm = outcome_name.strip().lower()
        if outcome_norm in ("yes", "up", "over"):
            settlement_value = 1.0 if is_met else 0.0
        elif outcome_norm in ("no", "down", "under"):
            settlement_value = 0.0 if is_met else 1.0
        else:
            settlement_value = 1.0 if is_met else 0.0

        return is_met, settlement_value
