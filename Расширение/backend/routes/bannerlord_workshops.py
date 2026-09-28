"""
Sprint 5.33 (BLT-parity SHOP) — Workshops passive income loop.

Workflow:
  1. Viewer покупает workshop: hero.buy_workshop(settlement_id, workshop_type)
     - Backend INSERT row + enqueue mod-action (1000⦷ + capital from Hero.Gold).
     - Mod применяет ChangeOwnerOfWorkshopAction.ApplyByPlayerBuying.
  2. Каждый game-day mod pushes event hero.workshop_profit_sync:
     - {workshop_id, profit_made (gross динары), expense (gross динары)}
     - Backend: net = profit-expense; total_profit += net;
       credit viewer crustic = net // 100 (ratio 100 динаров = 1⦷, see DINAR_TO_CRUSTIC).
  3. Viewer может sell_workshop — engine refund 50% capital, backend marks status='sold'.

NB: workshop creation cost определяется engine (depends на settlement prosperity).
Backend resets initial_capital ПОСЛЕ mod confirms через workshop_opened event.
Для MVP backend хранит declared cost; mod проверяет Hero.Gold reality.

Endpoints:
  GET /api/bannerlord/my-workshops  — мои active workshops
  GET /api/bannerlord/workshop-towns — список settlements + workshop_types
                                       (mod пушит как catalog event)
"""
from __future__ import annotations

import logging
import json as _json

import uuid as _uuid

from fastapi import APIRouter, Request

from dependencies import require_jwt_user
from dependencies import get_db
from routes._mod_queue import enqueue_mod_action

log = logging.getLogger(__name__)
router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "auth required"}

# Conversion ratio: in-game динары → крустики viewer'у.
# 100 динаров = 1⦷ — conservative (avg workshop ~600 dinars/day = 6⦷/day,
# 7-day week = 42⦷ — economy-balanced, не overpowered passive).
DINAR_TO_CRUSTIC = 100

# Hard limit workshops per viewer — anti-snowball.
MAX_WORKSHOPS_PER_VIEWER = 3


# ─── GET endpoints ────────────────────────────────────────────────────────────


