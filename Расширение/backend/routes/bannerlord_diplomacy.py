"""
Sprint 5.33 (BLT-parity DIPLO) — Kingdom diplomacy (Lait fork inspired).

3 actions:
  hero.enact_policy   — viewer-king proposes & passes kingdom policy
  hero.make_peace     — viewer-king offers peace с enemy kingdom
  hero.pay_ransom     — any viewer pays into ransom pool для captured hero

Также endpoints для UI:
  GET /api/bannerlord/kingdom-state — мой kingdom + active policies + wars + captures
  GET /api/bannerlord/ransom-pool   — текущий pool для each captured hero

Mod-side responsibilities (PartyOrderBehavior + diplomacy hooks):
  - На pending policy request → KingdomDecision.AddNewDecision(EnactPolicyDecision)
  - На peace offer → MakePeaceAction.Apply(my_kingdom, target, tribute)
  - На enqueued ransom-release (когда pool достиг cost) →
    EndCaptivityAction.ApplyByRansom(prisoner, payer)

Backend держит state-of-truth для viewers; mod при connect читает pending
requests и применяет engine API на next OnHourly tick.
"""
from __future__ import annotations

import logging
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Request

from auth import require_jwt_user
from dependencies import get_db

log = logging.getLogger(__name__)
router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "auth required"}

# Ransom cost scaling — base + per-tier multiplier. Mirror кладём в frontend
# для preview, но source-of-truth тут backend.
RANSOM_BASE_COST = 1_500       # крустиков total pool за low-tier hero
RANSOM_PER_TIER = 1_000        # дополнительный per gear-tier viewer'а


# ─── GET endpoints ────────────────────────────────────────────────────────────


