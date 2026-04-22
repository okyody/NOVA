"""
NOVA Setup Wizard
=================
Interactive configuration wizard that runs on first launch.
Helps users set up LLM, voice, and platform configuration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def prompt(prompt_text: str, default: str = "") -> str:
    """Prompt user for input with a default value."""
    if default:
        result = input(f"{prompt_text} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt_text}: ").strip()


def yes_no(prompt_text: str, default: bool = True) -> bool:
    """Prompt for yes/no answer."""
    default_str = "Y/n" if default else "y/N"
    result = input(f"{prompt_text} [{default_str}]: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes", "是")


def run_wizard() -> dict:
    """Run the interactive setup wizard."""
    print("═══════════════════════════════════")
    print("  NOVA — Setup Wizard")
    print("═══════════════════════════════════")
    print()

    config = {}

    # LLM Configuration
    print("── LLM Configuration ──")
    print("NOVA requires an OpenAI-compatible LLM API (Ollama, OpenAI, etc.)")
    config["llm"] = {
        "base_url": prompt("LLM API URL", "http://localhost:11434/v1"),
        "api_key":  prompt("API Key", "ollama"),
        "model":    prompt("Model name", "qwen2.5:14b"),
    }
    print()

    # Voice Configuration
    print("── Voice Configuration ──")
    config["voice"] = {
        "backend":  prompt("TTS Backend (edge_tts/cosyvoice2/gptsovits)", "edge_tts"),
        "voice_id": prompt("Voice ID", "zh-CN-XiaoyiNeural"),
    }
    print()

    # Character
    print("── Character Configuration ──")
    char_path = prompt("Character card path (leave empty for default)", "")
    config["character"] = {"path": char_path}
    print()

    # Knowledge Base
    print("── Knowledge Base (RAG) ──")
    kb_enabled = yes_no("Enable knowledge base?", default=False)
    config["knowledge"] = {
        "enabled": kb_enabled,
        "embedding": {
            "backend": prompt("Embedding backend (ollama/openai)", "ollama"),
            "base_url": prompt("Embedding API URL", "http://localhost:11434"),
            "model": prompt("Embedding model", "nomic-embed-text"),
        },
        "vector_store": {
            "backend": prompt("Vector store (memory/qdrant)", "memory"),
        },
    }
    print()

    # Platform Configuration
    print("── Platform Configuration ──")
    platforms = []

    if yes_no("Add Bilibili live room?", default=False):
        platforms.append({
            "platform": "bilibili",
            "room_id": int(prompt("Room ID", "0")),
            "token": prompt("Access token", ""),
            "uid": int(prompt("UID", "0")),
        })

    if yes_no("Add Douyin live room?", default=False):
        platforms.append({
            "platform": "douyin",
            "room_id": prompt("Room ID", ""),
            "app_id": prompt("App ID", ""),
            "app_secret": prompt("App Secret", ""),
        })

    if yes_no("Add YouTube Live?", default=False):
        platforms.append({
            "platform": "youtube",
            "live_chat_id": prompt("Live Chat ID", ""),
            "api_key": prompt("API Key", ""),
        })

    if yes_no("Add Twitch?", default=False):
        platforms.append({
            "platform": "twitch",
            "channel": prompt("Channel name", ""),
            "oauth_token": prompt("OAuth token", ""),
            "username": prompt("Bot username", "nova_bot"),
        })

    config["platforms"] = platforms
    print()

    # Avatar
    config["avatar"] = {
        "enabled": yes_no("Enable Live2D avatar?", default=False),
        "ws_port": 8767,
    }

    # Ops
    config["ops"] = {
        "safety": {"enabled": True, "semantic_check_rate": 0.05},
        "metrics_port": 9090,
        "log_level": "INFO",
    }

    # Perception
    config["perception"] = {
        "aggregator_window_ms": 300,
        "silence_threshold_s": 30,
        "context_update_s": 10,
    }

    # NLU / Tools / Consolidation
    config["nlu"] = {"enabled": True}
    config["tools"] = {"enabled": True}
    config["consolidation"] = {"enabled": True}

    # Lipsync
    config["lipsync"] = {"enabled": True}

    return config


def main() -> None:
    config = run_wizard()

    output_path = Path("nova.config.json")
    output_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("═══════════════════════════════════")
    print(f"  Configuration saved to {output_path}")
    print("═══════════════════════════════════")
    print()
    print("Next steps:")
    print("  1. Start Ollama:  ollama pull qwen2.5:14b")
    print("  2. Start NOVA:    python -m apps.nova_server.main")


if __name__ == "__main__":
    main()
