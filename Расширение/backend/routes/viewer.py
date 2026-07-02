"""
routes/viewer.py — статистика и активность зрителей.
"""
import asyncio
import logging
import re as _re
from datetime import date

from fastapi import APIRouter, Request

from config import (
    ACTIVITY_CONFIG,
    MIN_HEARTBEAT_SECONDS,
    POINTS_PER_MINUTE,
    PRESENCE_WATCHTIME_ENABLED,
    QUESTS_CONFIG,
    WATCH_TIME_CAP,
    sanitize_username,
)
from dependencies import (
    check_rate_limit,
    get_bot,
    get_db,
    require_jwt_channel,
    require_jwt_user,
    require_stream_live,
    resolve_channel_id_or_default,
    set_request_channel_id,
)
from models import ActivityRequest, ChatMessageRequest, UserAction

_AUTH_FAIL = {"status": "unauthorized", "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}

router = APIRouter()
logger = logging.getLogger("rimlink")


@router.post("/api/viewer/online")
async def viewer_online(action: UserAction, request: Request):
    """Зритель открыл расширение"""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    if not check_rate_limit(username, 20):
        return {"status": "rate_limited"}
    logger.info("ONLINE: %s", username)

    db = get_db()
    async with db._connect() as conn:
        await conn.execute("""
            INSERT INTO viewers (channel_id, username, last_seen, is_afk)
            VALUES (?, ?, datetime('now'), 0)
            ON CONFLICT(channel_id, username) DO UPDATE SET
                last_seen = datetime('now'),
                is_afk = 0
        """, (channel_id, username))
        await conn.commit()
    return {"status": "ok"}


@router.get("/api/viewer/stats/{username}")
async def viewer_stats(username: str, request: Request):
    """Статистика для зрителя. Multi-tenant scoping через JWT —
    показываем стат именно на канале просмотра, а не cross-channel."""
    channel_id = require_jwt_channel(request)
    if channel_id is None:
        return {"status": "unauthorized"}
    uname = username.lower()
    db    = get_db()
    bot   = get_bot()

    points    = await db.get_points(uname, channel_id=channel_id)
    inventory = await db.get_inventory(uname, channel_id=channel_id) or []
    quests    = await db.get_quests(uname, channel_id=channel_id)
    # 2026-05-13 (Phase 8.C): inventory → cases. Items больше cosmetic-only,
    # а главный «инвентарь» юзера — кейсы (закрытые/открытые).
    unopened_cases = await db.count_unopened_cases(uname, channel_id=channel_id)

    async with db._connect() as conn:
        today = date.today().isoformat()

        cur = await conn.execute(
            "SELECT COUNT(*), SUM(message_length) FROM chat_stats "
            "WHERE channel_id=? AND username=? AND date(created_at)=?",
            (channel_id, uname, today))
        row = await cur.fetchone()
        chat_count, chat_length = (row[0] or 0, row[1] or 0) if row else (0, 0)

        cur = await conn.execute(
            "SELECT SUM(watch_time) FROM activity_stats "
            "WHERE channel_id=? AND username=? AND date(created_at)=?",
            (channel_id, uname, today))
        row = await cur.fetchone()
        watch_time_today = row[0] if row and row[0] else 0

        cur = await conn.execute(
            "SELECT SUM(watch_time) FROM activity_stats WHERE channel_id=? AND username=?",
            (channel_id, uname))
        row = await cur.fetchone()
        watch_time_total = row[0] if row and row[0] else 0

        cur = await conn.execute(
            "SELECT COUNT(*), SUM(message_length) FROM chat_stats WHERE channel_id=? AND username=?",
            (channel_id, uname))
        row = await cur.fetchone()
        chat_total_count, chat_total_length = (row[0] or 0, row[1] or 0) if row else (0, 0)

    try:
        # item_bonus убран 2026-05-13 (Phase 8.C): items больше не дают passive
        # income (§5.3 — digital goods cosmetic-only, без game advantage).
        base_income = POINTS_PER_MINUTE
        level_data  = await db.get_user_level(uname, channel_id=channel_id)
        level_pct   = db.get_level_info(level_data.get("level", 1)).get("bonus_pct", 0)
        income_per_min = int(base_income * (1 + level_pct / 100))
    except Exception:
        income_per_min = POINTS_PER_MINUTE

    active_event = False
    try:
        active_event = bot.event_manager.active_event is not None
    except AttributeError:
        pass

    # 2026-05-15 (Sprint 1.5): active_module — для conditional render
    # tab «🔌 Интеграция» в extension.html (rimworld / bannerlord / null).
    active_module = None
    try:
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT active_module FROM channels WHERE channel_id=?",
                (channel_id,))
            row = await cur.fetchone()
            active_module = row[0] if row else None
    except Exception:
        pass

    return {
        "points":         points,
        "inventory":      inventory,         # legacy cosmetic items (без bonus)
        "unopened_cases": unopened_cases,    # {common: N, rare: M, epic: K, legendary: L}
        "quests":         quests,
        "income_per_min": income_per_min,
        "active_event":   active_event,
        "active_module":  active_module,     # 'rimworld' | 'bannerlord' | null
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
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
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

    async with db._connect() as conn:
        await conn.execute("""
            INSERT INTO viewers (channel_id, username, last_seen, is_afk)
            VALUES (?, ?, datetime('now'), 0)
            ON CONFLICT(channel_id, username) DO UPDATE SET last_seen = datetime('now'), is_afk = 0
        """, (channel_id, username))
        stream_live = False
        try:
            stream_live = await bot._is_stream_live(channel_id=channel_id)
        except Exception:
            pass
        # 2026-06-06 — при PRESENCE_WATCHTIME_ENABLED watch_time начисляет
        # серверный reward_points_loop (по списку чата Twitch), а heartbeat его
        # НЕ даёт (иначе десктоп считался бы дважды). last_seen выше обновляется
        # всегда — клиентский сигнал остаётся валиден для очков.
        if stream_live and not PRESENCE_WATCHTIME_ENABLED:
            await conn.execute("""
                INSERT INTO activity_stats (channel_id, username, watch_time)
                VALUES (?, ?, ?)
            """, (channel_id, username, watch_time))
        await conn.commit()

    bot.update_viewer_presence(username, channel_id)

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
    """Presence-trace для chat-сообщений приходящих с frontend'а.

    DEDUP NOTE: настоящий учёт чата (chat_stats INSERT, бонус за длину,
    quest tick) идёт через IRC-бот в main.py (TwitchChatBot.event_message).
    Раньше этот endpoint дублировал ту же работу — тот же event приходил
    от Twitch IRC и от frontend'а, и записывался ДВАЖДЫ в chat_stats,
    а бонус начислялся ДВАЖДЫ.

    Сейчас здесь — только presence trace (update_viewer_chat) на случай
    если frontend знает о чате раньше IRC bot'а (вариант: открытое
    расширение с собственным WebSocket к Twitch). Запись в chat_stats
    и quest update отвечает IRC bot, источник правды.

    Ничего не возвращает в смысле бонуса — frontend не должен ожидать
    points от этого endpoint'а; они придут от IRC handler'а.
    """
    if err := await require_stream_live():
        return {"status": "offline", "message": err["message"]}
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    bot = get_bot()
    bot.update_viewer_chat(username, channel_id)
    return {"status": "ok", "deduped": True}


@router.post("/api/viewer/click")
async def track_click(request: Request):
    """Отслеживание кликов"""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    safe_username, channel_id = auth
    if not check_rate_limit(safe_username, 10):
        return {"status": "rate_limited"}
    db = get_db()
    if ACTIVITY_CONFIG.get("activity_bonus_enabled", True):
        bonus = ACTIVITY_CONFIG.get("bonus_per_click", 1)
        await db.add_points(safe_username, bonus)
    return {"status": "ok"}


@router.get("/api/viewer/quests/{username}")
async def get_viewer_quests(username: str, request: Request):
    """Получить детальную информацию о квестах. Multi-tenant scoping
    через JWT — viewer может смотреть квесты только в рамках своего
    стримерского канала."""
    channel_id = require_jwt_channel(request)
    if channel_id is None:
        return {"quests": [], "status": "unauthorized"}
    db     = get_db()
    quests = await db.get_quests(username, channel_id=channel_id)
    for quest in quests:
        quest_config = QUESTS_CONFIG.get(quest["type"])
        if quest_config:
            quest["reward_description"] = f"{quest['reward']}💎"
            if quest_config.get("reward_item"):
                quest["reward_description"] += " + предмет"
    return {"quests": quests}


@router.get("/api/user/level/{username}")
async def get_user_level(username: str, request: Request):
    """Получить уровень и EXP пользователя.

    Public-gate (2026-07-02): требует JWT. Без JWT (до Twitch-авторизации/если
    зритель не поделился личностью) — возвращаем нейтральные дефолты, НЕ данные
    default-канала (иначе при multi-tenant любой без JWT читал бы данные
    стримера 98319857).
    """
    username = sanitize_username(username)
    if not username:
        return {"level": 1, "exp": 0, "total_exp": 0, "exp_needed": 100, "title": "Зритель", "bonus_pct": 0}

    auth = require_jwt_user(request)
    if not auth:
        return {"level": 1, "exp": 0, "total_exp": 0, "exp_needed": 100, "title": "Зритель", "bonus_pct": 0}
    channel_id = auth[1]
    set_request_channel_id(channel_id)

    db         = get_db()
    level_data = await db.get_user_level(username, channel_id=channel_id)
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
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    data    = await request.json()
    minutes = int(data.get("minutes", 0))
    bot     = get_bot()
    result  = await bot.record_viewer_attendance(username, minutes, channel_id=channel_id)
    return {"success": True, **result}


@router.get("/api/viewer/streak/{username}")
async def get_viewer_streak(username: str, request: Request):
    """Стрик зрителя. Multi-tenant scoping через JWT."""
    channel_id = require_jwt_channel(request)
    if channel_id is None:
        return {"current_streak": 0, "max_streak": 0, "last_stream_id": "", "status": "unauthorized"}
    return await get_db().get_streak(username, channel_id=channel_id)


@router.get("/api/achievements")
async def get_all_achievements():
    """Список ВСЕХ доступных достижений (определения). Game-agnostic, не требует JWT —
    каталог достижений общий для всех каналов."""
    return {"achievements": await get_db().get_achievements()}


@router.get("/api/viewer/achievements/{username}")
async def get_viewer_achievements(username: str, request: Request):
    """Какие достижения зритель уже получил на канале. Per-channel scoped через JWT."""
    channel_id = require_jwt_channel(request)
    if channel_id is None:
        return {"achievements": [], "status": "unauthorized"}
    db       = get_db()
    all_ach  = await db.get_achievements()
    unlocked = {a["key"]: a["unlocked_at"]
                for a in await db.get_user_achievements(username, channel_id=channel_id)}
    for a in all_ach:
        a["unlocked"]    = a["key"] in unlocked
        a["unlocked_at"] = unlocked.get(a["key"])
    return {"achievements": all_ach}


@router.get("/api/viewer/online-list")
async def get_online_users(request: Request):
    """Список пользователей онлайн (не AFK) для дропдаунов — scoped по каналу из
    JWT. Public-gate (2026-07-02): без JWT → пустой список (иначе протекает
    presence между каналами при multi-tenant)."""
    auth = require_jwt_user(request)
    if not auth:
        return {"users": []}
    channel_id = auth[1]
    db = get_db()
    async with db._connect() as conn:
        cursor = await conn.execute("""
            SELECT username FROM viewers
            WHERE channel_id = ? AND is_afk = 0
            AND last_seen > datetime('now', '-10 minutes')
            ORDER BY username
        """, (channel_id,))
        rows = await cursor.fetchall()
    return {"users": [r[0] for r in rows]}


# Sprint 5.31 #45b — Perks/tier endpoint для бейджа в шапке расширения.
# Возвращает текущему viewer'у его role + boosty_tier + twitch_sub_tier чтобы
# фронт мог нарисовать "TS1" / "BS2" / "👑 Стример" / "🛡 Модер" рядом с ником.
@router.get("/api/viewer/perks")
async def viewer_perks(request: Request):
    """Return {role, twitch_sub_tier, boosty_tier} для текущего JWT-юзера.

    Sprint 5.31 #45c — каждая ветка отказа логируется чтобы можно было
    дебажить "почему мой бейдж не показывает BS2" без переоткрытия issue.
    """
    from auth import verify_twitch_jwt
    jwt_data = verify_twitch_jwt(request)
    if jwt_data.get("status") != "valid":
        logger.info("[perks] invalid JWT status=%s — returning anon defaults",
                    jwt_data.get("status"))
        return {"success": False, "role": "viewer",
                "twitch_sub_tier": 0, "boosty_tier": 0}
    role = (jwt_data.get("role") or "viewer").lower()
    user_id = str(jwt_data.get("user_id") or "")
    try:
        channel_id = int(jwt_data.get("channel_id") or 0)
    except (TypeError, ValueError):
        channel_id = 0

    # Username для Boosty lookup — без него Boosty tier не определить.
    # require_jwt_user даёт sanitized login, но если viewer не залогинен —
    # будет None, и Boosty всё равно не сможем зарезолвить. Тогда возвращаем 0.
    auth = require_jwt_user(request)
    username = auth[0] if auth else ""

    # Boosty tier (manual list).
    boosty_tier = 0
    if channel_id and username:
        try:
            from routes.bannerlord_boosty import get_boosty_tier
            boosty_tier = await get_boosty_tier(channel_id, username)
        except Exception as e:
            logger.warning("[perks] boosty lookup failed: %s", e)
    else:
        logger.debug("[perks] boosty lookup skipped: ch=%s user=%s "
                     "(missing channel_id or username — JWT без identity share?)",
                     channel_id, username)

    # Twitch sub tier (Helix). Только если есть user_id + channel_id.
    twitch_sub_tier = 0
    if channel_id and user_id:
        try:
            from twitch_subs import get_subscription_tier
            t = await get_subscription_tier(channel_id, user_id)
            twitch_sub_tier = int(t or 0)
        except Exception as e:
            logger.warning("[perks] twitch sub lookup failed: %s", e)
    else:
        logger.debug("[perks] twitch sub lookup skipped: ch=%s user_id=%s "
                     "(missing channel_id or user_id)", channel_id, user_id)

    logger.info("[perks] resolved ch=%s user=%s role=%s TS=%s BS=%s",
                channel_id, username or "?", role, twitch_sub_tier, boosty_tier)
    return {
        "success":          True,
        "role":             role,             # viewer | moderator | broadcaster
        "twitch_sub_tier":  twitch_sub_tier,  # 0 | 1 | 2 | 3
        "boosty_tier":      boosty_tier,      # 0 | 1 | 2 | 3
    }
