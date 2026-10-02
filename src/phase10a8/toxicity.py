"""Pre-Trade Toxicity Analysis and Conditional Microstructure Stratification for Phase 10A.8.

Responsibilities:
1. Relate pre-trade observables (spread, imbalance, flow momentum, volatility, intensity)
   to subsequent adverse selection and fill rates.
2. Stratify fills by toxicity indicators to test Hypothesis H3 (Toxicity Filtering).
3. Strictly prevent lookahead: all conditioning features use data timestamped prior to quote.
"""

from typing import Dict, Any, List, Optional
import numpy as np
from src.phase10a8.schema import (
    QuoteSide,
    MakerEconomicsRecord,
    PassiveQuote,
)


class ToxicityAnalyzer:
    """Evaluates conditional adverse selection and fill dynamics given pre-trade microstructure states."""

    @staticmethod
    def classify_toxicity_condition(
        quote: PassiveQuote,
    ) -> Dict[str, str]:
        """Categorizes quote into descriptive toxicity dimensions using pre-quote data."""
        # 1. Flow Alignment: Does recent order flow push against our passive quote?
        # If BUY quote and recent trade flow is heavily negative -> Adverse flow
        # If SELL quote and recent trade flow is heavily positive -> Adverse flow
        is_adverse_flow = (
            (quote.side == QuoteSide.BUY and quote.recent_trade_flow_usd < -100.0) or
            (quote.side == QuoteSide.SELL and quote.recent_trade_flow_usd > 100.0)
        )
        flow_condition = "TOXIC_FLOW" if is_adverse_flow else "BENIGN_FLOW"

        # 2. Book Imbalance: Is book heavily skewed against our quote?
        is_adverse_imbalance = (
            (quote.side == QuoteSide.BUY and quote.book_imbalance < -0.30) or
            (quote.side == QuoteSide.SELL and quote.book_imbalance > 0.30)
        )
        imbalance_condition = "ADVERSE_IMBALANCE" if is_adverse_imbalance else "NORMAL_IMBALANCE"

        # 3. Volatility State: Is short-term volatility elevated?
        vol_condition = "HIGH_VOLATILITY" if quote.recent_volatility_bps > 50.0 else "LOW_VOLATILITY"

        # 4. Trade Intensity: Is trading unusually active?
        intensity_condition = "HIGH_INTENSITY" if quote.recent_trade_intensity > 5.0 else "LOW_INTENSITY"

        return {
            "flow": flow_condition,
            "imbalance": imbalance_condition,
            "volatility": vol_condition,
            "intensity": intensity_condition,
            "is_toxic_composite": (is_adverse_flow or is_adverse_imbalance or vol_condition == "HIGH_VOLATILITY"),
        }

    @classmethod
    def aggregate_conditional_results(
        cls,
        quotes: List[PassiveQuote],
        economics_records: List[MakerEconomicsRecord],
    ) -> Dict[str, Dict[str, Any]]:
        """Computes fill probability, adverse selection, and net EV across pre-trade toxicity strata."""
        quotes_map = {q.quote_id: q for q in quotes}
        
        strata: Dict[str, List[MakerEconomicsRecord]] = {
            "ALL": [],
            "BENIGN_FLOW": [],
            "TOXIC_FLOW": [],
            "NORMAL_IMBALANCE": [],
            "ADVERSE_IMBALANCE": [],
            "LOW_VOLATILITY": [],
            "HIGH_VOLATILITY": [],
            "COMPOSITE_BENIGN": [],
            "COMPOSITE_TOXIC": [],
        }

        for rec in economics_records:
            strata["ALL"].append(rec)
            q = quotes_map.get(rec.quote_id)
            if not q:
                continue

            conds = cls.classify_toxicity_condition(q)
            
            if conds["flow"] == "TOXIC_FLOW":
                strata["TOXIC_FLOW"].append(rec)
            else:
                strata["BENIGN_FLOW"].append(rec)

            if conds["imbalance"] == "ADVERSE_IMBALANCE":
                strata["ADVERSE_IMBALANCE"].append(rec)
            else:
                strata["NORMAL_IMBALANCE"].append(rec)

            if conds["volatility"] == "HIGH_VOLATILITY":
                strata["HIGH_VOLATILITY"].append(rec)
            else:
                strata["LOW_VOLATILITY"].append(rec)

            if conds["is_toxic_composite"]:
                strata["COMPOSITE_TOXIC"].append(rec)
            else:
                strata["COMPOSITE_BENIGN"].append(rec)

        results: Dict[str, Dict[str, Any]] = {}
        for stratum_name, recs in strata.items():
            if not recs:
                results[stratum_name] = {
                    "count": 0,
                    "fill_rate": 0.0,
                    "gross_spread_bps": 0.0,
                    "adverse_selection_bps": 0.0,
                    "liquidation_cost_bps": 0.0,
                    "net_ev_bps": 0.0,
                }
                continue

            n_total = len(recs)
            filled_recs = [r for r in recs if r.is_filled]
            n_filled = len(filled_recs)
            fill_rate = n_filled / n_total if n_total > 0 else 0.0

            if filled_recs:
                mean_gross = float(np.mean([r.gross_spread_capture_bps for r in filled_recs]))
                mean_adv = float(np.mean([r.adverse_selection_bps for r in filled_recs]))
                mean_liq = float(np.mean([r.liquidation_cost_bps for r in filled_recs]))
                mean_net = float(np.mean([r.net_maker_pnl_bps for r in filled_recs]))
            else:
                mean_gross = 0.0
                mean_adv = 0.0
                mean_liq = 0.0
                mean_net = 0.0

            results[stratum_name] = {
                "count": n_total,
                "n_filled": n_filled,
                "fill_rate": round(fill_rate, 4),
                "gross_spread_bps": round(mean_gross, 2),
                "adverse_selection_bps": round(mean_adv, 2),
                "liquidation_cost_bps": round(mean_liq, 2),
                "net_ev_bps": round(mean_net, 2),
            }

        return results
