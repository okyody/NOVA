"""
NOVA Perception Module
======================
Semantic aggregation, silence detection, and context sensing.
"""
from packages.perception.semantic_aggregator import SemanticAggregator
from packages.perception.silence_detector import SilenceDetector
from packages.perception.context_sensor import ContextSensor, HeatLevel, StreamContext

__all__ = [
    "SemanticAggregator", "SilenceDetector",
    "ContextSensor", "HeatLevel", "StreamContext",
]
