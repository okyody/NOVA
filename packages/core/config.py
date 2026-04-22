"""
NOVA Configuration
==================
Pydantic-based configuration with env var override, type validation,
and secret management. The single source of truth for all settings.

Priority: Environment variables > .env file > config JSON > defaults
All NOVA_* env vars are auto-mapped via pydantic-settings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─── Sub-configs ─────────────────────────────────────────────────────────────

class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_LLM_")

    base_url: str = "http://localhost:11434/v1"
    api_key: SecretStr = SecretStr("ollama")
    model: str = "qwen2.5:14b"
    timeout: float = 30.0
    max_tokens: int = 150
    temperature: float = 0.85

    @field_validator("temperature")
    @classmethod
    def clamp_temperature(cls, v: float) -> float:
        return max(0.0, min(2.0, v))


class VoiceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_VOICE_")

    backend: Literal[
        "edge_tts", "cosyvoice2", "gpt_sovits", "azure", "elevenlabs"
    ] = "edge_tts"
    voice_id: str = "zh-CN-XiaoyiNeural"
    cosyvoice2_url: str = "http://localhost:7860"
    azure_region: str = "eastasia"
    azure_api_key: SecretStr = SecretStr("")
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    gpt_sovits_url: str = "http://localhost:9880"
    fallback_chain: list[str] = Field(
        default_factory=lambda: ["edge_tts"]
    )


class CharacterConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_CHARACTER_")

    path: str = ""


class KnowledgeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_KNOWLEDGE_")

    enabled: bool = False
    embedding_backend: Literal["ollama", "openai"] = "ollama"
    embedding_base_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_api_key: SecretStr = SecretStr("")
    vector_backend: Literal["memory", "qdrant"] = "memory"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "nova_knowledge"
    chunk_size: int = 512
    chunk_overlap: int = 64
    retrieval_top_k: int = 3
    retrieval_score_threshold: float = 0.25


class NLUConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_NLU_")

    enabled: bool = True
    llm_based: bool = False
    confidence_threshold: float = 0.6


class ToolsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_TOOLS_")

    enabled: bool = True
    max_rounds: int = 2
    require_audit: bool = True


class ConsolidationConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_CONSOLIDATION_")

    enabled: bool = True
    interval_s: int = 300
    min_entries: int = 20


class PerceptionConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_PERCEPTION_")

    aggregator_window_ms: int = 300
    silence_threshold_s: int = 30
    context_update_s: int = 10


class SafetyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_SAFETY_")

    enabled: bool = True
    semantic_check_rate: float = 0.05
    block_patterns: list[str] = Field(default_factory=list)
    warn_patterns: list[str] = Field(default_factory=list)


class AvatarConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_AVATAR_")

    enabled: bool = False
    ws_port: int = 8767
    driver: Literal["web", "vtube_studio"] = "web"


class PersistenceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_PERSIST_")

    enabled: bool = False
    backend: Literal["json", "redis"] = "json"
    base_dir: str = "data/state"
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0
    redis_ttl: int = 604800  # 7 days
    auto_save_interval_s: int = 300


class ResilienceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_RESILIENCE_")

    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_s: float = 30.0
    health_check_interval_s: int = 30


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_AUTH_")

    enabled: bool = False
    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    api_key: SecretStr = SecretStr("")  # simple API key auth
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8765"]
    )


class ObservabilityConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_OBSERVABILITY_")

    metrics_enabled: bool = True
    tracing_enabled: bool = False
    tracing_endpoint: str = "http://localhost:4317"  # OTLP gRPC
    tracing_service_name: str = "nova"
    log_level: str = "INFO"
    log_json: bool = False
    log_file: str | None = None


class PlatformConfig(BaseSettings):
    """Single platform connection config."""
    model_config = SettingsConfigDict(env_prefix="NOVA_PLATFORM_")

    platform: str = "bilibili"
    room_id: int = 0
    token: SecretStr = SecretStr("")
    uid: int = 0
    app_id: str = ""
    app_secret: SecretStr = SecretStr("")


# ─── Top-level Settings ──────────────────────────────────────────────────────

class NovaSettings(BaseSettings):
    """
    Top-level NOVA configuration.

    Priority: Environment variables > .env file > config JSON > defaults
    All NOVA_* env vars are auto-mapped.
    Nested config uses __ delimiter, e.g. NOVA_LLM__BASE_URL.
    """
    model_config = SettingsConfigDict(
        env_prefix="NOVA_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Core
    config_path: Path = Field(default=Path("nova.config.json"), alias="CONFIG")
    port: int = 8765
    debug: bool = False

    # Sub-configs
    llm: LLMConfig = Field(default_factory=LLMConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    character: CharacterConfig = Field(default_factory=CharacterConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    # Platforms (list — configured via JSON, not env vars)
    platforms: list[PlatformConfig] = Field(default_factory=list)

    @field_validator("port")
    @classmethod
    def valid_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be 1-65535, got {v}")
        return v


# ─── Loading ──────────────────────────────────────────────────────────────────

def load_settings(config_path: str | Path | None = None) -> NovaSettings:
    """
    Load settings from:
      1. Environment variables (highest priority)
      2. .env file
      3. JSON config file
      4. Defaults (lowest priority)
    """
    path = Path(config_path) if config_path else Path(
        os.environ.get("NOVA_CONFIG", "nova.config.json")
    )

    kwargs: dict[str, Any] = {}

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            # Flatten nested dicts for pydantic-settings _env parsing
            kwargs = _flatten_config(raw)
        except (json.JSONDecodeError, OSError) as e:
            import logging
            logging.getLogger("nova.config").warning("Failed to load %s: %s", path, e)

    return NovaSettings(**kwargs)


def _flatten_config(raw: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict for pydantic model init. Only top-level keys are used."""
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and key in (
            "llm", "voice", "character", "knowledge", "nlu", "tools",
            "consolidation", "perception", "safety", "avatar",
            "persistence", "resilience", "auth", "observability",
        ):
            result[key] = value
        else:
            result[key] = value
    return result
