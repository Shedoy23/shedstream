"""
routes/cases.py — endpoints для системы кейсов (Phase 2 of
COMPLIANCE_REWORK_PLAN.md).

Compliance: бесплатные loot boxes с детерминированным содержимым
(фиксированная награда крустиков per tier). §5.3 Twitch Extension
Guidelines permits. Никаких mystery boxes за крустики/Bits.

Endpoints:
  GET  /api/viewer/cases                     — список кейсов юзера (его JWT)
  GET  /api/viewer/cases/unopened-count      — badge counts per tier
  POST /api/viewer/case/open                 — открыть кейс (атомарно)
  GET  /api/case/preview/{tier}              — preview reward per tier (public)

  POST /api/admin/case/grant                 — grant вручную (admin only)
"""
from fastapi import APIRouter, Depends, Request

from config import CASE_TIER_REWARDS, sanitize_username
from dependencies import (
    get_db,
    require_admin,
    require_jwt_user,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}


# ── Viewer endpoints ───────────────────────────────────────────────────────────

@router.get("/api/viewer/cases")
async def viewer_cases(request: Request):
    """Список кейсов юзера (открытые + неоткрытые), новейшие первыми.

    Multi-tenant scoping через JWT (channel_id из токена + username владельца).
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    cases = await db.list_cases(username, channel_id=channel_id, include_opened=True, limit=100)
    counts = await db.count_unopened_cases(username, channel_id=channel_id)

    return {
        "success": True,
        "cases": cases,
        "unopened_counts": counts,
    }


@router.get("/api/viewer/cases/unopened-count")
async def viewer_unopened_count(request: Request):
    """Badge-count для UI: сколько закрытых кейсов per tier.

    Облегчённый endpoint для частого polling без загрузки full list.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    counts = await db.count_unopened_cases(username, channel_id=channel_id)
    return {"success": True, "counts": counts}


@router.post("/api/viewer/case/open")
async def viewer_case_open(request: Request):
    """Открыть кейс. Атомарно: validate ownership/state → mark opened → credit points.

    Body: {"case_id": int}

    Returns:
        {success: True, tier, reward_points, new_balance, message}
        if opened first time;
        {success: False, message, reason} в остальных случаях.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    try:
        case_id = int(data.get("case_id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный case_id"}
    if case_id <= 0:
        return {"success": False, "message": "Неверный case_id"}

    db = get_db()
    result = await db.open_case(case_id, username, channel_id=channel_id)

    if result["opened"]:
        tier_emoji = {"common": "🎁", "rare": "💎", "epic": "💠", "legendary": "👑"}.get(result["tier"], "🎁")
        return {
            "success": True,
            "tier": result["tier"],
            "reward_points": result["reward_points"],
            "new_balance": result["new_balance"],
            "message": f"{tier_emoji} +{result['reward_points']:,}💎",
        }
    else:
        reason_msg = {
            "not_found":             "Кейс не найден",
            "not_owner":             "Это не твой кейс",
            "already_opened":        "Кейс уже открыт",
            "invalid_tier_no_reward":"Неподдерживаемый тир кейса",
        }.get(result["reason"], "Не удалось открыть кейс")
        return {
            "success": False,
            "reason":  result["reason"],
            "message": reason_msg,
        }


# ── Public preview endpoint ────────────────────────────────────────────────────

@router.get("/api/case/preview/{tier}")
async def case_preview(tier: str):
    """Preview награды per tier. Public — viewer видит **до** открытия что
    получит. Compliance: detерминированный prize, юзер всегда знает шансы
    (а здесь шансов нет вообще — фиксированно).

    Returns:
        {success: True, tier, reward_points, label, color}
        | {success: False, message}
    """
    tier = tier.lower().strip()
    if tier not in CASE_TIER_REWARDS:
        return {"success": False, "message": "Неизвестный тир"}

    labels = {
        "common":    "Обычный",
        "rare":      "Редкий",
        "epic":      "Эпический",
        "legendary": "Легендарный",
    }
    colors = {
        "common":    "#9ca3af",  # серый
        "rare":      "#3b82f6",  # синий
        "epic":      "#a855f7",  # фиолетовый
        "legendary": "#fbbf24",  # золотой
    }
    return {
        "success":       True,
        "tier":          tier,
        "label":         labels[tier],
        "color":         colors[tier],
        "reward_points": CASE_TIER_REWARDS[tier],
    }


@router.get("/api/case/preview")
async def case_preview_all():
    """All tiers в одном запросе — для UI catalog'а / FAQ."""
    labels = {"common": "Обычный", "rare": "Редкий", "epic": "Эпический", "legendary": "Легендарный"}
    colors = {"common": "#9ca3af", "rare": "#3b82f6", "epic": "#a855f7", "legendary": "#fbbf24"}
    tiers = []
    for tier_key in ("common", "rare", "epic", "legendary"):
        tiers.append({
            "tier":          tier_key,
            "label":         labels[tier_key],
            "color":         colors[tier_key],
            "reward_points": CASE_TIER_REWARDS[tier_key],
        })
    return {"success": True, "tiers": tiers}


# ── Admin endpoints ────────────────────────────────────────────────────────────

@router.post("/api/admin/case/grant")
async def admin_case_grant(request: Request, _admin: str = Depends(require_admin)):
    """Admin: выдать кейс юзеру вручную. Audit-trail через source='admin_grant'.

    Используется для тестов, refund'ов, support-кейсов.

    Body: {"username": str, "tier": str, "trigger_key": str (опц)}
    Auth: require_admin (HTTP Basic)
    """
    data = await request.json()
    username = sanitize_username(data.get("username", ""))
    tier = (data.get("tier") or "").lower().strip()
    trigger_key = data.get("trigger_key")  # optional

    if not username:
        return {"success": False, "message": "Неверный username"}
    if tier not in CASE_TIER_REWARDS:
        return {"success": False, "message": f"Тир должен быть один из: {list(CASE_TIER_REWARDS.keys())}"}

    # channel_id — берём из admin-сессии (или из body для cross-channel admin'а).
    # Пока: используем resolve_channel_id_or_default через grant_case (она внутри сделает).
    db = get_db()
    result = await db.grant_case(
        username, tier, source="admin_grant", trigger_key=trigger_key,
    )

    if result["granted"]:
        return {
            "success":  True,
            "case_id":  result["case_id"],
            "message":  f"✅ Кейс {tier} выдан @{username}",
        }
    else:
        return {
            "success":  False,
            "reason":   result["reason"],
            "message":  f"Не удалось выдать: {result['reason']}",
        }
