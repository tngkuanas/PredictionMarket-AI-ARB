"""Phase 3: Resolution-Rule Analysis, Basis-Risk Adjusted Net EV, and Walk-Forward OOS Testing.
Separates opportunities into Baseline Control Group (Structural & Logical) vs Novel AI-Discovered.
Answers the central research question:
'After removing all mechanically discoverable relationships, does AI discover additional relationships
that produce positive net EV out-of-sample?'
"""
import json
import logging
from typing import List, Dict, Any
import pandas as pd
from tabulate import tabulate

from src.db.duckdb_store import get_db
from src.normalization.normalizer import MarketNormalizer
from src.normalization.schema import (
    CandidateRelationship,
    CanonicalMarket,
    Market,
    OpportunityClass,
    HypothesisVerdict,
)
from src.llm.relationship_discovery import RelationshipDiscoveryEngine
from src.llm.resolution_analyzer import ResolutionRuleAnalyzer
from src.statistics.falsification_engine import HypothesisFalsificationEngine
from src.strategies.ev_engine import MispricingEVEngine
from src.execution.fee_model import DynamicExecutionCostModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_phase3_pipeline() -> dict:
    db = get_db()
    with db.get_connection() as con:
        df_markets = con.execute("SELECT * FROM markets").df()
        df_canon = con.execute("SELECT * FROM canonical_markets").df()
        df_obs = con.execute("SELECT * FROM market_snapshots ORDER BY timestamp ASC").df()

    logger.info(f"Loaded {len(df_markets)} markets and {len(df_obs)} snapshots from DuckDB.")

    # Reconstruct Market and CanonicalMarket lookup dictionaries
    markets_by_id = {}
    canon_by_id = {}

    for _, row in df_markets.iterrows():
        outcomes = json.loads(row["outcome_labels"]) if isinstance(row["outcome_labels"], str) else row["outcome_labels"]
        tokens = json.loads(row["clob_token_ids"]) if isinstance(row["clob_token_ids"], str) else row.get("clob_token_ids", [])
        m = Market(
            platform=row["platform"],
            market_id=str(row["market_id"]),
            event_id=str(row["event_id"]),
            title=row["title"],
            description=row["description"] or "",
            resolution_rules=row["resolution_rules"] or "",
            outcome_labels=outcomes or ["Yes", "No"],
            category=row["category"],
            open_time=row["open_time"] if not pd.isna(row["open_time"]) else None,
            close_time=row["close_time"] if not pd.isna(row["close_time"]) else None,
            status=row["status"],
            clob_token_ids=tokens,
            volume=float(row["volume"] or 0.0),
            liquidity=float(row["liquidity"] or 0.0),
        )
        markets_by_id[m.market_id] = m

    for _, row in df_canon.iterrows():
        entities = json.loads(row["entities"]) if isinstance(row["entities"], str) else row["entities"]
        flags = json.loads(row["ambiguity_flags"]) if isinstance(row["ambiguity_flags"], str) else row["ambiguity_flags"]
        c = CanonicalMarket(
            market_id=str(row["market_id"]),
            platform=row["platform"],
            title=row["title"],
            underlying_event=str(row["underlying_event"]),
            entities=entities or [],
            geographic_scope=str(row["geographic_scope"]),
            time_horizon=str(row["time_horizon"]),
            event_type=str(row["event_type"]),
            threshold=str(row["threshold"]) if not pd.isna(row["threshold"]) else None,
            direction=str(row["direction"]) if not pd.isna(row["direction"]) else None,
            resolution_date=str(row["resolution_date"]) if not pd.isna(row["resolution_date"]) else None,
            resolution_source=str(row["resolution_source"]) if not pd.isna(row["resolution_source"]) else None,
            resolution_methodology=str(row["resolution_methodology"]) if not pd.isna(row["resolution_methodology"]) else None,
            ambiguity_flags=flags or [],
        )
        canon_by_id[c.market_id] = c

    # Step 1: Generate Candidates across Baseline Control vs Novel AI
    discovery_engine = RelationshipDiscoveryEngine()
    logger.info("=== STEP 1: Discovering Hypotheses (Baseline Control vs Novel AI) ===")
    canonical_list = list(canon_by_id.values())
    candidates = discovery_engine.discover_hypotheses(canonical_list, max_candidates=50)
    logger.info(f"Generated {len(candidates)} candidate hypotheses.")
    db.save_relationships(candidates)

    # Step 2: Resolution Rule Comparison
    logger.info("=== STEP 2: Running Resolution-Rule & Basis Risk Analysis ===")
    res_analyzer = ResolutionRuleAnalyzer()
    resolution_reports = {}
    for cand in candidates:
        ma = markets_by_id.get(cand.discovery.market_a_id)
        mb = markets_by_id.get(cand.discovery.market_b_id)
        if ma and mb:
            ca = canon_by_id.get(ma.market_id)
            cb = canon_by_id.get(mb.market_id)
            res_analysis = res_analyzer.analyze_pair(
                market_a=ma,
                market_b=mb,
                canonical_a=ca,
                canonical_b=cb,
                opportunity_class=cand.discovery.opportunity_class
            )
            resolution_reports[cand.constraint.constraint_id] = res_analysis

    # Step 3: Prepare hourly aligned price time-series
    logger.info("=== STEP 3: Preparing Point-in-Time Hourly Price Series ===")
    market_to_token = {}
    for m in markets_by_id.values():
        if m.clob_token_ids:
            market_to_token[m.market_id] = str(m.clob_token_ids[0])

    df_obs_clean = df_obs.copy()
    df_obs_clean["hourly_ts"] = pd.to_datetime(df_obs_clean["timestamp"]).dt.floor("1h")
    hourly_df = df_obs_clean.groupby(["hourly_ts", "market_id"])["yes_mid"].mean().reset_index()
    pivoted = hourly_df.pivot(index="hourly_ts", columns="market_id", values="yes_mid")

    # Step 4: Strict Walk-Forward In-Sample (60%) vs Out-of-Sample (40%) Falsification
    logger.info("=== STEP 4: Executing Walk-Forward In-Sample & Out-of-Sample Testing ===")
    cost_model = DynamicExecutionCostModel(
        default_taker_fee=0.001,
        default_maker_fee=0.0,
        min_spread_cents=0.005
    )
    ev_engine = MispricingEVEngine(
        min_required_net_edge=0.015,
        default_spread=0.012,
        dynamic_cost_model=cost_model
    )
    falsifier = HypothesisFalsificationEngine(
        min_net_edge_pp=0.015,
        epoch_window_hours=72.0, # 72-hour independent macro event epoch clustering
        ev_engine=ev_engine
    )

    falsification_reports = []
    for cand in candidates:
        m_a = cand.discovery.market_a_id
        m_b = cand.discovery.market_b_id
        tok_a = market_to_token.get(m_a)
        tok_b = market_to_token.get(m_b)
        res_rep = resolution_reports.get(cand.constraint.constraint_id)

        if tok_a in pivoted.columns and tok_b in pivoted.columns:
            s_a = pivoted[tok_a].dropna()
            s_b = pivoted[tok_b].dropna()
            if not s_a.empty and not s_b.empty:
                start_date = max(s_a.index.min(), s_b.index.min())
                end_date = min(s_a.index.max(), s_b.index.max())
                if (end_date - start_date).total_seconds() >= 48 * 3600:
                    idx_range = pd.date_range(start_date, end_date, freq="1h")
                    series_a = s_a.reindex(idx_range).ffill()
                    series_b = s_b.reindex(idx_range).ffill()
                    mb_obj = markets_by_id.get(m_b)
                    liq_b = mb_obj.liquidity if mb_obj else 50_000.0

                    report = falsifier.test_hypothesis_walk_forward(
                        relationship=cand,
                        series_a=series_a,
                        series_b=series_b,
                        resolution_analysis=res_rep,
                        liquidity_b=liq_b,
                        split_ratio=0.60
                    )
                else:
                    report = falsifier._build_verdict(
                        cand, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                        False, False, 0.0, 0.016, 0.0,
                        HypothesisVerdict.REJECTED_UNDERPOWERED,
                        kill_reason="Insufficient overlapping active trading span (<48h)"
                    )
            else:
                report = falsifier._build_verdict(
                    cand, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                    False, False, 0.0, 0.016, 0.0,
                    HypothesisVerdict.REJECTED_UNDERPOWERED,
                    kill_reason="Empty price history for one or both markets"
                )
        else:
            report = falsifier._build_verdict(
                cand, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0,
                False, False, 0.0, 0.016, 0.0,
                HypothesisVerdict.REJECTED_UNDERPOWERED,
                kill_reason="Market token ID not found in historical snapshot series"
            )
        falsification_reports.append(report)

    db.save_falsification_reports(falsification_reports)

    # Step 5: Comparative Analysis: Baseline Control Group vs Novel AI Opportunities
    table_rows = []
    group_stats = {
        "Baseline Control (Structural)": {"tested": 0, "tradeable": 0, "oos_edge_sum": 0.0},
        "Baseline Control (Logical)": {"tested": 0, "tradeable": 0, "oos_edge_sum": 0.0},
        "Novel AI Discovered": {"tested": 0, "tradeable": 0, "oos_edge_sum": 0.0}
    }

    for rep, cand in zip(falsification_reports, candidates):
        opp_class = cand.discovery.opportunity_class
        v = rep.verdict.value if hasattr(rep.verdict, "value") else str(rep.verdict)

        if opp_class == OpportunityClass.STRUCTURAL:
            group = "Baseline Control (Structural)"
        elif opp_class == OpportunityClass.CROSS_MARKET_LOGICAL:
            group = "Baseline Control (Logical)"
        else:
            group = "Novel AI Discovered"

        group_stats[group]["tested"] += 1
        if v == "TRADEABLE":
            group_stats[group]["tradeable"] += 1
            group_stats[group]["oos_edge_sum"] += rep.net_expected_edge_pp

        t_a = markets_by_id[rep.market_a].title[:24] if rep.market_a in markets_by_id else rep.market_a[:16]
        t_b = markets_by_id[rep.market_b].title[:24] if rep.market_b in markets_by_id else rep.market_b[:16]

        table_rows.append([
            group[:18],
            f"{t_a} -> {t_b}",
            f"{rep.is_sample_size_n}/{rep.oos_sample_size_n}",
            f"{rep.net_effect_pp*100:+.1f}%" if rep.is_sample_size_n > 0 else "N/A",
            f"{rep.oos_net_effect_pp*100:+.1f}%" if rep.oos_sample_size_n > 0 else "N/A",
            f"{rep.resolution_divergence_prob*100:.0f}%",
            f"{rep.friction_costs_pp*100:.2f}%",
            f"{rep.net_expected_edge_pp*100:+.2f}%",
            v
        ])

    print("\n" + "="*110)
    print("PHASE 3: RESOLUTION-RULE BASIS RISK & WALK-FORWARD OUT-OF-SAMPLE AUDIT")
    print("="*110)
    headers = [
        "Opportunity Group", "Hypothesis (A -> B)", "N (IS/OOS)",
        "IS NetEff", "OOS NetEff", "P(div)", "Friction", "Net EV", "Verdict"
    ]
    print(tabulate(table_rows, headers=headers, tablefmt="github"))
    print("="*110)

    print("\n" + "="*80)
    print("SUMMARY: BASELINE CONTROL GROUP VS NOVEL AI DISCOVERY")
    print("="*80)
    summary_rows = []
    for grp, stats in group_stats.items():
        avg_edge = (stats["oos_edge_sum"] / stats["tradeable"]) if stats["tradeable"] > 0 else 0.0
        summary_rows.append([
            grp,
            stats["tested"],
            stats["tradeable"],
            f"{(stats['tradeable']/stats['tested']*100 if stats['tested'] > 0 else 0):.1f}%",
            f"{avg_edge*100:+.2f}%"
        ])
    print(tabulate(summary_rows, headers=["Opportunity Group", "Tested", "Tradeable", "Pass Rate", "Avg Net OOS EV"], tablefmt="github"))
    print("="*80)

    # Core Research Question Empirical Answer
    ai_tradeable = group_stats["Novel AI Discovered"]["tradeable"]
    struct_tradeable = group_stats["Baseline Control (Structural)"]["tradeable"]
    print("\nRESEARCH QUESTION ANSWER:")
    if ai_tradeable > 0:
        print(f"-> YES: AI discovered {ai_tradeable} non-mechanical opportunities that survived strict OOS walk-forward testing and basis risk deductions.")
    else:
        print(f"-> NO: While mechanical structural arbitrage succeeded ({struct_tradeable} tradeable bounds), zero non-mechanical AI semantic relationships survived strict OOS replication and basis-risk friction.")

    return {
        "group_stats": group_stats,
        "total_hypotheses": len(candidates),
        "falsification_reports": [r.model_dump() for r in falsification_reports]
    }

if __name__ == "__main__":
    run_phase3_pipeline()
