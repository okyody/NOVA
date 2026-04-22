"""
NOVA Core Module
================
Event bus, type system, configuration, and structured logging.
"""
from packages.core.types import (
    ActionType,
    AgentDecision,
    AvatarCommand,
    EmotionLabel,
    EmotionState,
    EventType,
    GenerationRequest,
    MemoryEntry,
    NovaEvent,
    Platform,
    Priority,
    ViewerProfile,
    VoiceChunk,
)
from packages.core.event_bus import EventBus
from packages.core.config import NovaSettings, load_settings
from packages.core.logger import get_logger, setup_logging, bind_trace_id

__all__ = [
    # Types
    "ActionType", "AgentDecision", "AvatarCommand", "EmotionLabel", "EmotionState",
    "EventType", "GenerationRequest", "MemoryEntry", "NovaEvent", "Platform",
    "Priority", "ViewerProfile", "VoiceChunk",
    # Core
    "EventBus", "NovaSettings", "load_settings",
    # Logger
    "get_logger", "setup_logging", "bind_trace_id",
]