@router.get("/api/bannerlord/my-workshops")
async def my_workshops(request: Request):
    """Список моих active workshops + cumulative profit."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, settlement_id, settlement_name, workshop_type, "
            "       workshop_type_name, initial_capital, total_profit, "
            "       opened_at, last_synced_at "
            "FROM bannerlord_workshops "
            "WHERE channel_id=? AND owner_username=? AND status='active' "
            "ORDER BY opened_at ASC",
            (channel_id, username))
        rows = await cur.fetchall()

    workshops = []
    for r in rows:
        workshops.append({
            "id":                  r[0],
            "settlement_id":       r[1],
            "settlement_name":     r[2],
            "workshop_type":       r[3],
            "workshop_type_name":  r[4],
            "initial_capital":     r[5] or 0,
            "total_profit":        r[6] or 0,
            # Sprint 5.33 DECOUPLE-1 — passive ⦷-payout removed; field kept
            # для backward-compat (returns 0) so old clients don't crash.
            "estimated_crustic":   0,
            "opened_at":           r[7],
            "last_synced_at":      r[8],
        })
    return {
        "success": True,
        "workshops": workshops,
        "max_workshops": MAX_WORKSHOPS_PER_VIEWER,
    }


# ─── Action handlers ──────────────────────────────────────────────────────────


async def handle_buy_workshop(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Buy workshop в town. Mod применяет engine ApplyByPlayerBuying."""
    settlement_id = (data.get("settlement_id") or "").strip()
    settlement_name = (data.get("settlement_name") or "").strip() or settlement_id
    workshop_type = (data.get("workshop_type") or "").strip()
    workshop_type_name = (data.get("workshop_type_name") or "").strip() or workshop_type

    log.info("[SHOP-BUY ENTRY] ch=%s @%s settlement=%s type=%s",
             channel_id, owner, settlement_id, workshop_type)

    if not settlement_id or not workshop_type:
        log.info("[SHOP-BUY REFUSE] missing fields ch=%s @%s", channel_id, owner)
        return {"success": False, "message": "settlement_id и workshop_type required"}

    # Limit check.
    cur = await conn.execute(
        "SELECT COUNT(*) FROM bannerlord_workshops "
        "WHERE channel_id=? AND owner_username=? AND status='active'",
        (channel_id, owner))
    row = await cur.fetchone()
    if (row[0] or 0) >= MAX_WORKSHOPS_PER_VIEWER:
        return {"success": False,
                "message": f"Лимит workshop'ов ({MAX_WORKSHOPS_PER_VIEWER}/{MAX_WORKSHOPS_PER_VIEWER})"}

    # INSERT (UNIQUE partial idx защищает от dupe purchase same slot).
    try:
        cur = await conn.execute(
            "INSERT INTO bannerlord_workshops "
            "(channel_id, owner_username, settlement_id, settlement_name, "
            " workshop_type, workshop_type_name, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (channel_id, owner, settlement_id, settlement_name,
             workshop_type, workshop_type_name))
        workshop_id = cur.lastrowid
    except Exception as e:
        log.info("[SHOP-BUY] dupe @%s ch=%s settlement=%s type=%s: %s",
                 owner, channel_id, settlement_id, workshop_type, e)
        return {"success": False, "message": "Этот workshop уже занят"}

    # Enqueue mod-action.
    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":         owner,
        "target":               owner,
        "workshop_id":          workshop_id,
        "settlement_id":        settlement_id,
        "settlement_name":      settlement_name,
        "workshop_type":        workshop_type,
        "workshop_type_name":   workshop_type_name,
    }
    await enqueue_mod_action(conn, channel_id, action_id,
                             "hero.buy_workshop", payload, data)

    log.info("[SHOP-BUY] ch=%s @%s → %s in %s",
             channel_id, owner, workshop_type_name, settlement_name)
    return {
        "success": True,
        "message": f"🏭 Куплен «{workshop_type_name}» в {settlement_name}",
    }


