"""Statistical and quantitative validation package."""
from src.statistics.falsification_engine import HypothesisFalsificationEngine
from src.statistics.multiple_testing import benjamini_hochberg_correction, PipelineFunnelAuditor

__all__ = ["HypothesisFalsificationEngine", "benjamini_hochberg_correction", "PipelineFunnelAuditor"]
