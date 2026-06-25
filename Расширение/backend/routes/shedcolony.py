"""
routes/shedcolony.py — viewer-facing endpoints для модуля ShedColony.

  POST /api/shedcolony/action       — купить действие (списать крустики + enqueue в module_actions)
  GET  /api/shedcolony/my-colonist  — состояние СВОЕГО колониста (link + state)
  GET  /api/shedcolony/capacity      — свободные слоты колонии (для slot-availability UI)

Зеркалит проверенный bannerlord buy-паттерн (routes/bannerlord.py):
require_jwt_user → per-user lock → allowlist → server-side price → atomic charge + enqueue.
Мод забирает action'ы через generic Module API (routes/module_api.py) long-poll'ом.

БЕЗОПАСНОСТЬ: и username, и channel_id берутся ТОЛЬКО из JWT. citizen_id для действий над
колонистом РЕЗОЛВИТСЯ на сервере из link-таблицы (клиентский citizen_id игнорируется), иначе
зритель мог бы управлять чужим колонистом.

COMPLIANCE: price+initiated_by кладутся в data → провал действия (ack success=false) авто-рефандит
крустики через ShedColonyAdapter._on_action_failed. Цены — только тут (server-enforced).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()
log = logging.getLogger("rimlink.shedcolony")

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}

# ── Per-(channel, user) asyncio lock — double-spend prevention (как в bannerlord) ──
_user_action_locks: dict[tuple[int, str], asyncio.Lock] = {}
_user_action_locks_meta_lock = asyncio.Lock()


async def _get_user_lock(channel_id: int, username: str) -> asyncio.Lock:
    key = (channel_id, (username or "").lower())
    if key not in _user_action_locks:
        async with _user_action_locks_meta_lock:
            if key not in _user_action_locks:
                _user_action_locks[key] = asyncio.Lock()
    return _user_action_locks[key]


# ── Allowlist — MUST match modules/shedcolony/manifest.yaml extensions.actions ──
_PURCHASABLE_ACTIONS = (
    "colonist.spawn",
    "colonist.assign_job",
    "colonist.assign_home",
    "colonist.add_xp",
    "colonist.fulfill_request",
)

# Server-side prices — viewer-supplied price is IGNORED (frontend draws what backend sends).
_ACTION_PRICES: dict[str, int] = {
    "colonist.spawn":           1000,
    "colonist.assign_job":       300,
    "colonist.assign_home":      200,
    "colonist.add_xp":           150,
    "colonist.fulfill_request":  100,
}

# Fixed XP per add_xp purchase (viewer picks the skill, server fixes the amount).
_XP_AMOUNT = 1000

# Actions that operate on the viewer's EXISTING colonist (need a resolved citizen_id).
_NEEDS_CITIZEN = (
    "colonist.assign_job",
    "colonist.assign_home",
    "colonist.add_xp",
    "colonist.fulfill_request",
)


async def _resolve_citizen(conn, channel_id: int, viewer: str) -> str | None:
    """The viewer's own active colonist id, from the link table. None if not linked."""
    cur = await conn.execute(
        "SELECT citizen_id FROM shedcolony_colony_link "
        "WHERE channel_id=? AND viewer_id=? AND status='active'",
        (channel_id, viewer))
    row = await cur.fetchone()
    return row[0] if row else None


async def _charge_and_enqueue(action_type: str, data: dict, price: int,
                              username: str, channel_id: int) -> tuple[str, None] | dict:
    """BEGIN IMMEDIATE: idempotency + atomic charge + enqueue. Mirrors bannerlord.

    Stores price + initiated_by + viewer_id in the enqueued data so the mod can act and so a
    failed action auto-refunds. Returns (action_id, None) or a refusal-dict.
    """
    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            # ── Idempotency replay (client_action_id) ──
            client_action_id = (data.get("client_action_id") or "").strip() or None
            if client_action_id:
                cur = await conn.execute(
                    "SELECT action_id FROM module_actions "
                    "WHERE channel_id=? AND module_id='shedcolony' AND client_action_id=? LIMIT 1",
                    (channel_id, client_action_id))
                row = await cur.fetchone()
                if row:
                    await conn.execute("ROLLBACK")
                    return {"success": True, "message": "Действие уже принято",
                            "action_id": row[0], "idempotent_replay": True}

            # ── Atomic charge ──
            if price > 0:
                cur = await conn.execute(
                    "UPDATE viewers SET points = points - ? "
                    "WHERE channel_id=? AND username=? AND points >= ?",
                    (price, channel_id, username, price))
                if cur.rowcount != 1:
                    cur2 = await conn.execute(
                        "SELECT points FROM viewers WHERE channel_id=? AND username=?",
                        (channel_id, username))
                    bal_row = await cur2.fetchone()
                    balance = (bal_row[0] if bal_row else 0) or 0
                    await conn.execute("ROLLBACK")
                    return {"success": False,
                            "message": f"Недостаточно крустиков: {balance} < {price}"}

            # ── Enqueue (price + initiated_by → refund-on-failure; viewer_id → mod identity) ──
            action_id = uuid.uuid4().hex
            payload = dict(data)
            payload["initiated_by"] = username
            payload["viewer_id"] = username
            payload["price"] = price
            await conn.execute(
                "INSERT INTO module_actions "
                "(channel_id, module_id, action_id, type, data, status, client_action_id) "
                "VALUES (?, 'shedcolony', ?, ?, ?, 'queued', ?)",
                (channel_id, action_id, action_type,
                 json.dumps(payload, ensure_ascii=False), client_action_id))

            await conn.commit()
        except Exception as ex:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            log.exception("[shedcolony buy] commit failed ch=%s user=%s action=%s: %s",
                          channel_id, username, action_type, ex)
            raise
    return (action_id, None)


