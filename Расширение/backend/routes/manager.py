# -*- coding: utf-8 -*-
"""HTTP/browser boundary for Manager pairing.

Twitch credentials remain in the existing browser OAuth/session flow. The
desktop client receives only a Manager session after explicit browser approval.
"""
from __future__ import annotations

import html
import json
import logging
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import manager_auth
from config import MANAGER_PUBLIC_BASE_URL
from dependencies import check_rate_limit, get_db
from routes.streamer import _read_session_cookie


log = logging.getLogger("rimlink.manager")
router = APIRouter()


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
