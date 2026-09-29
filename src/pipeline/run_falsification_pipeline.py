"""Pipeline to run Phase 2 AI Relationship Discovery and Quantitative Falsification."""
import json
import logging
import pandas as pd
from tabulate import tabulate

from src.db.duckdb_store import get_db
from src.normalization.normalizer import MarketNormalizer
from src.normalization.schema import (
    CandidateRelationship,
    CanonicalMarket,
    HypothesisVerdict
)
from src.llm.relationship_discovery import RelationshipDiscoveryEngine
from src.statistics.falsification_engine import HypothesisFalsificationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_falsification_pipeline() -> dict:
    db = get_db()
    with db.get_connection() as con:
        df_markets = con.execute("SELECT * FROM markets").df()
        df_canon = con.execute("SELECT * FROM canonical_markets").df()
        df_obs = con.execute("SELECT * FROM market_snapshots ORDER BY timestamp ASC").df()

    logger.info(f"Loaded {len(df_markets)} markets and {len(df_obs)} snapshots from DuckDB.")

    # Reconstruct CanonicalMarket objects
    canonical_list = []
    normalizer = MarketNormalizer()
    for _, row in df_canon.iterrows():
        entities = json.loads(row["entities"]) if isinstance(row["entities"], str) else row["entities"]
        flags = json.loads(row["ambiguity_flags"]) if isinstance(row["ambiguity_flags"], str) else row["ambiguity_flags"]
        def clean_val(v):
            return None if pd.isna(v) else v

        canonical_list.append(CanonicalMarket(
            market_id=str(row["market_id"]),
            platform=row["platform"],
            title=row["title"],
            underlying_event=str(row["underlying_event"]),
            entities=entities,
            geographic_scope=str(row["geographic_scope"]),
            time_horizon=str(row["time_horizon"]),
            event_type=str(row["event_type"]),
            threshold=clean_val(row["threshold"]),
            direction=clean_val(row["direction"]),
            resolution_date=clean_val(row["resolution_date"]),
            resolution_source=clean_val(row["resolution_source"]),
            resolution_methodology=clean_val(row["resolution_methodology"]),
            ambiguity_flags=flags,
        ))

    # Step 1: Run AI Relationship Discovery (Outputs A & B)
    discovery_engine = RelationshipDiscoveryEngine()
    logger.info("=== STEP 1: Discovering Second-Order Falsifiable Hypotheses ===")
    candidates = discovery_engine.discover_hypotheses(canonical_list, max_candidates=40)
    logger.info(f"Generated {len(candidates)} candidate hypotheses with dual Output A and Output B structure.")

    # Save candidates to DuckDB
    db.save_relationships(candidates)

    # Step 2: Prepare price time-series mapping
    # Create market_id -> hourly Series
    # Map market_id to token_id
    market_to_token = {}
    for _, row in df_markets.iterrows():
        t_ids = row.get("clob_token_ids")
        if isinstance(t_ids, str):
            try:
                t_ids = json.loads(t_ids)
            except Exception:
                t_ids = []
        if isinstance(t_ids, list) and t_ids:
            market_to_token[str(row["market_id"])] = str(t_ids[0])

    df_obs_clean = df_obs.copy()
    df_obs_clean["hourly_ts"] = pd.to_datetime(df_obs_clean["timestamp"]).dt.floor("1h")
    hourly_df = df_obs_clean.groupby(["hourly_ts", "market_id"])["yes_mid"].mean().reset_index()
    pivoted = hourly_df.pivot(index="hourly_ts", columns="market_id", values="yes_mid").ffill().bfill()

    # Step 3: Run Hypothesis Falsification Engine
    logger.info("=== STEP 2: Running Quantitative Hypothesis Falsification Engine ===")
    falsifier = HypothesisFalsificationEngine(
        min_sample_size=10,
        min_net_edge_pp=0.010,
        default_spread_pp=0.012
    )

    falsification_reports = []
    market_titles = {str(row["market_id"]): row["title"] for _, row in df_markets.iterrows()}

    for cand in candidates:
        m_a = cand.discovery.market_a_id
        m_b = cand.discovery.market_b_id

        tok_a = market_to_token.get(m_a)
        tok_b = market_to_token.get(m_b)

        if tok_a in pivoted.columns and tok_b in pivoted.columns:
            series_a = pivoted[tok_a]
            series_b = pivoted[tok_b]
            report = falsifier.test_hypothesis(cand, series_a, series_b)
        else:
            report = falsifier._build_verdict(
                cand, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, False, False, 0.0,
                HypothesisVerdict.REJECTED_UNDERPOWERED,
                kill_reason="Market token ID not found in historical snapshot series"
            )
        falsification_reports.append(report)

    db.save_falsification_reports(falsification_reports)

    # Step 4: Summary Table
    table_rows = []
    verdict_counts = {}
    for rep, cand in zip(falsification_reports, candidates):
        v = rep.verdict.value if hasattr(rep.verdict, "value") else str(rep.verdict)
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        t_a = market_titles.get(rep.market_a, rep.market_a)[:28]
        t_b = market_titles.get(rep.market_b, rep.market_b)[:28]
        eff_str = f"{rep.net_effect_pp*100:+.2f}%" if rep.sample_size_n > 0 else "N/A"
        ci_str = f"[{rep.ci_95_low_pp*100:+.1f}%, {rep.ci_95_high_pp*100:+.1f}%]" if rep.sample_size_n > 0 else "N/A"
        net_str = f"{rep.net_expected_edge_pp*100:+.2f}%" if rep.sample_size_n > 0 else "N/A"

        table_rows.append([
            cand.discovery.domain_cluster[:24],
            f"{t_a} -> {t_b}",
            rep.sample_size_n,
            eff_str,
            ci_str,
            net_str,
            v
        ])

    logger.info(f"Falsification pipeline complete! Verdict summary: {verdict_counts}")

    print("\n" + "="*95)
    print("HYPOTHESIS FALSIFICATION & KILL-LAYER REPORT")
    print("="*95)
    headers = ["Domain / Channel", "Hypothesis (A -> B)", "N", "Net Effect", "95% CI", "Net Edge", "Verdict"]
    print(tabulate(table_rows, headers=headers, tablefmt="github"))
    print("="*95)

    return {
        "total_hypotheses": len(candidates),
        "verdict_summary": verdict_counts,
        "reports": [r.dict() for r in falsification_reports]
    }

if __name__ == "__main__":
    run_falsification_pipeline()
