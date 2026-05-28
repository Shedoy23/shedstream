"""
Sprint 5.33 (BLT-parity FIEF) — Fief tribute passive income.

Pure passive ⦷ loop, parallel to SHOP но kingdom-scale:
  - Mod каждый game-day diff'ит owned-fief gold/hearth, push event.
  - Backend конвертирует net dinars → крустики (200:1 ratio — fiefs дают
    меньше per dinar чем workshops чтобы кланы-leaders не overpower'или
    обычных viewers).
  - Optional active: hero.tribute_boost (2000⦷) — 7-day +50% multiplier.

Mod responsibility:
  - OnDailyTick scan Settlement.All:
      town → если town.OwnerClan?.Leader is [BLink] hero → diff Gold
      castle → same pattern
      village → diff Hearth (proxy для prosperity gains)
  - Push event hero.fief_tribute_sync с {owner, fief_id, fief_type, net_dinars}.
  - Backend ensures row existence (auto-INSERT при first sync), apply boost,
    convert + credit.
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

# Conversion ratio для fiefs — half rate of workshops (SHOP = 100:1, FIEF = 200:1).
# Reasoning: владение fief = engine-natural perk (heritage of becoming lord);
# не должен полностью overpower обычных viewers без fief'ов.
DINAR_TO_CRUSTIC_FIEF = 200

# Boost duration + multiplier.
TRIBUTE_BOOST_DAYS = 7
TRIBUTE_BOOST_MULT = 1.5


# ─── GET endpoint ─────────────────────────────────────────────────────────────


@router.get("/api/bannerlord/my-fiefs")
async def my_fiefs(request: Request):
    """Список моих fiefs + cumulative ⦷."""
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, fief_id, fief_name, fief_type, total_collected_dinars, "
            "       boost_until, last_synced_at, opened_at "
            "FROM bannerlord_fiefs "
            "WHERE channel_id=? AND owner_username=? "
            "ORDER BY opened_at ASC",
            (channel_id, username))
        rows = await cur.fetchall()

    fiefs = []
    for r in rows:
        boost_until = r[5]
        # boost active = boost_until > now (SQLite stores ISO format).
        boost_active = False
        if boost_until:
            cur2 = await conn.execute("SELECT datetime('now') < ?", (boost_until,))
            boost_active = bool((await cur2.fetchone())[0])
        fiefs.append({
            "id":                      r[0],
            "fief_id":                 r[1],
            "fief_name":               r[2],
            "fief_type":               r[3],
            "total_collected_dinars":  r[4] or 0,
            "estimated_crustic":       (r[4] or 0) // DINAR_TO_CRUSTIC_FIEF,
            "boost_until":             boost_until,
            "boost_active":            boost_active,
            "last_synced_at":          r[6],
            "opened_at":               r[7],
        })
    return {
        "success":         True,
        "fiefs":           fiefs,
        "boost_mult":      TRIBUTE_BOOST_MULT,
        "boost_days":      TRIBUTE_BOOST_DAYS,
    }


# ─── Action handler ───────────────────────────────────────────────────────────


async def handle_tribute_boost(conn, channel_id: int, owner: str, data: dict) -> dict:
    """Apply 7-day +50% boost к specified fief. Backend-only (no mod action)."""
    raw = data.get("fief_id_internal")
    log.info("[FIEF-BOOST ENTRY] ch=%s @%s fief_id_internal=%s",
             channel_id, owner, raw)
    try:
        fief_row_id = int(raw or 0)
    except (TypeError, ValueError):
        fief_row_id = 0
    if fief_row_id <= 0:
        log.info("[FIEF-BOOST REFUSE] invalid fief_id_internal raw=%r", raw)
        return {"success": False, "message": "fief_id_internal required"}

    # Validate ownership.
    cur = await conn.execute(
        "SELECT fief_name, boost_until FROM bannerlord_fiefs "
        "WHERE id=? AND channel_id=? AND owner_username=?",
        (fief_row_id, channel_id, owner))
    row = await cur.fetchone()
    if not row:
        return {"success": False, "message": "Fief не твой или не найден"}
    fief_name, existing_boost = row[0], row[1]

    # Cooldown: нельзя boost'ать пока active.
    if existing_boost:
        cur = await conn.execute("SELECT datetime('now') < ?", (existing_boost,))
        if bool((await cur.fetchone())[0]):
            return {"success": False,
                    "message": f"Boost уже активен до {existing_boost}"}

    # Apply +TRIBUTE_BOOST_DAYS days.
    await conn.execute(
        "UPDATE bannerlord_fiefs SET "
        "  boost_until = datetime('now', ?) "
        "WHERE id=? AND channel_id=?",
        (f"+{TRIBUTE_BOOST_DAYS} days", fief_row_id, channel_id))

    log.info("[FIEF-BOOST] ch=%s @%s fief=%s boosted +%d days x%.2f",
             channel_id, owner, fief_name, TRIBUTE_BOOST_DAYS, TRIBUTE_BOOST_MULT)
    return {
        "success": True,
        "message": f"⚡ Boost +{int((TRIBUTE_BOOST_MULT-1)*100)}% на «{fief_name}» "
                   f"({TRIBUTE_BOOST_DAYS} дней)",
    }


# ─── Sync helper (called from adapter event handler) ──────────────────────────


async def credit_fief_tribute(channel_id: int, owner: str, fief_id: str,
                               fief_name: str, fief_type: str,
                               net_dinars: int) -> int:
    """Called by _on_fief_tribute_sync — UPSERT row, apply boost mult, credit.

    Returns crustic credited.
    """
    if net_dinars <= 0:
        return 0
    db = get_db()
    async with db._connect() as conn:
        # Auto-UPSERT row (channel + fief_id UNIQUE). Owner may have changed
        # if engine reassigned fief — refresh on every sync.
        await conn.execute(
            "INSERT INTO bannerlord_fiefs "
            "(channel_id, owner_username, fief_id, fief_name, fief_type, last_synced_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(channel_id, fief_id) DO UPDATE SET "
            "  owner_username = excluded.owner_username, "
            "  fief_name = excluded.fief_name, "
            "  fief_type = excluded.fief_type, "
            "  last_synced_at = CURRENT_TIMESTAMP",
            (channel_id, owner, fief_id, fief_name, fief_type))

        # Read back row (нужен boost_until для multiplier).
        cur = await conn.execute(
            "SELECT id, boost_until FROM bannerlord_fiefs "
            "WHERE channel_id=? AND fief_id=?",
            (channel_id, fief_id))
        row = await cur.fetchone()
        if not row:
            await conn.commit()
            return 0
        row_id, boost_until = row[0], row[1]

        # Compute multiplier.
        mult = 1.0
        if boost_until:
            cur = await conn.execute("SELECT datetime('now') < ?", (boost_until,))
            if bool((await cur.fetchone())[0]):
                mult = TRIBUTE_BOOST_MULT

        boosted_dinars = int(net_dinars * mult)
        # Update total + commit.
        await conn.execute(
            "UPDATE bannerlord_fiefs SET "
            "  total_collected_dinars = total_collected_dinars + ? "
            "WHERE id=?",
            (boosted_dinars, row_id))
        await conn.commit()

    # Credit crustic.
    crustic = boosted_dinars // DINAR_TO_CRUSTIC_FIEF
    if crustic > 0:
        await db.add_points(owner, crustic, channel_id=channel_id)
        log.info("[FIEF-SYNC] ch=%s @%s fief=%s +%d dinars (x%.1f) → +%d⦷",
                 channel_id, owner, fief_name, net_dinars, mult, crustic)
    return crustic
