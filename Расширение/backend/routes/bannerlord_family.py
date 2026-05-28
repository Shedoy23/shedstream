"""
Sprint 5.33 / BLT-parity FAM — Viewer↔Viewer marriage proposals между взрослыми детьми.

Inspiration: Randomchair22/Bannerlord-Twitch + Lait96-fork — самая виральная
фича из всех найденных в community forks. Превращает чат в multi-generation
soap-opera, плюс retention loop (дети → grand-children → great-grand → ...).

## Flow

1. Viewer A покупает `hero.propose_marriage` action с payload:
     {proposer_child_hero_id, target_username, target_child_hero_id}
   → backend INSERT в bannerlord_marriage_proposals (status='pending', +24h expiry)
   → push event (TODO: bot notify в Twitch chat?)

2. Viewer B видит proposal в Hero pane → `bnr-incoming-proposals-badge` показывает count
3. Viewer B покупает `hero.respond_marriage_proposal` с {proposal_id, accept: bool}
   → if accept: UPDATE status='accepted' + enqueue mod-action `hero.activate_marriage`
                с payload {child_a_hero_id, child_b_hero_id}
   → if reject: UPDATE status='rejected'

4. Mod handler `ActivateMarriageHandler` (новый, mod-side):
   → resolve обоих heroes через MBObjectManager.GetObject<Hero>
   → Hero.Spouse = other Hero (mutual)
   → engine handles clan transfer + dynastic linkage natively
   → push event `hero.marriage_activated` для logging

5. Background loop (новый — `_proposals_expire_loop` в main.py):
   → каждые 60s mark expired pending proposals (created+24h < now) → status='expired'

## Endpoints

  GET  /api/bannerlord/my-children      — список своих живых > 18 heirs
  GET  /api/bannerlord/public-children  — ?username=X — для UI dropdown в propose modal
  GET  /api/bannerlord/proposals        — incoming + outgoing pending

Propose/respond/cancel actions handled через общий /api/bannerlord/action endpoint
(POST /api/bannerlord/family/* handlers are здесь же для clarity).
"""
from __future__ import annotations

import logging
import time
from fastapi import APIRouter, Request

from dependencies import require_jwt_user
from dependencies import get_db

log = logging.getLogger(__name__)
router = APIRouter()


_AUTH_FAIL = {"success": False, "message": "auth required"}


@router.get("/api/bannerlord/my-children")
async def my_children(request: Request):
    """Список своих взрослых детей (heirs из M48) для UI.

    Returns: {success, children: [{hero_id, name, came_of_age_at}]}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT heir_hero_id, heir_name, came_of_age_at "
            "FROM bannerlord_heirs "
            "WHERE channel_id=? AND parent_username=? "
            "AND alive=1 AND activated=0 "
            "ORDER BY came_of_age_at DESC",
            (channel_id, username))
        rows = await cur.fetchall()

    return {
        "success": True,
        "children": [
            {"hero_id": r[0], "name": r[1], "came_of_age_at": r[2]}
            for r in rows
        ],
    }


@router.get("/api/bannerlord/public-children")
async def public_children(request: Request):
    """Список взрослых детей **другого** viewer'а — для UI dropdown в propose modal.

    Query: ?username=other_viewer
    Returns: {success, children: [{hero_id, name}]}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _, channel_id = auth

    target_username = (request.query_params.get("username") or "").strip().lower()
    if not target_username:
        return {"success": False, "message": "username query param required"}

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT heir_hero_id, heir_name "
            "FROM bannerlord_heirs "
            "WHERE channel_id=? AND parent_username=? "
            "AND alive=1 AND activated=0 "
            "ORDER BY came_of_age_at DESC",
            (channel_id, target_username))
        rows = await cur.fetchall()

    log.info("[FAM-PUB] ch=%s requester=@%s target=@%s children=%d",
             channel_id, auth[0], target_username, len(rows))
    return {
        "success": True,
        "target_username": target_username,
        "children": [
            {"hero_id": r[0], "name": r[1]} for r in rows
        ],
    }