@router.get("/api/bannerlord/kingdom-state")
async def my_kingdom_state(request: Request):
    """Compact view: am I king? Active policies? Wars? Captured (me)?"""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        # Мой hero state из cache — нужны kingdom_id + is_king flag.
        cur = await conn.execute(
            "SELECT kingdom_id, kingdom_name, is_clan_leader, is_king, captured "
            "FROM bannerlord_heroes "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
        if not row:
            return {"success": True, "has_hero": False}
        kingdom_id, kingdom_name, is_clan_leader, is_king, captured = (
            row[0], row[1], bool(row[2]), bool(row[3]), bool(row[4]))

        # Active policy requests для моего kingdom'а.
        policies_pending = []
        policies_enacted = []
        if kingdom_id:
            cur = await conn.execute(
                "SELECT id, policy_id, policy_name, requester, status, requested_at "
                "FROM bannerlord_policy_requests "
                "WHERE channel_id=? AND kingdom_id=? "
                "  AND status IN ('pending','enacted') "
                "ORDER BY requested_at DESC LIMIT 30",
                (channel_id, kingdom_id))
            for r in await cur.fetchall():
                bucket = policies_pending if r[4] == "pending" else policies_enacted
                bucket.append({
                    "id":           r[0],
                    "policy_id":    r[1],
                    "policy_name":  r[2],
                    "requester":    r[3],
                    "status":       r[4],
                    "requested_at": r[5],
                })

        # Pending peace offers (sender side).
        peace_offers = []
        if kingdom_id:
            cur = await conn.execute(
                "SELECT id, target_kingdom_id, target_kingdom_name, "
                "       offered_tribute, status, offered_at "
                "FROM bannerlord_peace_offers "
                "WHERE channel_id=? AND my_kingdom_id=? "
                "  AND status='pending' "
                "ORDER BY offered_at DESC LIMIT 10",
                (channel_id, kingdom_id))
            for r in await cur.fetchall():
                peace_offers.append({
                    "id":                  r[0],
                    "target_kingdom_id":   r[1],
                    "target_kingdom_name": r[2],
                    "offered_tribute":     r[3],
                    "status":              r[4],
                    "offered_at":          r[5],
                })

    return {
        "success":          True,
        "has_hero":         True,
        "kingdom_id":       kingdom_id,
        "kingdom_name":     kingdom_name,
        "is_clan_leader":   is_clan_leader,
        "is_king":          is_king,
        "captured":         captured,
        "policies_pending": policies_pending,
        "policies_enacted": policies_enacted,
        "peace_offers":     peace_offers,
    }


@router.get("/api/bannerlord/ransom-pool")
async def ransom_pool_status(request: Request):
    """Все captured heroes канала + текущий pool per hero.

    Любой авторизованный viewer видит pools — чтобы решать кому помочь.
    """
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _username, channel_id = auth

    async with get_db()._connect() as conn:
        # Все captured viewers (по cache).
        cur = await conn.execute(
            "SELECT username, gear_tier, level, captor_party "
            "FROM bannerlord_heroes "
            "WHERE channel_id=? AND captured=1 "
            "ORDER BY username",
            (channel_id,))
        captured_rows = await cur.fetchall()

        result = []
        for cr in captured_rows:
            uname, gear_tier, level, captor = cr[0], cr[1] or 1, cr[2] or 0, cr[3]
            cost = RANSOM_BASE_COST + RANSOM_PER_TIER * max(0, (gear_tier or 1) - 1)
            # Sum pool.
            cur = await conn.execute(
                "SELECT COALESCE(SUM(amount),0), COUNT(*) "
                "FROM bannerlord_ransom_pool "
                "WHERE channel_id=? AND captured_hero=? AND status='pooled'",
                (channel_id, uname))
            pool_row = await cur.fetchone()
            pool_total = pool_row[0] or 0
            contributors_count = pool_row[1] or 0
            result.append({
                "captured_hero": uname,
                "gear_tier":     gear_tier,
                "level":         level,
                "captor_party":  captor,
                "ransom_cost":   cost,
                "pool_total":    pool_total,
                "contributors":  contributors_count,
                "remaining":     max(0, cost - pool_total),
            })
    return {"success": True, "captures": result}


# ─── Action handlers ──────────────────────────────────────────────────────────


async def handle_enact_policy(conn, channel_id: int, owner: str, data: dict) -> dict:
    """King-only: propose policy для своего kingdom'а. Mod применит engine API."""
    policy_id = (data.get("policy_id") or "").strip()
    policy_name = (data.get("policy_name") or "").strip() or policy_id
    log.info("[DIPLO-POLICY ENTRY] ch=%s @%s policy=%s name='%s'",
             channel_id, owner, policy_id, policy_name)
    if not policy_id or len(policy_id) < 3:
        log.info("[DIPLO-POLICY REFUSE] invalid policy_id ch=%s @%s raw=%r",
                 channel_id, owner, policy_id)
        return {"success": False, "message": "policy_id required (≥3 chars)"}

    # Check: viewer должен быть king (или хотя бы clan leader в kingdom).
    cur = await conn.execute(
        "SELECT kingdom_id, kingdom_name, is_king, is_clan_leader "
        "FROM bannerlord_heroes "
        "WHERE channel_id=? AND username=?",
        (channel_id, owner))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "hero не найден"}
    kingdom_id, kingdom_name, is_king, is_clan_leader = (
        row[0], row[1], bool(row[2]), bool(row[3]))
    if not kingdom_id:
        return {"success": False, "message": "Не состоишь в kingdom'е"}
    if not is_king and not is_clan_leader:
        return {"success": False, "message": "Только король/лидер клана может предлагать политики"}

    # INSERT (UNIQUE partial idx защищает от dupe pending).
    try:
        await conn.execute(
            "INSERT INTO bannerlord_policy_requests "
            "(channel_id, requester, kingdom_id, policy_id, policy_name, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (channel_id, owner, kingdom_id, policy_id, policy_name))
    except Exception as e:
        # UNIQUE conflict — already pending.
        log.info("[DIPLO-POL] dupe @%s ch=%s policy=%s: %s", owner, channel_id, policy_id, e)
        return {"success": False, "message": "Эта политика уже на голосовании"}

    # Enqueue mod-action.
    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":   owner,
        "target":         owner,
        "kingdom_id":     kingdom_id,
        "policy_id":      policy_id,
        "policy_name":    policy_name,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.enact_policy', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[DIPLO-POL] ch=%s king=@%s kingdom=%s policy=%s",
             channel_id, owner, kingdom_name, policy_name)
    return {
        "success": True,
        "message": f"📜 Политика «{policy_name}» предложена",
    }


