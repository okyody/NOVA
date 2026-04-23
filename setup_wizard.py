"""Interactive setup wizard for NOVA."""

from __future__ import annotations

import json
from pathlib import Path


def prompt(prompt_text: str, default: str = "") -> str:
    if default:
        result = input(f"{prompt_text} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt_text}: ").strip()


def yes_no(prompt_text: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    result = input(f"{prompt_text} [{default_str}]: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def run_wizard() -> dict:
    print("== NOVA setup wizard ==")
    print()

    config: dict = {}

    print("[LLM]")
    config["llm"] = {
        "base_url": prompt("LLM API URL", "http://localhost:11434/v1"),
        "api_key": prompt("API key", "ollama"),
        "model": prompt("Model", "qwen2.5:14b"),
        "timeout": 30.0,
        "max_tokens": 150,
        "temperature": 0.85,
    }
    print()

    print("[Voice]")
    config["voice"] = {
        "backend": prompt("TTS backend", "edge_tts"),
        "voice_id": prompt("Voice ID", "zh-CN-XiaoyiNeural"),
        "fallback_chain": ["edge_tts"],
        "cosyvoice2_url": "http://localhost:7860",
        "gptsovits_url": "http://localhost:9880",
        "voices_dir": "voices",
        "speaker": "nova",
        "azure_region": "eastasia",
        "azure_api_key": "",
        "elevenlabs_api_key": "",
        "elevenlabs_voice_id": "",
    }
    print()

    print("[Character]")
    config["character"] = {
        "path": prompt("Character card path", "characters/nova_default.toml"),
    }
    print()

    print("[Knowledge]")
    kb_enabled = yes_no("Enable knowledge base?", False)
    config["knowledge"] = {
        "enabled": kb_enabled,
        "embedding_backend": prompt("Embedding backend", "ollama"),
        "embedding_base_url": prompt("Embedding API URL", "http://localhost:11434"),
        "embedding_model": prompt("Embedding model", "nomic-embed-text"),
        "embedding_api_key": "",
        "vector_backend": prompt("Vector store backend", "memory"),
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "nova_knowledge",
        "chunk_size": 512,
        "chunk_overlap": 64,
        "retrieval_top_k": 3,
        "retrieval_score_threshold": 0.25,
    }
    print()

    print("[Platforms]")
    platforms = []

    if yes_no("Add Bilibili?", False):
        platforms.append({
            "platform": "bilibili",
            "room_id": int(prompt("Room ID", "0")),
            "token": prompt("Access token", ""),
            "uid": int(prompt("UID", "0")),
        })

    if yes_no("Add Douyin?", False):
        platforms.append({
            "platform": "douyin",
            "room_id": prompt("Room ID", ""),
            "app_id": prompt("App ID", ""),
            "app_secret": prompt("App Secret", ""),
            "webhook_port": 8766,
        })

    if yes_no("Add YouTube Live?", False):
        platforms.append({
            "platform": "youtube",
            "live_chat_id": prompt("Live Chat ID", ""),
            "api_key": prompt("API Key", ""),
            "poll_interval": 3.0,
        })

    if yes_no("Add Twitch?", False):
        platforms.append({
            "platform": "twitch",
            "channel": prompt("Channel name", ""),
            "oauth_token": prompt("OAuth token", ""),
            "username": prompt("Bot username", "nova_bot"),
        })

    if yes_no("Add Kuaishou?", False):
        platforms.append({
            "platform": "kuaishou",
            "room_id": prompt("Room ID", ""),
            "token": prompt("Access token", ""),
            "app_id": prompt("App ID", ""),
            "app_secret": prompt("App Secret", ""),
        })

    if yes_no("Add WeChat?", False):
        platforms.append({
            "platform": "wechat",
            "room_id": prompt("Room ID", ""),
            "app_id": prompt("App ID", ""),
            "app_secret": prompt("App Secret", ""),
            "mode": prompt("Mode", "polling"),
        })

    config["platforms"] = platforms
    print()

    config["avatar"] = {
        "enabled": yes_no("Enable avatar?", False),
        "ws_port": 8767,
        "driver": "web",
    }
    config["perception"] = {
        "aggregator_window_ms": 300,
        "silence_threshold_s": 30,
        "context_update_s": 10,
    }
    config["nlu"] = {"enabled": True, "llm_based": False, "confidence_threshold": 0.6}
    config["tools"] = {"enabled": True, "max_rounds": 2, "require_audit": True}
    config["consolidation"] = {"enabled": True, "interval_s": 300, "min_entries": 20}
    config["safety"] = {
        "enabled": True,
        "semantic_check_rate": 0.05,
        "block_patterns": [],
        "warn_patterns": [],
    }
    config["persistence"] = {
        "enabled": False,
        "backend": "json",
        "base_dir": "data/state",
        "redis_url": "redis://localhost:6379",
        "redis_db": 0,
        "redis_ttl": 604800,
        "auto_save_interval_s": 300,
    }
    config["resilience"] = {
        "circuit_breaker_enabled": True,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_recovery_s": 30.0,
        "health_check_interval_s": 30,
    }
    config["auth"] = {
        "enabled": False,
        "jwt_secret": "change-me-in-production",
        "jwt_algorithm": "HS256",
        "jwt_expire_minutes": 1440,
        "api_key": "",
        "allowed_origins": ["http://localhost:3000", "http://localhost:8765"],
    }
    config["observability"] = {
        "metrics_enabled": True,
        "tracing_enabled": False,
        "tracing_endpoint": "http://localhost:4317",
        "tracing_service_name": "nova",
        "log_level": "INFO",
        "log_json": False,
        "log_file": None,
    }

    return config


def main() -> None:
    config = run_wizard()
    output_path = Path("nova.config.json")
    output_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"Configuration saved to {output_path}")
    print("Next steps:")
    print("  1. ollama pull qwen2.5:14b")
    print("  2. python -m apps.nova_server.main")
    print("  3. curl http://127.0.0.1:8765/health")


if __name__ == "__main__":
    main()
