"""
NOVA Backup & Recovery Tool
============================
CLI tool for backing up and restoring NOVA state.

Usage:
    python -m deploy.tools.backup --action backup [--output nova_backup_20260422.tar.gz]
    python -m deploy.tools.backup --action restore --input nova_backup_20260422.tar.gz
    python -m deploy.tools.backup --action schedule --interval 3600 --output /backups/nova_auto.tar.gz
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)s │ %(message)s")
log = logging.getLogger("nova.backup")


# ─── Backup ──────────────────────────────────────────────────────────────────

def create_backup(
    output_path: str = "",
    state_dir: str = "data/state",
    knowledge_dir: str = "knowledge",
    characters_dir: str = "characters",
    config_path: str = "nova.config.json",
) -> str:
    """
    Create a backup archive of NOVA state.

    Includes: state persistence, knowledge docs, character cards, config.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if not output_path:
        output_path = f"nova_backup_{timestamp}.tar.gz"

    log.info("Creating backup: %s", output_path)

    with tarfile.open(output_path, "w:gz") as tar:
        # State persistence data
        if Path(state_dir).exists():
            tar.add(state_dir, arcname="state")
            log.info("  Added: %s/", state_dir)

        # Knowledge documents
        if Path(knowledge_dir).exists():
            tar.add(knowledge_dir, arcname="knowledge")
            log.info("  Added: %s/", knowledge_dir)

        # Character cards
        if Path(characters_dir).exists():
            tar.add(characters_dir, arcname="characters")
            log.info("  Added: %s/", characters_dir)

        # Configuration
        if Path(config_path).exists():
            tar.add(config_path, arcname="config/nova.config.json")
            log.info("  Added: %s", config_path)

        # Metadata
        metadata = {
            "version": "2.0.0",
            "timestamp": timestamp,
            "created_by": "nova_backup_tool",
        }
        meta_bytes = json.dumps(metadata, indent=2).encode("utf-8")
        import io
        meta_file = tarfile.TarInfo(name="backup_metadata.json")
        meta_file.size = len(meta_bytes)
        tar.addfile(meta_file, io.BytesIO(meta_bytes))

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    log.info("Backup created: %s (%.1f MB)", output_path, size_mb)
    return output_path


# ─── Restore ─────────────────────────────────────────────────────────────────

def restore_backup(
    input_path: str,
    state_dir: str = "data/state",
    knowledge_dir: str = "knowledge",
    characters_dir: str = "characters",
    config_path: str = "nova.config.json",
    dry_run: bool = False,
) -> None:
    """
    Restore NOVA state from a backup archive.

    Args:
        dry_run: If True, list contents without extracting.
    """
    if not Path(input_path).exists():
        raise FileNotFoundError(f"Backup file not found: {input_path}")

    log.info("Restoring from backup: %s", input_path)

    with tarfile.open(input_path, "r:gz") as tar:
        if dry_run:
            log.info("Dry run — contents:")
            for member in tar.getmembers():
                log.info("  %s (%d bytes)", member.name, member.size)
            return

        # Validate metadata
        try:
            meta_file = tar.extractfile("backup_metadata.json")
            if meta_file:
                metadata = json.loads(meta_file.read().decode("utf-8"))
                log.info("Backup version: %s, created: %s",
                         metadata.get("version", "?"), metadata.get("timestamp", "?"))
        except KeyError:
            log.warning("No metadata in backup")

        # Backup current state before overwriting
        if Path(state_dir).exists():
            backup_current = f"{state_dir}_pre_restore_{int(time.time())}"
            shutil.copytree(state_dir, backup_current)
            log.info("Current state backed up to: %s", backup_current)

        # Extract
        tar.extractall(path=".", filter="data")
        log.info("Backup restored successfully")


# ─── Qdrant Backup ───────────────────────────────────────────────────────────

async def backup_qdrant(url: str = "http://localhost:6333", collection: str = "nova_knowledge") -> dict[str, Any]:
    """Trigger a Qdrant snapshot backup via API."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{url}/collections/{collection}/snapshots")
        resp.raise_for_status()
        result = resp.json()
        log.info("Qdrant snapshot created: %s", result.get("result", {}).get("name", "?"))
        return result


# ─── Redis Backup ────────────────────────────────────────────────────────────

async def backup_redis(url: str = "redis://localhost:6379") -> str:
    """Trigger Redis BGSAVE and return the RDB file path."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(url)
        await client.bgsave()
        info = await client.info("persistence")
        rdb_path = info.get("rdb_last_bgsave_status", "unknown")
        await client.close()
        log.info("Redis BGSAVE triggered, status: %s", rdb_path)
        return rdb_path
    except ImportError:
        log.warning("redis.asyncio not installed, skipping Redis backup")
        return "skipped"


# ─── Scheduled Backup ────────────────────────────────────────────────────────

async def schedule_backup(interval_s: int = 3600, output_dir: str = "/backups") -> None:
    """Run periodic backups."""
    log.info("Scheduled backup every %d seconds to %s", interval_s, output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    while True:
        await asyncio.sleep(interval_s)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(output_dir) / f"nova_auto_{timestamp}.tar.gz")
        try:
            create_backup(output_path=output_path)

            # Also backup external services
            try:
                await backup_qdrant()
            except Exception as e:
                log.warning("Qdrant backup failed: %s", e)

            try:
                await backup_redis()
            except Exception as e:
                log.warning("Redis backup failed: %s", e)

            # Clean old backups (keep last 24)
            backups = sorted(Path(output_dir).glob("nova_auto_*.tar.gz"))
            if len(backups) > 24:
                for old in backups[:-24]:
                    old.unlink()
                    log.info("Removed old backup: %s", old)

        except Exception as e:
            log.error("Scheduled backup failed: %s", e)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NOVA Backup & Recovery Tool")
    parser.add_argument("--action", choices=["backup", "restore", "schedule"], required=True)
    parser.add_argument("--output", default="", help="Output path for backup archive")
    parser.add_argument("--input", default="", help="Input path for restore archive")
    parser.add_argument("--interval", type=int, default=3600, help="Backup interval in seconds (schedule mode)")
    parser.add_argument("--dry-run", action="store_true", help="List contents without extracting")
    args = parser.parse_args()

    if args.action == "backup":
        create_backup(output_path=args.output)
    elif args.action == "restore":
        restore_backup(input_path=args.input, dry_run=args.dry_run)
    elif args.action == "schedule":
        asyncio.run(schedule_backup(interval_s=args.interval))


if __name__ == "__main__":
    main()
