"""
Sprint 5.33 (BLT-parity CARAVAN) — Mobile passive income + rescue events.

Closes passive trilogy: SHOP (static) + FIEF (territorial) + CARAVAN (mobile risk).

Ratios:
  SHOP    = 100:1 dinars→crustic (static workshop)
  CARAVAN = 150:1                (mid — mobile, traveling)
  FIEF    = 200:1                (territorial, kingdom-scale)

CARAVAN has emotional capture/destroyed events — when bandits destroy your
caravan, рассылается чату rescue-pool opportunity (parallel to ransom).

Endpoints:
  GET /api/bannerlord/my-caravans
  GET /api/bannerlord/caravan-rescues  — destroyed caravans waiting rescue

Actions:
  hero.buy_caravan          — create new caravan (1500⦷ + 15K Hero.Gold)
  hero.sell_caravan         — disband / sell к MainHero
  hero.pay_caravan_rescue   — chip into rescue pool — backend respawns when full
"""
from __future__ import annotations

import logging
import json as _json
import uuid as _uuid

from fastapi import APIRouter, Request

from dependencies import require_jwt_user
from dependencies import get_db

log = logging.getLogger(__name__)
router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "auth required"}

DINAR_TO_CRUSTIC_CARAVAN = 150
MAX_CARAVANS_PER_VIEWER = 2  # tighter than workshops — caravans more powerful
CARAVAN_RESCUE_COST = 2500     # крустики total to respawn destroyed caravan


# ─── GET endpoints ────────────────────────────────────────────────────────────


@router.get("/api/bannerlord/my-caravans")
async def my_caravans(request: Request):
    """Список моих active caravans."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, party_id, home_settlement_id, home_settlement_name, "
            "       initial_capital, total_collected_dinars, "
            "       last_synced_at, opened_at, status, destroyed_at "
            "FROM bannerlord_caravans "
            "WHERE channel_id=? AND owner_username=? "
            "  AND status IN ('active','destroyed') "
            "ORDER BY opened_at ASC",
            (channel_id, username))
        rows = await cur.fetchall()

    caravans = []
    for r in rows:
        caravans.append({
            "id":                     r[0],
            "party_id":               r[1],
            "home_settlement_id":     r[2],
            "home_settlement_name":   r[3],
            "initial_capital":        r[4] or 0,
            "total_collected_dinars": r[5] or 0,
            "estimated_crustic":      (r[5] or 0) // DINAR_TO_CRUSTIC_CARAVAN,
            "last_synced_at":         r[6],
            "opened_at":              r[7],
            "status":                 r[8],
            "destroyed_at":           r[9],
        })
    return {
        "success":        True,
        "caravans":       caravans,
        "max_caravans":   MAX_CARAVANS_PER_VIEWER,
        "rescue_cost":    CARAVAN_RESCUE_COST,
    }


@router.get("/api/bannerlord/caravan-rescues")
async def caravan_rescues(request: Request):
    """Все destroyed caravans на канале + pool status — viewers могут помочь."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    _username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, owner_username, home_settlement_name, destroyed_at "
            "FROM bannerlord_caravans "
            "WHERE channel_id=? AND status='destroyed' "
            "ORDER BY destroyed_at DESC LIMIT 10",
            (channel_id,))
        rows = await cur.fetchall()
        result = []
        for r in rows:
            caravan_id = r[0]
            cur2 = await conn.execute(
                "SELECT COALESCE(SUM(amount),0), COUNT(*) "
                "FROM bannerlord_caravan_rescue_pool "
                "WHERE channel_id=? AND caravan_id=? AND status='pooled'",
                (channel_id, caravan_id))
            pool_row = await cur2.fetchone()
            pool_total = pool_row[0] or 0
            contributors = pool_row[1] or 0
            result.append({
                "caravan_id":       caravan_id,
                "owner":            r[1],
                "home_name":        r[2],
                "destroyed_at":     r[3],
                "pool_total":       pool_total,
                "contributors":     contributors,
                "rescue_cost":      CARAVAN_RESCUE_COST,
                "remaining":        max(0, CARAVAN_RESCUE_COST - pool_total),
            })
    return {"success": True, "rescues": result}


# ─── Action handlers ──────────────────────────────────────────────────────────


