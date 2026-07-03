"""
routes/voting.py — Voting events endpoints (Phase 4 of COMPLIANCE_REWORK_PLAN.md).

Compliance: §6.1.4 voting activities. Стример настраивает templates
(прямо §6.2.8 protection — items/выборы заданы каналом, не ad-hoc),
юзеры голосуют через крустики, prize = действие стримера.

Endpoints:
  Viewer:
    GET  /api/voting/status              — текущий event + pool progress
    POST /api/voting/bid                 — body {option_id, amount}

  Streamer (JWT broadcaster role или admin):
    POST /api/voting/templates           — body {name, options, is_default}
    GET  /api/voting/templates           — список templates канала
    DELETE /api/voting/templates/{id}    — удалить template
    POST /api/voting/start               — body {template_id} — force-start
    POST /api/voting/finalize/{event_id} — admin force-finalize

  Public (no JWT):
    нет, всё требует канал-контекст
"""
from fastapi import APIRouter, Request

from config import (
    VOTING_POOL_THRESHOLD, VOTING_EVENT_DURATION_SEC, VOTING_MIN_BID,
)
from dependencies import (
    get_db,
    require_jwt_user,
    require_admin,
)
from fastapi import Depends

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.get("/api/voting/status")
async def voting_status(request: Request):
    """Текущее состояние voting-системы канала.

    Returns:
      {success, active_event: {...} | None, pool_units, threshold,
       pool_pct, has_default_template}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    event = await db.get_active_voting_event(channel_id=channel_id)
    pool = await db.get_voting_pool(channel_id=channel_id)
    templates = await db.list_voting_templates(channel_id=channel_id)
    has_default = any(t.get("is_default") for t in templates)

    top_bidders = []
    if event:
        top_bidders = await db.get_voting_top_bidders(event["event_id"], limit=5)

    return {
        "success":              True,
        "active_event":         event,
        "top_bidders":          top_bidders,
        "pool_units":           pool,
        "threshold":            VOTING_POOL_THRESHOLD,
        "pool_pct":             min(100, round(pool / VOTING_POOL_THRESHOLD * 100)),
        "has_default_template": has_default,
        "templates_count":      len(templates),
    }


@router.post("/api/voting/bid")
async def voting_bid(request: Request):
    """Юзер вкидывает крустики в опцию.

    Body: {"option_id": int, "amount": int}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    try:
        option_id = int(data.get("option_id", 0))
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверные параметры"}
    if option_id <= 0 or amount <= 0:
        return {"success": False, "message": "Неверные параметры"}

    # Найти текущий active event для канала чтобы знать event_id
    db = get_db()
    event = await db.get_active_voting_event(channel_id=channel_id)
    if not event:
        return {"success": False, "reason": "no_active_event",
                "message": "Нет активного голосования"}

    result = await db.place_voting_bid(
        event["event_id"], option_id, username, amount, channel_id=channel_id
    )

    if result.get("placed"):
        # Phase C (2026-05-17): immediate vote_tick broadcast — другие зрители
        # увидят updated pool в течение 1 сек (throttle), без 4-сек polling.
        # voting_loop ещё fire'ит vote_tick раз/10s как baseline (race-safe:
        # frontend dedupe'ит по seq, последний выигрывает).
        try:
            from pubsub import broadcast as _pubsub_broadcast
            state = await db.get_active_voting_event(channel_id=channel_id)
            if state:
                _pubsub_broadcast(channel_id, "vote_tick", {
                    "event_id":   state["event_id"],
                    "total_pool": state["total_pool"],
                    "options": [
                        {"id": o["id"], "pool": o["pool"]}
                        for o in state["options"]
                    ],
                })
        except Exception as e:
            import logging
            logging.getLogger("rimlink.voting").warning(
                "post-bid vote_tick broadcast failed: %s", e
            )
        return {
            "success":    True,
            "event_id":   result["event_id"],
            "option_id":  result["option_id"],
            "amount":     result["amount"],
            "message":    f"✅ +{amount}💎 в голосование!",
        }
    reason_msg = {
        "event_not_active":    "Голосование уже завершено",
        "wrong_channel":       "Неверный канал",
        "option_not_in_event": "Опция не из этого голосования",
        "too_small":           f"Минимум {VOTING_MIN_BID}💎",
        "insufficient_funds":  "Недостаточно крустиков",
    }.get(result.get("reason"), "Не удалось внести bid")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


# ── Streamer / admin endpoints (HTTP Basic) ───────────────────────────────────
# Стример управляет templates через admin auth. В Phase 5+ переедем на
# OAuth streamer flow когда у /streamer dashboard'а будет UI для templates.

