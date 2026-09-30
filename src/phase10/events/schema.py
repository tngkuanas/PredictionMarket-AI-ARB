"""Information Latency Event Schema.
Strict Pydantic models for real-world information events, source hierarchies,
temporal boundaries, and bounded forecast distributions.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


class SourceType(str, Enum):
    OFFICIAL_PRIMARY = "official_primary"          # Government agencies (BLS, BEA), official Fed press release, SEC EDGAR
    REGULATORY_GOVERNMENT = "regulatory_gov"        # Statutory registers, regulatory notices, executive orders
    OFFICIAL_INSTITUTIONAL = "official_inst"       # Official election commission tallies, central bank statements
    DIRECT_STATEMENT = "direct_statement"          # Direct verified press conferences
    HIGH_QUALITY_NEWSWIRE = "high_quality_wire"    # Bloomberg, Reuters, AP
    MAJOR_NEWS = "major_news"                      # FT, WSJ, NYT, BBC
    SECONDARY_AGGREGATOR = "secondary_aggregator"  # Aggregators, secondary terminal feeds
    SOCIAL_MEDIA = "social_media"                  # Social media, unverified rumors


class EventDirection(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    UNCERTAIN = "uncertain"


class ImpactDistribution(BaseModel):
    """Bounded forecast distribution for probability impact rather than a single point value."""
    model_config = ConfigDict(frozen=True)

    impact_point: float = Field(..., description="Point estimate of probability impact in [-1.0, 1.0]")
    impact_lower: float = Field(..., description="Lower bound of probability impact in [-1.0, 1.0]")
    impact_upper: float = Field(..., description="Upper bound of probability impact in [-1.0, 1.0]")
    impact_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in forecast distribution [0.0, 1.0]")
    impact_horizon_seconds: float = Field(..., gt=0.0, description="Expected time-to-reprice horizon in seconds")

    @model_validator(mode="after")
    def validate_bounds(self) -> "ImpactDistribution":
        if not (-1.0 <= self.impact_lower <= 1.0):
            raise ValueError(f"impact_lower must be in [-1.0, 1.0], got {self.impact_lower}")
        if not (-1.0 <= self.impact_upper <= 1.0):
            raise ValueError(f"impact_upper must be in [-1.0, 1.0], got {self.impact_upper}")
        if not (-1.0 <= self.impact_point <= 1.0):
            raise ValueError(f"impact_point must be in [-1.0, 1.0], got {self.impact_point}")
        if not (self.impact_lower <= self.impact_point <= self.impact_upper):
            raise ValueError(
                f"Impact distribution order violated: impact_lower ({self.impact_lower}) <= "
                f"impact_point ({self.impact_point}) <= impact_upper ({self.impact_upper}) must hold"
            )
        return self


class InformationEvent(BaseModel):
    """Immutable, fully-auditable real-world information event."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., min_length=5, description="Immutable unique identifier for the event")
    timestamp_publication: datetime = Field(..., description="UTC timestamp of official source publication")
    timestamp_extraction: datetime = Field(..., description="UTC timestamp when system observed/extracted information")
    source: str = Field(..., min_length=2, description="Source organization or publishing body")
    source_type: SourceType = Field(..., description="Categorical source hierarchy tier")
    source_reliability: float = Field(..., ge=0.0, le=1.0, description="Source reliability score [0.0, 1.0]")
    event_type: str = Field(..., min_length=2, description="Event classification (e.g. macro_indicator, court_ruling)")
    title: str = Field(..., min_length=5, description="Event headline or summary")
    raw_content: str = Field(..., min_length=5, description="Full statement or raw publication text")
    entities: List[str] = Field(..., min_length=1, description="Normalized entities involved in the event")
    direction: EventDirection = Field(..., description="Directional impulse on affected probability")
    impact_distribution: ImpactDistribution = Field(..., description="Bounded probability impact distribution")
    mechanism: str = Field(..., min_length=5, description="Causal / economic transmission mechanism")
    invalidation_conditions: List[str] = Field(default_factory=list, description="Conditions that falsify this event's impact")
    resolution_relevance: float = Field(..., ge=0.0, le=1.0, description="Degree to which event directly resolves contract [0.0, 1.0]")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Audit and provenance metadata")

    @field_validator("timestamp_publication", "timestamp_extraction")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_temporal_causality(self) -> "InformationEvent":
        if self.timestamp_extraction < self.timestamp_publication:
            raise ValueError(
                f"Temporal causality violation: extraction timestamp ({self.timestamp_extraction}) "
                f"cannot precede publication timestamp ({self.timestamp_publication})"
            )
        return self

    @property
    def information_latency_seconds(self) -> float:
        """Measure information latency: t_market_observation - t_source_publication."""
        return (self.timestamp_extraction - self.timestamp_publication).total_seconds()
