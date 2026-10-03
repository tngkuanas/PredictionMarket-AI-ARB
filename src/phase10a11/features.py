"""Deterministic Feature Table and Anti-Lookahead Validator for Phase 10A.11.

Constructs microstructure features strictly using information available at timestamp t.
Enforces the causal timeline: feature_ts <= signal_ts <= exec_ts.
Prevents any leakage of future prices, books, volumes, or resolution states.
"""

from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional, Any, Tuple
import math
import numpy as np


class LookaheadViolationError(Exception):
    """Raised when any feature or signal depends on future information."""
    pass


@dataclass
class MicrostructureFeatures:
    """Deterministic microstructure features at timestamp t."""
    timestamp: datetime.datetime
    market_id: str
    token_id: str
    best_bid: float
    best_ask: float
    midpoint: float
    spread: float
    spread_bps: float
    depth_bid_usd: float
    depth_ask_usd: float
    depth_imbalance: float
    liquidity_concentration: float
    trade_intensity_60s: int
    trade_volume_usd_60s: float
    trade_clustering_ratio: float
    price_velocity_30s: float
    price_acceleration_30s: float
    book_resiliency_ratio: float
    volume_regime: str  # "LOW", "MEDIUM", "HIGH"
    spread_regime: str  # "TIGHT", "NORMAL", "WIDE"
    time_to_expiry_sec: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": str(self.timestamp),
            "market_id": self.market_id,
            "token_id": self.token_id,
            "best_bid": round(self.best_bid, 4),
            "best_ask": round(self.best_ask, 4),
            "midpoint": round(self.midpoint, 4),
            "spread": round(self.spread, 4),
            "spread_bps": round(self.spread_bps, 2),
            "depth_bid_usd": round(self.depth_bid_usd, 2),
            "depth_ask_usd": round(self.depth_ask_usd, 2),
            "depth_imbalance": round(self.depth_imbalance, 4),
            "liquidity_concentration": round(self.liquidity_concentration, 4),
            "trade_intensity_60s": self.trade_intensity_60s,
            "trade_volume_usd_60s": round(self.trade_volume_usd_60s, 2),
            "trade_clustering_ratio": round(self.trade_clustering_ratio, 4),
            "price_velocity_30s": round(self.price_velocity_30s, 6),
            "price_acceleration_30s": round(self.price_acceleration_30s, 6),
            "book_resiliency_ratio": round(self.book_resiliency_ratio, 4),
            "volume_regime": self.volume_regime,
            "spread_regime": self.spread_regime,
            "time_to_expiry_sec": round(self.time_to_expiry_sec, 1) if self.time_to_expiry_sec is not None else None,
        }


class FeatureLookaheadValidator:
    """Automated validator ensuring absolute strict causality and zero future data leakage."""

    FORBIDDEN_LEAKAGE_KEYS = {
        "future_price",
        "future_midpoint",
        "future_ask",
        "future_bid",
        "future_volume",
        "outcome",
        "outcome_value",
        "resolution_value",
        "settlement_value",
        "terminal_payoff",
        "is_winner",
        "target_return",
        "forward_return",
    }

    def validate_causal_timeline(
        self,
        feature_timestamp: datetime.datetime,
        signal_timestamp: datetime.datetime,
        execution_timestamp: datetime.datetime,
    ) -> bool:
        """Validates feature_timestamp <= signal_timestamp <= execution_timestamp."""
        if feature_timestamp > signal_timestamp:
            raise LookaheadViolationError(
                f"Feature timestamp ({feature_timestamp}) > Signal timestamp ({signal_timestamp}). "
                "Feature was computed using future data relative to the signal!"
            )
        if signal_timestamp > execution_timestamp:
            raise LookaheadViolationError(
                f"Signal timestamp ({signal_timestamp}) > Execution timestamp ({execution_timestamp}). "
                "Execution occurred before signal was generated!"
            )
        return True

    def validate_feature_dictionary(
        self,
        feature_dict: Dict[str, Any],
        observation_timestamp: datetime.datetime,
    ) -> bool:
        """Validates that a feature dictionary contains no future or resolution leakage fields."""
        for key in feature_dict.keys():
            k_lower = key.lower()
            for forbidden in self.FORBIDDEN_LEAKAGE_KEYS:
                if forbidden in k_lower:
                    raise LookaheadViolationError(
                        f"Forbidden leakage key '{key}' found in feature dictionary! "
                        f"Matches prohibited keyword '{forbidden}'."
                    )
        return True

    def validate_dataset_chronology(
        self,
        observations: List[Dict[str, Any]],
        timestamp_key: str = "timestamp",
    ) -> bool:
        """Validates that a dataset is strictly sorted in chronological order."""
        prev_ts = None
        for i, obs in enumerate(observations):
            ts = obs[timestamp_key]
            if isinstance(ts, str):
                ts = datetime.datetime.fromisoformat(ts)
            if prev_ts is not None and ts < prev_ts:
                raise LookaheadViolationError(
                    f"Dataset chronology broken at index {i}: timestamp {ts} < previous {prev_ts}."
                )
            prev_ts = ts
        return True