@router.post("/api/voting/templates")
async def voting_create_template(
    request: Request,
    _admin: str = Depends(require_admin),
):
    """Создать template голосования. Admin/streamer only.

    Body: {"name": str, "options": [{"key", "label", "description"}],
           "is_default": bool, "channel_id": int}
    """
    data = await request.json()
    name = (data.get("name") or "").strip()
    options = data.get("options") or []
    is_default = bool(data.get("is_default", False))
    channel_id = data.get("channel_id")

    if not name or len(name) > 100:
        return {"success": False, "message": "name обязателен (1-100 chars)"}

    db = get_db()
    result = await db.create_voting_template(
        name, options, is_default=is_default, channel_id=channel_id,
    )
    if result.get("created"):
        return {"success": True, "template_id": result["template_id"],
                "message": f"📋 Template «{name}» создан"}
    return {"success": False, "reason": result.get("reason"),
            "message": result.get("message", "Не удалось создать template")}


@router.get("/api/voting/templates")
async def voting_list_templates(request: Request):
    """Список templates канала. Требует JWT; channel_id берётся из токена."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    db = get_db()
    templates = await db.list_voting_templates(channel_id=channel_id)
    return {"success": True, "templates": templates}


@router.delete("/api/voting/templates/{template_id}")
async def voting_delete_template(
    template_id: int,
    request: Request,
    _admin: str = Depends(require_admin),
):
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    channel_id = data.get("channel_id")

    db = get_db()
    deleted = await db.delete_voting_template(template_id, channel_id=channel_id)
    return {"success": deleted, "message": "Template удалён" if deleted else "Не найден"}


@router.post("/api/voting/start")
async def voting_force_start(
    request: Request,
    _admin: str = Depends(require_admin),
):
    """Admin принудительно стартует event из template.

    Body: {"template_id": int, "channel_id": int}
    """
    data = await request.json()
    try:
        template_id = int(data.get("template_id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный template_id"}
    channel_id = data.get("channel_id")

    db = get_db()
    result = await db.start_voting_event(template_id, channel_id=channel_id)
    if result.get("started"):
        return {
            "success":       True,
            "event_id":      result["event_id"],
            "template_name": result["template_name"],
            "options_count": result["options_count"],
            "ends_at":       result["ends_at"],
            "message":       f"🗳️ Голосование «{result['template_name']}» запущено!",
        }
    reason_msg = {
        "template_not_found":   "Template не найден",
        "active_event_exists":  "Уже идёт другое голосование",
    }.get(result.get("reason"), "Не удалось запустить")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/voting/finalize/{event_id}")
async def voting_force_finalize(
    event_id: int,
    request: Request,
    _admin: str = Depends(require_admin),
):
    """Admin принудительно завершает event."""
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    channel_id = data.get("channel_id")

    db = get_db()
    result = await db.finalize_voting_event(event_id, channel_id=channel_id)
    if result.get("finalized"):
        winner = result.get("winner_option")
        return {
            "success":  True,
            "outcome":  result["outcome"],
            "winner_option": winner,
            "message":  f"🏆 Победил «{winner['label']}»!" if winner
                        else "Никто не проголосовал, отменено",
        }
    reason_msg = {
        "not_found":     "Event не найден",
        "wrong_channel": "Неверный канал",
        "not_active":    "Event уже завершён",
    }.get(result.get("reason"), "Не удалось завершить")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


# ── «Народный выбор игры» (M88) — viewer предлагает свою игру (open mode) ──────
# Compliance (docs/COMPLIANCE_GAME_VOTE_2026-07-02.md): вклад списывается ПОСЛЕ
# одобрения стримером; очередь-одобрение = UGC-модерация §7 (ник автора виден
# стримеру, любое можно отклонить). Нейтральная лексика: «вклад / народный выбор».

def _bcast(channel_id: int, event_type: str, data: dict) -> None:
    """Тихий broadcast — фронт на любой vote_* просто перезапрашивает статус."""
    try:
        from pubsub import broadcast as _pubsub_broadcast
        _pubsub_broadcast(channel_id, event_type, data)
    except Exception as e:
        import logging
        logging.getLogger("rimlink.voting").warning(
            "%s broadcast failed: %s", event_type, e)


@router.post("/api/voting/propose")
async def voting_propose(request: Request):
    """Зритель предлагает свою игру в открытый раунд → очередь на одобрение.
    Вклад списывается ПОСЛЕ одобрения стримером (не сейчас).

    Body: {"label": str, "pledge": int}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    data = await request.json()
    label = (data.get("label") or "").strip()
    try:
        pledge = int(data.get("pledge", 0))
    except (TypeError, ValueError):
        pledge = 0

    db = get_db()
    result = await db.create_voting_proposal(
        channel_id=channel_id, username=username, label=label, pledge=pledge,
    )
    if result.get("created"):
        return {
            "success": True,
            "proposal_id": result["proposal_id"],
            # Платно + отложенный исход → явный тост: заявка, спишется если одобрят.
            "message": "📨 Игра отправлена на одобрение — вклад спишется, только если стример одобрит.",
        }
    reason_msg = {
        "no_active_event":    "Сейчас нет активного голосования",
        "proposals_closed":   "В этом раунде нельзя предлагать игры",
        "bad_label":          "Название игры 2–60 символов",
        "too_small":          result.get("message", "Слишком маленький вклад"),
        "insufficient_funds": "Недостаточно крустиков на вклад",
        "too_many_pending":   "У тебя уже есть игра в очереди на одобрение",
        "full":               "Список игр уже заполнен",
    }.get(result.get("reason"), "Не удалось предложить игру")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


