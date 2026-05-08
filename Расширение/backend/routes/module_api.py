"""
routes/module_api.py — Module API HTTP endpoints (этап 3 step 1).

Реализует подмножество docs/MODULE_API.md §3.1 (REST long-poll transport):
  - POST /v1/module/<id>/hello       — handshake (§6)
  - GET  /v1/module/<id>/info        — manifest dump (debug/admin)
  - GET  /v1/modules                 — list discovered modules

Не реализовано в этом коммите (поэтапная миграция):
  - POST /v1/module/<id>/events      — приём событий от connector'а
  - GET  /v1/module/<id>/actions     — long-poll outbox для actions
  - POST /v1/module/<id>/ack         — connector'ский ACK
  - module-token авторизация (§4)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from modules._loader import get_module, list_modules

router = APIRouter()


@router.get("/v1/modules", include_in_schema=False)
async def list_modules_endpoint():
    """Список зарегистрированных модулей. Полезно для debug + admin UI."""
    return {
        "modules": [
            {
                "id": m.manifest.id,
                "version": m.manifest.version,
                "display_name": m.manifest.display_name,
                "description": m.manifest.description,
                "events": m.manifest.events + m.manifest.extension_events,
                "actions": m.manifest.actions + m.manifest.extension_actions,
                "catalogs": m.manifest.catalogs,
                "active_channels": len(m._active_channels),
            }
            for m in list_modules()
        ]
    }


@router.get("/v1/module/{module_id}/info", include_in_schema=False)
async def module_info(module_id: str):
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    m = adapter.manifest
    return {
        "id": m.id,
        "version": m.version,
        "core_api_version": m.core_api_version,
        "display_name": m.display_name,
        "description": m.description,
        "icon": m.icon,
        "events": m.events,
        "actions": m.actions,
        "extensions": {
            "events": m.extension_events,
            "actions": m.extension_actions,
        },
        "catalogs": m.catalogs,
        "ui_slots": m.ui_slots,
    }


@router.post("/v1/module/{module_id}/hello", include_in_schema=False)
async def module_hello(module_id: str, request: Request):
    """Handshake (§6 спеки). Connector прислал manifest digest + version,
    core отвечает welcome'ом со списком capabilities.

    Минимальная имплементация: НЕТ авторизации, НЕТ session-tracking.
    Следующие шаги добавят module-token check (§4) и persisted session.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Channel определяется через JWT (extension iframe context) — но для
    # mod connector'а JWT нет. До добавления module-token в §4 просто
    # принимаем broadcaster_id из body. TODO M5+: enforce HMAC signature.
    raw_cid = body.get("channel_id") or 0
    try:
        channel_id = int(raw_cid)
    except (TypeError, ValueError):
        channel_id = 0
    if channel_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "channel_id_required", "message": "body.channel_id обязательно"},
        )

    connector_version = str(body.get("connector_version", "unknown"))
    manifest_digest = str(body.get("manifest_digest", ""))

    welcome = await adapter.on_hello(channel_id, connector_version, manifest_digest)
    return JSONResponse({"status": "welcome", **welcome})
