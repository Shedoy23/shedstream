# -*- coding: utf-8 -*-
"""HTTP/browser boundary for Manager pairing.

Twitch credentials remain in the existing browser OAuth/session flow. The
desktop client receives only a Manager session after explicit browser approval.
"""
from __future__ import annotations

import html
import json
import logging
import time
import uuid
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import manager_auth
from config import MANAGER_PUBLIC_BASE_URL
from dependencies import check_rate_limit, get_db
from routes.streamer import _read_session_cookie


log = logging.getLogger("rimlink.manager")
router = APIRouter()
DIAGNOSTIC_TTL_SECONDS = 120


def _client_key(request: Request, action: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"manager:{action}:{ip}"


def _auth_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, manager_auth.ManagerAuthUnavailable):
        return JSONResponse({"status": "manager_auth_unavailable"}, status_code=503)
    code = exc.code if isinstance(exc, manager_auth.ManagerAuthError) else "internal_error"
    statuses = {
        "authorization_pending": 202,
        "pairing_denied": 403,
        "pairing_expired": 410,
        "pairing_exchanged": 409,
        "pairing_already_exchanged": 409,
        "pairing_not_found": 404,
        "invalid_device_secret": 401,
        "invalid_manager_access": 401,
        "module_scope_mismatch": 403,
        "credential_not_found": 404,
        "credential_not_active": 409,
        "invalid_refresh_token": 401,
        "refresh_reuse_detected": 401,
        "manager_session_expired": 401,
        "invalid_manager_session": 401,
    }
    return JSONResponse({"status": code}, status_code=statuses.get(code, 400))


def _browser_error(exc: Exception) -> str:
    if isinstance(exc, manager_auth.ManagerAuthUnavailable):
        return "Manager pairing временно недоступен."
    if isinstance(exc, manager_auth.ManagerAuthError):
        return exc.code
    return "internal_error"


async def _json_body(request: Request) -> dict:
    try:
        raw = await request.body()
        if len(raw) > 8192:
            raise manager_auth.ManagerAuthError("request_too_large")
        body = json.loads(raw.decode("utf-8"))
    except manager_auth.ManagerAuthError:
        raise
    except Exception as exc:
        raise manager_auth.ManagerAuthError("invalid_json") from exc
    if not isinstance(body, dict):
        raise manager_auth.ManagerAuthError("invalid_json")
    return body


async def _optional_json_body(request: Request) -> dict:
    """Accept an empty body for compatibility with Manager builds before modes."""
    raw = await request.body()
    if not raw:
        return {}
    if len(raw) > 8192:
        raise manager_auth.ManagerAuthError("request_too_large")
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise manager_auth.ManagerAuthError("invalid_json") from exc
    if not isinstance(body, dict):
        raise manager_auth.ManagerAuthError("invalid_json")
    return body


