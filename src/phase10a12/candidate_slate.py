"""Preregistered 10 Candidate Mechanisms for Phase 10A.12 Discovery Slate.

Each candidate defines all 13 required forensic properties before empirical testing:
1. Mechanism
2. Economic rationale
3. Observable inputs
4. Signal definition
5. Direction
6. Entry condition
7. Exit/markout condition
8. Execution model
9. Required liquidity
10. Expected holding period
11. Main falsification test
12. Primary failure mode
13. Why it is not equivalent to a closed family
"""

from dataclasses import dataclass
from typing import Dict, List, Any

from src.phase10a12 import CandidateID, CandidateStatus


@dataclass(frozen=True)
class CandidateSpecification:
    candidate_id: CandidateID
    name: str
    mechanism: str
    economic_rationale: str
    observable_inputs: str
    signal_definition: str
    direction: str
    entry_condition: str
    exit_condition: str
    execution_model: str
    required_liquidity_usd: float
    expected_holding_period_sec: float
    main_falsification_test: str
    primary_failure_mode: str
    not_closed_family_proof: str
    status: CandidateStatus = CandidateStatus.PREREGISTERED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id.value,
            "name": self.name,
            "mechanism": self.mechanism,
            "economic_rationale": self.economic_rationale,
            "observable_inputs": self.observable_inputs,
            "signal_definition": self.signal_definition,
            "direction": self.direction,
            "entry_condition": self.entry_condition,
            "exit_condition": self.exit_condition,
            "execution_model": self.execution_model,
            "required_liquidity_usd": self.required_liquidity_usd,
            "expected_holding_period_sec": self.expected_holding_period_sec,
            "main_falsification_test": self.main_falsification_test,
            "primary_failure_mode": self.primary_failure_mode,
            "not_closed_family_proof": self.not_closed_family_proof,
            "status": self.status.value,
        }