async def handle_buy_caravan(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Create new caravan. Mod вызывает CaravanPartyComponent.CreateCaravanParty."""
    home_settlement_id = (data.get("home_settlement_id") or "").strip()
    home_settlement_name = (data.get("home_settlement_name") or "").strip() or home_settlement_id
    log.info("[CARAVAN-BUY ENTRY] ch=%s @%s home=%s",
             channel_id, owner, home_settlement_id)
    if not home_settlement_id:
        log.info("[CARAVAN-BUY REFUSE] missing home_settlement_id ch=%s @%s",
                 channel_id, owner)
        return {"success": False, "message": "home_settlement_id required"}

    # Limit check.
    cur = await conn.execute(
        "SELECT COUNT(*) FROM bannerlord_caravans "
        "WHERE channel_id=? AND owner_username=? AND status='active'",
        (channel_id, owner))
    row = await cur.fetchone()
    if (row[0] or 0) >= MAX_CARAVANS_PER_VIEWER:
        return {"success": False,
                "message": f"Лимит караванов ({MAX_CARAVANS_PER_VIEWER}/{MAX_CARAVANS_PER_VIEWER})"}

    cur = await conn.execute(
        "INSERT INTO bannerlord_caravans "
        "(channel_id, owner_username, home_settlement_id, home_settlement_name, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (channel_id, owner, home_settlement_id, home_settlement_name))
    caravan_id = cur.lastrowid

    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":             owner,
        "target":                   owner,
        "caravan_id":               caravan_id,
        "home_settlement_id":       home_settlement_id,
        "home_settlement_name":     home_settlement_name,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.buy_caravan', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[CARAVAN-BUY] ch=%s @%s home=%s caravan_id=%d",
             channel_id, owner, home_settlement_name, caravan_id)
    return {
        "success": True,
        "message": f"🐪 Караван формируется из {home_settlement_name}",
    }


async def handle_sell_caravan(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Sell caravan. Mod вызывает TransferCaravanOwnership к MainHero."""
    raw = data.get("caravan_id")
    log.info("[CARAVAN-SELL ENTRY] ch=%s @%s caravan_id=%s", channel_id, owner, raw)
    try:
        caravan_id = int(raw or 0)
    except (TypeError, ValueError):
        log.info("[CARAVAN-SELL REFUSE] invalid caravan_id raw=%r", raw)
        return {"success": False, "message": "caravan_id required"}

    cur = await conn.execute(
        "SELECT party_id, home_settlement_name FROM bannerlord_caravans "
        "WHERE id=? AND channel_id=? AND owner_username=? AND status='active'",
        (caravan_id, channel_id, owner))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "Караван не найден"}
    party_id, home_name = row[0], row[1]

    await conn.execute(
        "UPDATE bannerlord_caravans SET status='sold' "
        "WHERE id=? AND channel_id=?",
        (caravan_id, channel_id))

    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":     owner,
        "target":           owner,
        "caravan_id":       caravan_id,
        "party_id":         party_id,
    }
    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status) "
        "VALUES (?, 'bannerlord', ?, 'hero.sell_caravan', ?, 'queued')",
        (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))

    log.info("[CARAVAN-SELL] ch=%s @%s caravan_id=%d", channel_id, owner, caravan_id)
    return {
        "success": True,
        "message": f"💰 Караван продан (home: {home_name})",
    }


