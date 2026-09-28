"""
routes/bannerlord_boosty.py — Boosty subscriber list endpoints.

Sprint 5.31 #45. Boosty не имеет matching API для Twitch identity, поэтому
streamer ведёт список вручную:
  - Twitch username
  - Boosty tier (1/2/3)
  - Optional note

Sprint 5.33 TOS-COMPLIANCE (2026-05-28): Boosty tier больше НЕ даёт gameplay
benefits (Twitch ToS prohibits paid-subscription-gated rewards в Extensions —
spirit applies к third-party paid subs тоже). Endpoints остаются для
cosmetic-only badge UI; bannerlord.buy_action больше НЕ читает get_boosty_tier.

Endpoints:
  GET  /api/streamer/boosty/subscribers — список (streamer auth)
  POST /api/streamer/boosty/subscribers — add/update viewer
  POST /api/streamer/boosty/subscribers/delete — remove viewer
  GET  /api/bannerlord/boosty-tier?username=X — cosmetic helper (no gameplay effect)

Streamer-only endpoints защищены через broadcaster role + JWT check.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from fastapi import APIRouter, Request

from dependencies import get_db

router = APIRouter()
log = logging.getLogger("rimlink.bannerlord.boosty")


# ── In-memory cache (avoid DB hit per buy_action) ────────────────────────────
# Cache: (channel_id, username) → (tier, refreshed_at)
# Refresh при mutation (POST /subscribers) — invalidates entire channel.
_BOOSTY_CACHE: dict[tuple[int, str], int] = {}
_BOOSTY_CACHE_LOADED_FOR_CHANNEL: set[int] = set()


async def _ensure_channel_loaded(channel_id: int) -> None:
    """Lazy-load entire channel's subscriber list в cache on first access."""
    if channel_id in _BOOSTY_CACHE_LOADED_FOR_CHANNEL:
        return
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT twitch_username, tier FROM bannerlord_boosty_subscribers "
            "WHERE channel_id=?",
            (channel_id,))
        rows = await cur.fetchall()
    for row in rows:
        _BOOSTY_CACHE[(channel_id, (row[0] or "").lower())] = int(row[1])
    _BOOSTY_CACHE_LOADED_FOR_CHANNEL.add(channel_id)
    log.info("[boosty cache] ch=%s loaded %d subscribers", channel_id, len(rows))


def _invalidate_channel(channel_id: int) -> None:
    """Drop cache для channel — next access reload'нёт."""
    keys = [k for k in _BOOSTY_CACHE if k[0] == channel_id]
    for k in keys:
        _BOOSTY_CACHE.pop(k, None)
    _BOOSTY_CACHE_LOADED_FOR_CHANNEL.discard(channel_id)


async def get_boosty_tier(channel_id: int, username: str) -> int:
    """Return Boosty tier (1/2/3) для viewer или 0 если нет в списке.
    Public API для bannerlord.buy_action."""
    if not channel_id or not username:
        return 0
    await _ensure_channel_loaded(channel_id)
    return _BOOSTY_CACHE.get((channel_id, username.lower()), 0)


# Sprint 5.31 #45f (codegraph dead-code audit) — JWT-auth endpoints удалены.
# Раньше виделся админ-модал из расширения (Sprint #45), потом перенесли на
# /streamer/dashboard (Sprint #45b) и кнопку из viewer.js убрали. Маршруты
# `/api/streamer/boosty/*` остались dead — удалены вместе с `_require_streamer_role`.
# Сохраняем ТОЛЬКО cookie-auth dashboard'овские endpoint'ы (ниже).

# ── Cookie-auth shim'ы для /streamer/dashboard (Sprint 5.31 #45b) ────────────
# Дашборд использует session cookie (_streamer_session) вместо Twitch JWT.
# Эти endpoint'ы делают то же что и JWT-версии, но проверяют cookie.

def _require_dashboard_session(request: Request) -> Optional[int]:
    """Прочитать streamer_session cookie → channel_id или None."""
    try:
        from routes.streamer import _read_session_cookie
    except Exception:
        return None
    return _read_session_cookie(request)


