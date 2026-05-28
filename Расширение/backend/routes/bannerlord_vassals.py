"""
Sprint 5.33 (BLT-parity VAS) — Vassal sub-clan system.

Endpoints:
  GET /api/bannerlord/vassals — list своих вассалов (parent_username = me)
  GET /api/bannerlord/eligible-heirs — список heirs которых можно выделить
                                       в vassals (взрослые + alive + не уже vassal-leader)

Actions handled in bannerlord.py _bannerlord_buy_action_locked:
  hero.create_vassal_clan — payload {heir_hero_id, vassal_name}
    → backend INSERT в bannerlord_vassals (vassal_clan_id заполняется mod'ом
      на response с clan_id через event hero.vassal_created)
    → enqueue mod-action with payload
  hero.rename_vassal — payload {vassal_clan_id, new_name}
    → backend UPDATE name + enqueue mod-action для Clan.SetClanName
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request

from dependencies import require_jwt_user
from dependencies import get_db

log = logging.getLogger(__name__)
router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "auth required"}


@router.get("/api/bannerlord/vassals")
async def my_vassals(request: Request):
    """Список своих вассалов. Returns {success, vassals: [...]}"""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, vassal_clan_id, vassal_leader_hero_id, vassal_name, "
            "       income_share_pct, banner_code, created_at "
            "FROM bannerlord_vassals "
            "WHERE channel_id=? AND parent_username=? "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, username))
        rows = await cur.fetchall()

    log.info("[VAS-LIST] ch=%s user=@%s vassals=%d", channel_id, username, len(rows))
    return {
        "success": True,
        "vassals": [
            {
                "id":               r[0],
                "vassal_clan_id":   r[1],
                "vassal_leader_hero_id": r[2],
                "vassal_name":      r[3],
                "income_share_pct": r[4],
                "banner_code":      r[5],
                "created_at":       r[6],
            }
            for r in rows
        ],
    }


@router.get("/api/bannerlord/eligible-heirs")
async def eligible_heirs(request: Request):
    """Heirs которые можно выделить в vassal-leader.

    Filter: alive, not activated (= не повысились до primary hero после parent's death),
            not уже vassal-leader.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        # Exclude heir_hero_ids которые уже vassal-leaders.
        cur = await conn.execute(
            "SELECT h.heir_hero_id, h.heir_name, h.came_of_age_at "
            "FROM bannerlord_heirs h "
            "WHERE h.channel_id=? AND h.parent_username=? "
            "AND h.alive=1 AND h.activated=0 "
            "AND NOT EXISTS ("
            "    SELECT 1 FROM bannerlord_vassals v "
            "    WHERE v.channel_id=h.channel_id "
            "      AND v.vassal_leader_hero_id=h.heir_hero_id"
            ") "
            "ORDER BY h.came_of_age_at DESC LIMIT 20",
            (channel_id, username))
        rows = await cur.fetchall()

    return {
        "success": True,
        "heirs": [
            {"hero_id": r[0], "name": r[1], "came_of_age_at": r[2]}
            for r in rows
        ],
    }


# ─── Action handlers вызываются из _bannerlord_buy_action_locked ───────────────


async def handle_create_vassal(conn, channel_id: int, parent_user: str, data: dict) -> dict:
    """Sprint 5.33 VAS — validate + INSERT vassal row + enqueue mod action.

    Mod handler `hero.create_vassal_clan` потом сам через event возвращает
    vassal_clan_id (engine assigns на CreateClan), backend updates row.
    """
    import json as _json
    import uuid as _uuid

    heir_hero_id = (data.get("heir_hero_id") or "").strip()
    vassal_name = (data.get("vassal_name") or "").strip()
    if not heir_hero_id:
        return {"success": False, "message": "Нужен heir_hero_id"}
    if not vassal_name or len(vassal_name) > 50:
        return {"success": False, "message": "Имя клана 1-50 символов"}

    # Validate heir belongs to parent.
    cur = await conn.execute(
        "SELECT heir_name FROM bannerlord_heirs "
        "WHERE channel_id=? AND parent_username=? AND heir_hero_id=? "
        "AND alive=1 AND activated=0",
        (channel_id, parent_user, heir_hero_id))
    heir_row = await cur.fetchone()
    if not heir_row:
        return {"success": False, "message": "Наследник не найден или активирован"}
    heir_name = heir_row[0]

    # Check not already vassal-leader.
    cur = await conn.execute(
        "SELECT 1 FROM bannerlord_vassals "
        "WHERE channel_id=? AND vassal_leader_hero_id=?",
        (channel_id, heir_hero_id))
    if await cur.fetchone():
        return {"success": False, "message": f"'{heir_name}' уже лидер вассала"}

    # Vassal limit per parent (anti-spam — viewer должен hard выбирать).
    cur = await conn.execute(
        "SELECT COUNT(*) FROM bannerlord_vassals "
        "WHERE channel_id=? AND parent_username=?",
        (channel_id, parent_user))
    cnt_row = await cur.fetchone()
    if cnt_row and cnt_row[0] >= 5:
        return {"success": False,
                "message": f"Максимум 5 вассалов. Сейчас: {cnt_row[0]}"}

    # INSERT initial row — vassal_clan_id будет updated mod'ом через event.
    # Placeholder ID = "pending_{action_id}" — mod заменит на реальный.
    action_id = _uuid.uuid4().hex
    placeholder_clan_id = f"pending_{action_id[:16]}"
    await conn.execute(
        "INSERT INTO bannerlord_vassals "
        "(channel_id, parent_username, vassal_clan_id, vassal_leader_hero_id, "
        " vassal_name, income_share_pct) "
        "VALUES (?, ?, ?, ?, ?, 25.0)",
        (channel_id, parent_user, placeholder_clan_id, heir_hero_id, vassal_name))

    # Enqueue mod-action. Mod создаст Clan через engine API + push event
    # `hero.vassal_created` с реальным clan_id для backend UPDATE.
    payload = {
        "initiated_by":         parent_user,
        "target":               parent_user,
        "parent_username":      parent_user,
        "heir_hero_id":         heir_hero_id,
        "heir_name":            heir_name,
        "vassal_name":          vassal_name,
        "placeholder_clan_id":  placeholder_clan_id,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.create_vassal_clan', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[VAS-CREATE] ch=%s parent=@%s heir='%s' vassal='%s' placeholder=%s",
             channel_id, parent_user, heir_name, vassal_name, placeholder_clan_id)
    return {
        "success": True,
        "message": f"🏰 Создание вассала '{vassal_name}' (leader: {heir_name}). "
                   f"Engine применит через ~1 сек.",
        "placeholder_clan_id": placeholder_clan_id,
    }


async def handle_rename_vassal(conn, channel_id: int, parent_user: str, data: dict) -> dict:
    """Sprint 5.33 VAS — rename vassal clan + enqueue mod action."""
    import json as _json
    import uuid as _uuid

    try:
        vassal_id = int(data.get("vassal_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный vassal_id"}
    new_name = (data.get("new_name") or "").strip()
    if not new_name or len(new_name) > 50:
        return {"success": False, "message": "Имя 1-50 символов"}

    cur = await conn.execute(
        "SELECT vassal_clan_id, vassal_name FROM bannerlord_vassals "
        "WHERE id=? AND channel_id=? AND parent_username=?",
        (vassal_id, channel_id, parent_user))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "Вассал не найден"}
    vassal_clan_id, old_name = row

    await conn.execute(
        "UPDATE bannerlord_vassals SET vassal_name=? WHERE id=?",
        (new_name, vassal_id))

    # Enqueue mod-action — Clan.SetClanName в-game.
    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":    parent_user,
        "target":          parent_user,
        "vassal_clan_id":  vassal_clan_id,
        "new_name":        new_name,
        "old_name":        old_name,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.rename_vassal', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[VAS-RENAME] ch=%s parent=@%s vassal_id=%d '%s' → '%s'",
             channel_id, parent_user, vassal_id, old_name, new_name)
    return {
        "success": True,
        "message": f"🏰 '{old_name}' → '{new_name}'",
    }