async def handle_pay_caravan_rescue(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Crowd-fund rescue для destroyed caravan. На pool ≥ cost — backend
    auto-respawns caravan через enqueue hero.buy_caravan action."""
    raw = data.get("caravan_id")
    log.info("[CARAVAN-RESCUE ENTRY] ch=%s contributor=@%s caravan_id=%s",
             channel_id, owner, raw)
    try:
        caravan_id = int(raw or 0)
    except (TypeError, ValueError):
        log.info("[CARAVAN-RESCUE REFUSE] invalid caravan_id raw=%r", raw)
        return {"success": False, "message": "caravan_id required"}
    contribution = 500

    # Verify caravan destroyed + still rescuable.
    cur = await conn.execute(
        "SELECT owner_username, home_settlement_id, home_settlement_name, status "
        "FROM bannerlord_caravans WHERE id=? AND channel_id=?",
        (caravan_id, channel_id))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "Караван не найден"}
    cara_owner, home_id, home_name, status = row[0], row[1], row[2], row[3]
    if status != "destroyed":
        return {"success": False, "message": f"Караван не destroyed (status={status})"}

    # INSERT contribution.
    await conn.execute(
        "INSERT INTO bannerlord_caravan_rescue_pool "
        "(channel_id, caravan_id, contributor, amount, status) "
        "VALUES (?, ?, ?, ?, 'pooled')",
        (channel_id, caravan_id, owner, contribution))

    # Check if pool full.
    cur = await conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM bannerlord_caravan_rescue_pool "
        "WHERE channel_id=? AND caravan_id=? AND status='pooled'",
        (channel_id, caravan_id))
    pool_row = await cur.fetchone()
    pool_total = pool_row[0] or 0

    if pool_total >= CARAVAN_RESCUE_COST:
        # Mark caravan as rescued + mark pool released.
        await conn.execute(
            "UPDATE bannerlord_caravans SET status='active', destroyed_at=NULL "
            "WHERE id=? AND channel_id=?",
            (caravan_id, channel_id))
        await conn.execute(
            "UPDATE bannerlord_caravan_rescue_pool SET status='released' "
            "WHERE channel_id=? AND caravan_id=? AND status='pooled'",
            (channel_id, caravan_id))

        # Enqueue mod re-create action — mod создаст fresh CaravanParty.
        action_id = _uuid.uuid4().hex
        payload = {
            "initiated_by":             cara_owner,
            "target":                   cara_owner,
            "caravan_id":               caravan_id,
            "home_settlement_id":       home_id,
            "home_settlement_name":     home_name,
        }
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'hero.buy_caravan', ?, 'queued')",
            (channel_id, action_id, _json.dumps(payload, ensure_ascii=False)))
        log.info("[CARAVAN-RESCUE] FULL ch=%s caravan=%d → respawn", channel_id, caravan_id)
        return {
            "success": True,
            "message": f"💰 Pool ПОЛНЫЙ! Караван @{cara_owner} respawn'ится",
        }
    return {
        "success": True,
        "message": f"💰 +{contribution}⦷ → pool {pool_total}/{CARAVAN_RESCUE_COST}",
    }


# ─── Sync helpers (called from adapter event handlers) ────────────────────────


async def credit_caravan_profit(channel_id: int, owner: str, party_id: str,
                                  net_dinars: int) -> int:
    """Sync handler — update + credit."""
    if net_dinars <= 0:
        return 0
    db = get_db()
    crustic = int(net_dinars) // DINAR_TO_CRUSTIC_CARAVAN
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE bannerlord_caravans SET "
            "  total_collected_dinars = total_collected_dinars + ?, "
            "  last_synced_at = CURRENT_TIMESTAMP "
            "WHERE channel_id=? AND party_id=? AND status='active'",
            (net_dinars, channel_id, party_id))
        affected = cur.rowcount
        await conn.commit()
    if affected == 0:
        log.warning("[CARAVAN-SYNC] no active row ch=%s party_id=%s", channel_id, party_id)
        return 0
    if crustic > 0:
        await db.add_points(owner, crustic, channel_id=channel_id)
        log.info("[CARAVAN-SYNC] ch=%s @%s party=%s +%d dinars → +%d⦷",
                 channel_id, owner, party_id, net_dinars, crustic)
    return crustic


async def mark_caravan_destroyed(channel_id: int, party_id: str, captor_name: str = ""):
    """Called from _on_caravan_destroyed handler."""
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE bannerlord_caravans SET "
            "  status='destroyed', destroyed_at=CURRENT_TIMESTAMP "
            "WHERE channel_id=? AND party_id=? AND status='active'",
            (channel_id, party_id))
        affected = cur.rowcount
        await conn.commit()
    log.info("[CARAVAN-DESTROYED] ch=%s party=%s captor=%s affected=%d",
             channel_id, party_id, captor_name, affected)


async def backfill_caravan_party_id(channel_id: int, caravan_id: int, party_id: str):
    """Called when mod confirms caravan creation — backfill engine StringId."""
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE bannerlord_caravans SET party_id=? "
            "WHERE id=? AND channel_id=?",
            (party_id, caravan_id, channel_id))
        await conn.commit()
    log.info("[CARAVAN-BACKFILL] ch=%s id=%d party_id=%s",
             channel_id, caravan_id, party_id)
