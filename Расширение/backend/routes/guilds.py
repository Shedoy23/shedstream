"""
routes/guilds.py — endpoints для гильдий (Phase 3 of COMPLIANCE_REWORK_PLAN.md).

Социальная механика per канал. Multi-tenant scope через JWT.

Compliance: §7.4 broadcaster-control разрешён (master может kick/disband).
НЕТ бустов накопления участникам (Variant 2a). Все cost'ы — sink крустиков
(GUILD_CREATE_COST 100k, skill upgrades по cost_per_level).

Endpoints:
  POST /api/guild/create              — создать (cost 100k💎)
  POST /api/guild/join                — вступить (body: guild_id)
  POST /api/guild/leave               — выйти (master must disband)
  POST /api/guild/disband             — master: расформировать
  POST /api/guild/contribute          — вклад в balance (body: amount)
  POST /api/guild/kick                — master: kick member (body: target)
  POST /api/guild/upgrade-skill       — master: прокачать (body: skill_key)
  GET  /api/guild/my                  — моя гильдия
  GET  /api/guild/{id}                — public info + members + top-contributors
  GET  /api/guild/list                — top по balance
  GET  /api/guild/skills/config       — описание доступных skills (для UI)
"""
from fastapi import APIRouter, Request

from config import (
    GUILD_CREATE_COST, GUILD_NAME_MIN_LEN, GUILD_NAME_MAX_LEN,
    GUILD_TAGLINE_MAX_LEN, GUILD_MIN_CONTRIBUTE, GUILD_SKILLS_CONFIG,
    sanitize_username,
)
from dependencies import get_db, require_jwt_user

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.post("/api/guild/create")
async def guild_create(request: Request):
    """Создать гильдию.

    Body: {"name": str, "tagline": str (опц)}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    name = (data.get("name") or "").strip()
    tagline = (data.get("tagline") or "").strip()

    if not (GUILD_NAME_MIN_LEN <= len(name) <= GUILD_NAME_MAX_LEN):
        return {
            "success": False,
            "reason": "invalid_name",
            "message": f"Имя гильдии должно быть {GUILD_NAME_MIN_LEN}-{GUILD_NAME_MAX_LEN} символов",
        }
    if len(tagline) > GUILD_TAGLINE_MAX_LEN:
        return {
            "success": False,
            "reason": "tagline_too_long",
            "message": f"Tagline макс {GUILD_TAGLINE_MAX_LEN} символов",
        }

    db = get_db()
    result = await db.create_guild(name, username, tagline=tagline, channel_id=channel_id)

    if result.get("created"):
        return {
            "success": True,
            "guild_id": result["guild_id"],
            "cost": result["cost"],
            "remaining_balance": result["remaining_balance"],
            "message": f"⚔️ Гильдия «{name}» создана! Списано {result['cost']:,}💎",
        }

    reason_msg = {
        "already_in_guild": "Ты уже в гильдии",
        "name_taken": f"Имя «{name}» уже занято на этом канале",
        "insufficient_funds": f"Нужно {GUILD_CREATE_COST:,}💎 для создания",
        "invalid_name": "Неверное имя",
    }.get(result.get("reason"), "Не удалось создать гильдию")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/guild/join")
async def guild_join(request: Request):
    """Вступить в гильдию.

    Body: {"guild_id": int}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    try:
        guild_id = int(data.get("guild_id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный guild_id"}
    if guild_id <= 0:
        return {"success": False, "message": "Неверный guild_id"}

    db = get_db()
    result = await db.join_guild(guild_id, username, channel_id=channel_id)

    if result.get("joined"):
        return {
            "success": True,
            "guild_id": result["guild_id"],
            "guild_name": result.get("guild_name"),
            "message": f"⚔️ Ты вступил в «{result.get('guild_name', '?')}»",
        }
    reason_msg = {
        "already_in_guild": "Ты уже в гильдии",
        "guild_not_found": "Гильдия не найдена",
        "wrong_channel": "Гильдия не с этого канала",
        "guild_full": f"Гильдия заполнена ({result.get('current')}/{result.get('max')})",
    }.get(result.get("reason"), "Не удалось вступить")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/guild/leave")
async def guild_leave(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    result = await db.leave_guild(username, channel_id=channel_id)

    if result.get("left"):
        return {"success": True, "message": "👋 Ты покинул гильдию"}
    reason_msg = {
        "not_in_guild": "Ты не в гильдии",
        "master_must_disband": "Master не может покинуть — используй расформирование",
    }.get(result.get("reason"), "Не удалось выйти")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/guild/disband")
async def guild_disband(request: Request):
    """Master расформировывает гильдию. Balance не возвращается участникам
    (sink крустиков; гильдия — collective decision)."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    result = await db.disband_guild(username, channel_id=channel_id)

    if result.get("disbanded"):
        return {"success": True, "guild_id": result["guild_id"],
                "message": "🏴 Гильдия расформирована"}
    return {"success": False, "reason": result.get("reason"),
            "message": "Только master может расформировать"}


@router.post("/api/guild/contribute")
async def guild_contribute(request: Request):
    """Вклад крустиков в guild balance.

    Body: {"amount": int}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверная сумма"}
    if amount <= 0:
        return {"success": False, "message": "Сумма должна быть положительной"}

    db = get_db()
    result = await db.contribute_to_guild(username, amount, channel_id=channel_id)

    if result.get("contributed"):
        return {
            "success": True,
            "guild_id": result["guild_id"],
            "amount": result["amount"],
            "new_balance": result["new_balance"],
            "message": f"💰 +{result['amount']:,}💎 в гильдию (баланс: {result['new_balance']:,}💎)",
        }
    reason_msg = {
        "not_in_guild": "Ты не в гильдии",
        "too_small": f"Минимум {GUILD_MIN_CONTRIBUTE}💎",
        "insufficient_funds": "Недостаточно крустиков",
    }.get(result.get("reason"), "Не удалось внести")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/guild/kick")
async def guild_kick(request: Request):
    """Master выгоняет участника.

    Body: {"target": str}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    target = sanitize_username(data.get("target", ""))
    if not target:
        return {"success": False, "message": "Неверный target"}

    db = get_db()
    result = await db.kick_member(username, target, channel_id=channel_id)

    if result.get("kicked"):
        return {"success": True, "target": result["target"],
                "message": f"👢 @{result['target']} изгнан"}
    reason_msg = {
        "cannot_kick_self": "Себя нельзя",
        "not_master": "Только master может кикать",
        "target_not_member": "Этот юзер не в твоей гильдии",
    }.get(result.get("reason"), "Не удалось кикнуть")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/guild/upgrade-skill")
async def guild_upgrade_skill(request: Request):
    """Master прокачивает skill из guild.balance.

    Body: {"skill_key": str}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    skill_key = (data.get("skill_key") or "").strip()

    db = get_db()
    result = await db.upgrade_guild_skill(username, skill_key, channel_id=channel_id)

    if result.get("upgraded"):
        skill_name = GUILD_SKILLS_CONFIG.get(skill_key, {}).get("name", skill_key)
        return {
            "success": True,
            "skill_key": result["skill_key"],
            "new_level": result["new_level"],
            "cost": result["cost"],
            "new_balance": result["new_balance"],
            "message": f"⬆️ «{skill_name}» Lv.{result['new_level']} (−{result['cost']:,}💎)",
        }
    reason_msg = {
        "unknown_skill": "Неизвестный skill",
        "not_master": "Только master может прокачивать",
        "max_level": f"Достигнут max уровень ({result.get('level')})",
        "insufficient_guild_balance": f"Недостаточно баланса гильдии (нужно {result.get('cost'):,}💎)",
    }.get(result.get("reason"), "Не удалось прокачать")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.get("/api/guild/my")
async def guild_my(request: Request):
    """Моя гильдия + summary."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    guild = await db.get_my_guild(username, channel_id=channel_id)
    if not guild:
        return {"success": True, "in_guild": False}
    return {"success": True, "in_guild": True, "guild": guild}


@router.get("/api/guild/list")
async def guild_list(request: Request):
    """Top гильдий канала.

    ВАЖНО: routing — этот endpoint должен идти ДО `/api/guild/{guild_id}`,
    иначе FastAPI ловит «list» как guild_id и возвращает 422 (int_parsing).
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    guilds = await db.list_guilds(channel_id=channel_id, limit=20)
    return {"success": True, "guilds": guilds}


@router.get("/api/guild/skills/config")
async def guild_skills_config():
    """Описание доступных skills для UI (public, не требует auth)."""
    return {
        "success": True,
        "skills": [
            {
                "skill_key": key,
                "name": cfg["name"],
                "description": cfg["description"],
                "max_level": cfg["max_level"],
                "cost_per_level": cfg["cost_per_level"],
                "effect_per_level": cfg["effect_per_level"],
            }
            for key, cfg in GUILD_SKILLS_CONFIG.items()
        ],
    }


# `/{guild_id}` — ловит ВСЁ после /api/guild/, поэтому идёт ПОСЛЕ всех
# конкретных путей (/list, /my, /skills/config) чтобы их не перекрыть.
@router.get("/api/guild/{guild_id}")
async def guild_get(guild_id: int, request: Request):
    """Public info о гильдии (только если на твоём канале)."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    guild = await db.get_guild(guild_id, channel_id=channel_id)
    if not guild:
        return {"success": False, "message": "Гильдия не найдена"}
    return {"success": True, "guild": guild}