def _secret_response(payload: dict, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


async def _manager_claims(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not token:
        raise manager_auth.ManagerAuthError("invalid_manager_access")
    db = get_db()
    async with db._connect() as conn:
        claims = await manager_auth.verify_access_token(conn, token)
    if not claims:
        raise manager_auth.ManagerAuthError("invalid_manager_access")
    return claims


@router.post("/v1/manager/pairings", include_in_schema=False)
async def manager_pairing_create(request: Request):
    if not check_rate_limit(_client_key(request, "create"), limit=10):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        body = await _json_body(request)
        module_id = str(body.get("module_id") or "").strip()
        from modules._loader import get_module
        if get_module(module_id) is None:
            return JSONResponse({"status": "module_not_found"}, status_code=404)
        db = get_db()
        async with db._connect() as conn:
            result = await manager_auth.create_pairing(
                conn,
                str(body.get("installation_id") or ""),
                module_id,
                str(body.get("device_challenge") or ""),
            )
        return JSONResponse({
            "status": "ok",
            **result,
            "verification_uri": f"{MANAGER_PUBLIC_BASE_URL}/manager/pair?code={quote(result['user_code'])}",
            "expires_in": manager_auth.PAIRING_TTL_SECONDS,
        })
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post("/v1/manager/pairings/{pairing_id}/exchange", include_in_schema=False)
async def manager_pairing_exchange(pairing_id: str, request: Request):
    if not check_rate_limit(_client_key(request, "exchange"), limit=60):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        body = await _json_body(request)
        db = get_db()
        async with db._connect() as conn:
            result = await manager_auth.exchange_pairing(
                conn, pairing_id, str(body.get("device_secret") or "")
            )
        return JSONResponse({"status": "ok", **result})
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post("/v1/manager/session/refresh", include_in_schema=False)
async def manager_session_refresh(request: Request):
    if not check_rate_limit(_client_key(request, "session_refresh"), limit=30):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        body = await _json_body(request)
        db = get_db()
        async with db._connect() as conn:
            result = await manager_auth.refresh_manager_session(
                conn, str(body.get("refresh_token") or "")
            )
        return _secret_response({"status": "ok", **result})
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post("/v1/manager/logout", include_in_schema=False)
async def manager_session_logout(request: Request):
    if not check_rate_limit(_client_key(request, "session_logout"), limit=30):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        db = get_db()
        async with db._connect() as conn:
            await manager_auth.revoke_manager_session(conn, claims)
        return _secret_response({"status": "ok", "logged_out": True})
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post("/v1/manager/diagnostics/test-action", include_in_schema=False)
async def manager_diagnostic_start(request: Request):
    if not check_rate_limit(_client_key(request, "diagnostic_start"), limit=10):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        channel_id = int(claims["channel_id"])
        module_id = str(claims.get("module_id") or "")
        if module_id not in {"rimworld", "bannerlord", "shedcolony"}:
            return JSONResponse({"status": "diagnostic_not_supported"}, status_code=409)
        body = await _optional_json_body(request)
        mode = str(body.get("mode") or "ready").strip().lower()
        if mode not in {"ready", "refuse", "lost_ack"}:
            return JSONResponse({"status": "invalid_diagnostic_mode"}, status_code=400)
        if module_id != "rimworld" and mode != "ready":
            return JSONResponse({"status": "diagnostic_mode_not_supported"}, status_code=409)
        import module_liveness
        db = get_db()
        if not await module_liveness.is_on_air(db, channel_id, module_id):
            return JSONResponse({"status": "module_offline"}, status_code=409)

        diagnostic_id = f"diag_{mode}_" + uuid.uuid4().hex
        command_id = f"manager_{mode}_" + uuid.uuid4().hex
        now = time.time()
        command = {
            "id": command_id,
            "type": "diagnostic_refuse" if mode == "refuse" else "diagnostic_ping",
            "channel_id": channel_id,
            "diagnostic_id": diagnostic_id,
            "diagnostic_mode": mode,
            "price": 0,
        }
        # The currently published ShedColony connector predates the generic
        # diagnostic action. Its authenticated long-poll heartbeat is still a
        # real proof that the game mod, config and backend channel are alive.
        # Record that readiness directly until the next connector release adds
        # diagnostic_ping parity with Bannerlord.
        if module_id == "shedcolony":
            async with db._connect() as conn:
                await conn.execute(
                    "INSERT INTO manager_diagnostic_actions "
                    "(diagnostic_id,channel_id,module_id,command_id,status,created_at,completed_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (diagnostic_id, channel_id, module_id, command_id,
                     "acked", now, now),
                )
                await conn.commit()
            return _secret_response({
                "status": "queued",
                "diagnostic_id": diagnostic_id,
                "mode": mode,
                "expires_in": DIAGNOSTIC_TTL_SECONDS,
            }, status_code=201)
        async with db._connect() as conn:
            if module_id == "rimworld":
                import rimworld
                await rimworld._ensure_pending_commands_table(conn)
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute(
                "INSERT INTO manager_diagnostic_actions "
                "(diagnostic_id,channel_id,module_id,command_id,status,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (diagnostic_id, channel_id, module_id, command_id, "queued", now),
            )
            if module_id == "rimworld":
                await conn.execute(
                    "INSERT INTO rimworld_pending_commands "
                    "(channel_id,cmd_id,cmd_json,status) VALUES (?,?,?,'queued')",
                    (channel_id, command_id, json.dumps(command, ensure_ascii=False)),
                )
            else:
                await conn.execute(
                    "INSERT INTO module_actions "
                    "(channel_id,module_id,action_id,type,data,status) "
                    "VALUES (?,?,?,?,?,'queued')",
                    (channel_id, module_id, command_id, command["type"],
                     json.dumps(command, ensure_ascii=False)),
                )
            await conn.commit()
        return _secret_response({
            "status": "queued",
            "diagnostic_id": diagnostic_id,
            "mode": mode,
            "expires_in": DIAGNOSTIC_TTL_SECONDS,
        }, status_code=201)
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.get(
    "/v1/manager/diagnostics/test-action/{diagnostic_id}",
    include_in_schema=False,
)
async def manager_diagnostic_result(diagnostic_id: str, request: Request):
    if not check_rate_limit(_client_key(request, "diagnostic_result"), limit=180):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        channel_id = int(claims["channel_id"])
        module_id = str(claims.get("module_id") or "")
        db = get_db()
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT status,created_at,completed_at,error,command_id "
                "FROM manager_diagnostic_actions "
                "WHERE diagnostic_id=? AND channel_id=? AND module_id=?",
                (diagnostic_id, channel_id, module_id),
            )
            row = await cur.fetchone()
            if not row:
                return JSONResponse({"status": "diagnostic_not_found"}, status_code=404)
            result_status, created_at, completed_at, error, command_id = row
            if result_status in ("queued", "delivered") and (
                time.time() - float(created_at) >= DIAGNOSTIC_TTL_SECONDS
            ):
                result_status = "expired"
                completed_at = time.time()
                if str(command_id).startswith("manager_lost_ack_"):
                    error = "simulated_ack_timeout"
                await conn.execute(
                    "UPDATE manager_diagnostic_actions "
                    "SET status='expired',completed_at=?,error=? "
                    "WHERE diagnostic_id=?",
                    (completed_at, error, diagnostic_id),
                )
                if module_id == "rimworld":
                    await conn.execute(
                        "DELETE FROM rimworld_pending_commands "
                        "WHERE channel_id=? AND cmd_id=?",
                        (channel_id, command_id),
                    )
                else:
                    await conn.execute(
                        "DELETE FROM module_actions "
                        "WHERE channel_id=? AND module_id=? AND action_id=? "
                        "AND status IN ('queued','dispatched')",
                        (channel_id, module_id, command_id),
                    )
                await conn.commit()
        diagnostic_mode = "ready"
        for candidate in ("refuse", "lost_ack"):
            if str(command_id).startswith(f"manager_{candidate}_"):
                diagnostic_mode = candidate
                break
        return _secret_response({
            "status": result_status,
            "diagnostic_id": diagnostic_id,
            "mode": diagnostic_mode,
            "created_at": created_at,
            "completed_at": completed_at,
            "error": error,
        })
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post("/v1/manager/module-credentials", include_in_schema=False)
async def manager_credential_issue(request: Request):
    if not check_rate_limit(_client_key(request, "credential_issue"), limit=20):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        body = await _json_body(request)
        db = get_db()
        async with db._connect() as conn:
            result = await manager_auth.issue_module_credential(
                conn,
                claims,
                str(body.get("module_id") or ""),
                str(body.get("label") or ""),
            )
        return _secret_response({"status": "ok", **result}, status_code=201)
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.post(
    "/v1/manager/module-credentials/{credential_id}/rotate",
    include_in_schema=False,
)
async def manager_credential_rotate(credential_id: str, request: Request):
    if not check_rate_limit(_client_key(request, "credential_rotate"), limit=20):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        body = await _json_body(request)
        db = get_db()
        async with db._connect() as conn:
            result = await manager_auth.rotate_module_credential(
                conn, claims, credential_id, str(body.get("label") or "")
            )
        return _secret_response({"status": "ok", **result}, status_code=201)
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


