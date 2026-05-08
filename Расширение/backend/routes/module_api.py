"""
routes/module_api.py — Module API HTTP endpoints (этап 3 steps 1+2).

Реализует подмножество docs/MODULE_API.md §3.1 (REST long-poll transport):
  - GET  /v1/modules                 — list discovered modules
  - GET  /v1/module/<id>/info        — manifest dump (debug/admin)
  - POST /v1/module/<id>/hello       — handshake (§6)
  - POST /v1/module/<id>/events      — приём событий от connector'а (§7)

Не реализовано (Step 3+):
  - GET  /v1/module/<id>/actions     — long-poll outbox для actions
  - POST /v1/module/<id>/ack         — connector'ский ACK
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Set

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from modules._base import ModuleEnvelope
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


# ── Этап 3 step 2: events endpoint ───────────────────────────────────────────

# In-memory dedup ring. Хранит последние N envelope id'ов чтобы повтор от
# connector'а (после reconnect / retry) не приводил к double-processing.
# Per-channel ring чтобы не блокировать каналы взаимными retry'ями.
_DEDUP_RING_SIZE = 5000
_processed_envelopes: dict = {}  # channel_id → (Set[id], Deque[id])


def _is_duplicate_envelope(channel_id: int, env_id: str) -> bool:
    """True если уже видели этот id за последние _DEDUP_RING_SIZE сообщений."""
    if not env_id:
        return False  # пустой id не дедуплицируем — caller'у виднее
    pair = _processed_envelopes.get(channel_id)
    if pair is None:
        pair = (set(), deque())
        _processed_envelopes[channel_id] = pair
    seen, q = pair
    if env_id in seen:
        return True
    seen.add(env_id)
    q.append(env_id)
    if len(q) > _DEDUP_RING_SIZE:
        old = q.popleft()
        seen.discard(old)
    return False


def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


@router.post("/v1/module/{module_id}/events", include_in_schema=False)
async def module_events(module_id: str, request: Request):
    """Принимает массив envelope'ов от connector'а. Per docs/MODULE_API.md §7.

    Auth: Authorization: Bearer <module-token>. Token issuance — через
    GET /api/streamer/module-token (M4.4 dashboard, требует session cookie).

    Body: {channel_id: int, envelopes: [{id, kind, type, ts, data}]}.
    Caller channel_id должен совпадать с token.channel_id (защита от
    cross-channel injection через cтянутый токен с другого канала).

    Returns: {status: "ok", acks: [{id, success, error?}]}.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )

    # 1. Auth
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "missing_auth", "message": "Authorization: Bearer <module-token> required"},
        )
    # Late-import чтобы избежать циклической зависимости routes ↔ streamer.
    from routes.streamer import verify_module_token
    claims = verify_module_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "invalid_token", "message": "Module-token не валиден или истёк"},
        )
    if claims["module_id"] != module_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "module_id_mismatch",
                    "message": f"Token issued for {claims['module_id']}, route is {module_id}"},
        )

    # 2. Body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "bad_json"},
        )
    raw_cid = body.get("channel_id") or 0
    try:
        body_channel_id = int(raw_cid)
    except (TypeError, ValueError):
        body_channel_id = 0
    if body_channel_id != claims["channel_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "channel_id_mismatch",
                    "message": "body.channel_id не совпадает с token.channel_id"},
        )
    channel_id = body_channel_id

    envelopes_raw = body.get("envelopes") or []
    if not isinstance(envelopes_raw, list):
        # Fallback: одиночный envelope без wrapper'а
        envelopes_raw = [body] if body.get("type") else []
    if not envelopes_raw:
        return {"status": "ok", "acks": []}

    # 3. Dispatch each envelope
    acks: list = []
    for raw in envelopes_raw:
        if not isinstance(raw, dict):
            acks.append({"id": "?", "success": False, "error": "envelope_not_object"})
            continue
        env = ModuleEnvelope(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or "event"),
            type=str(raw.get("type") or ""),
            ts=int(raw.get("ts") or 0),
            data=raw.get("data") or {},
        )
        if not env.type:
            acks.append({"id": env.id, "success": False, "error": "type_required"})
            continue
        # Manifest validation: тип события должен быть declared в manifest'е
        if not adapter.manifest.supports_event(env.type):
            acks.append({"id": env.id, "success": False, "error": "event_not_in_manifest"})
            continue
        # Dedup
        if _is_duplicate_envelope(channel_id, env.id):
            acks.append({"id": env.id, "success": True, "duplicate": True})
            continue
        # Lifecycle hooks для module.* events
        try:
            if env.type == "module.session_start":
                await adapter.on_session_start(channel_id, env.data)
            elif env.type == "module.session_end":
                await adapter.on_session_end(channel_id, env.data)
            # Все custom + remaining standard события идут в handle_event
            # (включая module.heartbeat — adapter сам решает no-op'ить или нет)
            await adapter.handle_event(channel_id, env)
            acks.append({"id": env.id, "success": True})
        except Exception as e:
            acks.append({"id": env.id, "success": False, "error": f"{type(e).__name__}: {e}"})

    return {"status": "ok", "acks": acks}
