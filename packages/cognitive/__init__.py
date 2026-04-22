"""
NOVA Cognitive Module
=====================
Emotion, memory, personality agents + orchestrator + NLU + tool calling.
"""
from packages.cognitive.emotion_agent import EmotionAgent
from packages.cognitive.memory_agent import MemoryAgent, WorkingMemory, EpisodicMemory, ViewerGraph
from packages.cognitive.personality_agent import PersonalityAgent, CharacterCard
from packages.cognitive.orchestrator import Orchestrator, LLMClient
from packages.cognitive.nlu import IntentClassifier, IntentType
from packages.cognitive.tool_calling import ToolRegistry, ToolExecutor, ToolDefinition, create_builtin_tools
from packages.cognitive.proactive import ProactiveIntelligence, ProactiveStrategy
from packages.cognitive.memory_consolidation import MemoryConsolidator
from packages.cognitive.state_persistence import (
    StateManager, JSONFileBackend, RedisBackend, create_persistence_backend,
)

__all__ = [
    # Agents
    "EmotionAgent", "MemoryAgent", "PersonalityAgent", "Orchestrator", "LLMClient",
    # Memory
    "WorkingMemory", "EpisodicMemory", "ViewerGraph", "CharacterCard",
    # NLU
    "IntentClassifier", "IntentType",
    # Tools
    "ToolRegistry", "ToolExecutor", "ToolDefinition", "create_builtin_tools",
    # Proactive
    "ProactiveIntelligence", "ProactiveStrategy",
    # Consolidation
    "MemoryConsolidator",
    # State persistence
    "StateManager", "JSONFileBackend", "RedisBackend", "create_persistence_backend",
]
