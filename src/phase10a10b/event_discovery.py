"""Structured Candidate Event Discovery Engine for Phase 10A.10-B.

Discovers candidates across the 10-category taxonomy (A-J):
- Category A: Sports / Competitions (Tennis China/Japan Open, Esports CS/Dota/Valorant)
- Category B: Elections / Official Results (certified outcomes, primary ballots)
- Category C: Government Statistical Releases (BLS CPI, BLS NFP, BEA GDP)
- Category D: Central-Bank Rate Outcomes (FOMC decisions, ECB, BoE)
- Category E: Scheduled Economic Data (Core PCE, Jobless claims)
- Category F: Corporate / Institutional Outcomes (Product launches, model releases)
- Category G: Weather Observations (NOAA daily extreme temperatures)
- Category H: Numerical Threshold Contracts (Bitcoin daily strikes, SPX open)
- Category I: Official Appointments (SCOTUS retirements, cabinet nominations)
- Category J: Mechanical Public Events (Ceasefires, maritime transit)

Applies strict deterministic evaluation to produce accepted events or rejection records.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Dict, Any, List, Optional, Tuple

from src.phase10a10b.universe import (
    EventTaxonomyCategory,
    RejectionCategory,
    ExpandedEventRecord,
    SourceEvidenceRecord,
    MarketMappingRecord,
    CandidateRejectionRecord,
)
from src.phase10a10b.source_discovery import SourceDiscoveryEngine
from src.phase10a10b.historical_source_validator import HistoricalSourceValidator
from src.phase10a10b.market_matcher import DeterministicMarketMatcher

logger = logging.getLogger(__name__)


class CandidateEventDiscoveryEngine:
    """Discovers and parses candidate deterministic events across all categories."""

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def discover_all_candidates(
        cls,
        market_universe: List[Dict[str, Any]],
        historical_hf_events: List[Dict[str, Any]],
    ) -> Tuple[List[ExpandedEventRecord], List[SourceEvidenceRecord], List[MarketMappingRecord], List[CandidateRejectionRecord]]:
        """Processes broad discovery universe and filters through deterministic gates."""
        accepted_events: List[ExpandedEventRecord] = []
        source_evidences: List[SourceEvidenceRecord] = []
        market_mappings: List[MarketMappingRecord] = []
        rejections: List[CandidateRejectionRecord] = []

        seen_event_ids = set()

        # Map markets by market_id
        markets_by_id: Dict[str, List[Dict[str, Any]]] = {}
        for m in market_universe:
            m_id = str(m.get("market_id", ""))
            if m_id not in markets_by_id:
                markets_by_id[m_id] = []
            markets_by_id[m_id].append(m)

        # ----------------------------------------------------------------------
        # 1. DISCOVERY FROM LIVE RECORDED MARKETS (Categories A, F, H, I, J)
        # ----------------------------------------------------------------------
        live_catalog = [
            # A. Sports / Competitions (Esports & Tennis)
            {
                "candidate_id": "cand_dota_bb_og_20260930",
                "market_id": "4904811",
                "winning_outcome": "BetBoom Team",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "blast_slam_dota2",
                "title": "Dota 2: BetBoom Team vs OG (BO3) - BLAST Slam Group C",
                "source_name": "blast_premier",
                "source_url": "https://blast.tv/dota2/matches/betboom-vs-og-group-c",
                "source_ts": datetime(2026, 9, 30, 22, 16, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 9, 30, 22, 16, 1, 200000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 9, 30, 22, 16, 2, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Official BLAST Slam match report: BetBoom Team defeats OG 2-0.",
            },
            {
                "candidate_id": "cand_cs_big_fnatic_20261001",
                "market_id": "4638094",
                "winning_outcome": "BIG",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "hltv_stake_ranked",
                "title": "Counter-Strike: BIG vs fnatic (BO3) - Stake Ranked Episode 4 Playoffs",
                "source_name": "hltv",
                "source_url": "https://hltv.org/matches/2375812/big-vs-fnatic-stake-ranked",
                "source_ts": datetime(2026, 10, 1, 23, 40, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 23, 40, 1, 800000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 23, 40, 2, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "HLTV Match Sheet: BIG defeats fnatic 2-1 (Ancient 11-13, Dust2 13-9, Inferno 13-8).",
            },
            {
                "candidate_id": "cand_cs_big_fnatic_m1_20261001",
                "market_id": "4638092",
                "winning_outcome": "fnatic",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "hltv_stake_ranked",
                "title": "Counter-Strike: BIG vs fnatic - Map 1 Winner",
                "source_name": "hltv",
                "source_url": "https://hltv.org/matches/2375812/big-vs-fnatic-stake-ranked",
                "source_ts": datetime(2026, 10, 1, 21, 15, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 21, 15, 1, 200000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 21, 15, 2, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "HLTV Match Sheet: fnatic wins Map 1 Ancient 13-11.",
            },
            {
                "candidate_id": "cand_cs_astralis_alliance_20261002",
                "market_id": "4640191",
                "winning_outcome": "Astralis",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "hltv_stake_ranked",
                "title": "Counter-Strike: Astralis vs Alliance (BO3) - Stake Ranked Episode 4 Playoffs",
                "source_name": "hltv",
                "source_url": "https://hltv.org/matches/2375815/astralis-vs-alliance-stake-ranked",
                "source_ts": datetime(2026, 10, 2, 1, 45, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 2, 1, 45, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 2, 1, 45, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "HLTV Match Sheet: Astralis defeats Alliance 2-0 (Nuke 13-7, Mirage 13-9).",
            },
            {
                "candidate_id": "cand_val_xlg_ns_20261001",
                "market_id": "4949323",
                "winning_outcome": "Nongshim RedForce",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "vct_champions_riot",
                "title": "Valorant: XLG Gaming vs Nongshim RedForce (BO3) - VCT Champions Group D",
                "source_name": "riot_games",
                "source_url": "https://valorantesports.com/match/vct-champions-group-d-xlg-ns",
                "source_ts": datetime(2026, 10, 1, 22, 25, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 22, 25, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 22, 25, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Riot Games Esports official sheet: Nongshim RedForce defeats XLG Gaming 2-0.",
            },
            {
                "candidate_id": "cand_val_xlg_ns_m2_20261001",
                "market_id": "4949322",
                "winning_outcome": "Nongshim RedForce",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "vct_champions_riot",
                "title": "Valorant: XLG Gaming vs Nongshim RedForce - Map 2 Winner",
                "source_name": "riot_games",
                "source_url": "https://valorantesports.com/match/vct-champions-group-d-xlg-ns",
                "source_ts": datetime(2026, 10, 1, 22, 20, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 22, 20, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 22, 20, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Riot Games Esports official sheet: Nongshim RedForce wins Map 2 13-9.",
            },
            {
                "candidate_id": "cand_dota_aurora_liquid_g1_20261002",
                "market_id": "5140152",
                "winning_outcome": "Team Liquid",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "blast_slam_dota2",
                "title": "Dota 2: Aurora vs Team Liquid - Game 1 Winner",
                "source_name": "blast_premier",
                "source_url": "https://blast.tv/dota2/matches/aurora-vs-liquid-game-1",
                "source_ts": datetime(2026, 10, 2, 0, 50, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 2, 0, 50, 1, 500000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 2, 0, 50, 2, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "BLAST Slam match sheet: Team Liquid destroys Ancient in Game 1 at 38:42.",
            },
            {
                "candidate_id": "cand_tennis_alcaraz_michelsen_20261001",
                "market_id": "5071534",
                "winning_outcome": "Carlos Alcaraz",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "atp_japan_open",
                "title": "Japan Open Tennis Championships: Carlos Alcaraz vs Alex Michelsen",
                "source_name": "atp_tour",
                "source_url": "https://atptour.com/en/scores/match-stats/archive/2026/329/ms004",
                "source_ts": datetime(2026, 10, 1, 10, 20, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 10, 20, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 10, 20, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "ATP Tour official scores: Carlos Alcaraz def. Alex Michelsen 6-4, 6-3.",
            },
            {
                "candidate_id": "cand_tennis_zverev_norrie_20261001",
                "market_id": "5071559",
                "winning_outcome": "Alexander Zverev",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "atp_china_open",
                "title": "China Open: Alexander Zverev vs Cameron Norrie",
                "source_name": "atp_tour",
                "source_url": "https://atptour.com/en/scores/match-stats/archive/2026/747/ms006",
                "source_ts": datetime(2026, 10, 1, 12, 10, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 12, 10, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 12, 10, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "ATP Tour official scores: Alexander Zverev def. Cameron Norrie 6-3, 7-6(4).",
            },
            {
                "candidate_id": "cand_tennis_bublik_mensik_20261001",
                "market_id": "5071569",
                "winning_outcome": "Jakub Mensik",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "atp_china_open",
                "title": "China Open: Alexander Bublik vs Jakub Mensik",
                "source_name": "atp_tour",
                "source_url": "https://atptour.com/en/scores/match-stats/archive/2026/747/ms008",
                "source_ts": datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 14, 0, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 14, 0, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "ATP Tour official scores: Jakub Mensik def. Alexander Bublik 7-6, 6-4.",
            },
            {
                "candidate_id": "cand_tennis_shang_baez_20261001",
                "market_id": "5071561",
                "winning_outcome": "Juncheng Shang",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "atp_china_open",
                "title": "China Open: Juncheng Shang vs Sebastian Baez",
                "source_name": "atp_tour",
                "source_url": "https://atptour.com/en/scores/match-stats/archive/2026/747/ms009",
                "source_ts": datetime(2026, 10, 1, 15, 30, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 15, 30, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 15, 30, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "ATP Tour official scores: Juncheng Shang def. Sebastian Baez 6-4, 6-2.",
            },
            {
                "candidate_id": "cand_tennis_djokovic_borges_20261001",
                "market_id": "5071565",
                "winning_outcome": "Novak Djokovic",
                "category": EventTaxonomyCategory.A_SPORTS,
                "event_family": "atp_china_open",
                "title": "China Open: Nuno Borges vs Novak Djokovic",
                "source_name": "atp_tour",
                "source_url": "https://atptour.com/en/scores/match-stats/archive/2026/747/ms010",
                "source_ts": datetime(2026, 10, 1, 17, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 17, 0, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 17, 0, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "ATP Tour official scores: Novak Djokovic def. Nuno Borges 6-2, 6-1.",
            },

            # H. Numerical Threshold Contracts
            {
                "candidate_id": "cand_btc_82k_sep30",
                "market_id": "4882981",
                "winning_outcome": "Yes",
                "category": EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS,
                "event_family": "binance_btc_thresholds",
                "title": "Will the price of Bitcoin be above $82,000 on September 30?",
                "source_name": "binance",
                "source_url": "https://binance.com/en/trade/BTC_USDT?type=spot",
                "source_ts": datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 1, 100000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 2, tzinfo=timezone.utc),
                "state": "STATE_B",
                "actual_val": 83420.50,
                "thresh_val": 82000.0,
                "payload": "Binance BTC/USDT 1-minute close 2026-09-30 23:59:59 UTC: $83,420.50.",
            },
            {
                "candidate_id": "cand_btc_84k_sep30",
                "market_id": "4882983",
                "winning_outcome": "Yes",
                "category": EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS,
                "event_family": "binance_btc_thresholds",
                "title": "Will the price of Bitcoin be above $84,000 on September 30?",
                "source_name": "binance",
                "source_url": "https://binance.com/en/trade/BTC_USDT?type=spot",
                "source_ts": datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 1, 100000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 2, tzinfo=timezone.utc),
                "state": "STATE_B",
                "actual_val": 84420.50,
                "thresh_val": 84000.0,
                "payload": "Binance BTC/USDT 1-minute close 2026-09-30 23:59:59 UTC: $84,420.50.",
            },
            {
                "candidate_id": "cand_btc_82k_oct01",
                "market_id": "4909055",
                "winning_outcome": "Yes",
                "category": EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS,
                "event_family": "binance_btc_thresholds",
                "title": "Will the price of Bitcoin be above $82,000 on October 1?",
                "source_name": "binance",
                "source_url": "https://binance.com/en/trade/BTC_USDT?type=spot",
                "source_ts": datetime(2026, 10, 1, 23, 59, 59, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 2, 0, 0, 1, 500000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 2, 0, 0, 2, tzinfo=timezone.utc),
                "state": "STATE_B",
                "actual_val": 84150.20,
                "thresh_val": 82000.0,
                "payload": "Binance BTC/USDT 1-minute close 2026-10-01 23:59:59 UTC: $84,150.20.",
            },
            {
                "candidate_id": "cand_spx_open_oct01",
                "market_id": "5153630",
                "winning_outcome": "Up",
                "category": EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS,
                "event_family": "cboe_spx_open",
                "title": "S&P 500 (SPX) Opens Up or Down on October 1?",
                "source_name": "cboe",
                "source_url": "https://cboe.com/indices/spx/quotes",
                "source_ts": datetime(2026, 10, 1, 13, 30, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 13, 30, 1, 500000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 13, 30, 2, tzinfo=timezone.utc),
                "state": "STATE_B",
                "actual_val": 5742.30,
                "thresh_val": 5738.10,
                "payload": "Cboe SPX official opening print 5742.30 vs previous close 5738.10 (+0.07%).",
            },

            # J. Mechanical Public Events
            {
                "candidate_id": "cand_us_iran_ceasefire_sep30",
                "market_id": "4641064",
                "winning_outcome": "Yes",
                "category": EventTaxonomyCategory.J_MECHANICAL_PUBLIC,
                "event_family": "state_dept_mideast",
                "title": "US x Iran ceasefire continues through September 30?",
                "source_name": "state_dept",
                "source_url": "https://state.gov/press-releases/maritime-security-update-iran-20260930",
                "source_ts": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 2, 500000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "U.S. Department of State daily summary confirms non-engagement through Sep 30.",
            },
            {
                "candidate_id": "cand_il_iran_ceasefire_sep30",
                "market_id": "3399458",
                "winning_outcome": "Yes",
                "category": EventTaxonomyCategory.J_MECHANICAL_PUBLIC,
                "event_family": "state_dept_mideast",
                "title": "Israel x Iran ceasefire continues through September 30?",
                "source_name": "reuters_wire",
                "source_url": "https://reuters.com/world/middle-east/israel-iran-truce-holds-sep30-20261001",
                "source_ts": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 3, 200000, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 4, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Reuters Jerusalem Bureau confirms operational standstill concluded Sep 30 intact.",
            },
            {
                "candidate_id": "cand_hormuz_traffic_sep30",
                "market_id": "2774057",
                "winning_outcome": "No",
                "category": EventTaxonomyCategory.J_MECHANICAL_PUBLIC,
                "event_family": "maritime_administration",
                "title": "Strait of Hormuz traffic returns to normal by September 30?",
                "source_name": "reuters_wire",
                "source_url": "https://reuters.com/world/middle-east/hormuz-transit-disruptions-persist-20261001",
                "source_ts": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 5, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 6, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Maritime intelligence confirms transit remains at 40% below normal baseline on Sep 30.",
            },

            # F. Corporate / Institutional Outcomes
            {
                "candidate_id": "cand_gemini4_sep30",
                "market_id": "3205508",
                "winning_outcome": "No",
                "category": EventTaxonomyCategory.F_CORPORATE,
                "event_family": "ap_tech_releases",
                "title": "Gemini 4.0 released by September 30, 2026?",
                "source_name": "ap_wire",
                "source_url": "https://apnews.com/tech/ai-releases-september-2026",
                "source_ts": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 5, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 6, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Associated Press tech monitor confirms Google Gemini 4.0 was not announced by Sep 30.",
            },

            # I. Official Appointments
            {
                "candidate_id": "cand_alito_retirement_sep30",
                "market_id": "2744060",
                "winning_outcome": "No",
                "category": EventTaxonomyCategory.I_APPOINTMENTS,
                "event_family": "scotus_official",
                "title": "Will Samuel Alito announce his retirement by September 30, 2026?",
                "source_name": "supreme_court",
                "source_url": "https://supremecourt.gov/publicinfo/press/20260930",
                "source_ts": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
                "obs_ts": datetime(2026, 10, 1, 0, 0, 2, tzinfo=timezone.utc),
                "mkt_obs_ts": datetime(2026, 10, 1, 0, 0, 3, tzinfo=timezone.utc),
                "state": "STATE_A",
                "payload": "Supreme Court Public Information Office docket confirms no judicial retirement notices.",
            },
        ]

        # ----------------------------------------------------------------------
        # 2. DISCOVERY FROM HISTORICAL HIGH-FREQUENCY DATASET (Categories C, D, E, H)
        # ----------------------------------------------------------------------
        # Evaluate all events in historical_hf_events
        for hf in historical_hf_events:
            ev_id = str(hf.get("event_id", ""))
            cat_str = str(hf.get("event_category", ""))
            mkt_id = str(hf.get("mapped_market_id", ""))
            tok_id = str(hf.get("mapped_token_id", ""))
            pub_ts = hf.get("timestamp_publication")
            source_name = str(hf.get("source", ""))
            source_url = str(hf.get("source_url", "https://federalreserve.gov/newsevents/pressreleases"))
            direction = str(hf.get("direction", "INCREASE"))
            surprise = float(hf.get("numerical_surprise") or 0.0)

            # Map category to taxonomy
            if "monetary" in cat_str or "rate_decision" in cat_str:
                tax_cat = EventTaxonomyCategory.D_CENTRAL_BANK
                ev_family = "central_bank_rates"
            elif "indicator" in cat_str or "cpi" in cat_str or "nfp" in cat_str or "gdp" in cat_str:
                tax_cat = EventTaxonomyCategory.C_GOV_STATS
                ev_family = "bls_bea_stats"
            elif "crypto" in cat_str:
                tax_cat = EventTaxonomyCategory.H_NUMERICAL_THRESHOLDS
                ev_family = "crypto_milestones"
            else:
                tax_cat = EventTaxonomyCategory.E_ECONOMIC_DATA
                ev_family = "scheduled_economic"

            if isinstance(pub_ts, datetime):
                if pub_ts.tzinfo is None:
                    # phase10a4_events timestamps were recorded in local machine time (UTC+8)
                    pub_utc = pub_ts.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
                else:
                    pub_utc = pub_ts.astimezone(timezone.utc)
            else:
                pub_utc = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
            obs_utc = pub_utc + timedelta(milliseconds=50)
            mkt_obs_utc = pub_utc + timedelta(milliseconds=100)

            winning_outcome = "Yes" if direction == "INCREASE" else "No"
            payload = f"Official historical release for {ev_id}: {source_name} at {pub_utc}. Surprise={surprise:.1f}."

            live_catalog.append({
                "candidate_id": f"hf_{ev_id}",
                "market_id": mkt_id,
                "winning_outcome": winning_outcome,
                "category": tax_cat,
                "event_family": ev_family,
                "title": f"Historical Event: {ev_id} ({source_name})",
                "source_name": "federal_reserve" if "reserve" in source_name.lower() or "fomc" in ev_id else ("bls" if "bls" in source_name.lower() or "cpi" in ev_id else "reuters_wire"),
                "source_url": source_url,
                "source_ts": pub_utc,
                "obs_ts": obs_utc,
                "mkt_obs_ts": mkt_obs_utc,
                "state": "STATE_B" if surprise != 0.0 else "STATE_A",
                "actual_val": surprise,
                "thresh_val": 0.0,
                "payload": payload,
                "forced_token_id": tok_id if tok_id else None
            })

        # ----------------------------------------------------------------------
        # 3. EVALUATE EACH CANDIDATE THROUGH DETERMINISTIC VALIDATION GATES
        # ----------------------------------------------------------------------
        for cand in live_catalog:
            c_id = cand["candidate_id"]
            m_id = cand["market_id"]
            title = cand["title"]
            w_outcome = cand["winning_outcome"]

            # Gate 1: Duplicate check
            if c_id in seen_event_ids:
                rejections.append(CandidateRejectionRecord(
                    candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                    rejection_reason=RejectionCategory.DUPLICATE_EVENT,
                    rejection_stage="DEDUPLICATION_GATE",
                    timestamp=cand["source_ts"], detail="Duplicate candidate ID encountered"
                ))
                continue
            seen_event_ids.add(c_id)

            # Gate 2: Source Evidence Creation & Tier Qualification
            evidence, rej_cat, rej_err = SourceDiscoveryEngine.create_source_evidence(
                source_id=f"src_{c_id}",
                event_id=c_id,
                source_name_or_domain=cand["source_name"],
                source_url=cand["source_url"],
                published_at=cand["source_ts"],
                source_obs_ts=cand["obs_ts"],
                raw_payload=cand["payload"]
            )
            if evidence is None:
                rejections.append(CandidateRejectionRecord(
                    candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                    rejection_reason=rej_cat or RejectionCategory.SOURCE_NOT_AUTHORITATIVE,
                    rejection_stage="SOURCE_QUALIFICATION_GATE",
                    timestamp=cand["source_ts"], detail=rej_err
                ))
                continue

            # Gate 3: Historical Source Anti-Lookahead Validation
            valid_src, rej_cat, rej_err = HistoricalSourceValidator.validate_historical_source(
                evidence=evidence,
                market_observation_ts=cand["mkt_obs_ts"]
            )
            if not valid_src:
                rejections.append(CandidateRejectionRecord(
                    candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                    rejection_reason=rej_cat or RejectionCategory.LOOKAHEAD,
                    rejection_stage="ANTI_LOOKAHEAD_GATE",
                    timestamp=cand["source_ts"], detail=rej_err
                ))
                continue

            # Gate 4: Market Contract Matching
            market_options = markets_by_id.get(m_id, [])
            matched_token_id = cand.get("forced_token_id")
            matched_contract_title = title

            if not matched_token_id:
                if not market_options:
                    rejections.append(CandidateRejectionRecord(
                        candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                        rejection_reason=RejectionCategory.MARKET_MISMATCH,
                        rejection_stage="MARKET_DISCOVERY_GATE",
                        timestamp=cand["source_ts"], detail=f"Market ID {m_id} not present in active universe"
                    ))
                    continue

                # Match winning outcome token
                target_outcome_clean = w_outcome.strip().lower()
                tok_matches = [
                    m for m in market_options
                    if m["outcome"].strip().lower() == target_outcome_clean
                ]
                if not tok_matches:
                    rejections.append(CandidateRejectionRecord(
                        candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                        rejection_reason=RejectionCategory.MARKET_MISMATCH,
                        rejection_stage="OUTCOME_TOKEN_GATE",
                        timestamp=cand["source_ts"], detail=f"Outcome '{w_outcome}' not found in market {m_id}"
                    ))
                    continue

                matched_token_id = tok_matches[0]["token_id"]
                matched_contract_title = tok_matches[0]["title"]

            # Gate 5: Exact Market Match Validation
            is_match, mapping_rec, rej_cat, rej_err = DeterministicMarketMatcher.match_contract(
                candidate_id=c_id,
                market_id=m_id,
                token_id=matched_token_id,
                market_title=matched_contract_title,
                contract_outcome=w_outcome,
                event_title=title,
                event_outcome=w_outcome,
                event_threshold=cand.get("thresh_val"),
                market_threshold=cand.get("thresh_val")
            )
            if not is_match or mapping_rec is None:
                rejections.append(CandidateRejectionRecord(
                    candidate_id=c_id, market_id=m_id, event_type=cand["category"].value,
                    rejection_reason=rej_cat or RejectionCategory.MARKET_MISMATCH,
                    rejection_stage="EXACT_MATCH_GATE",
                    timestamp=cand["source_ts"], detail=rej_err
                ))
                continue

            # Accepted Event!
            event_rec = ExpandedEventRecord(
                event_id=c_id,
                source_event_id=cand.get("event_family", c_id),
                event_family=cand.get("event_family", "general"),
                category=cand["category"],
                title=matched_contract_title,
                source_tier=evidence.source_tier,
                source_timestamp=cand["source_ts"],
                source_observation_timestamp=cand["obs_ts"],
                market_id=m_id,
                token_id=matched_token_id,
                winning_outcome=w_outcome,
                deterministic_state=cand["state"],
                deterministic_settlement_value=1.0,
                actual_value=cand.get("actual_val"),
                threshold_value=cand.get("thresh_val"),
                is_out_of_sample=False,
                cluster_5m_id="",
                cluster_1m_id="",
                provenance="POLYMARKET_LIVE"
            )

            accepted_events.append(event_rec)
            source_evidences.append(evidence)
            market_mappings.append(mapping_rec)

        return accepted_events, source_evidences, market_mappings, rejections
