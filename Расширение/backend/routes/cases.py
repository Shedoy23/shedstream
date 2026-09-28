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

  (POST /api/admin/case/grant удалён 2026-06-14 — админка read-only.)
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
    """Список ТОЛЬКО закрытых кейсов юзера, новейшие первыми.

    Sprint 5.28: UX cleanup — раньше отдавали include_opened=True (история
    открытых тоже шла в grid как dimmed cards). Юзер пожаловался: badge
    «все открыты» + «Нет закрытых кейсов» + 12 серых карточек = confusing.
    Историю не показываем; список = inbox закрытых.

    Multi-tenant scoping через JWT (channel_id из токена + username владельца).
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    cases = await db.list_cases(username, channel_id=channel_id, include_opened=False, limit=100)
    counts = await db.count_unopened_cases(username, channel_id=channel_id)
    # Sprint 5.28: lifetime count — нужно frontend'у чтобы различать
    # «никогда не было кейсов» vs «все открыл» в empty-state сообщении.
    lifetime = await db.count_all_cases(username, channel_id=channel_id)

    return {
        "success": True,
        "cases": cases,
        "unopened_counts": counts,
        "lifetime_count": lifetime,
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


@router.post("/api/viewer/cases/open-all")
async def viewer_cases_open_all(request: Request):
    """Открыть все свои кейсы разом.

    Причина появления (2026-09-05): 923 кейса лежали неоткрытыми на 1.1 млн
    крустиков — открывать по одному через модалку никто не досиживал, и зритель
    при этом жаловался, что крустиков не хватает. Награда, до которой нельзя
    дотянуться, ничем не отличается от невыданной.

    Body: не нужен. Открывает пачкой (лимит на вызов), остаток — следующим
    нажатием, чтобы не держать базу на гигантской транзакции.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    result = await get_db().open_all_cases(username, channel_id=channel_id)
    if not result["opened"]:
        return {"success": False, "opened": 0, "message": "Нет неоткрытых кейсов"}

    parts = []
    for tier, emoji in (("common", "🎁"), ("rare", "💎"), ("epic", "💠"), ("legendary", "👑")):
        n = result["by_tier"].get(tier)
        if n:
            parts.append(f"{emoji}×{n}")
    tail = f" Осталось {result['left']} — нажми ещё раз." if result["left"] else ""
    return {
        "success": True,
        "opened": result["opened"],
        "total_reward": result["total_reward"],
        "by_tier": result["by_tier"],
        "new_balance": result["new_balance"],
        "left": result["left"],
        "message": (f"Открыто {result['opened']} кейсов ({' '.join(parts)}): "
                    f"+{result['total_reward']:,}💎".replace(",", " ") + tail),
    }


# ── Public preview endpoint ────────────────────────────────────────────────────

@router.get("/api/case/preview/{tier}")
async def case_preview(tier: str, request: Request):
    """Preview награды per tier. Public — viewer видит **до** открытия что
    получит. Compliance: detерминированный prize, юзер всегда знает шансы
    (а здесь шансов нет вообще — фиксированно).

    Sprint 5.31 #45e (audit MED-9) — добавлен per-IP rate limit (60/min).
    Раньше endpoint был полностью anon без guard'а — trivial DoS vector
    пока Nginx-level лимиты не активизируются.

    Returns:
        {success: True, tier, reward_points, label, color}
        | {success: False, message}
    """
    from dependencies import check_rate_limit
    client_ip = (request.client.host if request.client else "unknown")
    if not check_rate_limit(client_ip, limit=60):
        return {"success": False, "message": "Слишком много запросов"}
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
async def case_preview_all(request: Request):
    """All tiers в одном запросе — для UI catalog'а / FAQ."""
    # Sprint 5.31 #45e (audit MED-9) — rate limit как у /preview/{tier}.
    from dependencies import check_rate_limit
    client_ip = (request.client.host if request.client else "unknown")
    if not check_rate_limit(client_ip, limit=60):
        return {"success": False, "message": "Слишком много запросов"}
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


# 2026-06-14 (audit): POST /api/admin/case/grant удалён — админка read-only,
# god-mode «выдать кейс вручную» убран. Автоматическая выдача кейсов
# (quests/triggers через db.grant_case в bot_core) — игровой флоу, остаётся.
# Редкие support/refund-кейсы — разовым залогированным скриптом.
# См. docs/SECURITY_AUDIT_2026-06-14.md.
