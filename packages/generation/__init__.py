"""
NOVA Generation Module
======================
Voice pipeline, TTS backends, lip sync, avatar driver, SD client.
"""
from packages.generation.voice_pipeline import VoicePipeline, TTSBackend, EdgeTTSBackend, CosyVoice2Backend, ProsodyParams
from packages.generation.tts_factory import TTSFallbackChain, create_tts_backend
from packages.generation.lip_sync import LipSyncEngine
from packages.generation.avatar_driver import AvatarDriver
from packages.generation.sd_client import SDClient

__all__ = [
    # Voice
    "VoicePipeline", "TTSBackend", "EdgeTTSBackend", "CosyVoice2Backend", "ProsodyParams",
    # TTS factory
    "TTSFallbackChain", "create_tts_backend",
    # Lip sync
    "LipSyncEngine",
    # Avatar
    "AvatarDriver",
    # SD
    "SDClient",
]