async def handle_make_peace(conn, channel_id: int, owner: str, data: dict) -> dict:
    """King-only: peace offer с target kingdom'ом. Mod применит MakePeaceAction."""
    target_kingdom_id = (data.get("target_kingdom_id") or "").strip()
    target_kingdom_name = (data.get("target_kingdom_name") or "").strip() or target_kingdom_id
    try:
        offered_tribute = int(data.get("offered_tribute") or 0)
    except (TypeError, ValueError):
        offered_tribute = 0
    offered_tribute = max(-10_000, min(10_000, offered_tribute))  # cap

    log.info("[DIPLO-PEACE ENTRY] ch=%s @%s target='%s' (id=%s) tribute=%d",
             channel_id, owner, target_kingdom_name, target_kingdom_id, offered_tribute)

    if not target_kingdom_id or len(target_kingdom_id) < 2:
        log.info("[DIPLO-PEACE REFUSE] missing target_kingdom_id ch=%s @%s",
                 channel_id, owner)
        return {"success": False, "message": "target_kingdom_id required"}

    # Check: viewer должен быть king.
    cur = await conn.execute(
        "SELECT kingdom_id, kingdom_name, is_king "
        "FROM bannerlord_heroes "
        "WHERE channel_id=? AND username=?",
        (channel_id, owner))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "hero не найден"}
    my_kingdom_id, my_kingdom_name, is_king = row[0], row[1], bool(row[2])
    if not my_kingdom_id:
        return {"success": False, "message": "Не состоишь в kingdom'е"}
    if not is_king:
        return {"success": False, "message": "Только король может предлагать peace"}
    if my_kingdom_id == target_kingdom_id:
        return {"success": False, "message": "Нельзя сделать peace с самим собой"}

    try:
        await conn.execute(
            "INSERT INTO bannerlord_peace_offers "
            "(channel_id, requester, my_kingdom_id, target_kingdom_id, "
            " target_kingdom_name, offered_tribute, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (channel_id, owner, my_kingdom_id, target_kingdom_id,
             target_kingdom_name, offered_tribute))
    except Exception as e:
        log.info("[DIPLO-PEACE] dupe @%s ch=%s target=%s: %s",
                 owner, channel_id, target_kingdom_id, e)
        return {"success": False, "message": "Peace offer уже отправлен"}

    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":         owner,
        "target":               owner,
        "my_kingdom_id":        my_kingdom_id,
        "target_kingdom_id":    target_kingdom_id,
        "target_kingdom_name":  target_kingdom_name,
        "offered_tribute":      offered_tribute,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.make_peace', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[DIPLO-PEACE] ch=%s king=@%s %s → %s tribute=%s",
             channel_id, owner, my_kingdom_name, target_kingdom_name, offered_tribute)
    return {
        "success": True,
        "message": f"🕊 Peace offer → {target_kingdom_name} (tribute={offered_tribute})",
    }


async def handle_pay_ransom(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Any viewer: chip into ransom pool для captured hero.

    Когда pool ≥ cost — backend сам enqueues release-action и mod применяет.
    """
    captured = (data.get("captured_hero") or "").strip().lower()
    log.info("[DIPLO-RANSOM ENTRY] ch=%s contributor=@%s captured=@%s",
             channel_id, owner, captured)
    if not captured:
        log.info("[DIPLO-RANSOM REFUSE] missing captured_hero ch=%s @%s",
                 channel_id, owner)
        return {"success": False, "message": "captured_hero required"}
    # 5.33 — fixed contribution per pay action (UI shows total pool progress).
    # 500⦷ = ACTION_PRICES_DEFAULT — viewer оплачивает крустиками side-track,
    # это backend-only side-effect.
    contribution = 500

    # Verify captured hero exists + captured=1.
    cur = await conn.execute(
        "SELECT gear_tier, captor_party, captured "
        "FROM bannerlord_heroes "
        "WHERE channel_id=? AND username=?",
        (channel_id, captured))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": f"@{captured} — нет героя в кэше"}
    gear_tier = row[0] or 1
    captor_party = row[1] or ""
    if not bool(row[2]):
        return {"success": False, "message": f"@{captured} не в плену"}

    cost = RANSOM_BASE_COST + RANSOM_PER_TIER * max(0, gear_tier - 1)

    # INSERT contribution.
    await conn.execute(
        "INSERT INTO bannerlord_ransom_pool "
        "(channel_id, captured_hero, contributor, amount, status) "
        "VALUES (?, ?, ?, ?, 'pooled')",
        (channel_id, captured, owner, contribution))

    # Check if pool reached cost.
    cur = await conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM bannerlord_ransom_pool "
        "WHERE channel_id=? AND captured_hero=? AND status='pooled'",
        (channel_id, captured))
    pool_row = await cur.fetchone()
    pool_total = pool_row[0] or 0

    log.info("[DIPLO-RANSOM] ch=%s @%s contributed %d to @%s pool — total=%d/%d",
             channel_id, owner, contribution, captured, pool_total, cost)

    if pool_total >= cost:
        # Pool full → enqueue release action + mark contributions released.
        action_id = _uuid.uuid4().hex
        payload = {
            "initiated_by":  captured,
            "target":        captured,
            "captured_hero": captured,
            "captor_party":  captor_party,
            "pool_total":    pool_total,
        }
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'hero.pay_ransom', ?, 'queued')",
            (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))
        await conn.execute(
            "UPDATE bannerlord_ransom_pool SET status='released' "
            "WHERE channel_id=? AND captured_hero=? AND status='pooled'",
            (channel_id, captured))
        log.info("[DIPLO-RANSOM] POOL FULL ch=%s @%s released action_id=%s",
                 channel_id, captured, action_id)
        return {
            "success": True,
            "message": f"💰 Pool ПОЛНЫЙ! @{captured} освобождается",
        }
    return {
        "success": True,
        "message": f"💰 Вложено {contribution}⦷ — pool {pool_total}/{cost}",
    }