# ── Streamer dashboard endpoints (session cookie) ─────────────────────────────
# Стример управляет раундом из своего дашборда (сессия), не через admin-basic.

def _streamer_channel(request: Request):
    """channel_id из dashboard-сессии стримера, или None."""
    from routes.streamer import _read_session_cookie
    return _read_session_cookie(request)


@router.post("/api/streamer/voting/start")
async def streamer_voting_start(request: Request):
    """Стример открывает раунд «Народный выбор игры» (allow_proposals=1).
    Body: {"duration_sec"?: int, "options"?: [{"label"} | "label"]}
    """
    cid = _streamer_channel(request)
    if cid is None:
        return {"success": False, "message": "Нет сессии стримера"}
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    duration = data.get("duration_sec")
    options = data.get("options") or []

    db = get_db()
    result = await db.start_open_voting_event(
        channel_id=cid, duration_sec=duration, options=options,
    )
    if result.get("started"):
        _bcast(cid, "vote_started", {"event_id": result["event_id"]})
        return {"success": True, "event_id": result["event_id"],
                "ends_at": result["ends_at"], "options_count": result["options_count"],
                "message": "🗳️ Голосование открыто!"}
    reason_msg = {"active_event_exists": "Уже идёт голосование"}.get(
        result.get("reason"), "Не удалось открыть")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/streamer/voting/finalize")
async def streamer_voting_finalize(request: Request):
    """Стример закрывает текущий раунд и объявляет победителя."""
    cid = _streamer_channel(request)
    if cid is None:
        return {"success": False, "message": "Нет сессии стримера"}
    db = get_db()
    event = await db.get_active_voting_event(channel_id=cid)
    if not event:
        return {"success": False, "reason": "no_active_event",
                "message": "Нет активного голосования"}
    result = await db.finalize_voting_event(event["event_id"], channel_id=cid)
    if result.get("finalized"):
        winner = result.get("winner_option")
        _bcast(cid, "vote_ended", {"event_id": event["event_id"],
                                   "outcome": result["outcome"],
                                   "winner": winner})  # {id,key,label,pool}|None — фронт покажет победителя
        return {"success": True, "outcome": result["outcome"], "winner_option": winner,
                "message": f"🏆 Победила «{winner['label']}»!" if winner
                           else "Никто не вложил — раунд отменён"}
    return {"success": False, "reason": result.get("reason"),
            "message": "Не удалось закрыть"}


@router.get("/api/streamer/voting/status")
async def streamer_voting_status(request: Request):
    """Текущее состояние раунда + очередь pending-предложений (для дашборда)."""
    cid = _streamer_channel(request)
    if cid is None:
        return {"success": False, "message": "Нет сессии стримера"}
    db = get_db()
    event = await db.get_active_voting_event(channel_id=cid)
    pending = await db.list_voting_proposals(channel_id=cid, status='pending') if event else []
    return {"success": True, "active_event": event, "pending": pending}


@router.post("/api/streamer/voting/proposals/{proposal_id}/approve")
async def streamer_voting_approve(proposal_id: int, request: Request):
    """Стример одобряет предложение → игра появляется в вотуме, пледж списывается."""
    cid = _streamer_channel(request)
    if cid is None:
        return {"success": False, "message": "Нет сессии стримера"}
    db = get_db()
    result = await db.approve_voting_proposal(proposal_id, channel_id=cid)
    if result.get("approved"):
        _bcast(cid, "vote_tick", {"event_id": result["event_id"]})
        return {"success": True, "option_id": result["option_id"],
                "label": result["label"], "pool": result["pool"],
                "message": f"✅ «{result['label']}» в голосовании"}
    reason_msg = {
        "not_found":        "Предложение не найдено",
        "not_pending":      "Уже обработано",
        "event_not_active": "Голосование не активно",
    }.get(result.get("reason"), "Не удалось одобрить")
    return {"success": False, "reason": result.get("reason"), "message": reason_msg}


@router.post("/api/streamer/voting/proposals/{proposal_id}/reject")
async def streamer_voting_reject(proposal_id: int, request: Request):
    """Стример отклоняет предложение (ничего не списывается)."""
    cid = _streamer_channel(request)
    if cid is None:
        return {"success": False, "message": "Нет сессии стримера"}
    db = get_db()
    ok = await db.reject_voting_proposal(proposal_id, channel_id=cid)
    return {"success": ok, "message": "Отклонено" if ok else "Не найдено"}