@router.get("/api/dashboard/boosty/subscribers")
async def dashboard_list_boosty_subscribers(request: Request):
    """List Boosty subscribers — cookie-auth (для /streamer/dashboard)."""
    cid = _require_dashboard_session(request)
    if cid is None:
        return {"success": False, "message": "session expired — re-login"}
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT twitch_username, tier, note, set_at "
            "FROM bannerlord_boosty_subscribers "
            "WHERE channel_id=? "
            "ORDER BY tier DESC, twitch_username ASC",
            (cid,))
        rows = await cur.fetchall()
    return {
        "success": True,
        "subscribers": [
            {"username": r[0], "tier": r[1], "note": r[2], "set_at": r[3]}
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/api/dashboard/boosty/subscribers")
async def dashboard_upsert_boosty_subscriber(request: Request):
    """Upsert — cookie-auth. tier=0 → delete."""
    cid = _require_dashboard_session(request)
    if cid is None:
        return {"success": False, "message": "session expired — re-login"}
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "bad JSON"}
    username = (body.get("username") or "").strip().lower()
    try:
        tier = int(body.get("tier") or 0)
    except (TypeError, ValueError):
        return {"success": False, "message": "tier должен быть числом"}
    note = (body.get("note") or "").strip()[:120]
    if not username:
        return {"success": False, "message": "username required"}
    if tier < 0 or tier > 3:
        return {"success": False, "message": "tier должен быть 0-3"}
    async with get_db()._connect() as conn:
        if tier == 0:
            await conn.execute(
                "DELETE FROM bannerlord_boosty_subscribers "
                "WHERE channel_id=? AND twitch_username=?",
                (cid, username))
            msg = f"@{username} удалён"
        else:
            await conn.execute(
                "INSERT INTO bannerlord_boosty_subscribers "
                "(channel_id, twitch_username, tier, note) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(channel_id, twitch_username) DO UPDATE SET "
                "tier=excluded.tier, note=excluded.note, set_at=CURRENT_TIMESTAMP",
                (cid, username, tier, note))
            msg = f"@{username} → tier {tier}{(' ('+note+')') if note else ''}"
        await conn.commit()
    _invalidate_channel(cid)
    log.info("[boosty dash] ch=%s upsert user=%s tier=%s note='%s'",
             cid, username, tier, note)
    return {"success": True, "message": msg}


@router.post("/api/dashboard/boosty/subscribers/bulk")
async def dashboard_bulk_set_boosty_subscribers(request: Request):
    """Bulk replace/merge — cookie-auth."""
    cid = _require_dashboard_session(request)
    if cid is None:
        return {"success": False, "message": "session expired — re-login"}
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "bad JSON"}
    entries = body.get("entries") or []
    if not isinstance(entries, list):
        return {"success": False, "message": "entries должен быть list"}
    replace_all = bool(body.get("replace_all"))
    inserted, skipped = 0, 0
    async with get_db()._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            if replace_all:
                await conn.execute(
                    "DELETE FROM bannerlord_boosty_subscribers WHERE channel_id=?",
                    (cid,))
            for e in entries:
                if not isinstance(e, dict):
                    skipped += 1
                    continue
                u = (e.get("username") or "").strip().lower()
                try:
                    t = int(e.get("tier") or 0)
                except (TypeError, ValueError):
                    skipped += 1
                    continue
                if not u or t < 1 or t > 3:
                    skipped += 1
                    continue
                note = (e.get("note") or "").strip()[:120]
                await conn.execute(
                    "INSERT INTO bannerlord_boosty_subscribers "
                    "(channel_id, twitch_username, tier, note) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(channel_id, twitch_username) DO UPDATE SET "
                    "tier=excluded.tier, note=excluded.note, set_at=CURRENT_TIMESTAMP",
                    (cid, u, t, note))
                inserted += 1
            # 2026-07-31 (аудит спеки §17). `replace_all` СНАЧАЛА стирает весь
            # список канала, а негодные записи ниже просто пропускаются. Значит
            # присланный целиком, но неверный по формату файл (все tier=0, или
            # поле названо иначе) молча оставлял стримера БЕЗ списка платных
            # подписчиков — и ответ при этом был success. Восстановить неоткуда:
            # список ведётся руками, второго экземпляра нет.
            # Замена на пустоту допустима, только если её попросили явно —
            # пустым `entries`, а не сорока негодными записями.
            if replace_all and entries and inserted == 0:
                await conn.execute("ROLLBACK")
                log.warning("[boosty dash] ch=%s bulk replace_all отклонён: "
                            "%d записей, ни одной годной — список НЕ стёрт",
                            cid, skipped)
                return {
                    "success": False,
                    "message": (f"Ни одна из {skipped} записей не годится "
                                f"(нужны username и tier 1-3). Список не тронут — "
                                f"иначе он был бы стёрт целиком."),
                    "skipped": skipped,
                }
            await conn.commit()
        except Exception as ex:
            try: await conn.execute("ROLLBACK")
            except Exception: pass
            log.exception("dashboard bulk boosty failed: %s", ex)
            return {"success": False, "message": f"server error: {ex}"}
    _invalidate_channel(cid)
    log.info("[boosty dash] ch=%s bulk inserted=%s skipped=%s replace_all=%s",
             cid, inserted, skipped, replace_all)
    return {
        "success": True,
        "message": f"Принято: {inserted}, пропущено: {skipped}"
                   + (" (полная замена)" if replace_all else " (merge)"),
        "inserted": inserted,
        "skipped":  skipped,
    }


# Sprint 5.31 #45f — JWT bulk endpoint удалён вместе с другими /api/streamer/*.
# Dashboard использует /api/dashboard/boosty/subscribers/bulk (выше).
