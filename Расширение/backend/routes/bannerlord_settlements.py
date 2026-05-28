"""
Sprint 5.33 CATALOG-2 (2026-05-28) — live settlements catalog endpoint.

Mod пушит `world.settlements_catalog` event на game load (handler в
modules/bannerlord/_adapter.py:_on_settlements_catalog) — backend кэширует
per-channel в memory.

Этот endpoint возвращает кэш для extension:
  GET /api/bannerlord/settlements?type=town
       ?type=town,village,castle (CSV filter)
       (no type → все)

Response:
  {
    "success": true,
    "updated_at": <unix-ts | null>,
    "settlements": [
      {"id": "town_V3", "name": "Марунат", "type": "town",
       "culture": "battania", "faction": "battania",
       "faction_n": "Баттания"},
      ...
    ],
    "count": 145,
  }

Если mod ещё не пушил catalog (свежий startup без save load) →
returns empty list + success=true. Extension показывает «Загружаются...»
или скрывает dropdown gracefully.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request

from dependencies import require_jwt_user

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/bannerlord/settlements")
async def settlements_catalog(request: Request, type: Optional[str] = None):
    """Returns cached settlement list optionally filtered by type."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    _username, channel_id = auth

    # Lazy import чтобы не циклить modules ↔ routes на startup.
    try:
        from modules._loader import get_module
        adapter = get_module("bannerlord")
        if adapter is None:
            log.warning("[CATALOG-API] bannerlord adapter не зарегистрирован")
            return {"success": True, "settlements": [], "count": 0, "updated_at": None}
        cache = adapter.get_settlements(channel_id)
    except Exception as ex:
        log.exception("[CATALOG-API] get_settlements crash: %s", ex)
        return {"success": True, "settlements": [], "count": 0, "updated_at": None}

    if not cache:
        return {"success": True, "settlements": [], "count": 0, "updated_at": None}

    settlements = cache.get("settlements") or []

    # Filter by type if requested (CSV: "town,village").
    if type:
        types_set = {t.strip().lower() for t in type.split(",") if t.strip()}
        settlements = [s for s in settlements
                       if (s.get("type") or "").lower() in types_set]

    return {
        "success":     True,
        "settlements": settlements,
        "count":       len(settlements),
        "updated_at":  cache.get("updated_at"),
    }
