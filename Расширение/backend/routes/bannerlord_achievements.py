"""
Sprint 5.29 / BLT-parity #5 — Achievements config + check logic + API.

Achievements хранятся как hardcoded list (легко добавлять без миграций).
Каждое achievement = (id, name, description, icon, criteria) где criteria
это (stat_key, op, threshold).

Stats updated в `modules/bannerlord/_adapter.py` (incremental по events
от мода). После каждого update вызываем check_achievements(channel, user)
которая ищет новые unlock'и и пишет в bannerlord_achievements_unlocked.

Endpoint:
  GET /api/bannerlord/achievements — список всех + unlocked для viewer'а
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()
log = logging.getLogger("rimlink.bannerlord.achievements")


# ── Achievement definitions ──────────────────────────────────────────────────
# (id, name, description, icon, stat_key, threshold)
# stat_key matched против bannerlord_user_stats. threshold — minimum value.
# Порядок отражает "прогрессию" в UI (от лёгких до сложных).
ACHIEVEMENTS: List[Dict] = [
    # Combat (стрим-friendly, easy to unlock)
    {"id": "first_blood",        "name": "Первая кровь",        "icon": "🩸",
     "description": "Убей первого врага в бою",
     "stat_key": "kills", "threshold": 1},
    {"id": "bloodthirsty",       "name": "Кровожадный",         "icon": "⚔️",
     "description": "Убей 100 врагов",
     "stat_key": "kills", "threshold": 100},
    {"id": "slayer",             "name": "Истребитель",          "icon": "💀",
     "description": "Убей 500 врагов",
     "stat_key": "kills", "threshold": 500},
    {"id": "warlord",            "name": "Полководец",           "icon": "🏴",
     "description": "Убей 1000 врагов",
     "stat_key": "kills", "threshold": 1000},

    # Tournament
    {"id": "first_tournament",   "name": "Дебют на арене",       "icon": "🥉",
     "description": "Участвуй в турнире зрителей",
     "stat_key": "tournament_participations", "threshold": 1},
    {"id": "tournament_champion","name": "Чемпион арены",        "icon": "🏆",
     "description": "Победи в турнире зрителей",
     "stat_key": "tournament_wins", "threshold": 1},
    {"id": "tournament_dynasty", "name": "Династия чемпионов",   "icon": "👑",
     "description": "Победи в 3 турнирах",
     "stat_key": "tournament_wins", "threshold": 3},

    # Progression
    {"id": "level_10",           "name": "Опытный воин",         "icon": "⭐",
     "description": "Достигни 10 уровня",
     "stat_key": "level_max", "threshold": 10},
    {"id": "level_20",           "name": "Легенда",              "icon": "🌟",
     "description": "Достигни 20 уровня",
     "stat_key": "level_max", "threshold": 20},
    {"id": "rich",               "name": "Богач",                 "icon": "💰",
     "description": "Накопи 500K💰 динаров",
     "stat_key": "gold_max", "threshold": 500_000},
    {"id": "millionaire",        "name": "Миллионер",            "icon": "💎",
     "description": "Накопи 1M💰 динаров",
     "stat_key": "gold_max", "threshold": 1_000_000},

    # Social / political
    {"id": "lord",               "name": "Лорд",                  "icon": "🏰",
     "description": "Создай свой клан",
     "stat_key": "clan_created", "threshold": 1},
    {"id": "king",               "name": "Король",                "icon": "👑",
     "description": "Создай своё королевство",
     "stat_key": "kingdom_created", "threshold": 1},
    # 2026-06-27: «Патриарх» (children_count) и «Семейный» (married) убраны из показа —
    # их статы НИКОГДА не пишутся (family-snapshot из мода не реализован), ачивки
    # висели невыполнимыми на 0%. Вернуть, когда мод начнёт слать брак/детей в stats.
]


def get_achievement(achievement_id: str) -> Optional[Dict]:
    for a in ACHIEVEMENTS:
        if a["id"] == achievement_id:
            return a
    return None


async def increment_stat(
    channel_id: int,
    username: str,
    stat_key: str,
    delta: int = 1,
) -> int:
    """Increment counter stat. Returns new value. Triggers check_achievements."""
    username = (username or "").lower()
    if not username or not stat_key or delta <= 0:
        return 0
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO bannerlord_user_stats "
            "(channel_id, username, stat_key, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(channel_id, username, stat_key) DO UPDATE SET "
            "value = value + excluded.value, updated_at = CURRENT_TIMESTAMP "
            "RETURNING value",
            (channel_id, username, stat_key, delta))
        row = await cur.fetchone()
        await conn.commit()
        new_value = row[0] if row else delta
    await _check_unlocks(channel_id, username)
    return new_value


async def set_stat_max(
    channel_id: int,
    username: str,
    stat_key: str,
    value: int,
) -> int:
    """Set high-water-mark (used for level_max / gold_max). Only updates если
    new value > existing. Returns final value."""
    username = (username or "").lower()
    if not username or not stat_key or value <= 0:
        return 0
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO bannerlord_user_stats "
            "(channel_id, username, stat_key, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(channel_id, username, stat_key) DO UPDATE SET "
            "value = MAX(value, excluded.value), updated_at = CURRENT_TIMESTAMP "
            "RETURNING value",
            (channel_id, username, stat_key, value))
        row = await cur.fetchone()
        await conn.commit()
        new_value = row[0] if row else value
    await _check_unlocks(channel_id, username)
    return new_value


async def set_stat_flag(
    channel_id: int,
    username: str,
    stat_key: str,
) -> None:
    """Set boolean flag (clan_created, kingdom_created, married). Idempotent."""
    await set_stat_max(channel_id, username, stat_key, 1)


async def _check_unlocks(channel_id: int, username: str) -> List[str]:
    """Проверить все achievements для user — unlock новые. Returns list of
    newly unlocked achievement_ids."""
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT stat_key, value FROM bannerlord_user_stats "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        stats = {row[0]: row[1] for row in await cur.fetchall()}

        cur = await conn.execute(
            "SELECT achievement_id FROM bannerlord_achievements_unlocked "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        unlocked = {row[0] for row in await cur.fetchall()}

        newly_unlocked = []
        for ach in ACHIEVEMENTS:
            aid = ach["id"]
            if aid in unlocked:
                continue
            cur_val = stats.get(ach["stat_key"], 0)
            if cur_val >= ach["threshold"]:
                await conn.execute(
                    "INSERT OR IGNORE INTO bannerlord_achievements_unlocked "
                    "(channel_id, username, achievement_id) VALUES (?, ?, ?)",
                    (channel_id, username, aid))
                newly_unlocked.append(aid)
        if newly_unlocked:
            await conn.commit()
            log.info("[bannerlord ACHIEVEMENT] ch=%s user=%s unlocked: %s",
                     channel_id, username, ", ".join(newly_unlocked))

    # Sprint 5.30 #44 — announce в Twitch chat через shedoyrobot.
    # Outside conn block (нет смысла блочить DB на IRC).
    if newly_unlocked:
        try:
            from bot_core import bot
            for aid in newly_unlocked:
                ach = get_achievement(aid)
                if not ach:
                    continue
                msg = (f"🏆 @{username} разблокировал «{ach['name']}» "
                       f"{ach.get('icon', '')} — {ach.get('description', '')}")
                # bot.send_message — fire-and-forget; failures logged внутри
                try:
                    await bot.send_message(msg, channel_id=channel_id)
                except Exception as ex:
                    log.warning("[bannerlord ACHIEVEMENT] chat send failed: %s", ex)
        except ImportError:
            # bot_core может быть не загружен в test/dev
            pass
        except Exception as ex:
            log.warning("[bannerlord ACHIEVEMENT] announce flow failed: %s", ex)
    return newly_unlocked


# ── API ──────────────────────────────────────────────────────────────────────

@router.get("/api/bannerlord/achievements")
async def viewer_achievements(request: Request):
    """Список всех achievements + unlock status для текущего viewer'а.

    Returns:
        {success: true, achievements: [{id, name, description, icon,
                                         stat_key, threshold,
                                         current_value, unlocked, unlocked_at}]}
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT stat_key, value FROM bannerlord_user_stats "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        stats = {row[0]: row[1] for row in await cur.fetchall()}

        cur = await conn.execute(
            "SELECT achievement_id, unlocked_at FROM bannerlord_achievements_unlocked "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        unlocked = {row[0]: row[1] for row in await cur.fetchall()}

    result = []
    for ach in ACHIEVEMENTS:
        result.append({
            "id":            ach["id"],
            "name":          ach["name"],
            "description":   ach["description"],
            "icon":          ach["icon"],
            "stat_key":      ach["stat_key"],
            "threshold":     ach["threshold"],
            "current_value": stats.get(ach["stat_key"], 0),
            "unlocked":      ach["id"] in unlocked,
            "unlocked_at":   unlocked.get(ach["id"]),
        })
    unlocked_count = sum(1 for a in result if a["unlocked"])
    return {
        "success":       True,
        "achievements":  result,
        "total":         len(result),
        "unlocked_count": unlocked_count,
    }