class PreregisteredCandidateSlate:
    """Registry containing the 10 preregistered candidate mechanisms."""

    CANDIDATES: Dict[CandidateID, CandidateSpecification] = {
        CandidateID.C1_OFA_BURST: CandidateSpecification(
            candidate_id=CandidateID.C1_OFA_BURST,
            name="Order-Flow Acceleration & Trade-Burst Momentum",
            mechanism="Arrival rate acceleration of consecutive aggressive taker trades within 500ms windows.",
            economic_rationale="Informed liquidations or news-driven traders execute bursts of orders that temporarily overwhelm top-of-book depth, producing short-term momentum.",
            observable_inputs="Trade arrival timestamps, trade sizes, sides, and inter-trade arrival intervals.",
            signal_definition=">= 3 consecutive same-side trades totaling > $250 within 1.0s window.",
            direction="Momentum (Follow burst direction: BUY on buy-burst, SELL on sell-burst).",
            entry_condition="Immediate taker fill at prevailing best ask (buy) or best bid (sell).",
            exit_condition="Fixed 5.0s markout or opposite trade arrival.",
            execution_model="Taker execution crossing top level.",
            required_liquidity_usd=100.0,
            expected_holding_period_sec=5.0,
            main_falsification_test="Randomized trade timestamp permutation (destroys temporal clustering).",
            primary_failure_mode="Burst represents end of order flow; immediate adverse mean reversion upon entry.",
            not_closed_family_proof="Operates on trade arrival point-process intensity rather than order book depth sweeps (M1) or static imbalance (10A.7).",
        ),
        CandidateID.C2_CANCEL_RATIO_FLIP: CandidateSpecification(
            candidate_id=CandidateID.C2_CANCEL_RATIO_FLIP,
            name="Quote Cancellation-to-Trade Imbalance Shift",
            mechanism="Asymmetric quote cancellation volume relative to executed volume over 2-second windows.",
            economic_rationale="Fast market makers possessing low-latency off-chain price feeds cancel resting orders before being picked off, signaling imminent price displacement away from canceled side.",
            observable_inputs="Order book depth changes not matched by trade records (inferred quote cancellations).",
            signal_definition="Bid cancellation volume > 3x Ask cancellation volume without matching sell trades.",
            direction="Directional away from canceled side (SELL when bids vanish).",
            entry_condition="Taker sell at remaining best bid before quote markup.",
            exit_condition="10.0s markout or quote replenishment.",
            execution_model="Taker order crossing inside quote.",
            required_liquidity_usd=200.0,
            expected_holding_period_sec=10.0,
            main_falsification_test="Directional sign permutation (invert cancellation ratio).",
            primary_failure_mode="Cancellations represent quote flickering/jitter with zero genuine information.",
            not_closed_family_proof="Focuses on the ratio of cancellations to executed trades, not resting maker inventory (10A.8).",
        ),
        CandidateID.C3_SPREAD_COMPRESSION_BREAKOUT: CandidateSpecification(
            candidate_id=CandidateID.C3_SPREAD_COMPRESSION_BREAKOUT,
            name="Tightening Spread Volatility Breakout",
            mechanism="Prolonged spread compression to historical minimum followed by an aggressive widening trade.",
            economic_rationale="Competitive market makers tighten quotes during balanced inventory. An aggressive trade breaking the compressed regime indicates fresh information arrival forcing spread expansion.",
            observable_inputs="Rolling 60s median spread vs instantaneous spread, and subsequent trade volume.",
            signal_definition="Spread <= 0.5x rolling median spread followed by trade > $100.",
            direction="Direction of the breakout trade.",
            entry_condition="Taker fill at new expanded quote.",
            exit_condition="30.0s markout or spread re-compression.",
            execution_model="Taker fill at breakout price.",
            required_liquidity_usd=300.0,
            expected_holding_period_sec=30.0,
            main_falsification_test="Time-shifted event boundary placebo.",
            primary_failure_mode="Breakout trade is non-directional; market makers widen quotes defensively then mean-revert.",
            not_closed_family_proof="Evaluates dynamic spread regime transitions (compression to expansion), not static tick wedges (M2).",
        ),
        CandidateID.C4_NON_SWEEP_ABSORPTION: CandidateSpecification(
            candidate_id=CandidateID.C4_NON_SWEEP_ABSORPTION,
            name="Hidden Liquidity Absorption at Support/Resistance",
            mechanism="Heavy volume executed at a single price level without price movement (iceberg absorption).",
            economic_rationale="Large passive institutional limit orders absorb aggressive selling/buying without moving. When aggressive flow exhausts, price bounces in the opposite direction.",
            observable_inputs="Cumulative trade volume at fixed price P relative to visible depth.",
            signal_definition="Volume at level > $500 with zero price change over 5.0s.",
            direction="Reversal (BUY if sells absorbed, SELL if buys absorbed).",
            entry_condition="Taker order in bounce direction immediately following absorption pause.",
            exit_condition="15.0s markout or absorption level breach.",
            execution_model="Taker execution at prevailing inside quote.",
            required_liquidity_usd=100.0,
            expected_holding_period_sec=15.0,
            main_falsification_test="Randomized trade size permutation.",
            primary_failure_mode="Iceberg liquidity exhausts and market order sweeps through the level (toxic adverse selection).",
            not_closed_family_proof="Explicitly requires non-sweep absorption, unlike M1 which required depth to be completely swept.",
        ),
        CandidateID.C5_VOLATILITY_SPIKE_REBALANCE: CandidateSpecification(
            candidate_id=CandidateID.C5_VOLATILITY_SPIKE_REBALANCE,
            name="Volatility-Conditioned Quote Recalibration",
            mechanism="Order book quote dispersion expansion following high-frequency volatility shocks.",
            economic_rationale="Prediction market spreads widen asymmetrically during macro volatility bursts; the side with wider spread overreacts relative to historical contract volatility.",
            observable_inputs="10-second realized quote volatility sigma_10s vs 60-second baseline sigma_60s.",
            signal_definition="sigma_10s > 3x sigma_60s with asymmetric spread widening > 200 bps.",
            direction="Position towards the narrower / calibrated quote side.",
            entry_condition="Taker entry on lagging quote side.",
            exit_condition="20.0s markout.",
            execution_model="Taker fill.",
            required_liquidity_usd=250.0,
            expected_holding_period_sec=20.0,
            main_falsification_test="Non-volatility matched control windows.",
            primary_failure_mode="Elevated volatility increases spread crossing costs beyond any directional drift.",
            not_closed_family_proof="Volatility regime conditioning rather than deterministic resolution lag (10A.10).",
        ),
        CandidateID.C6_ASYMMETRIC_CROSS_IMPACT: CandidateSpecification(
            candidate_id=CandidateID.C6_ASYMMETRIC_CROSS_IMPACT,
            name="Asymmetric Information Transmission in Correlated Contracts",
            mechanism="High-volume parent market price discovery transmitting with discrete delay to low-volume satellite market.",
            economic_rationale="Informed volume concentrates in high-liquidity flagship contracts. Market makers in low-liquidity satellite contracts reprice with a latency lag.",
            observable_inputs="Synchronized price ticks between parent contract (Volume > $10k/hr) and satellite contract.",
            signal_definition="Parent moves > 2 ticks while satellite midpoint unchanged over prior 3.0s.",
            direction="In direction of parent move.",
            entry_condition="Taker order on satellite contract at prevailing ask/bid.",
            exit_condition="10.0s markout or satellite reprice.",
            execution_model="Taker execution on satellite book.",
            required_liquidity_usd=100.0,
            expected_holding_period_sec=10.0,
            main_falsification_test="Shuffled parent-satellite contract pairings.",
            primary_failure_mode="Satellite spread exceeds parent move; satellite quotes widen preemptively.",
            not_closed_family_proof="Cross-contract information transmission (not stat-arb cointegration Phase 3-9, nor multi-outcome M3).",
        ),
        CandidateID.C7_REPLENISHMENT_ASYMMETRY: CandidateSpecification(
            candidate_id=CandidateID.C7_REPLENISHMENT_ASYMMETRY,
            name="Asymmetric Quote Replenishment Following Partial Depth Fill",
            mechanism="One book side rapidly replenishes liquidity post-trade while the opposite side remains depleted.",
            economic_rationale="Asymmetric replenishment reveals private market maker inventory positioning and reluctance to quote the depleted side.",
            observable_inputs="Depth recovery delta D(t+2s) - D(t) on bid side vs ask side.",
            signal_definition="One side recovers > 80% depth within 2s while opposite recovers < 20%.",
            direction="Direction of replenishing side (BUY if bids replenish).",
            entry_condition="Taker fill on depleted side before markup.",
            exit_condition="15.0s markout.",
            execution_model="Taker fill.",
            required_liquidity_usd=50.0,
            expected_holding_period_sec=15.0,
            main_falsification_test="Randomized directional assignment.",
            primary_failure_mode="Depleted side quote widens instantly, imposing spread penalty greater than signal value.",
            not_closed_family_proof="Compares relative replenishment asymmetry between bid and ask, not sweep replenishment (M1).",
        ),
        CandidateID.C8_DEPTH_CONCENTRATION_TRANSITION: CandidateSpecification(
            candidate_id=CandidateID.C8_DEPTH_CONCENTRATION_TRANSITION,
            name="Order Book Depth Migration from Outer to Inner Ticks",
            mechanism="Migration of resting depth from outer ladder levels (levels 3-5) to inside quotes (level 1).",
            economic_rationale="Market makers shifting capital from outer levels to inside quotes signals readiness to absorb flow and impending quote stability.",
            observable_inputs="Ratio R = D_1 / sum(D_1..D_5) across bid and ask books.",
            signal_definition="R_bid surges from < 0.20 to > 0.60 within 3.0s while R_ask remains flat.",
            direction="Direction of concentrating side (BUY).",
            entry_condition="Taker fill at prevailing ask.",
            exit_condition="30.0s markout.",
            execution_model="Taker fill.",
            required_liquidity_usd=150.0,
            expected_holding_period_sec=30.0,
            main_falsification_test="Permuted depth level indices.",
            primary_failure_mode="Inside quote is fragile and quickly canceled upon arrival of adverse flow.",
            not_closed_family_proof="Measures multi-level depth migration ratio, not static imbalance (10A.7).",
        ),
        CandidateID.C9_REVERSAL_OF_EXHAUSTION: CandidateSpecification(
            candidate_id=CandidateID.C9_REVERSAL_OF_EXHAUSTION,
            name="Low-Volume Tick Rejection at Extremes",
            mechanism="Price touches an extreme boundary (p > 0.85 or p < 0.15) on minimal volume and fails to break through.",
            economic_rationale="Payoff asymmetry at extreme price levels causes retail momentum to stall on low volume; market makers push prices back towards the interior.",
            observable_inputs="Trade at p > 0.85 or p < 0.15 with volume < 0.2x 10-minute average trade size.",
            signal_definition="New extreme reached on volume < $25 followed by immediate quote pushback.",
            direction="Mean-reverting bounce away from extreme.",
            entry_condition="Taker order in bounce direction.",
            exit_condition="30.0s markout or 2-tick retreat.",
            execution_model="Taker order.",
            required_liquidity_usd=100.0,
            expected_holding_period_sec=30.0,
            main_falsification_test="Permuted price boundary thresholds.",
            primary_failure_mode="Low-volume push is followed by a large institutional breakout that sweeps through the extreme.",
            not_closed_family_proof="Volume exhaustion dynamics at price extremes, not sub-penny tick wedge (M2) or terminal payoff (10A.10).",
        ),
        CandidateID.C10_TRADE_SIZE_DISPARITY: CandidateSpecification(
            candidate_id=CandidateID.C10_TRADE_SIZE_DISPARITY,
            name="Institutional vs Retail Flow Divergence",
            mechanism="Divergence between large block trades (> $500) and consecutive retail micro-trades (< $15).",
            economic_rationale="Retail flow is noise-driven while large blocks reflect informed positioning; when a block opposes preceding micro-flow, the block dictates short-term direction.",
            observable_inputs="Trade sizes categorized into Large (> $500) vs Micro (< $15) over rolling 30s.",
            signal_definition="Large trade occurs in opposite direction of prior 5+ consecutive micro-trades.",
            direction="In direction of the large block trade.",
            entry_condition="Taker fill immediately following large trade.",
            exit_condition="30.0s markout.",
            execution_model="Taker fill.",
            required_liquidity_usd=100.0,
            expected_holding_period_sec=30.0,
            main_falsification_test="Randomized trade size classifications.",
            primary_failure_mode="Large trade causes immediate temporary market impact that reverts before markout.",
            not_closed_family_proof="Stratified size disparity dynamics, distinct from post-sweep recovery (M1) or static imbalance (10A.7).",
        ),
    }

    @classmethod
    def get_all_candidates(cls) -> Dict[CandidateID, CandidateSpecification]:
        return cls.CANDIDATES

    @classmethod
    def get_candidate(cls, cid: CandidateID) -> CandidateSpecification:
        return cls.CANDIDATES[cid]