@router.get("/api/bannerlord/proposals")
async def proposals(request: Request):
    """Pending proposals — incoming (to me) + outgoing (from me).

    Returns: {success, incoming: [...], outgoing: [...]}
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, proposer_username, proposer_child_name, "
            "       target_child_name, created_at, expires_at "
            "FROM bannerlord_marriage_proposals "
            "WHERE channel_id=? AND target_username=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, username))
        incoming_rows = await cur.fetchall()

        cur = await conn.execute(
            "SELECT id, target_username, proposer_child_name, "
            "       target_child_name, created_at, expires_at "
            "FROM bannerlord_marriage_proposals "
            "WHERE channel_id=? AND proposer_username=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, username))
        outgoing_rows = await cur.fetchall()

    return {
        "success": True,
        "incoming": [
            {
                "id": r[0],
                "proposer_username": r[1],
                "proposer_child_name": r[2],
                "target_child_name": r[3],
                "created_at": r[4],
                "expires_at": r[5],
            }
            for r in incoming_rows
        ],
        "outgoing": [
            {
                "id": r[0],
                "target_username": r[1],
                "proposer_child_name": r[2],
                "target_child_name": r[3],
                "created_at": r[4],
                "expires_at": r[5],
            }
            for r in outgoing_rows
        ],
    }


# ─── Action handler helpers — вызываются из routes/bannerlord.py:_bannerlord_buy_action_locked ────


async def handle_propose_marriage(conn, channel_id: int, proposer: str, data: dict) -> dict:
    """Sprint 5.33 FAM — внутри уже-открытой TX `_bannerlord_buy_action_locked`.

    Validation:
      - proposer_child_hero_id принадлежит proposer'у (в bannerlord_heirs)
      - target_username != proposer_username (нельзя свой ребёнок жениться на своём другом ребёнке)
      - target_child_hero_id принадлежит target_username
      - Нет уже pending proposal для этой пары (m49 UNIQUE partial index)

    Returns: {success, message, [proposal_id]} — caller привязывает к response.
    """
    proposer_child = (data.get("proposer_child_hero_id") or "").strip()
    target_user = (data.get("target_username") or "").strip().lower()
    target_child = (data.get("target_child_hero_id") or "").strip()

    if not proposer_child or not target_user or not target_child:
        return {"success": False,
                "message": "Нужны proposer_child_hero_id, target_username, target_child_hero_id"}
    if target_user == proposer:
        return {"success": False,
                "message": "Нельзя женить своих детей друг на друге"}

    # Validate proposer's child belongs to proposer.
    cur = await conn.execute(
        "SELECT heir_name FROM bannerlord_heirs "
        "WHERE channel_id=? AND parent_username=? AND heir_hero_id=? "
        "AND alive=1 AND activated=0",
        (channel_id, proposer, proposer_child))
    pc_row = await cur.fetchone()
    if not pc_row:
        return {"success": False,
                "message": "Твой ребёнок не найден / уже активирован / мёртв"}

    # Validate target's child.
    cur = await conn.execute(
        "SELECT heir_name FROM bannerlord_heirs "
        "WHERE channel_id=? AND parent_username=? AND heir_hero_id=? "
        "AND alive=1 AND activated=0",
        (channel_id, target_user, target_child))
    tc_row = await cur.fetchone()
    if not tc_row:
        return {"success": False,
                "message": f"У @{target_user} нет такого взрослого ребёнка"}

    # INSERT proposal. UNIQUE partial idx prevent дубликаты pending.
    try:
        cur = await conn.execute(
            "INSERT INTO bannerlord_marriage_proposals "
            "(channel_id, proposer_username, proposer_child_hero_id, proposer_child_name, "
            " target_username, target_child_hero_id, target_child_name, "
            " expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', '+24 hours')) "
            "RETURNING id",
            (channel_id, proposer, proposer_child, pc_row[0],
             target_user, target_child, tc_row[0]))
        row = await cur.fetchone()
        proposal_id = row[0] if row else None
    except Exception as ex:
        # UNIQUE constraint violation = уже есть pending для этой пары.
        if "UNIQUE" in str(ex) or "constraint" in str(ex).lower():
            return {"success": False,
                    "message": "Уже есть pending предложение для этих детей"}
        raise

    log.info("[FAM-PROPOSE] ch=%s proposer=@%s child='%s' → target=@%s child='%s' id=%d",
             channel_id, proposer, pc_row[0], target_user, tc_row[0], proposal_id)

    return {
        "success": True,
        "message": f"💍 Предложение @{target_user}: «поженить {pc_row[0]} и {tc_row[0]}»",
        "proposal_id": proposal_id,
    }


async def handle_respond_marriage(conn, channel_id: int, responder: str, data: dict) -> dict:
    """Sprint 5.33 FAM — accept/reject proposal.

    Returns: {success, message, [action_id]} — action_id если accept (enqueue mod activate).
    """
    import json as _json
    import uuid as _uuid

    try:
        proposal_id = int(data.get("proposal_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный proposal_id"}
    if proposal_id <= 0:
        return {"success": False, "message": "proposal_id required"}

    accept = bool(data.get("accept"))

    cur = await conn.execute(
        "SELECT proposer_username, proposer_child_hero_id, proposer_child_name, "
        "       target_username, target_child_hero_id, target_child_name, status "
        "FROM bannerlord_marriage_proposals "
        "WHERE id=? AND channel_id=?",
        (proposal_id, channel_id))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "Предложение не найдено"}
    proposer, p_child_id, p_child_name, target, t_child_id, t_child_name, status = row
    if target != responder:
        return {"success": False, "message": "Это не твоё предложение"}
    if status != "pending":
        return {"success": False, "message": f"Уже {status}"}

    new_status = "accepted" if accept else "rejected"
    await conn.execute(
        "UPDATE bannerlord_marriage_proposals "
        "SET status=?, resolved_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (new_status, proposal_id))

    action_id = None
    if accept:
        # Enqueue mod-action `hero.activate_marriage` с обоими hero_id'ами.
        action_id = _uuid.uuid4().hex
        payload = {
            "initiated_by":     responder,
            "target":           responder,
            "proposal_id":      proposal_id,
            "child_a_hero_id":  p_child_id,
            "child_a_name":     p_child_name,
            "child_b_hero_id":  t_child_id,
            "child_b_name":     t_child_name,
            "proposer_username": proposer,
            "target_username":   target,
        }
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'hero.activate_marriage', ?, 'queued')",
            (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[FAM-RESPOND] ch=%s responder=@%s proposal=%d %s",
             channel_id, responder, proposal_id, new_status.upper())
    return {
        "success": True,
        "message": (f"💍 Принято — браку быть! ({p_child_name} ❤ {t_child_name})"
                    if accept else
                    f"💔 Отклонено"),
        "action_id": action_id,
    }


async def handle_cancel_proposal(conn, channel_id: int, proposer: str, data: dict) -> dict:
    """Sprint 5.33 FAM — withdraw own proposal (only pending)."""
    try:
        proposal_id = int(data.get("proposal_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный proposal_id"}
    if proposal_id <= 0:
        return {"success": False, "message": "proposal_id required"}

    cur = await conn.execute(
        "UPDATE bannerlord_marriage_proposals "
        "SET status='cancelled', resolved_at=CURRENT_TIMESTAMP "
        "WHERE id=? AND channel_id=? AND proposer_username=? AND status='pending'",
        (proposal_id, channel_id, proposer))
    affected = cur.rowcount
    if affected == 0:
        return {"success": False,
                "message": "Предложение не найдено / уже resolved / не твоё"}
    log.info("[FAM-CANCEL] ch=%s proposer=@%s proposal=%d",
             channel_id, proposer, proposal_id)
    return {"success": True, "message": "Предложение отозвано"}


async def expire_old_proposals(channel_id: int = None) -> int:
    """Sprint 5.33 FAM — periodic background loop в main.py.

    Mark pending proposals as 'expired' если created_at + 24h < now.
    Returns affected count.
    """
    db = get_db()
    async with db._connect() as conn:
        if channel_id is None:
            cur = await conn.execute(
                "UPDATE bannerlord_marriage_proposals "
                "SET status='expired', resolved_at=CURRENT_TIMESTAMP "
                "WHERE status='pending' AND datetime(expires_at) < datetime('now')")
        else:
            cur = await conn.execute(
                "UPDATE bannerlord_marriage_proposals "
                "SET status='expired', resolved_at=CURRENT_TIMESTAMP "
                "WHERE status='pending' AND datetime(expires_at) < datetime('now') "
                "AND channel_id=?", (channel_id,))
        await conn.commit()
        return cur.rowcount or 0
