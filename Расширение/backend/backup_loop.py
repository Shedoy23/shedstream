"""
backup_loop.py — in-process async DB backup task.

Sprint 5.33 PHASE1-1 (2026-05-28, friend feedback follow-up):
архитектурный audit выявил DB как single-point-of-failure без auto-backup.
Existing backup_db.sh (cron) использовал stale path + не запускался
по дефолту. Этот loop работает В-process — стартует с backend, не зависит
от cron.

Approach:
  - sqlite3.Connection.backup() — atomic, online backup API. Не блокирует
    main pool (отдельная sqlite3.connect для source). WAL-safe.
  - asyncio.to_thread wrap т.к. sqlite3 sync.
  - Retention: keep last N (default 14) timestamped backups. Auto-prune.
  - Configurable interval (env BACKUP_INTERVAL_HOURS, default 6).
  - Skip backup если free disk < threshold (avoid filling disk).
  - Log size + count per cycle.

Offsite sync — out of scope. Operator can rclone/rsync `data/backups/` к S3/B2
по cron. Local backups protect от corruption; offsite protects от disk loss.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 6.0
DEFAULT_RETAIN_COUNT = 14
MIN_FREE_DISK_MB = 200      # skip backup if less than this free


def _resolve_db_path() -> Path:
    """Reconcile с тем что main.py фактически использует.

    main.py:260 — `Database("viewers.db")` — авторитарный path для production.
    db_pool fallback `data/rimworld.db` — legacy default, в проде не используется.
    Env DB_PATH override остаётся для dev/test setups.

    Logic:
      1. DB_PATH env override — если задан
      2. viewers.db (production default)
      3. data/rimworld.db (legacy fallback)
    """
    env_override = os.getenv("DB_PATH")
    if env_override:
        return Path(env_override)
    # Production: backend's CWD = /root/twitch-extension/backend, viewers.db там
    candidates = [Path("viewers.db"), Path("data/rimworld.db"), Path("data.db")]
    for cand in candidates:
        if cand.exists():
            return cand
    # Default — production layout
    return Path("viewers.db")


def _resolve_backup_dir() -> Path:
    """Where backups go. Default: <DB_PATH>/../backups/."""
    custom = os.getenv("DB_BACKUP_DIR")
    if custom:
        return Path(custom)
    db = _resolve_db_path()
    return db.parent / "backups"


def _free_disk_mb(path: Path) -> float:
    """Free space на disk containing path, in MB."""
    try:
        stat = shutil.disk_usage(str(path))
        return stat.free / (1024 * 1024)
    except Exception as e:
        log.warning("[DB-BACKUP] disk_usage check failed: %s", e)
        return 9999.0   # default OK if check fails


def _do_backup_sync(src: Path, dst: Path) -> dict:
    """Synchronous backup. Returns {success, size_bytes, duration_s, error}."""
    t0 = time.time()
    try:
        src_conn = sqlite3.connect(str(src))
        try:
            dst_conn = sqlite3.connect(str(dst))
            try:
                # backup() pages-at-a-time, won't block writers significantly
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()
        size = dst.stat().st_size if dst.exists() else 0
        return {"success": True, "size_bytes": size,
                "duration_s": time.time() - t0, "error": None}
    except Exception as e:
        return {"success": False, "size_bytes": 0,
                "duration_s": time.time() - t0, "error": str(e)}


def _prune_old(backup_dir: Path, keep_count: int) -> int:
    """Keep latest `keep_count` backups, delete rest. Returns deleted count."""
    try:
        files = sorted(
            backup_dir.glob("backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,    # newest first
        )
    except Exception as e:
        log.warning("[DB-BACKUP] prune scan failed: %s", e)
        return 0
    to_delete = files[keep_count:]
    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            log.warning("[DB-BACKUP] failed to delete %s: %s", f, e)
    return deleted


async def db_backup_loop():
    """Background task — started в main.py @app.on_event('startup').

    Loop:
      - sleep INTERVAL hours
      - check disk space
      - backup atomically
      - prune old
      - log result
    """
    try:
        interval_h = float(os.getenv("BACKUP_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS))
    except ValueError:
        interval_h = DEFAULT_INTERVAL_HOURS
    try:
        retain = int(os.getenv("BACKUP_RETAIN_COUNT", DEFAULT_RETAIN_COUNT))
    except ValueError:
        retain = DEFAULT_RETAIN_COUNT

    interval_sec = max(60.0, interval_h * 3600.0)
    log.info("[DB-BACKUP] loop started: interval=%.1fh retain=%d backups",
             interval_h, retain)

    # Do an initial backup ~60s after startup (give server time to settle).
    await asyncio.sleep(60.0)

    while True:
        try:
            db_path = _resolve_db_path()
            backup_dir = _resolve_backup_dir()
            backup_dir.mkdir(parents=True, exist_ok=True)

            if not db_path.exists():
                log.warning("[DB-BACKUP] source DB не существует: %s", db_path)
                await asyncio.sleep(interval_sec)
                continue

            # Disk space check.
            free_mb = _free_disk_mb(backup_dir)
            if free_mb < MIN_FREE_DISK_MB:
                log.warning("[DB-BACKUP] SKIP — free disk %.1f MB < %d MB threshold",
                            free_mb, MIN_FREE_DISK_MB)
                await asyncio.sleep(interval_sec)
                continue

            # Timestamp filename.
            ts = time.strftime("%Y%m%d_%H%M%S")
            dst = backup_dir / f"backup_{ts}.db"

            result = await asyncio.to_thread(_do_backup_sync, db_path, dst)

            if result["success"]:
                size_mb = result["size_bytes"] / (1024 * 1024)
                deleted = _prune_old(backup_dir, retain)
                log.info(
                    "[DB-BACKUP] OK %s — %.1f MB in %.1fs (pruned %d old, free disk %.0f MB)",
                    dst.name, size_mb, result["duration_s"], deleted, free_mb)
            else:
                log.error("[DB-BACKUP] FAILED: %s — error: %s",
                          dst.name, result["error"])
                # Don't leave a 0-byte file lying around
                try:
                    if dst.exists() and dst.stat().st_size == 0:
                        dst.unlink()
                except Exception:
                    pass

        except asyncio.CancelledError:
            log.info("[DB-BACKUP] loop cancelled (shutdown)")
            raise
        except Exception as ex:
            log.exception("[DB-BACKUP] loop iteration crashed: %s", ex)

        await asyncio.sleep(interval_sec)
