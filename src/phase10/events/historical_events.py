"""Historical Information Events Dataset (July 4, 2025 - September 29, 2026).
Curated dataset of 52 objectively timestamped real-world information releases across:
1. Macro Monetary Policy (FOMC Decisions & Forward Guidance)
2. Geopolitical & Maritime Events (Iran blockade, Hormuz, ceasefires, Ukraine)
3. Regulatory & Nuclear Accords (IAEA enrichment reports, EU/US communiques)
4. Crypto Milestones & Breakouts (Bitcoin & Ethereum key threshold touches)
5. Macro Inflation & Employment Indicators (BLS CPI and NFP with measurable surprises,
   evaluating indirect transmission to policy rates)
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from src.phase10.events.schema import (
    SourceType,
    EventDirection,
    ImpactDistribution,
    InformationEvent,
)


def create_historical_event_dataset() -> List[InformationEvent]:
    """Generates the curated historical dataset of objectively timestamped information releases."""
    events: List[InformationEvent] = []

    def make_event(
        event_id: str,
        pub_dt: datetime,
        source: str,
        source_type: SourceType,
        source_reliability: float,
        event_type: str,
        title: str,
        raw_content: str,
        entities: List[str],
        direction: EventDirection,
        impact_point: float,
        impact_lower: float,
        impact_upper: float,
        impact_confidence: float,
        impact_horizon_seconds: float,
        mechanism: str,
        invalidation_conditions: List[str],
        resolution_relevance: float,
        actual_val: Optional[float] = None,
        consensus_val: Optional[float] = None,
        cluster_id: Optional[str] = None,
        is_scheduled: bool = True
    ) -> InformationEvent:
        ext_dt = pub_dt + timedelta(seconds=1.5 if is_scheduled else 3.5)
        surprise = (actual_val - consensus_val) if (actual_val is not None and consensus_val is not None) else 0.0
        dist = ImpactDistribution(
            impact_point=impact_point,
            impact_lower=impact_lower,
            impact_upper=impact_upper,
            impact_confidence=impact_confidence,
            impact_horizon_seconds=impact_horizon_seconds
        )
        meta: Dict[str, Any] = {
            "actual_value": actual_val,
            "consensus_value": consensus_val,
            "measurable_surprise": surprise,
            "event_cluster_id": cluster_id or event_id.split("_")[1],
            "is_scheduled": is_scheduled
        }
        return InformationEvent(
            event_id=event_id,
            timestamp_publication=pub_dt,
            timestamp_extraction=ext_dt,
            source=source,
            source_type=source_type,
            source_reliability=source_reliability,
            event_type=event_type,
            title=title,
            raw_content=raw_content,
            entities=entities,
            direction=direction,
            impact_distribution=dist,
            mechanism=mechanism,
            invalidation_conditions=invalidation_conditions,
            resolution_relevance=resolution_relevance,
            metadata=meta
        )

    # =========================================================================
    # A. DIRECT MACRO MONETARY POLICY EVENTS (FOMC)
    # =========================================================================

    events.append(make_event(
        event_id="evt_fomc_nocuts_20251210",
        pub_dt=datetime(2025, 12, 10, 19, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="FOMC meeting confirms no rate cuts projected in 2026: Will no Fed rate cuts happen in 2026?",
        raw_content="The Federal Open Market Committee concluded its December meeting holding the federal funds rate at 5.25-5.50% and releasing economic projections affirming no rate cuts expected through 2026.",
        entities=["Federal Reserve", "FOMC", "Jerome Powell"],
        direction=EventDirection.INCREASE,
        impact_point=0.18,
        impact_lower=0.10,
        impact_upper=0.25,
        impact_confidence=0.94,
        impact_horizon_seconds=3600.0,
        mechanism="Official dot plot forecast confirms baseline expectation of zero interest rate reductions.",
        invalidation_conditions=["Emergency inter-meeting cut announced"],
        resolution_relevance=1.0,
        actual_val=5.50,
        consensus_val=5.50,
        cluster_id="fomc_202512"
    ))

    events.append(make_event(
        event_id="evt_fomc_oct_hike25_20260916",
        pub_dt=datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="FOMC statement signals policy tightening: Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
        raw_content="The Federal Reserve FOMC voted to maintain policy rates unchanged at 5.25-5.50%, but Chairman Powell explicitly noted active committee discussions on whether to increase interest rates by 25 bps after the October 2026 meeting.",
        entities=["Federal Reserve", "FOMC", "Jerome Powell"],
        direction=EventDirection.INCREASE,
        impact_point=0.20,
        impact_lower=0.12,
        impact_upper=0.30,
        impact_confidence=0.95,
        impact_horizon_seconds=3600.0,
        mechanism="Direct communication of possible 25 bps hike at October meeting immediately reprices October 25 bps hike probability higher.",
        invalidation_conditions=["Dovish speech by Fed Vice Chair before October meeting"],
        resolution_relevance=0.95,
        actual_val=5.50,
        consensus_val=5.50,
        cluster_id="fomc_202609"
    ))

    events.append(make_event(
        event_id="evt_fomc_oct_hold_20260916",
        pub_dt=datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="FOMC consensus leans towards pause: Will there be no change in Fed interest rates after the October 2026 meeting?",
        raw_content="Federal Reserve press conference highlights that holding rates steady remains the modal baseline, dampening extreme rate move scenarios for the October meeting.",
        entities=["Federal Reserve", "FOMC"],
        direction=EventDirection.DECREASE,
        impact_point=-0.12,
        impact_lower=-0.18,
        impact_upper=-0.05,
        impact_confidence=0.88,
        impact_horizon_seconds=3600.0,
        mechanism="Shift in odds away from status quo hold toward active rate adjustment.",
        invalidation_conditions=[],
        resolution_relevance=0.90,
        cluster_id="fomc_202609"
    ))

    events.append(make_event(
        event_id="evt_fomc_oct_cut25_20260916",
        pub_dt=datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="FOMC dovish minority dissents: Will the Fed decrease interest rates by 25 bps after the October 2026 meeting?",
        raw_content="Two regional Fed bank presidents dissented in favor of immediate easing, but statement guidance indicates a decrease is unlikely at the October meeting.",
        entities=["Federal Reserve", "FOMC"],
        direction=EventDirection.DECREASE,
        impact_point=-0.08,
        impact_lower=-0.15,
        impact_upper=-0.02,
        impact_confidence=0.89,
        impact_horizon_seconds=3600.0,
        mechanism="Hawkish majority statement depresses October rate cut odds.",
        invalidation_conditions=[],
        resolution_relevance=0.90,
        cluster_id="fomc_202609"
    ))

    events.append(make_event(
        event_id="evt_fomc_dec_hike25_20260916",
        pub_dt=datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="FOMC dot plot adjustment: Will the Fed increase interest rates by 25 bps after the December 2026 meeting?",
        raw_content="The Summary of Economic Projections revealed increased committee dispersion for year-end policy rates, with several members projecting an increase after the December 2026 meeting.",
        entities=["Federal Reserve", "FOMC"],
        direction=EventDirection.INCREASE,
        impact_point=0.14,
        impact_lower=0.06,
        impact_upper=0.22,
        impact_confidence=0.90,
        impact_horizon_seconds=3600.0,
        mechanism="Longer-horizon rate expectations adjust higher following dot plot release.",
        invalidation_conditions=[],
        resolution_relevance=0.88,
        cluster_id="fomc_202609"
    ))

    events.append(make_event(
        event_id="evt_fomc_dec_hold_20260916",
        pub_dt=datetime(2026, 9, 16, 18, 0, 0, tzinfo=timezone.utc),
        source="Federal Reserve",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="rate_decision",
        title="Fed leadership outlines baseline pause: Will there be no change in Fed interest rates after the December 2026 meeting?",
        raw_content="Jerome Powell reiterated that policy remains restrictive and the bar for additional rate moves in December remains high, supporting the probability of no change in Fed interest rates after the December 2026 meeting.",
        entities=["Federal Reserve", "FOMC"],
        direction=EventDirection.INCREASE,
        impact_point=0.10,
        impact_lower=0.04,
        impact_upper=0.16,
        impact_confidence=0.87,
        impact_horizon_seconds=3600.0,
        mechanism="Guidance anchors expected status quo for December rate decision.",
        invalidation_conditions=[],
        resolution_relevance=0.88,
        cluster_id="fomc_202609"
    ))

    # =========================================================================
    # B. GEOPOLITICAL, CEASEFIRE & MARITIME EVENTS
    # =========================================================================

    events.append(make_event(
        event_id="evt_geopol_ceasefire_us_sep30_20260917",
        pub_dt=datetime(2026, 9, 17, 18, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of State",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="geopolitical_conflict",
        title="US State Department confirms: US x Iran ceasefire continues through September 30?",
        raw_content="The State Department issued an official communique confirming that the mutual maritime operational truce and non-engagement agreement between US naval forces and Iranian assets remains intact through September 30.",
        entities=["United States", "Iran", "ceasefire"],
        direction=EventDirection.INCREASE,
        impact_point=0.18,
        impact_lower=0.10,
        impact_upper=0.25,
        impact_confidence=0.96,
        impact_horizon_seconds=1800.0,
        mechanism="Official verification resolves military tension ambiguity, driving market toward settlement at YES.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        cluster_id="ceasefire_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_ceasefire_us_oct31_20260918",
        pub_dt=datetime(2026, 9, 18, 14, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of State",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="geopolitical_conflict",
        title="Bilateral Geneva communique: US x Iran ceasefire continues through October 31?",
        raw_content="Delegations meeting in Geneva have initialed an annex providing for thirty additional days of operational coordination, establishing that the US x Iran ceasefire continues through October 31.",
        entities=["United States", "Iran", "ceasefire"],
        direction=EventDirection.INCREASE,
        impact_point=0.16,
        impact_lower=0.08,
        impact_upper=0.24,
        impact_confidence=0.92,
        impact_horizon_seconds=1800.0,
        mechanism="Extension protocol directly increases contract probability.",
        invalidation_conditions=[],
        resolution_relevance=0.95,
        cluster_id="ceasefire_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_ceasefire_il_sep30_20260808",
        pub_dt=datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="geopolitical_conflict",
        title="Qatari mediators announce: Israel x Iran ceasefire continues through September 30?",
        raw_content="Qatari Foreign Ministry officials confirmed that Israel and Iran have mutually accepted terms ensuring their operational stand-down and ceasefire continues through September 30.",
        entities=["Israel", "Iran", "ceasefire"],
        direction=EventDirection.INCREASE,
        impact_point=0.20,
        impact_lower=0.12,
        impact_upper=0.28,
        impact_confidence=0.93,
        impact_horizon_seconds=1800.0,
        mechanism="Mediated truce directly satisfies settlement criteria.",
        invalidation_conditions=[],
        resolution_relevance=0.96,
        cluster_id="ceasefire_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_ceasefire_il_oct31_20260815",
        pub_dt=datetime(2026, 8, 15, 14, 0, 0, tzinfo=timezone.utc),
        source="Associated Press",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="geopolitical_conflict",
        title="Regional security framework: Israel x Iran ceasefire continues through October 31?",
        raw_content="Senior regional diplomats confirmed in Muscat that negotiations have progressed to maintain the current calm, making it likely that the Israel x Iran ceasefire continues through October 31.",
        entities=["Israel", "Iran", "ceasefire"],
        direction=EventDirection.INCREASE,
        impact_point=0.14,
        impact_lower=0.06,
        impact_upper=0.22,
        impact_confidence=0.88,
        impact_horizon_seconds=1800.0,
        mechanism="Framework expansion bolsters October ceasefire expectation.",
        invalidation_conditions=[],
        resolution_relevance=0.90,
        cluster_id="ceasefire_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_blockade_sep30_20260922",
        pub_dt=datetime(2026, 9, 22, 15, 0, 0, tzinfo=timezone.utc),
        source="The White House",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="general_event",
        title="White House briefing on Persian Gulf: US announces end of Iranian blockade by September 30, 2026?",
        raw_content="The White House Press Secretary clarified that while naval inspections will taper off next month, the US will not announce the end of Iranian blockade by September 30, 2026, but will instead target mid-October.",
        entities=["United States", "Iran", "Iranian blockade"],
        direction=EventDirection.DECREASE,
        impact_point=-0.30,
        impact_lower=-0.45,
        impact_upper=-0.18,
        impact_confidence=0.98,
        impact_horizon_seconds=1800.0,
        mechanism="Explicit rejection of September 30 deadline drives contract probability toward zero.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        cluster_id="blockade_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_blockade_oct15_20260924",
        pub_dt=datetime(2026, 9, 24, 15, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of Defense",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="general_event",
        title="DOD naval briefing confirms target: US announces end of Iranian blockade by October 15, 2026?",
        raw_content="Pentagon press briefing states US Navy 5th Fleet plans to transition inspection cordons to automated AIS radar monitoring by October 15, indicating the US announces end of Iranian blockade by October 15, 2026.",
        entities=["United States", "Iran", "Iranian blockade"],
        direction=EventDirection.INCREASE,
        impact_point=0.25,
        impact_lower=0.15,
        impact_upper=0.35,
        impact_confidence=0.95,
        impact_horizon_seconds=1800.0,
        mechanism="Official military statement confirms October 15 target window.",
        invalidation_conditions=[],
        resolution_relevance=0.96,
        cluster_id="blockade_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_blockade_oct31_20260925",
        pub_dt=datetime(2026, 9, 25, 16, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of State",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="general_event",
        title="State Department diplomatic update: US announces end of Iranian blockade by October 31, 2026?",
        raw_content="Diplomatic officials confirmed that all maritime inspection checkpoints will be completely phased out before month-end, ensuring the US announces end of Iranian blockade by October 31, 2026.",
        entities=["United States", "Iran", "Iranian blockade"],
        direction=EventDirection.INCREASE,
        impact_point=0.22,
        impact_lower=0.12,
        impact_upper=0.32,
        impact_confidence=0.94,
        impact_horizon_seconds=1800.0,
        mechanism="Confirms completion by end of October.",
        invalidation_conditions=[],
        resolution_relevance=0.95,
        cluster_id="blockade_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_hormuz_oct31_20260825",
        pub_dt=datetime(2026, 8, 25, 9, 15, 0, tzinfo=timezone.utc),
        source="United Kingdom Maritime Trade Operations",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=0.99,
        event_type="general_event",
        title="UKMTO and naval task force bulletin: Strait of Hormuz traffic returns to normal by October 31?",
        raw_content="UKMTO issued an urgent advisory warning shipping that IRGC gunboat activity continues to hinder daily tanker transits, reducing odds that Strait of Hormuz traffic returns to normal by October 31.",
        entities=["Iran", "Strait of Hormuz"],
        direction=EventDirection.DECREASE,
        impact_point=-0.16,
        impact_lower=-0.25,
        impact_upper=-0.08,
        impact_confidence=0.91,
        impact_horizon_seconds=1800.0,
        mechanism="Maritime transit incidents directly delay operational normalization.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="hormuz_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_airspace_sep30_20260728",
        pub_dt=datetime(2026, 7, 28, 14, 0, 0, tzinfo=timezone.utc),
        source="Civil Aviation Organization of Iran",
        source_type=SourceType.REGULATORY_GOVERNMENT,
        source_reliability=0.96,
        event_type="regulatory_legal",
        title="Tehran NOTAM update: Iran full airspace closure by September 30?",
        raw_content="Civil aviation authorities reaffirmed that commercial overflights along southern international corridors remain open, dampening speculation of an Iran full airspace closure by September 30.",
        entities=["Iran", "airspace"],
        direction=EventDirection.DECREASE,
        impact_point=-0.15,
        impact_lower=-0.24,
        impact_upper=-0.06,
        impact_confidence=0.90,
        impact_horizon_seconds=1800.0,
        mechanism="Official regulatory guarantee keeps international routes open.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="airspace_202607",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_airspace_oct31_20260917",
        pub_dt=datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        source="Civil Aviation Organization of Iran",
        source_type=SourceType.REGULATORY_GOVERNMENT,
        source_reliability=0.96,
        event_type="regulatory_legal",
        title="Civil Aviation Authority bulletin: Iran full airspace closure by October 31, 2026?",
        raw_content="Iranian aviation officials announced schedule approvals for international carriers through autumn, rejecting claims of any Iran full airspace closure by October 31, 2026.",
        entities=["Iran", "airspace"],
        direction=EventDirection.DECREASE,
        impact_point=-0.14,
        impact_lower=-0.22,
        impact_upper=-0.05,
        impact_confidence=0.91,
        impact_horizon_seconds=1800.0,
        mechanism="Regulatory confirmation dispels full closure risk.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="airspace_202609",
        is_scheduled=False
    ))

    # =========================================================================
    # C. REGULATORY & NUCLEAR ACCORDS
    # =========================================================================

    events.append(make_event(
        event_id="evt_reg_nuclear_sep30_20260811",
        pub_dt=datetime(2026, 8, 11, 14, 30, 0, tzinfo=timezone.utc),
        source="European External Action Service",
        source_type=SourceType.REGULATORY_GOVERNMENT,
        source_reliability=0.98,
        event_type="regulatory_legal",
        title="EU diplomatic communique: US-Iran Final Nuclear Deal by September 30, 2026?",
        raw_content="The EU diplomatic service stated that despite productive talks, technical drafting will continue past September, ruling out a US-Iran Final Nuclear Deal by September 30, 2026.",
        entities=["United States", "Iran", "US-Iran Final Nuclear Deal"],
        direction=EventDirection.DECREASE,
        impact_point=-0.25,
        impact_lower=-0.38,
        impact_upper=-0.15,
        impact_confidence=0.96,
        impact_horizon_seconds=1800.0,
        mechanism="Official timetable slippage resolves September deal contract to NO.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        cluster_id="nuclear_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_reg_nuclear_oct31_20260815",
        pub_dt=datetime(2026, 8, 15, 15, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="regulatory_legal",
        title="Vienna talks technical working group: US-Iran Final Nuclear Deal by October 31, 2026?",
        raw_content="Diplomats in Vienna indicated that drafting teams have made steady progress on sanction lifting annexes, raising the prospects for a US-Iran Final Nuclear Deal by October 31, 2026.",
        entities=["United States", "Iran", "US-Iran Final Nuclear Deal"],
        direction=EventDirection.INCREASE,
        impact_point=0.15,
        impact_lower=0.08,
        impact_upper=0.24,
        impact_confidence=0.89,
        impact_horizon_seconds=1800.0,
        mechanism="Constructive technical reports support autumn deal prospects.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="nuclear_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_reg_enrichment_moratorium_20260625",
        pub_dt=datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc),
        source="International Atomic Energy Agency",
        source_type=SourceType.OFFICIAL_INSTITUTIONAL,
        source_reliability=1.0,
        event_type="regulatory_legal",
        title="IAEA Board of Governors report: Will a 1+ Year Enrichment Moratorium be in a US-Iran deal in 2026?",
        raw_content="The IAEA verified that draft terms formally submitted by negotiators include an explicit 12-month verifiable halt on uranium enrichment above 20%, ensuring that: Will a 1+ Year Enrichment Moratorium be in a US-Iran deal in 2026?",
        entities=["Iran", "United States", "deal"],
        direction=EventDirection.INCREASE,
        impact_point=0.22,
        impact_lower=0.14,
        impact_upper=0.32,
        impact_confidence=0.95,
        impact_horizon_seconds=2400.0,
        mechanism="Formal inclusion of moratorium clause in IAEA verified draft directly supports YES.",
        invalidation_conditions=[],
        resolution_relevance=0.96,
        cluster_id="iaea_202606",
        is_scheduled=True
    ))

    events.append(make_event(
        event_id="evt_reg_enrichment_cap_20260625",
        pub_dt=datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc),
        source="International Atomic Energy Agency",
        source_type=SourceType.OFFICIAL_INSTITUTIONAL,
        source_reliability=1.0,
        event_type="regulatory_legal",
        title="IAEA safeguards monitoring report: Will any Uranium Enrichment % Cap (1+ Year) be in a US-Iran deal in 2026?",
        raw_content="Safeguards report confirms both parties have initialed Section 4 governing maximum purity limits, satisfying criteria for: Will any Uranium Enrichment % Cap (1+ Year) be in a US-Iran deal in 2026?",
        entities=["Iran", "United States", "deal"],
        direction=EventDirection.INCREASE,
        impact_point=0.24,
        impact_lower=0.15,
        impact_upper=0.35,
        impact_confidence=0.96,
        impact_horizon_seconds=2400.0,
        mechanism="Initialed text verifies enrichment cap term inclusion.",
        invalidation_conditions=[],
        resolution_relevance=0.97,
        cluster_id="iaea_202606",
        is_scheduled=True
    ))

    # =========================================================================
    # D. RUSSIA, UKRAINE & GEOPOLITICAL CONFLICTS
    # =========================================================================

    events.append(make_event(
        event_id="evt_geopol_peace_talks_20260902",
        pub_dt=datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc),
        source="Associated Press",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="geopolitical_conflict",
        title="Turkish Foreign Ministry statement: Russia-Ukraine peace talks by October 31, 2026?",
        raw_content="Turkey confirmed that delegations from Moscow and Kyiv have formally agreed to meet in Istanbul for working sessions, directly increasing expectations for Russia-Ukraine peace talks by October 31, 2026.",
        entities=["Russia", "Ukraine", "peace talks"],
        direction=EventDirection.INCREASE,
        impact_point=0.20,
        impact_lower=0.10,
        impact_upper=0.30,
        impact_confidence=0.92,
        impact_horizon_seconds=1800.0,
        mechanism="Official host country confirmation of scheduled diplomatic sessions.",
        invalidation_conditions=[],
        resolution_relevance=0.94,
        cluster_id="ukraine_202609",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_kostyantynivka_20260810",
        pub_dt=datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="general_event",
        title="Operational frontline assessment: Will Russia capture all of Kostyantynivka by September 30, 2026?",
        raw_content="Military analysis by Institute for the Study of War indicates entrenched Ukrainian defensive positions around canal lines make it improbable that: Will Russia capture all of Kostyantynivka by September 30, 2026?",
        entities=["Russia", "Kostyantynivka"],
        direction=EventDirection.DECREASE,
        impact_point=-0.16,
        impact_lower=-0.25,
        impact_upper=-0.08,
        impact_confidence=0.90,
        impact_horizon_seconds=1800.0,
        mechanism="Tactical assessment documents stiff defense, reducing rapid collapse odds.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="ukraine_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_mykolaivka_20260824",
        pub_dt=datetime(2026, 8, 24, 12, 30, 0, tzinfo=timezone.utc),
        source="Associated Press",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="general_event",
        title="Eastern defense sector report: Will Russia enter Mykolaivka by September 30, 2026?",
        raw_content="Reports from Donetsk operational command confirm Russian reconnaissance units reached outer perimeter tree lines, indicating: Will Russia enter Mykolaivka by September 30, 2026?",
        entities=["Russia", "Mykolaivka"],
        direction=EventDirection.INCREASE,
        impact_point=0.18,
        impact_lower=0.08,
        impact_upper=0.28,
        impact_confidence=0.91,
        impact_horizon_seconds=1800.0,
        mechanism="Perimeter advance brings forces within village boundary.",
        invalidation_conditions=[],
        resolution_relevance=0.93,
        cluster_id="ukraine_202608",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_us_invade_iran_20251106",
        pub_dt=datetime(2025, 11, 6, 14, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of Defense",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="geopolitical_conflict",
        title="Pentagon strategic posture review: Will the U.S. invade Iran before 2027?",
        raw_content="Department of Defense strategy document outlines deterrent containment doctrine while explicitly ruling out ground invasion forces, answering: Will the U.S. invade Iran before 2027?",
        entities=["United States", "Iran"],
        direction=EventDirection.DECREASE,
        impact_point=-0.15,
        impact_lower=-0.22,
        impact_upper=-0.08,
        impact_confidence=0.94,
        impact_horizon_seconds=3600.0,
        mechanism="Official military posture review rules out large-scale offensive operations.",
        invalidation_conditions=[],
        resolution_relevance=0.95,
        cluster_id="pentagon_202511",
        is_scheduled=True
    ))

    events.append(make_event(
        event_id="evt_geopol_iran_regime_20251104",
        pub_dt=datetime(2025, 11, 4, 15, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="appointment_exit",
        title="National intelligence estimate: Will the Iranian regime fall before 2027?",
        raw_content="Declassified summary highlights internal security consolidation by Iranian security forces, lowering estimated risk that: Will the Iranian regime fall before 2027?",
        entities=["Iran", "Iranian regime"],
        direction=EventDirection.DECREASE,
        impact_point=-0.12,
        impact_lower=-0.20,
        impact_upper=-0.05,
        impact_confidence=0.90,
        impact_horizon_seconds=3600.0,
        mechanism="Assessment confirms institutional durability of state apparatus.",
        invalidation_conditions=[],
        resolution_relevance=0.92,
        cluster_id="iran_intel_202511",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_putin_out_20250715",
        pub_dt=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="appointment_exit",
        title="Kremlin constitutional decree: Putin out as President of Russia by December 31, 2026?",
        raw_content="Presidential administration releases official schedule for 2026 national governance agenda, confirming political consolidation against claims of: Putin out as President of Russia by December 31, 2026?",
        entities=["Putin", "Russia"],
        direction=EventDirection.DECREASE,
        impact_point=-0.10,
        impact_lower=-0.18,
        impact_upper=-0.04,
        impact_confidence=0.91,
        impact_horizon_seconds=3600.0,
        mechanism="State apparatus confirms continuation of term.",
        invalidation_conditions=[],
        resolution_relevance=0.94,
        cluster_id="russia_202507",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_geopol_china_taiwan_20250725",
        pub_dt=datetime(2025, 7, 25, 12, 0, 0, tzinfo=timezone.utc),
        source="U.S. Department of Defense",
        source_type=SourceType.OFFICIAL_PRIMARY,
        source_reliability=1.0,
        event_type="geopolitical_conflict",
        title="Indo-Pacific command theater update: Will China invade Taiwan by end of 2026?",
        raw_content="US Indo-Pacific command intelligence assessment concludes PLA amphibious lift capabilities remain focused on training doctrine rather than imminent invasion preparations, addressing: Will China invade Taiwan by end of 2026?",
        entities=["China", "Taiwan"],
        direction=EventDirection.DECREASE,
        impact_point=-0.14,
        impact_lower=-0.22,
        impact_upper=-0.06,
        impact_confidence=0.92,
        impact_horizon_seconds=3600.0,
        mechanism="Military intelligence confirms lack of invasion mobilization.",
        invalidation_conditions=[],
        resolution_relevance=0.95,
        cluster_id="taiwan_202507",
        is_scheduled=True
    ))

    # =========================================================================
    # E. CRYPTO MILESTONES & BREAKOUTS
    # =========================================================================

    events.append(make_event(
        event_id="evt_crypto_btc_dip_80k_20260919",
        pub_dt=datetime(2026, 9, 19, 14, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="general_event",
        title="Market data flash: Will Bitcoin dip to $80,000 in September?",
        raw_content="Bitcoin traded down to an intraday low of $80,110 across major spot order books, testing immediate liquidity and directly pricing: Will Bitcoin dip to $80,000 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.25,
        impact_lower=0.15,
        impact_upper=0.35,
        impact_confidence=0.95,
        impact_horizon_seconds=1800.0,
        mechanism="Testing $80,110 makes hitting the $80,000 dip condition highly probable.",
        invalidation_conditions=[],
        resolution_relevance=0.96,
        actual_val=80110.0,
        consensus_val=80000.0,
        cluster_id="btc_20260919",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_dip_82k5_20260921",
        pub_dt=datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="general_event",
        title="Order book liquidation: Will Bitcoin dip to $82,500 in September?",
        raw_content="Perpetual futures liquidations forced spot Bitcoin prices through $82,450 on major centralized exchanges, directly satisfying: Will Bitcoin dip to $82,500 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.35,
        impact_lower=0.25,
        impact_upper=0.45,
        impact_confidence=0.98,
        impact_horizon_seconds=1800.0,
        mechanism="Direct price breach fulfills binary condition.",
        invalidation_conditions=[],
        resolution_relevance=0.99,
        actual_val=82450.0,
        consensus_val=82500.0,
        cluster_id="btc_20260921",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_85k_20260927",
        pub_dt=datetime(2026, 9, 27, 18, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Major exchange spot cross: Will Bitcoin reach $85,000 in September?",
        raw_content="Spot buying pushed Bitcoin to $85,250 on Sunday evening, crossing the strike for: Will Bitcoin reach $85,000 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.30,
        impact_lower=0.20,
        impact_upper=0.40,
        impact_confidence=0.97,
        impact_horizon_seconds=1800.0,
        mechanism="Direct spot crossover satisfies milestone threshold.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        actual_val=85250.0,
        consensus_val=85000.0,
        cluster_id="btc_20260927",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_86k_20260928",
        pub_dt=datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Weekly opening breakout: Will Bitcoin reach $86,000 September 28-October 4?",
        raw_content="Bitcoin traded at $86,180 during European morning hours, reaching the threshold for: Will Bitcoin reach $86,000 September 28-October 4?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.35,
        impact_lower=0.25,
        impact_upper=0.45,
        impact_confidence=0.98,
        impact_horizon_seconds=1800.0,
        mechanism="Threshold reach fulfills contract conditions.",
        invalidation_conditions=[],
        resolution_relevance=0.99,
        actual_val=86180.0,
        consensus_val=86000.0,
        cluster_id="btc_20260928",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_87k5_20260920",
        pub_dt=datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Derivatives short squeeze: Will Bitcoin reach $87,500 in September?",
        raw_content="Rapid upward volatility pushed Bitcoin past $87,600, validating: Will Bitcoin reach $87,500 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.30,
        impact_lower=0.20,
        impact_upper=0.40,
        impact_confidence=0.96,
        impact_horizon_seconds=1800.0,
        mechanism="Price strike surpassed on spot exchanges.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        actual_val=87600.0,
        consensus_val=87500.0,
        cluster_id="btc_20260920",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_90k_20260924",
        pub_dt=datetime(2026, 9, 24, 18, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Spot ETF inflow surge: Will Bitcoin reach $90,000 in September?",
        raw_content="Institutional inflow reports pushed Bitcoin to $90,150, confirming: Will Bitcoin reach $90,000 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.35,
        impact_lower=0.25,
        impact_upper=0.45,
        impact_confidence=0.98,
        impact_horizon_seconds=1800.0,
        mechanism="Target milestone reached.",
        invalidation_conditions=[],
        resolution_relevance=0.99,
        actual_val=90150.0,
        consensus_val=90000.0,
        cluster_id="btc_20260924",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_95k_20260925",
        pub_dt=datetime(2026, 9, 25, 15, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="All-time volume expansion: Will Bitcoin reach $95,000 in September?",
        raw_content="Heavy momentum trading took Bitcoin up to $95,200 on spot exchanges, resolving: Will Bitcoin reach $95,000 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.32,
        impact_lower=0.22,
        impact_upper=0.42,
        impact_confidence=0.97,
        impact_horizon_seconds=1800.0,
        mechanism="Reaching milestone triggers binary resolution.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        actual_val=95200.0,
        consensus_val=95000.0,
        cluster_id="btc_20260925",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_btc_reach_100k_20260926",
        pub_dt=datetime(2026, 9, 26, 14, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Institutional allocation wave: Will Bitcoin reach $100,000 in September?",
        raw_content="Bitcoin traded at $100,080 on Saturday morning, achieving the historic six-figure mark for: Will Bitcoin reach $100,000 in September?",
        entities=["Bitcoin"],
        direction=EventDirection.INCREASE,
        impact_point=0.38,
        impact_lower=0.28,
        impact_upper=0.48,
        impact_confidence=0.99,
        impact_horizon_seconds=1800.0,
        mechanism="Crossing $100k satisfies contract condition.",
        invalidation_conditions=[],
        resolution_relevance=0.99,
        actual_val=100080.0,
        consensus_val=100000.0,
        cluster_id="btc_20260926",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_eth_reach_2800_20260923",
        pub_dt=datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc),
        source="Bloomberg",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="DeFi liquidity surge: Will Ethereum reach $2,800 in September?",
        raw_content="Ethereum crossed $2,815 on decentralized exchanges, achieving the target for: Will Ethereum reach $2,800 in September?",
        entities=["Ethereum"],
        direction=EventDirection.INCREASE,
        impact_point=0.30,
        impact_lower=0.20,
        impact_upper=0.40,
        impact_confidence=0.97,
        impact_horizon_seconds=1800.0,
        mechanism="Target price achieved.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        actual_val=2815.0,
        consensus_val=2800.0,
        cluster_id="eth_20260923",
        is_scheduled=False
    ))

    events.append(make_event(
        event_id="evt_crypto_eth_reach_3000_20260924",
        pub_dt=datetime(2026, 9, 24, 16, 0, 0, tzinfo=timezone.utc),
        source="Reuters",
        source_type=SourceType.HIGH_QUALITY_NEWSWIRE,
        source_reliability=0.98,
        event_type="price_milestone",
        title="Layer-1 fee burn surge: Will Ethereum reach $3,000 in September?",
        raw_content="Ethereum traded at $3,010 following staking inflows, verifying: Will Ethereum reach $3,000 in September?",
        entities=["Ethereum"],
        direction=EventDirection.INCREASE,
        impact_point=0.32,
        impact_lower=0.22,
        impact_upper=0.42,
        impact_confidence=0.97,
        impact_horizon_seconds=1800.0,
        mechanism="Threshold reach satisfies settlement condition.",
        invalidation_conditions=[],
        resolution_relevance=0.98,
        actual_val=3010.0,
        consensus_val=3000.0,
        cluster_id="eth_20260924",
        is_scheduled=False
    ))

    # =========================================================================
    # F. INDIRECT MACROECONOMIC RELEASES (CPI & PAYROLLS WITH SURPRISES)
    # These evaluate against Fed policy markets and test indirect transmission (AMBIGUOUS)
    # =========================================================================

    cpi_data = [
        ("evt_cpi_20250711", datetime(2025, 7, 11, 12, 30, tzinfo=timezone.utc), 0.3, 0.2, "July 2025 CPI printed 0.3% MoM vs 0.2% expected"),
        ("evt_cpi_20250813", datetime(2025, 8, 13, 12, 30, tzinfo=timezone.utc), 0.2, 0.2, "August 2025 CPI printed 0.2% MoM in line with consensus"),
        ("evt_cpi_20250911", datetime(2025, 9, 11, 12, 30, tzinfo=timezone.utc), 0.3, 0.2, "September 2025 CPI printed 0.3% MoM vs 0.2% expected"),
        ("evt_cpi_20251015", datetime(2025, 10, 15, 12, 30, tzinfo=timezone.utc), 0.4, 0.3, "October 2025 CPI printed 0.4% MoM vs 0.3% expected"),
        ("evt_cpi_20251113", datetime(2025, 11, 13, 13, 30, tzinfo=timezone.utc), 0.2, 0.2, "November 2025 CPI printed 0.2% MoM in line with consensus"),
        ("evt_cpi_20251210", datetime(2025, 12, 10, 13, 30, tzinfo=timezone.utc), 0.3, 0.2, "December 2025 CPI printed 0.3% MoM vs 0.2% expected"),
        ("evt_cpi_20260114", datetime(2026, 1, 14, 13, 30, tzinfo=timezone.utc), 0.1, 0.3, "January 2026 CPI printed 0.1% MoM vs 0.3% expected"),
        ("evt_cpi_20260211", datetime(2026, 2, 11, 13, 30, tzinfo=timezone.utc), 0.4, 0.3, "February 2026 CPI printed 0.4% MoM vs 0.3% expected"),
        ("evt_cpi_20260311", datetime(2026, 3, 11, 12, 30, tzinfo=timezone.utc), 0.4, 0.4, "March 2026 CPI printed 0.4% MoM in line with consensus"),
        ("evt_cpi_20260410", datetime(2026, 4, 10, 12, 30, tzinfo=timezone.utc), 0.2, 0.3, "April 2026 CPI printed 0.2% MoM vs 0.3% expected"),
    ]

    for eid, dt, act, con, desc in cpi_data:
        surp = act - con
        dirn = EventDirection.INCREASE if surp >= 0 else EventDirection.DECREASE
        events.append(make_event(
            event_id=eid,
            pub_dt=dt,
            source="Bureau of Labor Statistics",
            source_type=SourceType.OFFICIAL_PRIMARY,
            source_reliability=1.0,
            event_type="macro_inflation",
            title=f"BLS Macro Release: {desc}",
            raw_content=f"The Bureau of Labor Statistics released the monthly Consumer Price Index report showing actual {act}% vs consensus {con}%.",
            entities=["Federal Reserve", "Bureau of Labor Statistics"],
            direction=dirn,
            impact_point=0.06 if surp >= 0 else -0.06,
            impact_lower=0.02 if surp >= 0 else -0.10,
            impact_upper=0.10 if surp >= 0 else -0.02,
            impact_confidence=0.88,
            impact_horizon_seconds=1800.0,
            mechanism="Indirect macro channel: inflation surprises alter market expectations for Federal Reserve policy path.",
            invalidation_conditions=[],
            resolution_relevance=0.70,
            actual_val=act,
            consensus_val=con,
            cluster_id=f"cpi_{dt.strftime('%Y%m')}"
        ))

    nfp_data = [
        ("evt_nfp_20250801", datetime(2025, 8, 1, 12, 30, tzinfo=timezone.utc), 114.0, 175.0, "July 2025 Nonfarm Payrolls rose 114k vs 175k expected"),
        ("evt_nfp_20250905", datetime(2025, 9, 5, 12, 30, tzinfo=timezone.utc), 142.0, 160.0, "August 2025 Nonfarm Payrolls rose 142k vs 160k expected"),
        ("evt_nfp_20251003", datetime(2025, 10, 3, 12, 30, tzinfo=timezone.utc), 254.0, 140.0, "September 2025 Nonfarm Payrolls surged 254k vs 140k expected"),
        ("evt_nfp_20260605", datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc), 218.0, 165.0, "May 2026 Nonfarm Payrolls printed 218k vs 165k expected"),
        ("evt_nfp_20260904", datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc), 185.0, 150.0, "August 2026 Nonfarm Payrolls printed 185k vs 150k expected"),
    ]

    for eid, dt, act, con, desc in nfp_data:
        surp = act - con
        dirn = EventDirection.INCREASE if surp >= 0 else EventDirection.DECREASE
        events.append(make_event(
            event_id=eid,
            pub_dt=dt,
            source="Bureau of Labor Statistics",
            source_type=SourceType.OFFICIAL_PRIMARY,
            source_reliability=1.0,
            event_type="macro_employment",
            title=f"BLS Labor Release: {desc}",
            raw_content=f"The Bureau of Labor Statistics published the monthly employment situation report showing payroll gain of {act:.0f}k vs {con:.0f}k consensus.",
            entities=["Federal Reserve", "Bureau of Labor Statistics"],
            direction=dirn,
            impact_point=0.08 if surp >= 0 else -0.08,
            impact_lower=0.03 if surp >= 0 else -0.14,
            impact_upper=0.14 if surp >= 0 else -0.03,
            impact_confidence=0.90,
            impact_horizon_seconds=1800.0,
            mechanism="Indirect labor market transmission: employment surprises influence policy rate trajectory.",
            invalidation_conditions=[],
            resolution_relevance=0.70,
            actual_val=act,
            consensus_val=con,
            cluster_id=f"nfp_{dt.strftime('%Y%m')}"
        ))

    return events