@router.delete(
    "/v1/manager/module-credentials/{credential_id}",
    include_in_schema=False,
)
async def manager_credential_revoke(credential_id: str, request: Request):
    if not check_rate_limit(_client_key(request, "credential_revoke"), limit=40):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    try:
        claims = await _manager_claims(request)
        db = get_db()
        async with db._connect() as conn:
            await manager_auth.revoke_module_credential(conn, claims, credential_id)
        return _secret_response({"status": "ok", "revoked": True})
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _auth_error(exc)


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    response = HTMLResponse(
        "<!doctype html><html lang='ru'><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<body style='font:16px system-ui;max-width:640px;margin:48px auto;padding:0 20px'>"
        f"<h1>{html.escape(title)}</h1>{body}</body></html>",
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/manager/pair", include_in_schema=False)
async def manager_pair_page(request: Request):
    if not check_rate_limit(_client_key(request, "page"), limit=60):
        return _page("Слишком много запросов", "<p>Повтори позже.</p>", 429)
    code = (request.query_params.get("code") or "").strip().upper()
    if not code:
        return _page("Неверный код", "<p>Открой ссылку из ShedLink Manager.</p>", 400)
    channel_id = _read_session_cookie(request)
    if channel_id is None:
        return _page(
            "Нужен вход через Twitch",
            "<p>Войди через Twitch — после входа вернёшься на подтверждение.</p>"
            f"<p><a href='/api/streamer/auth/start?return_to={quote('/manager/pair?code=' + code, safe='')}'>"
            "Войти через Twitch</a></p>",
            401,
        )
    try:
        db = get_db()
        channel = await db.get_channel(channel_id)
        if not channel or not channel.get("approved"):
            return _page("Канал не одобрен", "<p>Pairing для этого канала пока недоступен.</p>", 403)
        async with db._connect() as conn:
            row = await manager_auth.find_pairing_by_user_code(conn, code)
        if row[2] != "pending":
            return _page("Pairing уже завершён", f"<p>Статус: {html.escape(row[2])}</p>", 409)
        csrf = manager_auth.issue_approval_csrf(row[0], channel_id)
        module_id = html.escape(row[1])
        pairing_id = html.escape(row[0], quote=True)
        csrf_html = html.escape(csrf, quote=True)
        return _page(
            "Подключить ShedLink Manager",
            f"<p>Канал: <strong>{html.escape(channel.get('display_name') or channel.get('login') or str(channel_id))}</strong></p>"
            f"<p>Integration: <strong>{module_id}</strong></p>"
            f"<p>Код: <strong>{html.escape(code)}</strong></p>"
            "<form method='post' action='/manager/pair'>"
            f"<input type='hidden' name='pairing_id' value='{pairing_id}'>"
            f"<input type='hidden' name='csrf' value='{csrf_html}'>"
            "<button name='decision' value='approve'>Разрешить</button> "
            "<button name='decision' value='deny'>Отклонить</button></form>",
        )
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        status_code = _auth_error(exc).status_code
        return _page("Pairing недоступен", f"<p>{html.escape(_browser_error(exc))}</p>", status_code)


@router.post("/manager/pair", include_in_schema=False)
async def manager_pair_decide(request: Request):
    if not check_rate_limit(_client_key(request, "approve"), limit=20):
        return _page("Слишком много запросов", "<p>Повтори позже.</p>", 429)
    channel_id = _read_session_cookie(request)
    if channel_id is None:
        return _page("Сессия истекла", "<p>Войди через Twitch и повтори.</p>", 401)
    try:
        raw = await request.body()
        if len(raw) > 4096:
            raise manager_auth.ManagerAuthError("request_too_large")
        form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        pairing_id = str((form.get("pairing_id") or [""])[0])
        csrf = str((form.get("csrf") or [""])[0])
        decision = str((form.get("decision") or [""])[0])
        if decision not in ("approve", "deny"):
            raise manager_auth.ManagerAuthError("invalid_decision")
        if not manager_auth.verify_approval_csrf(csrf, pairing_id, channel_id):
            raise manager_auth.ManagerAuthError("invalid_csrf")
        db = get_db()
        channel = await db.get_channel(channel_id)
        if not channel or not channel.get("approved"):
            return _page("Канал не одобрен", "<p>Pairing недоступен.</p>", 403)
        async with db._connect() as conn:
            await manager_auth.decide_pairing(
                conn, pairing_id, channel_id, approve=(decision == "approve")
            )
        title = "Manager подключён" if decision == "approve" else "Подключение отклонено"
        return _page(title, "<p>Можно вернуться в ShedLink Manager.</p>")
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable) as exc:
        return _page(
            "Pairing не выполнен",
            f"<p>{html.escape(_browser_error(exc))}</p>",
            _auth_error(exc).status_code,
        )