async def handle_sell_workshop(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Sell workshop. Engine refund 50% capital, backend marks sold."""
    workshop_id_raw = data.get("workshop_id")
    log.info("[SHOP-SELL ENTRY] ch=%s @%s workshop_id=%s",
             channel_id, owner, workshop_id_raw)
    try:
        workshop_id = int(workshop_id_raw)
    except (TypeError, ValueError):
        log.info("[SHOP-SELL REFUSE] invalid workshop_id raw=%r", workshop_id_raw)
        return {"success": False, "message": "workshop_id required"}

    # Validate ownership.
    cur = await conn.execute(
        "SELECT settlement_id, settlement_name, workshop_type, workshop_type_name "
        "FROM bannerlord_workshops "
        "WHERE id=? AND channel_id=? AND owner_username=? AND status='active'",
        (workshop_id, channel_id, owner))
    row = await cur.fetchone()
    if not row:
        log.info("[SHOP-SELL REFUSE] workshop not found / not owned ch=%s @%s id=%s",
                 channel_id, owner, workshop_id)
        return {"success": False, "message": "Workshop не найден"}
    settlement_id, settlement_name, workshop_type, workshop_type_name = (
        row[0], row[1], row[2], row[3])

    # Mark sold.
    await conn.execute(
        "UPDATE bannerlord_workshops SET status='sold' "
        "WHERE id=? AND channel_id=?",
        (workshop_id, channel_id))

    # Enqueue mod-action для engine apply.
    action_id = _uuid.uuid4().hex
    payload = {
        "initiated_by":         owner,
        "target":               owner,
        "workshop_id":          workshop_id,
        "settlement_id":        settlement_id,
        "workshop_type":        workshop_type,
    }
    await enqueue_mod_action(conn, channel_id, action_id,
                             "hero.sell_workshop", payload, data)

    log.info("[SHOP-SELL] ch=%s @%s sold %s in %s",
             channel_id, owner, workshop_type_name or workshop_type, settlement_name)
    return {
        "success": True,
        "message": f"💰 «{workshop_type_name or workshop_type}» продан (50% refund)",
    }


async def credit_workshop_profit(channel_id: int, owner: str, workshop_id: int,
                                  net_dinars: int) -> int:
    """Sprint 5.33 DECOUPLE-1 (2026-05-28) — passive income → ⦷ DISABLED.

    Workshop profit (net dinars) теперь оседает только в engine Hero.Gold —
    viewer тратит динары на gear/smith/marriage/etc. ⦷ — currency
    «внимания» (просмотр, чат) — не должны генерироваться пассивно от
    in-game собственности (anti-AFK-farm + cleaner ToS positioning).

    Backward note: viewers уже получили исторические ⦷ — не отзываем.
    Эта функция продолжает tracking total_profit для UI/stats, но
    add_points больше не вызывает.
    """
    if net_dinars <= 0:
        return 0
    db = get_db()
    async with db._connect() as conn:
        # Update workshop profit + last_synced_at (stat tracking only).
        await conn.execute(
            "UPDATE bannerlord_workshops SET "
            "  total_profit = total_profit + ?, "
            "  last_synced_at = CURRENT_TIMESTAMP, "
            "  last_payout_at = CURRENT_TIMESTAMP "
            "WHERE id=? AND channel_id=? AND status='active'",
            (net_dinars, workshop_id, channel_id))
        await conn.commit()
    log.info("[SHOP-SYNC] ch=%s @%s workshop=%s +%d dinars (engine; ⦷ payout disabled)",
             channel_id, owner, workshop_id, net_dinars)
    return 0   # 0 ⦷ credited — passive income decoupled from platform currency


async def reconcile_workshops(conn, channel_id: int, items: list) -> dict:
    """PROPERTIES-MIRROR (2026-06-02) — зеркалим snapshot мастерских из игры.

    items: [{owner, settlement_id, settlement_name, workshop_type,
    workshop_type_name}, ...]. Игровая identity = (settlement_id, workshop_type) —
    отдельного StringId у Workshop нет. Match active-строк по этой паре: UPDATE
    owner (НЕ трогая total_profit/opened_at/initial_capital), INSERT новых, DELETE
    отсутствующих active. Sold/destroyed строки не трогаем (история; GET их и так
    скрывает). owner → lowercase. conn — shared transaction; коммитит вызывающий.
    """
    snap = {}
    for it in items:
        sid = (it.get("settlement_id") or "").strip()
        wtype = (it.get("workshop_type") or "").strip()
        if not sid or not wtype:
            continue
        snap[(sid, wtype)] = {
            "owner": (it.get("owner") or "").strip().lower(),
            "settlement_name": (it.get("settlement_name") or "").strip(),
            "workshop_type_name": (it.get("workshop_type_name") or "").strip(),
        }
    cur = await conn.execute(
        "SELECT id, settlement_id, workshop_type FROM bannerlord_workshops "
        "WHERE channel_id=? AND status='active'", (channel_id,))
    rows = await cur.fetchall()
    existing = {(r[1], r[2]): r[0] for r in rows}

    removed = 0
    for key, rid in existing.items():
        if key not in snap:
            await conn.execute(
                "DELETE FROM bannerlord_workshops WHERE id=? AND channel_id=?",
                (rid, channel_id))
            removed += 1
    for (sid, wtype), v in snap.items():
        if (sid, wtype) in existing:
            await conn.execute(
                "UPDATE bannerlord_workshops SET "
                "  owner_username=?, "
                "  settlement_name=COALESCE(NULLIF(?,''), settlement_name), "
                "  workshop_type_name=COALESCE(NULLIF(?,''), workshop_type_name), "
                "  last_synced_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND channel_id=?",
                (v["owner"], v["settlement_name"], v["workshop_type_name"],
                 existing[(sid, wtype)], channel_id))
        else:
            await conn.execute(
                "INSERT INTO bannerlord_workshops "
                "(channel_id, owner_username, settlement_id, settlement_name, "
                " workshop_type, workshop_type_name, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (channel_id, v["owner"], sid, v["settlement_name"],
                 wtype, v["workshop_type_name"]))
    return {"n": len(snap), "removed": removed}