async def _buy_action_locked(username: str, channel_id: int,
                             action_type: str, data: dict) -> dict:
    # Allowlist + server-side price
    if action_type not in _PURCHASABLE_ACTIONS:
        return {"success": False, "message": f"Действие '{action_type}' не разрешено"}
    price = _ACTION_PRICES.get(action_type)
    if price is None:
        return {"success": False, "message": f"У '{action_type}' нет server-side цены"}
    data["price"] = price   # hard override

    db = get_db()
    # Resolve the viewer's own colonist server-side for colonist-targeted actions.
    if action_type in _NEEDS_CITIZEN:
        async with db._connect() as conn:
            citizen_id = await _resolve_citizen(conn, channel_id, username)
        if not citizen_id:
            return {"success": False, "message": "У тебя ещё нет колониста — сначала создай его"}
        data["citizen_id"] = citizen_id   # override any client-supplied value (security)

    if action_type == "colonist.spawn":
        # 1 viewer = 1 colonist: refuse a second spawn while one is alive (UI hides the
        # button, but the request is craftable — without this a re-roll burns 1000💎).
        async with db._connect() as conn:
            existing = await _resolve_citizen(conn, channel_id, username)
        if existing:
            return {"success": False, "message": "У тебя уже есть колонист в этой колонии"}
        data["name"] = username           # MVP: colonist named after the viewer
    elif action_type == "colonist.add_xp":
        data["amount"] = _XP_AMOUNT        # server-fixed XP per purchase

    result = await _charge_and_enqueue(action_type, data, price, username, channel_id)
    if isinstance(result, dict):
        return result
    action_id, _ = result
    log.info("[shedcolony ENQUEUE] action=%s user=@%s ch=%s price=%s id=%s",
             action_type, username, channel_id, price, action_id)
    return {"success": True, "action_id": action_id, "charged": price,
            "message": f"Действие в очереди ({price}💎 списано)"}


@router.post("/api/shedcolony/action")
async def shedcolony_buy_action(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    body = await request.json()
    action_type = (body.get("action_type") or "").strip()
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return {"success": False, "message": "data должен быть объектом"}

    user_lock = await _get_user_lock(channel_id, username)
    async with user_lock:
        return await _buy_action_locked(username, channel_id, action_type, data)


@router.get("/api/shedcolony/my-colonist")
async def shedcolony_my_colonist(request: Request):
    """Состояние СВОЕГО колониста зрителя (link + state). {linked:false} если нет."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT l.citizen_id, l.status, s.hp, s.job, s.skills_json, s.status, s.state_json "
            "FROM shedcolony_colony_link l "
            "LEFT JOIN shedcolony_colonist_state s "
            "  ON s.channel_id = l.channel_id AND s.citizen_id = l.citizen_id "
            "WHERE l.channel_id=? AND l.viewer_id=? AND l.status='active'",
            (channel_id, username))
        row = await cur.fetchone()
    if not row:
        return {"success": True, "linked": False}

    citizen_id, link_status, hp, job, skills_json, state_status, state_json = row
    try:
        skills = json.loads(skills_json or "{}")
    except Exception:
        skills = {}
    try:
        state = json.loads(state_json) if state_json else None   # full rich blob from the mod
    except Exception:
        state = None
    return {"success": True, "linked": True, "citizen_id": citizen_id,
            "name": username, "job": job, "hp": hp, "skills": skills,
            "status": state_status or link_status, "state": state}


@router.get("/api/shedcolony/capacity")
async def shedcolony_capacity(request: Request):
    """Свободные слоты колонии (для slot-availability UI). Мод пушит снимок (colony.capacity)."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    jobs: list[dict] = []
    free_beds = None
    db = get_db()
    try:
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT job_key, free_slots, total_slots FROM shedcolony_capacity "
                "WHERE channel_id=? ORDER BY job_key", (channel_id,))
            jobs = [{"job": r[0], "free": r[1], "total": r[2]} for r in await cur.fetchall()]
            cur = await conn.execute(
                "SELECT free_beds, total_beds FROM shedcolony_capacity_meta WHERE channel_id=?",
                (channel_id,))
            meta = await cur.fetchone()
            if meta:
                free_beds = meta[0]
    except Exception as ex:
        log.warning("[shedcolony capacity] read failed ch=%s: %s", channel_id, ex)
    return {"success": True, "jobs": jobs, "free_beds": free_beds}