# ── Воронка онбординга (ROADMAP §R4) ────────────────────────────────────────
# Manager шлёт сюда шаги установки. До входа в Twitch токена ещё нет, поэтому
# ранние шаги принимаются без него — иначе самая интересная часть воронки, «где
# люди отваливаются ДО входа», осталась бы невидимой. Защита от мусора: закрытый
# список имён, лимит частоты, ограничение длины полей и channel_id ТОЛЬКО из
# токена, никогда из тела.
@router.post("/v1/manager/onboarding", include_in_schema=False)
async def manager_onboarding_events(request: Request):
    if not check_rate_limit(_client_key(request, "onboarding"), limit=120):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    import onboarding

    body = await _optional_json_body(request)
    events = body.get("events")
    if not isinstance(events, list) or not events:
        return JSONResponse({"status": "no_events"}, status_code=400)
    if len(events) > 50:
        return JSONResponse({"status": "too_many_events"}, status_code=400)

    channel_id = None
    try:
        claims = await _manager_claims(request)
        channel_id = int(claims["channel_id"])
    except (manager_auth.ManagerAuthError, manager_auth.ManagerAuthUnavailable):
        channel_id = None      # ранние шаги идут без токена, это законно

    accepted, ignored, rejected = 0, 0, []
    db = get_db()
    async with db._connect() as conn:
        for item in events:
            if not isinstance(item, dict):
                rejected.append("not_an_object")
                continue
            name = str(item.get("event") or "").strip()
            if name not in onboarding.KNOWN_EVENTS:
                rejected.append("unknown_event")
                continue
            if name in onboarding.DERIVED_EVENTS:
                # Эти события бэкенд выводит сам. Принимать их снаружи значило
                # бы позволить нарисовать себе успешную воронку.
                rejected.append("derived_event_not_accepted")
                continue
            if name not in onboarding.PRE_AUTH_EVENTS and channel_id is None:
                rejected.append("auth_required")
                continue
            try:
                written = await onboarding.record(
                    conn,
                    name,
                    installation_id=item.get("installation_id"),
                    channel_id=channel_id,
                    integration_id=item.get("integration_id"),
                    integration_version=item.get("integration_version"),
                    manager_version=item.get("manager_version"),
                    elapsed_ms=item.get("elapsed_ms"),
                    result=item.get("result"),
                    source_step=item.get("source_step"),
                    client_event_id=item.get("client_event_id"),
                )
            except (ValueError, TypeError):
                rejected.append("bad_field")
                continue
            if written:
                accepted += 1
            else:
                ignored += 1        # повтор по client_event_id
        await conn.commit()
    return _secret_response({
        "status": "ok",
        "accepted": accepted,
        "ignored_duplicates": ignored,
        "rejected": rejected[:10],
    })
