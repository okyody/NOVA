"""
NOVA Core Types
===============
All shared data models. Every package imports from here.
No circular deps — this file has zero internal imports.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Literal


# ─────────────────────────────────────────────
# Platform & Viewer primitives
# ─────────────────────────────────────────────

class Platform(str, Enum):
    BILIBILI  = "bilibili"
    DOUYIN    = "douyin"
    YOUTUBE   = "youtube"
    TWITCH    = "twitch"
    TIKTOK    = "tiktok"
    KUAISHOU  = "kuaishou"
    WECHAT    = "wechat"
    LOCAL     = "local"


@dataclass
class ViewerProfile:
    viewer_id: str
    platform:  Platform
    username:  str
    is_member: bool = False
    gift_total: float = 0.0        # cumulative gift value (CNY or USD)
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen:  datetime = field(default_factory=datetime.utcnow)
    tags: frozenset[str] = field(default_factory=frozenset)


# ─────────────────────────────────────────────
# Event taxonomy
# ─────────────────────────────────────────────

class EventType(str, Enum):
    # Incoming platform events
    CHAT_MESSAGE      = "platform.chat_message"
    GIFT_RECEIVED     = "platform.gift_received"
    VIEWER_JOIN       = "platform.viewer_join"
    SUPER_CHAT        = "platform.super_chat"
    FOLLOW            = "platform.follow"
    LIVE_STATS        = "platform.live_stats"

    # Perception layer outputs
    SEMANTIC_CLUSTER  = "perception.semantic_cluster"
    EMOTION_SIGNAL    = "perception.emotion_signal"
    CONTEXT_UPDATE    = "perception.context_update"
    SILENCE_DETECTED  = "perception.silence_detected"

    # Cognitive layer inter-agent messages
    AGENT_DECISION    = "cognitive.agent_decision"
    MEMORY_RECALL     = "cognitive.memory_recall"
    MEMORY_STORE      = "cognitive.memory_store"
    EMOTION_STATE     = "cognitive.emotion_state"
    PERSONALITY_HINT  = "cognitive.personality_hint"
    ACTION_PLAN       = "cognitive.action_plan"
    STREAM_TOKEN      = "cognitive.stream_token"      # LLM streaming token
    ORCHESTRATOR_OUT  = "cognitive.orchestrator_output"
    SAFE_OUTPUT       = "cognitive.safe_output"       # post-safety-guard

    # Generation layer outputs
    VOICE_CHUNK       = "generation.voice_chunk"
    AVATAR_COMMAND    = "generation.avatar_command"
    CONTENT_READY     = "generation.content_ready"

    # System events
    SAFETY_BLOCK      = "system.safety_block"
    HEALTH_CHECK      = "system.health_check"
    SHUTDOWN          = "system.shutdown"


class Priority(int, Enum):
    CRITICAL = 0    # safety blocks, shutdown
    HIGH     = 1    # super chats, gifts
    NORMAL   = 2    # regular chat
    LOW      = 3    # background tasks, stats


@dataclass
class NovaEvent:
    type:       EventType
    payload:    dict[str, Any]
    priority:   Priority    = Priority.NORMAL
    event_id:   str         = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  datetime    = field(default_factory=datetime.utcnow)
    source:     str         = "unknown"
    trace_id:   str | None  = None     # for request correlation

    def __lt__(self, other: object) -> bool:
        """Required for asyncio.PriorityQueue when priority+timestamp tie."""
        if not isinstance(other, NovaEvent):
            return NotImplemented
        return self.event_id < other.event_id


# ─────────────────────────────────────────────
# Emotion model — 2D valence/arousal space
# ─────────────────────────────────────────────

class EmotionLabel(str, Enum):
    EXCITED   = "excited"    # high valence, high arousal
    HAPPY     = "happy"      # high valence, low-mid arousal
    CALM      = "calm"       # neutral valence, low arousal
    CURIOUS   = "curious"    # slight positive, mid arousal
    SURPRISED = "surprised"  # neutral, high arousal
    SAD       = "sad"        # low valence, low arousal
    ANXIOUS   = "anxious"    # low valence, high arousal
    NEUTRAL   = "neutral"


@dataclass
class EmotionState:
    valence:  float       # -1.0 (negative) .. +1.0 (positive)
    arousal:  float       # 0.0 (calm) .. 1.0 (agitated)
    label:    EmotionLabel
    intensity: float      # 0.0 .. 1.0, overall strength
    triggered_by: str = ""

    @classmethod
    def neutral(cls) -> "EmotionState":
        return cls(valence=0.0, arousal=0.3, label=EmotionLabel.NEUTRAL, intensity=0.3)

    def to_prosody_params(self) -> dict[str, float]:
        """Map emotion → TTS prosody parameters."""
        return {
            "speaking_rate": 0.9 + self.arousal * 0.4,   # 0.9x..1.3x
            "pitch_shift":   self.valence * 1.5,           # semitones
            "energy":        0.7 + self.intensity * 0.6,
        }


# ─────────────────────────────────────────────
# Memory primitives
# ─────────────────────────────────────────────

@dataclass
class MemoryEntry:
    content:    str
    embedding:  list[float] | None = None
    memory_id:  str                = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime           = field(default_factory=datetime.utcnow)
    importance: float              = 0.5      # 0.0..1.0
    decay_rate: float              = 0.01     # per hour
    metadata:   dict[str, Any]    = field(default_factory=dict)

    def effective_importance(self, now: datetime) -> float:
        hours = (now - self.created_at).total_seconds() / 3600
        return self.importance * (1 - self.decay_rate) ** hours


# ─────────────────────────────────────────────
# Generation primitives
# ─────────────────────────────────────────────

@dataclass
class VoiceChunk:
    audio_bytes: bytes
    sample_rate: int   = 24000
    is_final:    bool  = False
    chunk_index: int   = 0
    trace_id:    str   = ""


@dataclass
class AvatarCommand:
    expression:   str           # e.g. "smile", "surprised", "talking"
    mouth_open:   float = 0.0   # 0..1
    eye_blink:    float = 0.0
    head_tilt:    float = 0.0   # degrees
    blend_time_ms: int = 100


@dataclass
class GenerationRequest:
    text:         str
    emotion:      EmotionState
    viewer:       ViewerProfile | None = None
    context_hint: str = ""
    trace_id:     str = field(default_factory=lambda: str(uuid.uuid4()))


# ─────────────────────────────────────────────
# Agent decision output
# ─────────────────────────────────────────────

class ActionType(str, Enum):
    RESPOND       = "respond"      # reply to viewer(s)
    INITIATE      = "initiate"     # proactive speech (no trigger)
    SING          = "sing"
    DRAW          = "draw"
    PLAY_GAME     = "play_game"
    SILENCE       = "silence"      # intentional pause
    TOPIC_SHIFT   = "topic_shift"


@dataclass
class AgentDecision:
    action:       ActionType
    text:         str | None        # generated response text
    confidence:   float             # 0..1
    agent_id:     str               # which agent produced this
    reasoning:    str = ""          # for logging/debug
    metadata:     dict[str, Any] = field(default_factory=dict)
