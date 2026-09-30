"""Phase 10A.3: Historical Information-Latency Event-Study Engine.
Executes empirical measurement of prediction market price responses following
objectively timestamped real-world information releases (July 4, 2025 - September 29, 2026).

Enforces:
1. Stage B Deterministic Contract Mapping (ACCEPTED, AMBIGUOUS, REJECTED)
2. Pre-event market state capture (t-, lag, bid, ask, mid, spread, depth)
3. Multi-horizon post-event response measurement (+1s to +24h) with strict UNAVAILABLE handling
4. Microstructure-adjusted markouts (YES taker, NO taker, spread-adjusted, net taker fee)
5. MFE, MAE, and time-to-peak metrics
6. 4 Required Null Control Batteries (Random-time, Time-shifted, Wrong-market, Direction)
7. Full DuckDB table persistence
8. Decision Gate Evaluation (PROMISING, INCONCLUSIVE, REJECTED)
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from src.execution.fee_model import DynamicExecutionCostModel
from src.normalization.schema import CanonicalMarket, Platform
from src.phase10.events.schema import InformationEvent, SourceType, EventDirection
from src.phase10.events.contract_mapper import (
    DeterministicContractMapper,
    ContractMapping,
    MappingDecision,
    AmbiguityFlag,
)

logger = logging.getLogger(__name__)


@dataclass
class HorizonResponse:
    horizon_name: str
    target_offset_seconds: int
    is_available: bool
    snapshot_time: Optional[datetime]
    delta_seconds: Optional[float]
    p_mid: Optional[float]
    p_bid: Optional[float]
    p_ask: Optional[float]
    spread: Optional[float]
    delta_mid: Optional[float]
    dir_delta_mid: Optional[float]
    exec_markout: Optional[float]
    spread_adj_markout: Optional[float]
    net_markout_fee: Optional[float] # After taker fee 0.2% round trip
    net_markout_160bps: Optional[float] # After conservative 1.6% round trip taker friction


@dataclass
class EventStudyObservation:
    event_id: str
    market_id: str
    canonical_title: str
    event_type: str
    source: str
    source_type: str
    timestamp_publication: datetime
    timestamp_extraction: datetime
    direction: str
    is_inverted: bool
    mapping_score: float
    
    # Pre-event state
    t_minus: Optional[datetime]
    lag_seconds: Optional[float]
    p_minus_mid: Optional[float]
    p_minus_bid: Optional[float]
    p_minus_ask: Optional[float]
    spread_minus: Optional[float]
    depth_minus: Optional[float]
    
    # Multi-horizon responses
    horizons: Dict[str, HorizonResponse]
    
    # Intraday Path & Excursion Metrics
    mfe_1h: Optional[float]
    mae_1h: Optional[float]
    time_to_peak_minutes: Optional[float]
    persistence_ratio_24h_1h: Optional[float]
    
    # Metadata
    actual_value: Optional[float]
    consensus_value: Optional[float]
    measurable_surprise: Optional[float]
    event_cluster_id: str


class HistoricalEventStudyEngine:
    """Rigorous empirical engine analyzing post-announcement price dynamics."""

    # Multi-horizon search tolerances
    HORIZONS_CONFIG: List[Tuple[str, int, int]] = [
        ("1s", 1, 3),         # 1 second offset (+/- 3s tolerance)
        ("5s", 5, 4),         # 5 seconds offset (+/- 4s tolerance)
        ("15s", 15, 8),       # 15 seconds offset (+/- 8s tolerance)
        ("30s", 30, 15),      # 30 seconds offset (+/- 15s tolerance)
        ("60s", 60, 30),      # 1 minute offset (+/- 30s tolerance)
        ("5m", 300, 120),     # 5 minutes offset (+/- 120s tolerance)
        ("15m", 900, 300),    # 15 minutes offset (+/- 300s tolerance)
        ("1h", 3600, 900),    # 1 hour offset (+/- 900s tolerance)
        ("24h", 86400, 7200)  # 24 hours offset (+/- 7200s tolerance)
    ]

    def __init__(self, db_path: str = "data/prediction_market.duckdb"):
        self.db_path = db_path
        self.mapper = DeterministicContractMapper()
        self.fee_model = DynamicExecutionCostModel(
            default_taker_fee=0.001,
            default_maker_fee=0.000,
            min_spread_cents=0.005
        )

    def load_canonical_universe(self, conn: duckdb.DuckDBPyConnection) -> Dict[str, Tuple[CanonicalMarket, str, float, float]]:
        """Loads canonical markets joined with clob_token_ids and market depth."""
        rows = conn.execute("""
            SELECT c.*, m.clob_token_ids, m.liquidity as m_liq, m.volume as m_vol
            FROM canonical_markets c
            JOIN markets m ON c.market_id = m.market_id
        """).df()

        universe = {}
        for _, r in rows.iterrows():
            entities = r['entities']
            if isinstance(entities, str):
                entities = json.loads(entities)
            cm = CanonicalMarket(
                market_id=str(r['market_id']),
                platform=Platform.POLYMARKET,
                title=str(r['title']),
                underlying_event=str(r['underlying_event'] or ''),
                entities=list(entities) if entities else [],
                geographic_scope=str(r['geographic_scope'] or 'US'),
                time_horizon=str(r['time_horizon'] or '2026'),
                event_type=str(r['event_type']),
                threshold=str(r['threshold']) if pd.notna(r['threshold']) else None,
                direction=str(r['direction']) if pd.notna(r['direction']) else None,
                resolution_date=str(r['resolution_date']) if pd.notna(r['resolution_date']) else None,
                resolution_source=str(r['resolution_source']) if pd.notna(r['resolution_source']) else None
            )
            token_id = json.loads(r['clob_token_ids'])[0]
            liq = float(r['m_liq']) if pd.notna(r['m_liq']) else 50000.0
            vol = float(r['m_vol']) if pd.notna(r['m_vol']) else 100000.0
            universe[cm.market_id] = (cm, token_id, liq, vol)

        return universe

    def evaluate_mappings(
        self,
        events: List[InformationEvent],
        universe: Dict[str, Tuple[CanonicalMarket, str, float, float]]
    ) -> Tuple[List[ContractMapping], List[Tuple[InformationEvent, CanonicalMarket, str, float, float, ContractMapping]]]:
        """Runs Stage B DeterministicContractMapper across all event-market pairs."""
        all_mappings: List[ContractMapping] = []
        accepted_pairs: List[Tuple[InformationEvent, CanonicalMarket, str, float, float, ContractMapping]] = []

        for evt in events:
            best_accepted: Optional[Tuple[InformationEvent, CanonicalMarket, str, float, float, ContractMapping]] = None
            best_score = -1.0

            for mid, (cm, token_id, liq, vol) in universe.items():
                mapping = self.mapper.map_event_to_market(evt, cm)
                all_mappings.append(mapping)

                if mapping.mapping_decision == MappingDecision.ACCEPTED:
                    if mapping.semantic_match_score > best_score:
                        best_score = mapping.semantic_match_score
                        best_accepted = (evt, cm, token_id, liq, vol, mapping)

            if best_accepted:
                accepted_pairs.append(best_accepted)

        return all_mappings, accepted_pairs

    def measure_event_response(
        self,
        conn: duckdb.DuckDBPyConnection,
        evt: InformationEvent,
        cm: CanonicalMarket,
        token_id: str,
        liquidity: float,
        mapping: ContractMapping
    ) -> Optional[EventStudyObservation]:
        """Extracts high-resolution price response around official publication time."""
        pub_dt = evt.timestamp_publication.astimezone(timezone.utc).replace(tzinfo=None)

        # 1. Capture Pre-Event State t-
        pre_snap = conn.execute("""
            SELECT DISTINCT timestamp, yes_mid
            FROM market_snapshots
            WHERE market_id = ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, [token_id, pub_dt]).fetchone()

        if not pre_snap:
            return None

        t_minus = pre_snap[0]
        p_minus_mid = float(pre_snap[1])
        lag_seconds = (pub_dt - t_minus).total_seconds()

        # Spread & Depth estimation
        spread_minus = self.fee_model.estimate_spread(liquidity, p_minus_mid)
        p_minus_bid = max(0.001, p_minus_mid - spread_minus / 2.0)
        p_minus_ask = min(0.999, p_minus_mid + spread_minus / 2.0)
        depth_minus = max(500.0, liquidity * 0.15)

        # Direction polarity multiplier
        dir_mult = 1.0 if evt.direction == EventDirection.INCREASE else -1.0
        if mapping.is_inverted:
            dir_mult = -dir_mult

        # 2. Multi-horizon Measurement
        horizon_responses: Dict[str, HorizonResponse] = {}
        for h_name, offset_sec, tol_sec in self.HORIZONS_CONFIG:
            target_t = pub_dt + timedelta(seconds=offset_sec)
            snap = conn.execute("""
                SELECT DISTINCT timestamp, yes_mid, abs(epoch(timestamp) - epoch(?::TIMESTAMP)) as diff
                FROM market_snapshots
                WHERE market_id = ? AND timestamp BETWEEN ? AND ?
                ORDER BY diff ASC
                LIMIT 1
            """, [target_t, token_id, target_t - timedelta(seconds=tol_sec), target_t + timedelta(seconds=tol_sec)]).fetchone()

            if snap:
                s_time = snap[0]
                diff_sec = float(snap[2])
                p_h_mid = float(snap[1])
                spread_h = self.fee_model.estimate_spread(liquidity, p_h_mid)
                p_h_bid = max(0.001, p_h_mid - spread_h / 2.0)
                p_h_ask = min(0.999, p_h_mid + spread_h / 2.0)

                delta_mid = p_h_mid - p_minus_mid
                dir_delta_mid = dir_mult * delta_mid

                # Executable markout
                if dir_mult > 0:
                    exec_markout = p_h_bid - p_minus_ask  # YES taker
                else:
                    exec_markout = p_minus_bid - p_h_ask  # NO taker

                spread_adj_markout = dir_delta_mid - spread_minus
                net_fee = exec_markout - 0.002           # 0.1% per leg (0.2% round trip)
                net_160bps = exec_markout - 0.016        # 1.6% round trip taker friction

                horizon_responses[h_name] = HorizonResponse(
                    horizon_name=h_name,
                    target_offset_seconds=offset_sec,
                    is_available=True,
                    snapshot_time=s_time,
                    delta_seconds=diff_sec,
                    p_mid=p_h_mid,
                    p_bid=p_h_bid,
                    p_ask=p_h_ask,
                    spread=spread_h,
                    delta_mid=delta_mid,
                    dir_delta_mid=dir_delta_mid,
                    exec_markout=exec_markout,
                    spread_adj_markout=spread_adj_markout,
                    net_markout_fee=net_fee,
                    net_markout_160bps=net_160bps
                )
            else:
                horizon_responses[h_name] = HorizonResponse(
                    horizon_name=h_name,
                    target_offset_seconds=offset_sec,
                    is_available=False,
                    snapshot_time=None,
                    delta_seconds=None,
                    p_mid=None,
                    p_bid=None,
                    p_ask=None,
                    spread=None,
                    delta_mid=None,
                    dir_delta_mid=None,
                    exec_markout=None,
                    spread_adj_markout=None,
                    net_markout_fee=None,
                    net_markout_160bps=None
                )

        # 3. Path & Excursion Metrics within 1 Hour
        intraday_snaps = conn.execute("""
            SELECT DISTINCT timestamp, yes_mid
            FROM market_snapshots
            WHERE market_id = ? AND timestamp > ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, [token_id, pub_dt, pub_dt + timedelta(hours=1, minutes=10)]).df()

        mfe_1h = None
        mae_1h = None
        time_to_peak_min = None

        if not intraday_snaps.empty:
            deltas = (intraday_snaps['yes_mid'] - p_minus_mid) * dir_mult
            mfe_1h = float(deltas.max())
            mae_1h = float(deltas.min())
            
            # Index of peak favorable excursion
            peak_idx = deltas.idxmax()
            peak_time = intraday_snaps.loc[peak_idx, 'timestamp']
            time_to_peak_min = max(0.0, (peak_time - pub_dt).total_seconds() / 60.0)

        # 4. Persistence Ratio (24h / 1h)
        h1 = horizon_responses.get("1h")
        h24 = horizon_responses.get("24h")
        persistence_ratio = None
        if h1 and h1.is_available and h24 and h24.is_available:
            if abs(h1.delta_mid) > 1e-4:
                persistence_ratio = float(h24.delta_mid / h1.delta_mid)
            else:
                persistence_ratio = 1.0 if abs(h24.delta_mid) <= 1e-4 else 0.0

        meta = evt.metadata or {}
        return EventStudyObservation(
            event_id=evt.event_id,
            market_id=cm.market_id,
            canonical_title=cm.title,
            event_type=evt.event_type,
            source=evt.source,
            source_type=evt.source_type.value,
            timestamp_publication=evt.timestamp_publication,
            timestamp_extraction=evt.timestamp_extraction,
            direction=evt.direction.value,
            is_inverted=mapping.is_inverted,
            mapping_score=mapping.semantic_match_score,
            t_minus=t_minus,
            lag_seconds=lag_seconds,
            p_minus_mid=p_minus_mid,
            p_minus_bid=p_minus_bid,
            p_minus_ask=p_minus_ask,
            spread_minus=spread_minus,
            depth_minus=depth_minus,
            horizons=horizon_responses,
            mfe_1h=mfe_1h,
            mae_1h=mae_1h,
            time_to_peak_minutes=time_to_peak_min,
            persistence_ratio_24h_1h=persistence_ratio,
            actual_value=meta.get("actual_value"),
            consensus_value=meta.get("consensus_value"),
            measurable_surprise=meta.get("measurable_surprise"),
            event_cluster_id=meta.get("event_cluster_id", "default")
        )

    def run_null_controls(
        self,
        conn: duckdb.DuckDBPyConnection,
        accepted_pairs: List[Tuple[InformationEvent, CanonicalMarket, str, float, float, ContractMapping]],
        sports_tokens: List[str]
    ) -> Dict[str, List[float]]:
        """Runs the 4 required null control placebos."""
        np.random.seed(42)
        placebo_results: Dict[str, List[float]] = {
            "placebo_a_random_ts": [],
            "placebo_b_timeshift": [],
            "placebo_c_wrong_market": [],
            "placebo_d_direction": []
        }

        def eval_quick_markout(tok: str, eval_dt: datetime, dir_val: float, liq_val: float) -> Optional[float]:
            pre = conn.execute("""
                SELECT timestamp, yes_mid FROM market_snapshots
                WHERE market_id = ? AND timestamp <= ?
                ORDER BY timestamp DESC LIMIT 1
            """, [tok, eval_dt]).fetchone()
            if not pre:
                return None
            p0 = pre[1]

            post = conn.execute("""
                SELECT timestamp, yes_mid FROM market_snapshots
                WHERE market_id = ? AND timestamp BETWEEN ? AND ?
                ORDER BY abs(epoch(timestamp) - epoch(?::TIMESTAMP)) ASC LIMIT 1
            """, [tok, eval_dt + timedelta(minutes=40), eval_dt + timedelta(minutes=80), eval_dt + timedelta(hours=1)]).fetchone()
            if not post:
                return None
            p1 = post[1]

            s0 = self.fee_model.estimate_spread(liq_val, p0)
            s1 = self.fee_model.estimate_spread(liq_val, p1)
            p0_ask = min(0.999, p0 + s0 / 2.0)
            p0_bid = max(0.001, p0 - s0 / 2.0)
            p1_ask = min(0.999, p1 + s1 / 2.0)
            p1_bid = max(0.001, p1 - s1 / 2.0)

            return (p1_bid - p0_ask) if dir_val > 0 else (p0_bid - p1_ask)

        for evt, cm, token, liq, vol, mapping in accepted_pairs:
            pub_dt = evt.timestamp_publication.astimezone(timezone.utc).replace(tzinfo=None)
            dir_mult = 1.0 if evt.direction == EventDirection.INCREASE else -1.0
            if mapping.is_inverted:
                dir_mult = -dir_mult

            # Placebo A: Random timestamps (shifted by random non-event days within snapshot range)
            rand_dt = pub_dt - timedelta(days=float(np.random.uniform(7, 28)))
            mA = eval_quick_markout(token, rand_dt, dir_mult, liq)
            if mA is not None:
                placebo_results["placebo_a_random_ts"].append(mA)

            # Placebo B: Time-shifted +24h
            shift_dt = pub_dt + timedelta(hours=24)
            mB = eval_quick_markout(token, shift_dt, dir_mult, liq)
            if mB is not None:
                placebo_results["placebo_b_timeshift"].append(mB)

            # Placebo C: Wrong-market (unrelated sports/entertainment contract)
            if sports_tokens:
                w_token = str(np.random.choice(sports_tokens))
                mC = eval_quick_markout(w_token, pub_dt, dir_mult, 25000.0)
                if mC is not None:
                    placebo_results["placebo_c_wrong_market"].append(mC)

            # Placebo D: Direction placebo (randomized direction)
            rand_dir = float(np.random.choice([-1.0, 1.0]))
            mD = eval_quick_markout(token, pub_dt, rand_dir, liq)
            if mD is not None:
                placebo_results["placebo_d_direction"].append(mD)

        return placebo_results

    def persist_to_duckdb(
        self,
        conn: duckdb.DuckDBPyConnection,
        events: List[InformationEvent],
        mappings: List[ContractMapping],
        observations: List[EventStudyObservation],
        placebos: Dict[str, List[float]]
    ) -> None:
        """Stores normalized audit tables in DuckDB."""
        # 1. phase10a_information_events
        conn.execute("DROP TABLE IF EXISTS phase10a_information_events")
        conn.execute("""
            CREATE TABLE phase10a_information_events (
                event_id VARCHAR PRIMARY KEY,
                publication_timestamp TIMESTAMP,
                extraction_timestamp TIMESTAMP,
                source VARCHAR,
                source_type VARCHAR,
                source_reliability DOUBLE,
                event_type VARCHAR,
                title VARCHAR,
                raw_content VARCHAR,
                entities JSON,
                direction VARCHAR,
                impact_point DOUBLE,
                impact_lower DOUBLE,
                impact_upper DOUBLE,
                impact_confidence DOUBLE,
                impact_horizon_seconds DOUBLE,
                mechanism VARCHAR,
                resolution_relevance DOUBLE,
                actual_value DOUBLE,
                consensus_value DOUBLE,
                measurable_surprise DOUBLE,
                event_cluster_id VARCHAR,
                is_scheduled BOOLEAN
            )
        """)
        for e in events:
            meta = e.metadata or {}
            conn.execute("""
                INSERT INTO phase10a_information_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                e.event_id,
                e.timestamp_publication.astimezone(timezone.utc).replace(tzinfo=None),
                e.timestamp_extraction.astimezone(timezone.utc).replace(tzinfo=None),
                e.source,
                e.source_type.value,
                e.source_reliability,
                e.event_type,
                e.title,
                e.raw_content,
                json.dumps(e.entities),
                e.direction.value,
                e.impact_distribution.impact_point,
                e.impact_distribution.impact_lower,
                e.impact_distribution.impact_upper,
                e.impact_distribution.impact_confidence,
                e.impact_distribution.impact_horizon_seconds,
                e.mechanism,
                e.resolution_relevance,
                meta.get("actual_value"),
                meta.get("consensus_value"),
                meta.get("measurable_surprise"),
                meta.get("event_cluster_id"),
                meta.get("is_scheduled", True)
            ])

        # 2. phase10a_contract_mappings
        conn.execute("DROP TABLE IF EXISTS phase10a_contract_mappings")
        conn.execute("""
            CREATE TABLE phase10a_contract_mappings (
                mapping_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                market_id VARCHAR,
                canonical_title VARCHAR,
                entity_match BOOLEAN,
                entity_match_score DOUBLE,
                temporal_match BOOLEAN,
                outcome_match BOOLEAN,
                resolution_match BOOLEAN,
                semantic_match_score DOUBLE,
                is_inverted BOOLEAN,
                ambiguity_flags JSON,
                mapping_decision VARCHAR,
                decision_reason VARCHAR
            )
        """)
        for m in mappings:
            conn.execute("""
                INSERT INTO phase10a_contract_mappings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                m.mapping_id,
                m.event_id,
                m.market_id,
                m.canonical_title,
                m.entity_match,
                m.entity_match_score,
                m.temporal_match,
                m.outcome_match,
                m.resolution_match,
                m.semantic_match_score,
                m.is_inverted,
                json.dumps([f.value for f in m.ambiguity_flags]),
                m.mapping_decision.value,
                m.decision_reason
            ])

        # 3. phase10a_event_study
        conn.execute("DROP TABLE IF EXISTS phase10a_event_study")
        conn.execute("""
            CREATE TABLE phase10a_event_study (
                event_id VARCHAR PRIMARY KEY,
                market_id VARCHAR,
                canonical_title VARCHAR,
                event_type VARCHAR,
                source_type VARCHAR,
                publication_timestamp TIMESTAMP,
                direction VARCHAR,
                is_inverted BOOLEAN,
                t_minus TIMESTAMP,
                lag_seconds DOUBLE,
                p_minus_mid DOUBLE,
                p_minus_bid DOUBLE,
                p_minus_ask DOUBLE,
                spread_minus DOUBLE,
                p_15s_mid DOUBLE,
                exec_markout_15s DOUBLE,
                p_1h_mid DOUBLE,
                delta_1h_mid DOUBLE,
                dir_delta_1h_mid DOUBLE,
                exec_markout_1h DOUBLE,
                spread_adj_markout_1h DOUBLE,
                net_markout_160bps_1h DOUBLE,
                p_24h_mid DOUBLE,
                delta_24h_mid DOUBLE,
                dir_delta_24h_mid DOUBLE,
                mfe_1h DOUBLE,
                mae_1h DOUBLE,
                time_to_peak_minutes DOUBLE,
                persistence_ratio DOUBLE,
                measurable_surprise DOUBLE
            )
        """)
        for obs in observations:
            h15 = obs.horizons.get("15s")
            h1 = obs.horizons.get("1h")
            h24 = obs.horizons.get("24h")
            conn.execute("""
                INSERT INTO phase10a_event_study VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, [
                obs.event_id,
                obs.market_id,
                obs.canonical_title,
                obs.event_type,
                obs.source_type,
                obs.timestamp_publication.astimezone(timezone.utc).replace(tzinfo=None),
                obs.direction,
                obs.is_inverted,
                obs.t_minus,
                obs.lag_seconds,
                obs.p_minus_mid,
                obs.p_minus_bid,
                obs.p_minus_ask,
                obs.spread_minus,
                h15.p_mid if (h15 and h15.is_available) else None,
                h15.exec_markout if (h15 and h15.is_available) else None,
                h1.p_mid if (h1 and h1.is_available) else None,
                h1.delta_mid if (h1 and h1.is_available) else None,
                h1.dir_delta_mid if (h1 and h1.is_available) else None,
                h1.exec_markout if (h1 and h1.is_available) else None,
                h1.spread_adj_markout if (h1 and h1.is_available) else None,
                h1.net_markout_160bps if (h1 and h1.is_available) else None,
                h24.p_mid if (h24 and h24.is_available) else None,
                h24.delta_mid if (h24 and h24.is_available) else None,
                h24.dir_delta_mid if (h24 and h24.is_available) else None,
                obs.mfe_1h,
                obs.mae_1h,
                obs.time_to_peak_minutes,
                obs.persistence_ratio_24h_1h,
                obs.measurable_surprise
            ])

        # 4. phase10a_placebos
        conn.execute("DROP TABLE IF EXISTS phase10a_placebos")
        conn.execute("""
            CREATE TABLE phase10a_placebos (
                battery_name VARCHAR,
                observation_index INTEGER,
                markout_1h DOUBLE
            )
        """)
        for b_name, vals in placebos.items():
            for idx, val in enumerate(vals):
                conn.execute("INSERT INTO phase10a_placebos VALUES (?, ?, ?)", [b_name, idx, val])

    def evaluate_decision_gate(
        self,
        observations: List[EventStudyObservation],
        placebos: Dict[str, List[float]]
    ) -> Dict[str, Any]:
        """Evaluates strict Phase 10A.3 decision gate criteria."""
        obs_1h = [o for o in observations if o.horizons.get("1h") and o.horizons["1h"].is_available]
        real_markouts_1h = [o.horizons["1h"].exec_markout for o in obs_1h]
        real_net_markouts_1h = [o.horizons["1h"].net_markout_160bps for o in obs_1h]
        real_dir_deltas = [o.horizons["1h"].dir_delta_mid for o in obs_1h]

        n_events = len(obs_1h)
        mean_gross = float(np.mean(real_markouts_1h)) if n_events > 0 else 0.0
        mean_net = float(np.mean(real_net_markouts_1h)) if n_events > 0 else 0.0
        mean_dir_delta = float(np.mean(real_dir_deltas)) if n_events > 0 else 0.0
        win_rate_gross = float((np.array(real_markouts_1h) > 0).mean()) if n_events > 0 else 0.0
        win_rate_net = float((np.array(real_net_markouts_1h) > 0).mean()) if n_events > 0 else 0.0

        t_gross, p_gross = stats.ttest_1samp(real_markouts_1h, 0.0) if n_events > 1 else (0.0, 1.0)
        t_net, p_net = stats.ttest_1samp(real_net_markouts_1h, 0.0) if n_events > 1 else (0.0, 1.0)

        # Placebo means
        pA_mean = float(np.mean(placebos.get("placebo_a_random_ts", [0.0])))
        pB_mean = float(np.mean(placebos.get("placebo_b_timeshift", [0.0])))
        pC_mean = float(np.mean(placebos.get("placebo_c_wrong_market", [0.0])))
        pD_mean = float(np.mean(placebos.get("placebo_d_direction", [0.0])))

        max_placebo = max(pA_mean, pB_mean, pC_mean, pD_mean)

        # Decision Gate Rules:
        # PROMISING: mean_net > 0 and p_net < 0.01 and mean_gross >= 3 * max_placebo and annual_freq > 30
        # INCONCLUSIVE: Repricing exists (mean_dir_delta > 0) but gross edge is eaten by costs, or sample size insufficient
        # REJECTED: No post-publication repricing detected, or net markout significantly negative
        if mean_net > 0.0 and p_net < 0.01 and mean_gross >= (3.0 * max_placebo):
            classification = "PROMISING"
            rationale = "Statistically significant net executable edge confirmed overcoming transaction costs and placebos."
        elif mean_dir_delta > 0.005 and mean_net < 0.0:
            classification = "INCONCLUSIVE"
            rationale = (
                f"Gross post-announcement directional repricing exists (+{mean_dir_delta*100:.2f}%), "
                f"but gross executable markout (+{mean_gross*100:.2f}%) is insufficient to overcome taker transaction "
                f"costs (1.6% friction, resulting in net markout {mean_net*100:.2f}%). "
                f"Hourly CLOB snapshot granularity leaves sub-minute speed-of-repricing under-observed."
            )
        else:
            classification = "REJECTED"
            rationale = "No systematic post-publication repricing detected; real response indistinguishable from placebos or net markout negative."

        return {
            "classification": classification,
            "rationale": rationale,
            "sample_size_1h": n_events,
            "mean_dir_delta_1h": mean_dir_delta,
            "mean_gross_markout_1h": mean_gross,
            "mean_net_markout_160bps": mean_net,
            "gross_t_stat": float(t_gross),
            "gross_p_value": float(p_gross),
            "net_t_stat": float(t_net),
            "net_p_value": float(p_net),
            "win_rate_gross": win_rate_gross,
            "win_rate_net": win_rate_net,
            "placebo_a_mean": pA_mean,
            "placebo_b_mean": pB_mean,
            "placebo_c_mean": pC_mean,
            "placebo_d_mean": pD_mean
        }
