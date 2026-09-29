"""Market Normalization Engine.
Converts heterogeneous prediction market questions and descriptions into canonical representations.
"""
import re
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from src.normalization.schema import Market, CanonicalMarket, Platform

logger = logging.getLogger(__name__)

class MarketNormalizer:
    """Normalizes raw markets into canonical structured representations."""

    # Common entity patterns
    ENTITY_PATTERNS = {
        "Federal Reserve / Fed": [r"\bfed\b", r"\bfederal reserve\b", r"\bfomc\b", r"\bjerome powell\b"],
        "European Central Bank / ECB": [r"\becb\b", r"\beuropean central bank\b", r"\blagarde\b"],
        "Bank of Japan / BOJ": [r"\bboj\b", r"\bbank of japan\b", r"\bueda\b"],
        "Donald Trump": [r"\btrump\b", r"\bdonald trump\b"],
        "Kamala Harris": [r"\bharris\b", r"\bkamala harris\b"],
        "Joe Biden": [r"\bbiden\b", r"\bjoe biden\b"],
        "JD Vance": [r"\bvance\b", r"\bjd vance\b"],
        "Bitcoin": [r"\bbitcoin\b", r"\bbtc\b"],
        "Ethereum": [r"\beth\b", r"\bethereum\b"],
        "Solana": [r"\bsol\b", r"\bsolana\b"],
        "S&P 500": [r"\bs&p\b", r"\bspx\b", r"\bspy\b"],
        "Nasdaq": [r"\bnasdaq\b", r"\bqqq\b"],
        "Crude Oil": [r"\boil\b", r"\bwti\b", r"\bbrent\b"],
        "Gold": [r"\bgold\b", r"\bxau\b"],
        "US Congress": [r"\bcongress\b", r"\bsenate\b", r"\bhouse of representatives\b"],
        "Supreme Court": [r"\bsupreme court\b", r"\bscotus\b"],
        "China": [r"\bchina\b", r"\bbeijing\b", r"\bxi jinping\b"],
        "Russia": [r"\brussia\b", r"\bputin\b", r"\bmoscow\b"],
        "Ukraine": [r"\bukraine\b", r"\bkyiv\b", r"\bzelensky\b"],
        "Israel": [r"\bisrael\b", r"\bnetanyahu\b", r"\bidf\b"],
        "Iran": [r"\biran\b", r"\btehran\b"],
        "Tesla": [r"\btesla\b", r"\btsla\b", r"\belon musk\b"],
        "Apple": [r"\bapple\b", r"\baapl\b"],
        "Nvidia": [r"\bnvidia\b", r"\bnvda\b"],
        "OpenAI": [r"\bopenai\b", r"\bchatgpt\b", r"\bsam altman\b"],
    }

    EVENT_TYPES = {
        "rate_decision": [r"rate cut", r"rate hike", r"interest rate", r"bps cut", r"basis point"],
        "macro_indicator": [r"cpi", r"inflation", r"gdp", r"unemployment", r"nonfarm payroll", r"jobs report"],
        "election_outcome": [r"win the presidency", r"win presidential", r"win election", r"win the senate", r"win the house"],
        "appointment_exit": [r"out before", r"resign", r"step down", r"impeached", r"fired", r"replaced"],
        "price_milestone": [r"reach \$", r"hit \$", r"above \$", r"below \$", r"over \$", r"under \$"],
        "regulatory_legal": [r"approved", r"etf approval", r"indicted", r"ruling", r"verdict", r"pardon"],
        "geopolitical_conflict": [r"ceasefire", r"invade", r"strike", r"military action", r"nuclear"],
        "sports_championship": [r"win the championship", r"win the cup", r"win the title", r"win match", r"super bowl", r"nba finals"],
    }

    def normalize(self, market: Market) -> CanonicalMarket:
        """Derive canonical representation from Market title, description, and rules."""
        text = f"{market.title} {market.description} {market.resolution_rules}".lower()

        # 1. Identify Entities
        matched_entities: List[str] = []
        for entity_name, patterns in self.ENTITY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text):
                    matched_entities.append(entity_name)
                    break
        if not matched_entities:
            # Fallback: extract capitalized noun phrases from title
            caps = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", market.title)
            matched_entities = caps[:3] if caps else ["Unknown Entity"]

        # 2. Identify Event Type
        event_type = "general_event"
        for etype, patterns in self.EVENT_TYPES.items():
            for pat in patterns:
                if re.search(pat, text):
                    event_type = etype
                    break
            if event_type != "general_event":
                break

        # 3. Extract Geographic Scope
        geo = "Global"
        if any(w in text for w in ["fed", "us ", "u.s.", "united states", "biden", "trump", "congress", "senate", "dollar", "nasdaq"]):
            geo = "United States"
        elif any(w in text for w in ["ecb", "europe", "eurozone", "uk", "britain", "germany", "france"]):
            geo = "Europe"
        elif any(w in text for w in ["china", "xi jinping", "taiwan", "japan", "asia"]):
            geo = "Asia-Pacific"
        elif any(w in text for w in ["russia", "ukraine"]):
            geo = "Eastern Europe"
        elif any(w in text for w in ["israel", "gaza", "iran", "middle east"]):
            geo = "Middle East"

        # 4. Extract Threshold / Condition
        threshold = None
        direction = None
        num_cond: Dict[str, Any] = {}

        # Look for numbers/dollar amounts/percentages
        price_match = re.search(r"(\$|usd\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(k|m|b)?", text)
        if re.search(r"\b(above|greater than|over|more than|at least|reach|hit)\b", text):
            direction = ">="
        elif re.search(r"\b(below|less than|under|fewer than)\b", text):
            direction = "<="

        if price_match:
            val_str = price_match.group(2).replace(",", "")
            multiplier = 1.0
            unit = price_match.group(3)
            if unit == 'k':
                multiplier = 1000.0
            elif unit == 'm':
                multiplier = 1_000_000.0
            elif unit == 'b':
                multiplier = 1_000_000_000.0
            try:
                val = float(val_str) * multiplier
                threshold = f"{direction or '='} {val}"
                num_cond = {"value": val, "unit": unit or "dollars", "direction": direction}
            except Exception:
                pass

        # 5. Extract Time Horizon
        time_horizon = "Unknown"
        if market.close_time:
            time_horizon = f"Until {market.close_time.strftime('%Y-%m-%d')}"
        else:
            date_match = re.search(r"\b(by|before|in|end of)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4})\b", text)
            if date_match:
                time_horizon = f"Before {date_match.group(2)}"

        # 6. Extract Resolution Source & Ambiguity Flags
        source = market.metadata.get("resolutionSource") or "Official Market Resolution Source"
        methodology = "Binary Settlement"
        ambiguity_flags = []

        if len(market.resolution_rules.strip()) < 20:
            ambiguity_flags.append("sparse_resolution_rules")
        if "discretion" in text or "uma" in text or "consensus" in text:
            ambiguity_flags.append("oracle_discretion_risk")
        if "revision" in text or "preliminary" in text:
            ambiguity_flags.append("data_revision_risk")
        if "cancel" in text or "void" in text or "postpone" in text:
            ambiguity_flags.append("cancellation_clause_risk")

        underlying_event = f"{', '.join(matched_entities)}: {event_type}"

        return CanonicalMarket(
            market_id=market.market_id,
            platform=market.platform,
            title=market.title,
            underlying_event=underlying_event,
            entities=matched_entities,
            geographic_scope=geo,
            time_horizon=time_horizon,
            event_type=event_type,
            threshold=threshold,
            direction=direction,
            numerical_conditions=num_cond,
            resolution_date=market.close_time.isoformat() if market.close_time else None,
            resolution_source=source,
            resolution_methodology=methodology,
            ambiguity_flags=ambiguity_flags,
        )

    def normalize_batch(self, markets: List[Market]) -> List[CanonicalMarket]:
        return [self.normalize(m) for m in markets]