class FeatureExtractor:
    """Computes point-in-time deterministic microstructure features from L2 order-book snapshots."""

    def __init__(self, validator: Optional[FeatureLookaheadValidator] = None):
        self.validator = validator or FeatureLookaheadValidator()

    def extract_features(
        self,
        current_snapshot: Dict[str, Any],
        past_snapshots_30s: List[Dict[str, Any]],
        past_trades_60s: List[Dict[str, Any]],
        contract_close_time: Optional[datetime.datetime] = None,
    ) -> MicrostructureFeatures:
        """Extracts microstructure features strictly using data <= current_snapshot['timestamp']."""
        now = current_snapshot["timestamp"]
        if isinstance(now, str):
            now = datetime.datetime.fromisoformat(now)

        # Validate past snapshots only contain past data
        for snap in past_snapshots_30s:
            snap_ts = snap["timestamp"]
            if isinstance(snap_ts, str):
                snap_ts = datetime.datetime.fromisoformat(snap_ts)
            if snap_ts > now:
                raise LookaheadViolationError(f"Past snapshot timestamp {snap_ts} > current timestamp {now}!")

        # Validate past trades only contain past data
        for tr in past_trades_60s:
            tr_ts = tr["receive_timestamp"]
            if isinstance(tr_ts, str):
                tr_ts = datetime.datetime.fromisoformat(tr_ts)
            if tr_ts > now:
                raise LookaheadViolationError(f"Past trade timestamp {tr_ts} > current timestamp {now}!")

        best_bid = float(current_snapshot.get("best_bid", 0.0) or 0.0)
        best_ask = float(current_snapshot.get("best_ask", 0.0) or 0.0)
        midpoint = float(current_snapshot.get("midpoint", (best_bid + best_ask) / 2.0 if (best_bid + best_ask) > 0 else 0.5))
        spread = float(current_snapshot.get("spread", max(0.0, best_ask - best_bid)))
        spread_bps = float(current_snapshot.get("spread_bps", (spread / midpoint * 10000.0) if midpoint > 0 else 0.0))

        depth_bid = float(current_snapshot.get("depth_bid_usd", 0.0) or 0.0)
        depth_ask = float(current_snapshot.get("depth_ask_usd", 0.0) or 0.0)
        total_depth = depth_bid + depth_ask
        depth_imbalance = (depth_bid - depth_ask) / total_depth if total_depth > 0 else 0.0

        # Liquidity concentration: top-level depth relative to total
        top_bid_val = 0.0
        top_ask_val = 0.0
        bids = current_snapshot.get("bids", [])
        asks = current_snapshot.get("asks", [])
        if isinstance(bids, list) and len(bids) > 0:
            top_bid_val = float(bids[0].get("size", 0.0) or 0.0) * float(bids[0].get("price", 0.0) or 0.0)
        if isinstance(asks, list) and len(asks) > 0:
            top_ask_val = float(asks[0].get("size", 0.0) or 0.0) * float(asks[0].get("price", 0.0) or 0.0)
        top_depth = top_bid_val + top_ask_val
        liquidity_concentration = top_depth / total_depth if total_depth > 0 else 1.0

        # Trade intensity & volume in last 60s
        trade_intensity = len(past_trades_60s)
        trade_volume = sum(float(t.get("size_usd", 0.0) or 0.0) for t in past_trades_60s)

        # Trade clustering: variance to mean ratio of trade arrival deltas
        if len(past_trades_60s) >= 3:
            trade_times = []
            for t in past_trades_60s:
                tts = t["receive_timestamp"]
                if isinstance(tts, str):
                    tts = datetime.datetime.fromisoformat(tts)
                trade_times.append(tts.timestamp())
            trade_times.sort()
            deltas = np.diff(trade_times)
            mean_d = float(np.mean(deltas)) if len(deltas) > 0 else 0.0
            var_d = float(np.var(deltas)) if len(deltas) > 0 else 0.0
            clustering_ratio = (var_d / mean_d) if mean_d > 0 else 1.0
        else:
            clustering_ratio = 1.0

        # Price velocity and acceleration over last 30s
        if past_snapshots_30s:
            oldest_snap = past_snapshots_30s[0]
            old_mid = float(oldest_snap.get("midpoint", midpoint))
            old_ts = oldest_snap["timestamp"]
            if isinstance(old_ts, str):
                old_ts = datetime.datetime.fromisoformat(old_ts)
            dt = max(1.0, (now - old_ts).total_seconds())
            velocity = (midpoint - old_mid) / dt

            # Acceleration from midpoint of middle snapshot
            mid_idx = len(past_snapshots_30s) // 2
            mid_snap = past_snapshots_30s[mid_idx]
            mid_mid = float(mid_snap.get("midpoint", midpoint))
            mid_ts = mid_snap["timestamp"]
            if isinstance(mid_ts, str):
                mid_ts = datetime.datetime.fromisoformat(mid_ts)
            dt1 = max(1.0, (mid_ts - old_ts).total_seconds())
            dt2 = max(1.0, (now - mid_ts).total_seconds())
            v1 = (mid_mid - old_mid) / dt1
            v2 = (midpoint - mid_mid) / dt2
            acceleration = (v2 - v1) / ((dt1 + dt2) / 2.0)
        else:
            velocity = 0.0
            acceleration = 0.0

        # Book resiliency: post-trade depth recovery ratio
        # If recent trades occurred, ratio of current depth to pre-trade depth
        if past_trades_60s and past_snapshots_30s:
            pre_depth = float(past_snapshots_30s[0].get("depth_bid_usd", depth_bid) + past_snapshots_30s[0].get("depth_ask_usd", depth_ask))
            resiliency = total_depth / pre_depth if pre_depth > 0 else 1.0
        else:
            resiliency = 1.0

        # Regimes
        volume_regime = "HIGH" if trade_volume > 500 else ("MEDIUM" if trade_volume > 50 else "LOW")
        spread_regime = "TIGHT" if spread_bps < 200 else ("WIDE" if spread_bps > 800 else "NORMAL")

        # Time to expiry
        tte_sec = None
        if contract_close_time is not None:
            tte_sec = max(0.0, (contract_close_time - now).total_seconds())

        feat = MicrostructureFeatures(
            timestamp=now,
            market_id=current_snapshot.get("market_id", ""),
            token_id=current_snapshot.get("token_id", ""),
            best_bid=best_bid,
            best_ask=best_ask,
            midpoint=midpoint,
            spread=spread,
            spread_bps=spread_bps,
            depth_bid_usd=depth_bid,
            depth_ask_usd=depth_ask,
            depth_imbalance=depth_imbalance,
            liquidity_concentration=liquidity_concentration,
            trade_intensity_60s=trade_intensity,
            trade_volume_usd_60s=trade_volume,
            trade_clustering_ratio=clustering_ratio,
            price_velocity_30s=velocity,
            price_acceleration_30s=acceleration,
            book_resiliency_ratio=resiliency,
            volume_regime=volume_regime,
            spread_regime=spread_regime,
            time_to_expiry_sec=tte_sec,
        )

        # Validate anti-lookahead on the generated feature dictionary
        self.validator.validate_feature_dictionary(feat.to_dict(), now)
        return feat
