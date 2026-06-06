"""
routes/bannerlord_admin.py — Streamer admin tools для Bannerlord module.

Sprint 5.33 (2026-05-28) RESET-1: реализация friend's feedback —
"вернуть стримерам возможность влиять на данные своей игры. Мало ли что,
может залагает что и нужно будет данные подчистить".

Endpoints:
  POST /api/streamer/bannerlord/reset
    Wipes ALL per-channel Bannerlord game state. Atomic TX.
    Auth: broadcaster JWT only.
    Confirmation: request body must contain {"confirm_phrase": "<channel_id>"} —
    streamer'у нужно ввести свой channel_id чтобы избежать accidental wipe.

  GET /api/streamer/bannerlord/reset/preview
    Returns row counts per table — preview что будет удалено.
    Без actual delete. Auth: broadcaster JWT.

Не trashing:
  - Catalog tables (bannerlord_classes, bannerlord_class_powers,
    bannerlord_clan_upgrades_catalog) — это system-wide reference data
  - bannerlord_boosty_subscribers — streamer's manual list (cosmetic-UI per ToS)
  - bannerlord_events_log — audit log (oldest auto-pruned via retention)

Trash:
  per-channel game state tables (33 total — heroes/skills/equipment/workshops/
  fiefs/caravans/heirs/proposals/vassals/etc.) + module_actions queue.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Depends

from dependencies import get_db, require_admin, resolve_channel_id_or_default
# Reuse streamer's session-cookie auth helper — это streamer-dashboard endpoint,
# не Twitch Extension JWT (different auth flow). Auth = "streamer logged in
# через OAuth → session cookie set → these endpoints recognize his channel_id".
from routes.streamer import _read_session_cookie

log = logging.getLogger(__name__)
router = APIRouter()


# Tables wiped on reset (per-channel data). Order doesn't matter — all
# scoped by channel_id, no cross-table FK cascades critical.
RESETTABLE_TABLES = [
    # Hero core state
    "bannerlord_heroes",
    "bannerlord_skills",
    "bannerlord_attributes",
    "bannerlord_equipment",
    "bannerlord_hero_class",
    "bannerlord_channel_state",
    "bannerlord_retinue",
    # Clan / kingdom related
    "bannerlord_clan_upgrades_owned",
    "bannerlord_vassals",
    # Achievements / daily
    "bannerlord_user_stats",
    "bannerlord_achievements_unlocked",
    "bannerlord_daily_claims",
    # Tournament
    "bannerlord_tournament_queue",
    "bannerlord_tournament_state",
    "bannerlord_tournament_bets",
    # Auctions
    "bannerlord_auctions",
    "bannerlord_auction_bids",
    # Trophy items
    "bannerlord_custom_items",
    # Heir / family / marriage
    "bannerlord_heirs",
    "bannerlord_marriage_proposals",
    # Party orders / strategic
    "bannerlord_party_orders",
    # Diplomacy
    "bannerlord_policy_requests",
    "bannerlord_peace_offers",
    "bannerlord_ransom_pool",
    # Economic empire (passive income trilogy + heritage)
    "bannerlord_workshops",
    "bannerlord_fiefs",
    "bannerlord_caravans",
    "bannerlord_caravan_rescue_pool",
    "bannerlord_inheritance_log",
]

# Tables NOT touched by reset:
PRESERVED_TABLES = [
    "bannerlord_classes",              # system catalog
    "bannerlord_class_powers",         # system catalog
    "bannerlord_clan_upgrades_catalog",  # system catalog
    "bannerlord_boosty_subscribers",   # streamer's cosmetic badge list
    "bannerlord_events_log",           # audit (retention policy elsewhere)
]


def _require_streamer_session(request: Request) -> tuple[bool, int, str]:
    """Returns (is_authed, channel_id, message). channel_id может быть 0
    при auth failure. Auth = session cookie set when streamer OAuth'нулся через
    /streamer flow."""
    cid = _read_session_cookie(request)
    if cid is None:
        return False, 0, "Streamer session required — login через /streamer"
    return True, int(cid), ""


async def _reset_preview_data(channel_id: int) -> dict:
    """Preview row counts per resettable table (no delete). Shared by the
    streamer-dashboard and admin-panel endpoints."""
    db = get_db()
    counts: dict[str, int] = {}
    total = 0
    async with db._connect() as conn:
        for table in RESETTABLE_TABLES:
            try:
                cur = await conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE channel_id=?", (channel_id,))
                row = await cur.fetchone()
                count = (row[0] if row else 0) or 0
            except Exception as e:
                log.warning("[BNR-RESET preview] table %s missing: %s", table, e)
                count = -1   # signals "missing/error"
            counts[table] = count
            if count > 0:
                total += count

        try:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM module_actions "
                "WHERE channel_id=? AND module_id='bannerlord'", (channel_id,))
            row = await cur.fetchone()
            counts["module_actions (bannerlord)"] = (row[0] if row else 0) or 0
            total += counts["module_actions (bannerlord)"]
        except Exception as e:
            counts["module_actions (bannerlord)"] = -1
            log.warning("[BNR-RESET preview] module_actions count failed: %s", e)

    return {
        "success":           True,
        "channel_id":        channel_id,
        "total_rows":        total,
        "table_counts":      counts,
        "preserved_tables":  PRESERVED_TABLES,
    }


@router.get("/api/streamer/bannerlord/reset/preview")
async def bannerlord_reset_preview(request: Request):
    """Preview row counts per resettable table. Не deletes anything."""
    ok, channel_id, msg = _require_streamer_session(request)
    if not ok:
        return {"success": False, "message": msg}
    return await _reset_preview_data(channel_id)


@router.get("/api/admin/bannerlord/reset/preview")
async def admin_bannerlord_reset_preview(_admin: str = Depends(require_admin)):
    """Same preview, but via admin-panel Basic auth (default channel)."""
    return await _reset_preview_data(resolve_channel_id_or_default())


def _confirm_phrase_ok(body: dict, channel_id: int) -> tuple[bool, str]:
    """Destructive-action guard: caller must re-type the channel_id."""
    expected = str(channel_id)
    got = str((body or {}).get("confirm_phrase") or "").strip()
    if got != expected:
        return False, f"Confirm phrase mismatch — expected '{expected}', got '{got}'"
    return True, ""


async def _reset_wipe_data(channel_id: int) -> dict:
    """Wipe ALL per-channel Bannerlord state in one atomic TX. Shared by the
    streamer-dashboard and admin-panel endpoints (each does its own auth +
    confirm-phrase check before calling)."""
    db = get_db()
    deleted: dict[str, int] = {}
    total_deleted = 0

    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            for table in RESETTABLE_TABLES:
                try:
                    cur = await conn.execute(
                        f"DELETE FROM {table} WHERE channel_id=?",
                        (channel_id,))
                    rowcount = cur.rowcount or 0
                    deleted[table] = rowcount
                    total_deleted += rowcount
                except Exception as e:
                    log.warning("[BNR-RESET] table %s delete failed: %s", table, e)
                    deleted[table] = -1

            # module_actions
            try:
                cur = await conn.execute(
                    "DELETE FROM module_actions "
                    "WHERE channel_id=? AND module_id='bannerlord'",
                    (channel_id,))
                rowcount = cur.rowcount or 0
                deleted["module_actions (bannerlord)"] = rowcount
                total_deleted += rowcount
            except Exception as e:
                log.warning("[BNR-RESET] module_actions delete failed: %s", e)
                deleted["module_actions (bannerlord)"] = -1

            await conn.commit()
        except Exception as ex:
            try: await conn.execute("ROLLBACK")
            except Exception: pass
            log.exception("[BNR-RESET] TX failed for ch=%s: %s", channel_id, ex)
            return {
                "success": False,
                "message": f"Reset failed: {type(ex).__name__}: {ex}",
            }

    log.warning(
        "[BNR-RESET] ch=%s WIPE — %d rows deleted across %d tables",
        channel_id, total_deleted, len([v for v in deleted.values() if v > 0]))

    return {
        "success":        True,
        "channel_id":     channel_id,
        "total_deleted":  total_deleted,
        "deleted_by_table": deleted,
        "message":        f"🧹 Wiped {total_deleted} rows across "
                          f"{len([v for v in deleted.values() if v > 0])} tables. "
                          "Mod restart рекомендован если кампания active.",
    }


@router.post("/api/streamer/bannerlord/reset")
async def bannerlord_reset(request: Request):
    """Wipes ALL per-channel Bannerlord game state. Atomic TX.

    Body: {"confirm_phrase": "<channel_id_as_string>"} — re-type channel_id
    (protection от accidental button click).
    """
    ok, channel_id, msg = _require_streamer_session(request)
    if not ok:
        return {"success": False, "message": msg}
    try:
        body = await request.json()
    except Exception:
        body = {}
    cok, cmsg = _confirm_phrase_ok(body, channel_id)
    if not cok:
        return {"success": False, "message": cmsg}
    return await _reset_wipe_data(channel_id)


@router.post("/api/admin/bannerlord/reset")
async def admin_bannerlord_reset(request: Request, _admin: str = Depends(require_admin)):
    """Same wipe via admin-panel Basic auth (default channel). Body must still
    contain {"confirm_phrase": "<channel_id>"} — re-type to confirm."""
    channel_id = resolve_channel_id_or_default()
    try:
        body = await request.json()
    except Exception:
        body = {}
    cok, cmsg = _confirm_phrase_ok(body, channel_id)
    if not cok:
        return {"success": False, "message": cmsg}
    return await _reset_wipe_data(channel_id)
