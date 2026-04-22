"""
NOVA Platform Module
====================
Multi-platform adapters + platform manager.
"""
from packages.platform.adapters import BaseAdapter, BilibiliAdapter, create_adapter
from packages.platform.manager import PlatformManager

__all__ = [
    "BaseAdapter", "BilibiliAdapter", "create_adapter",
    "PlatformManager",
]
