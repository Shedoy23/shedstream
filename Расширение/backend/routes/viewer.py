"""
routes/viewer.py — статистика и активность зрителей.
"""
import asyncio
import logging
import re as _re
from datetime import date

import aiosqlite
from fastapi import APIRouter, Request

from config import (
    ACTIVITY_CONFIG,
    MIN_HEARTBEAT_SECONDS,
    POINTS_PER_MINUTE,
    QUEST_ORDER,
    QUESTS_CONFIG,
    WATCH_TIME_CAP,
    sanitize_username,
)
from dependencies import check_rate_limit, get_bot, get_db, require_jwt_user, require_stream_live
from models import ActivityRequest, ChatMessageRequest, UserAction

_AUTH_FAIL = {"status": "unauthorized", "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}

router = APIRouter()
logger = logging.getLogger("rimlink")


@router.post("/api/viewer/online")
async def viewer_online(action: UserAction, request: Request):
    """Зритель открыл расширение"""
    username = require_jwt_user(request)
    if not username:
        return _AUTH_FAIL
    if not check_rate_limit(username, 20):
        return {"status": "rate_limited"}
    logger.info("ONLINE: %s", username)

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("""
            INSERT INTO viewers (username, last_seen, is_afk)
            VALUES (?, datetime('now'), 0)
            ON CONFLICT(username) DO UPDATE SET
                last_seen = datetime('now'),
                is_afk = 0
        """, (username,))
        await conn.commit()
    return {"status": "ok"}


@router.get("/api/viewer/stats/{username}")
async def viewer_stats(username: str):
    """Статистика для зрителя"""
    uname = username.lower()
    db    = get_db()
    bot   = get_bot()

    points    = await db.get_points(uname)
    inventory = await db.get_inventory(uname) or []
    quests    = await db.get_quests(uname)

    async with aiosqlite.connect(db.db_path) as conn:
        today = date.today().isoformat()

        cur = await conn.execute(
            "SELECT COUNT(*), SUM(message_length) FROM chat_stats WHERE username = ? AND date(created_at) = ?",
            (uname, today))
        row = await cur.fetchone()
        chat_count, chat_length = (row[0] or 0, row[1] or 0) if row else (0, 0)

        cur = await conn.execute(
            "SELECT SUM(watch_time) FROM activity_stats WHERE username = ? AND date(created_at) = ?",
            (uname, today))
        row = await cur.fetchone()
        watch_time_today = row[0] if row and row[0] else 0

        cur = await conn.execute(
            "SELECT SUM(watch_time) FROM activity_stats WHERE username = ?", (uname,))
        row = await cur.fetchone()
        watch_time_total = row[0] if row and row[0] else 0

        cur = await conn.execute(
            "SELECT COUNT(*), SUM(message_length) FROM chat_stats WHERE username = ?", (uname,))
        row = await cur.fetchone()
        chat_total_count, chat_total_length = (row[0] or 0, row[1] or 0) if row else (0, 0)

    try:
        base_income = POINTS_PER_MINUTE
        item_bonus  = sum(item.get("bonus", 0) * item.get("quantity", 1) for item in (inventory or []))
        level_data  = await db.get_user_level(uname)
        level_pct   = db.get_level_info(level_data.get("level", 1)).get("bonus_pct", 0)
        income_per_min = int((base_income + item_bonus) * (1 + level_pct / 100))
    except Exception:
        income_per_min = POINTS_PER_MINUTE

    active_event = False
    try:
        active_event = bot.event_manager.active_event is not None
    except AttributeError:
        pass

    return {
        "points":         points,
        "inventory":      inventory,
        "quests":         quests,
        "income_per_min": income_per_min,
        "active_event":   active_event,
        "stats": {
            "chat_messages_today":  chat_count,
            "chat_length_today":    chat_length,
            "watch_time_today":     watch_time_today,
            "watch_time_total":     watch_time_total,
            "chat_messages_total":  chat_total_count,
            "chat_length_total":    chat_total_length,
        },
    }


@router.post("/api/viewer/activity")
async def track_activity(body: ActivityRequest, request: Request):
    """Отслеживание активности зрителя"""
    username = require_jwt_user(request)
    if not username:
        return _AUTH_FAIL
    if not check_rate_limit(username, 60):
        return {"status": "rate_limited"}

    watch_time = max(0, min(int(body.watch_time), WATCH_TIME_CAP))
    db  = get_db()
    bot = get_bot()

    # Минимальный heartbeat: меньше MIN_HEARTBEAT_SECONDS — не засчитываем.
    # Отсекает пустые пинги от фронта (watch_time=0) и усложняет «тихую»
    # накрутку сырыми POST-ами. Отвечаем 200 OK чтобы клиент не паниковал.
    if watch_time < MIN_HEARTBEAT_SECONDS:
        return {"status": "ignored", "reason": "watch_time_too_small"}

    # Уровень ДО добавления watch_time — для детекции milestone-повышения.
    # Если watch_time = 0 или стрим не идёт, до/после совпадут, ничего не сработает.
    try:
        level_before = (await db.get_user_level(username))["level"]
    except Exception:
        level_before = 0

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("""
            INSERT INTO viewers (username, last_seen, is_afk)
            VALUES (?, datetime('now'), 0)
            ON CONFLICT(username) DO UPDATE SET last_seen = datetime('now'), is_afk = 0
        """, (username,))
        stream_live = False
        try:
            stream_live = await bot._is_stream_live()
        except Exception:
            pass
        if stream_live:
            await conn.execute("""
                INSERT INTO activity_stats (username, watch_time, active_clicks, active_moves)
                VALUES (?, ?, 0, 0)
            """, (username, watch_time))
        await conn.commit()

    bot.update_viewer_presence(username)

    try:
        level_data  = await db.get_user_level(username)
        level_after = level_data["level"]
        await bot.check_and_unlock_achievements(username, "level_up", {"level": level_after})
        total_hours = await db.get_total_watch_hours(username)
        await bot.check_and_unlock_achievements(username, "watch_hours", {"hours": total_hours})

        # Milestone level-up → чат-оповещение (только для знаковых уровней,
        # чтобы не спамить каждый +1).
        MILESTONE_LEVELS = {10, 25, 50, 100}
        if level_after > level_before and level_after in MILESTONE_LEVELS:
            import asyncio as _asyncio
            title = db.get_level_info(level_after)["title"]
            _asyncio.create_task(bot.send_message(
                f"⭐🎉 @{username} достиг {level_after} уровня! Звание: «{title}» 🏅"
            ))
    except Exception:
        pass

    return {"status": "ok", "stream_live": stream_live}


@router.post("/api/viewer/chat-message")
async def track_chat_message(body: ChatMessageRequest, request: Request):
    """Отслеживание сообщений в чате (со стороны фронта).

    Внимание: настоящий учёт чата уже идёт через IRC-бот в main.py
    (TwitchChatBot.event_message). Этот эндпоинт остаётся для legacy-вызовов
    с фронта — но username берётся из JWT (а не из body), поэтому подделка
    «пишу длинное сообщение за чужой ник» больше не работает.
    """
    if err := await require_stream_live():
        return {"status": "offline", "message": err["message"]}
    username = require_jwt_user(request)
    if not username:
        return _AUTH_FAIL

    db  = get_db()
    bot = get_bot()
    bot.update_viewer_chat(username)

    safe_text = (body.message_text or "")[:1000] if body.message_text else ""

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("""
            INSERT INTO chat_stats (username, message_length, message_text)
            VALUES (?, ?, ?)
        """, (username, body.message_length, safe_text))
        await conn.commit()

    if ACTIVITY_CONFIG.get("chat_bonus_enabled", True):
        today = date.today().isoformat()
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("""
                SELECT SUM(message_length) FROM chat_stats
                WHERE username = ? AND date(created_at) = ?
            """, (username, today))
            total_today = await cursor.fetchone() or (0,)
        daily_limit = ACTIVITY_CONFIG.get("max_daily_chat_bonus", 500)
        if total_today[0] < daily_limit:
            bonus = min(body.message_length // 10, 10)
            if bonus > 0:
                await db.add_points(username, bonus)

    try:
        for quest in QUEST_ORDER:
            quest_config = QUESTS_CONFIG.get(quest)
            if quest_config and quest_config.get("type") == "chat":
                await bot._update_quest_progress(username, quest, 1)
    except Exception as e:
        print(f"Ошибка обновления чат-квестов для {username}: {e}")

    return {"status": "ok"}


@router.post("/api/viewer/click")
async def track_click(request: Request):
    """Отслеживание кликов"""
    safe_username = require_jwt_user(request)
    if not safe_username:
        return _AUTH_FAIL
    if not check_rate_limit(safe_username, 10):
        return {"status": "rate_limited"}
    db = get_db()
    if ACTIVITY_CONFIG.get("activity_bonus_enabled", True):
        bonus = ACTIVITY_CONFIG.get("bonus_per_click", 1)
        await db.add_points(safe_username, bonus)
    return {"status": "ok"}


@router.get("/api/viewer/quests/{username}")
async def get_viewer_quests(username: str):
    """Получить детальную информацию о квестах"""
    db     = get_db()
    quests = await db.get_quests(username)
    for quest in quests:
        quest_config = QUESTS_CONFIG.get(quest["type"])
        if quest_config:
            quest["reward_description"] = f"{quest['reward']}💎"
            if quest_config.get("reward_item"):
                quest["reward_description"] += " + предмет"
    return {"quests": quests}


@router.get("/api/user/level/{username}")
async def get_user_level(username: str):
    """Получить уровень и EXP пользователя"""
    username = sanitize_username(username)
    if not username:
        return {"level": 1, "exp": 0, "total_exp": 0, "exp_needed": 100, "title": "Зритель", "bonus_pct": 0}
    db         = get_db()
    level_data = await db.get_user_level(username)
    level_info = db.get_level_info(level_data["level"])
    return {
        "level":      level_data["level"],
        "exp":        level_data["exp"],
        "total_exp":  level_data["total_exp"],
        "exp_needed": level_info["exp_needed"],
        "title":      level_info["title"],
        "bonus_pct":  level_info["bonus_pct"],
    }


@router.post("/api/viewer/attendance")
async def viewer_attendance(request: Request):
    """Стрик-бонус за 15 мин просмотра."""
    username = require_jwt_user(request)
    if not username:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    data    = await request.json()
    minutes = int(data.get("minutes", 0))
    bot     = get_bot()
    result  = await bot.record_viewer_attendance(username, minutes)
    return {"success": True, **result}


@router.get("/api/viewer/streak/{username}")
async def get_viewer_streak(username: str):
    return await get_db().get_streak(username)


@router.get("/api/achievements")
async def get_all_achievements():
    return {"achievements": await get_db().get_achievements()}


@router.get("/api/viewer/achievements/{username}")
async def get_viewer_achievements(username: str):
    db       = get_db()
    all_ach  = await db.get_achievements()
    unlocked = {a["key"]: a["unlocked_at"] for a in await db.get_user_achievements(username)}
    for a in all_ach:
        a["unlocked"]    = a["key"] in unlocked
        a["unlocked_at"] = unlocked.get(a["key"])
    return {"achievements": all_ach}


@router.get("/api/viewer/online-list")
async def get_online_users():
    """Список пользователей онлайн (не AFK) для дропдаунов"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT username FROM viewers
            WHERE is_afk = 0
            AND last_seen > datetime('now', '-10 minutes')
            ORDER BY username
        """)
        rows = await cursor.fetchall()
    return {"users": [r[0] for r in rows]}
