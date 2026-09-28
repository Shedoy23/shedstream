"""
Sprint 5.33 (BLT-parity CARAVAN) — Mobile passive income.

Closes passive trilogy: SHOP (static) + FIEF (territorial) + CARAVAN (mobile risk).

Ratios:
  SHOP    = 100:1 dinars→crustic (static workshop)
  CARAVAN = 150:1                (mid — mobile, traveling)
  FIEF    = 200:1                (territorial, kingdom-scale)

Бандиты могут уничтожить караван — уничтоженный караван просто исчезает
(DELETE), слот владельца освобождается, зритель создаёт новый.

Endpoints:
  GET /api/bannerlord/my-caravans

Actions:
  hero.buy_caravan          — create new caravan (1500⦷ + 15K Hero.Gold)
  hero.sell_caravan         — disband / sell к MainHero
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

DINAR_TO_CRUSTIC_CARAVAN = 150
MAX_CARAVANS_PER_VIEWER = 2  # tighter than workshops — caravans more powerful


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
            "  AND status='active' "
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
            "estimated_crustic":      0,  # DECOUPLE-1: passive ⦷ disabled
            "last_synced_at":         r[6],
            "opened_at":              r[7],
            "status":                 r[8],
            "destroyed_at":           r[9],
        })
    return {
        "success":        True,
        "caravans":       caravans,
        "max_caravans":   MAX_CARAVANS_PER_VIEWER,
    }


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
    await enqueue_mod_action(conn, channel_id, action_id,
                             "hero.buy_caravan", payload, data)

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
    await enqueue_mod_action(conn, channel_id, action_id,
                             "hero.sell_caravan", payload, data)

    log.info("[CARAVAN-SELL] ch=%s @%s caravan_id=%d", channel_id, owner, caravan_id)
    return {
        "success": True,
        "message": f"💰 Караван продан (home: {home_name})",
    }


# ─── Sync helpers (called from adapter event handlers) ────────────────────────


async def credit_caravan_profit(channel_id: int, owner: str, party_id: str,
                                  net_dinars: int) -> int:
    """Sprint 5.33 DECOUPLE-1 (2026-05-28) — passive ⦷ payout REMOVED.

    Caravan profit оседает в engine Hero.Gold (PartyTradeGold). Динары
    идут на gear/smith/marriage — ⦷ остаются «вознаграждение за внимание»
    (просмотр, чат), не AFK farming.

    Tracking total_collected_dinars сохранён для UI ("ваш караван заработал
    150K дин."). add_points removed.
    """
    if net_dinars <= 0:
        return 0
    db = get_db()
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
    log.info("[CARAVAN-SYNC] ch=%s @%s party=%s +%d dinars (engine; ⦷ payout disabled)",
             channel_id, owner, party_id, net_dinars)
    return 0   # 0 ⦷ credited — passive income decoupled from platform currency


async def mark_caravan_destroyed(channel_id: int, party_id: str, captor_name: str = ""):
    """Called from _on_caravan_destroyed handler. Уничтоженный караван исчезает
    (DELETE) — слот владельца освобождается, зритель может создать новый."""
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "DELETE FROM bannerlord_caravans "
            "WHERE channel_id=? AND party_id=? AND status='active'",
            (channel_id, party_id))
        affected = cur.rowcount
        await conn.commit()
    log.info("[CARAVAN-DESTROYED] ch=%s party=%s captor=%s deleted=%d",
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


async def reconcile_caravans(conn, channel_id: int, items: list) -> dict:
    """PROPERTIES-MIRROR (2026-06-02) — зеркалим snapshot караванов из игры.

    items: [{owner, party_id, home_settlement_id, home_settlement_name}, ...] —
    караваны [BLink]-героев, ЖИВЫЕ в движке сейчас (party_id = engine StringId).

    Reconcile затрагивает ТОЛЬКО active+party_id IS NOT NULL — НЕ трогаем:
      - 'destroyed' (mid-rescue crowdfund), 'sold' (история),
      - active с party_id IS NULL (свежекупленные 'forming', ждут caravan_created).
    Логика:
      - matched party_id → UPDATE owner/home (сохраняя total_collected_dinars/opened_at)
      - active+party_id ОТСУТСТВУЕТ в snapshot → DELETE ("призрак": продан/уничтожен/
        re-owned; заодно чистим rescue-pool children, чтоб не было orphan'ов)
      - snapshot party_id без строки → усыновляем NULL-party active строку того же
        owner (backfill party_id), иначе INSERT
    owner → lowercase. conn — shared transaction; коммитит вызывающий.
    """
    snap = {}
    for it in items:
        pid = (it.get("party_id") or "").strip()
        if not pid:
            continue
        snap[pid] = {
            "owner": (it.get("owner") or "").strip().lower(),
            "home_id": (it.get("home_settlement_id") or "").strip(),
            "home_name": (it.get("home_settlement_name") or "").strip(),
        }
    cur = await conn.execute(
        "SELECT id, party_id, owner_username FROM bannerlord_caravans "
        "WHERE channel_id=? AND status='active'", (channel_id,))
    rows = await cur.fetchall()
    by_party = {r[1]: r[0] for r in rows if r[1]}                       # party_id -> id
    null_party = [(r[0], (r[2] or "").lower()) for r in rows if not r[1]]  # forming

    removed = 0
    for pid, rid in by_party.items():
        if pid not in snap:
            await conn.execute(
                "DELETE FROM bannerlord_caravans WHERE id=? AND channel_id=?",
                (rid, channel_id))
            removed += 1
    for pid, v in snap.items():
        if pid in by_party:
            await conn.execute(
                "UPDATE bannerlord_caravans SET "
                "  owner_username=?, "
                "  home_settlement_id=COALESCE(NULLIF(?,''), home_settlement_id), "
                "  home_settlement_name=COALESCE(NULLIF(?,''), home_settlement_name), "
                "  last_synced_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND channel_id=?",
                (v["owner"], v["home_id"], v["home_name"], by_party[pid], channel_id))
        else:
            adopt_id = None
            for rid, rowner in null_party:
                if rowner == v["owner"]:
                    adopt_id = rid
                    break
            if adopt_id is not None:
                null_party = [(i, o) for (i, o) in null_party if i != adopt_id]
                await conn.execute(
                    "UPDATE bannerlord_caravans SET party_id=?, "
                    "  home_settlement_id=COALESCE(NULLIF(?,''), home_settlement_id), "
                    "  home_settlement_name=COALESCE(NULLIF(?,''), home_settlement_name), "
                    "  last_synced_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND channel_id=?",
                    (pid, v["home_id"], v["home_name"], adopt_id, channel_id))
            else:
                await conn.execute(
                    "INSERT INTO bannerlord_caravans "
                    "(channel_id, owner_username, party_id, home_settlement_id, "
                    " home_settlement_name, status) "
                    "VALUES (?, ?, ?, ?, ?, 'active')",
                    (channel_id, v["owner"], pid, v["home_id"], v["home_name"]))
    return {"n": len(snap), "removed": removed}
