"""
routes/dev_login.py — Dev test page с Twitch OAuth login для viewers.

Use case: открыть https://shedoy23.ru/dev → login через Twitch →
получить preview extension URL который persists через restart server.

Архитектурно использует EXISTING `/api/streamer/auth/callback` redirect
URI (registered в Twitch Dev Console). State начинается с "dev_" чтобы
streamer.callback пере-направлял к нашему handle_dev_callback.

Flow:
  1. GET /dev — landing (HTML)
       - Если есть session cookie → button «Open extension preview»
       - Иначе → button «Login with Twitch»
  2. GET /dev/auth/start — генерим state="dev_<random>", redirect Twitch
  3. (callback к streamer.auth_callback который dispatches к нам по state)
  4. GET /dev/preview — read cookie → render page с auto-open extension
  5. GET /dev/logout — clear cookie

Session: HTTP-only cookie 'rimlink_dev_session' с подписанным JWT
(TWITCH_EXTENSION_SECRET, HS256). TTL 30 дней. Хранит login + user_id.
"""
from __future__ import annotations

import base64
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import aiohttp
import jwt as _jwt
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import (
    CHANNEL_POINTS_CONFIG,
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    TWITCH_EXTENSION_SECRET,
)

router = APIRouter()

_DEV_SESSION_COOKIE = "rimlink_dev_session"
_DEV_SESSION_TTL_SEC = 30 * 24 * 3600  # 30 days
_DEV_STATE_TTL_SEC = 600  # 10 минут OAuth flow
_DEV_STATE_PREFIX = "dev_"

# Использует тот же registered redirect URI что и streamer flow.
# Twitch требует exact match — Re-use чтобы не плодить registrations.
_DEV_REDIRECT_URI = "https://shedoy23.ru/api/streamer/auth/callback"

# OAuth scope: только viewer info, не streamer permissions.
# Empty scope = только publicly-available user info (login, display_name).
_DEV_SCOPE = ""

# In-memory state store (Anti-CSRF). Cleared при restart, что OK —
# state TTL 10 мин, redo OAuth flow.
_state_store: dict = {}  # {state: expires_at}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode_secret() -> bytes:
    """Decode TWITCH_EXTENSION_SECRET — base64url-encoded."""
    secret_b64 = TWITCH_EXTENSION_SECRET.replace("-", "+").replace("_", "/")
    padding = 4 - len(secret_b64) % 4
    if padding != 4:
        secret_b64 += "=" * padding
    return base64.b64decode(secret_b64)


def _issue_state() -> str:
    """Генерируем CSRF state для OAuth. Stored до consume."""
    state = _DEV_STATE_PREFIX + secrets.token_urlsafe(24)
    _state_store[state] = time.time() + _DEV_STATE_TTL_SEC
    # Cleanup expired
    now = time.time()
    expired = [s for s, exp in _state_store.items() if exp < now]
    for s in expired:
        del _state_store[s]
    return state


def _consume_state(state: str) -> bool:
    """One-time use state. Returns True если был valid (и удаляет)."""
    if not state or state not in _state_store:
        return False
    if _state_store[state] < time.time():
        del _state_store[state]
        return False
    del _state_store[state]
    return True


def _issue_dev_session_jwt(login: str, user_id: str) -> str:
    """Подписать JWT для cookie session. Содержит login + user_id.
    Использует тот же TWITCH_EXTENSION_SECRET — backend verify через
    `verify_twitch_jwt` распознает как валидный.
    """
    broadcaster_id = str(CHANNEL_POINTS_CONFIG.get("broadcaster_id") or "")
    payload = {
        "channel_id":     broadcaster_id,
        "user_id":        user_id,
        "sub":            login.lower(),
        "role":           "viewer",
        "opaque_user_id": f"U{user_id}",
        "exp":            int(time.time()) + _DEV_SESSION_TTL_SEC,
        "iss":            "rimlink_dev",
    }
    return _jwt.encode(payload, _decode_secret(), algorithm="HS256")


def _read_session_cookie(request: Request) -> Optional[dict]:
    """Возвращает {login, user_id} из cookie или None."""
    token = request.cookies.get(_DEV_SESSION_COOKIE, "")
    if not token:
        return None
    try:
        payload = _jwt.decode(
            token, _decode_secret(), algorithms=["HS256"], options={"verify_exp": True}
        )
        if payload.get("iss") != "rimlink_dev":
            return None
        return {
            "login":   payload.get("sub", ""),
            "user_id": payload.get("user_id", ""),
            "token":   token,
        }
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/dev", include_in_schema=False)
async def dev_landing(request: Request):
    """Landing — login button или extension preview если уже залогинен."""
    session = _read_session_cookie(request)
    if session:
        body = f"""
            <h1>RimLink Dev Preview</h1>
            <p>Logged in as <b>@{session['login']}</b></p>
            <p>
                <a class="btn primary" href="/dev/preview">🎮 Open Extension Preview</a>
            </p>
            <p>
                <a class="btn" href="/dev/logout">Logout</a>
            </p>
        """
    else:
        body = """
            <h1>RimLink Dev Preview</h1>
            <p>Login через Twitch чтобы тестить расширение.</p>
            <p>
                <a class="btn primary" href="/dev/auth/start">🟣 Login with Twitch</a>
            </p>
        """
    return HTMLResponse(_wrap_html(body))


@router.get("/dev/auth/start", include_in_schema=False)
async def dev_auth_start():
    """Начало OAuth flow для dev preview."""
    if not TWITCH_CLIENT_ID:
        return HTMLResponse(_wrap_html("<h1>Error</h1><p>OAuth не настроен.</p>"), status_code=503)
    state = _issue_state()
    params = {
        "client_id":     TWITCH_CLIENT_ID,
        "redirect_uri":  _DEV_REDIRECT_URI,
        "response_type": "code",
        "scope":         _DEV_SCOPE,
        "state":         state,
    }
    return RedirectResponse(
        f"https://id.twitch.tv/oauth2/authorize?{urlencode(params)}",
        status_code=302,
    )


async def handle_dev_callback(request: Request):
    """Called из routes/streamer.auth_callback когда state startswith 'dev_'.

    Не registered как route напрямую — dispatched внутри streamer callback.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")

    if request.query_params.get("error"):
        return HTMLResponse(_wrap_html(
            f"<h1>OAuth Cancelled</h1><p>{request.query_params.get('error_description', '')}</p>"
            "<p><a href='/dev'>← Back</a></p>"
        ))
    if not code:
        return HTMLResponse(_wrap_html("<h1>Error</h1><p>No code.</p>"), status_code=400)
    if not _consume_state(state):
        return HTMLResponse(_wrap_html(
            "<h1>CSRF Error</h1><p>State не валиден или истёк. <a href='/dev'>Try again</a></p>"
        ), status_code=400)
    if not (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET):
        return HTMLResponse(_wrap_html("<h1>Error</h1><p>OAuth не настроен.</p>"), status_code=503)

    # Step 1: exchange code → user_access_token
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post("https://id.twitch.tv/oauth2/token", data={
                "client_id":     TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "code":          code,
                "grant_type":    "authorization_code",
                "redirect_uri":  _DEV_REDIRECT_URI,
            }) as r:
                token_data = await r.json()
                if r.status != 200:
                    return HTMLResponse(_wrap_html(
                        f"<h1>Twitch Error</h1><pre>{token_data}</pre>"
                    ), status_code=502)
                user_token = token_data.get("access_token")
                if not user_token:
                    return HTMLResponse(_wrap_html(
                        "<h1>Error</h1><p>No access_token в ответе Twitch.</p>"
                    ), status_code=502)

            # Step 2: fetch user info
            async with sess.get(
                "https://api.twitch.tv/helix/users",
                headers={
                    "Client-Id":     TWITCH_CLIENT_ID,
                    "Authorization": f"Bearer {user_token}",
                },
            ) as r:
                user_data = await r.json()
                if r.status != 200 or not user_data.get("data"):
                    return HTMLResponse(_wrap_html(
                        f"<h1>Twitch Error</h1><pre>{user_data}</pre>"
                    ), status_code=502)
                user = user_data["data"][0]
                login = user.get("login", "").lower()
                user_id = user.get("id", "")
    except Exception as e:
        return HTMLResponse(_wrap_html(
            f"<h1>OAuth Error</h1><pre>{type(e).__name__}: {e}</pre>"
        ), status_code=502)

    if not login or not user_id:
        return HTMLResponse(_wrap_html(
            "<h1>Error</h1><p>Twitch не вернул login/id.</p>"
        ), status_code=502)

    # Step 3: issue dev session JWT в cookie
    session_jwt = _issue_dev_session_jwt(login, user_id)
    response = RedirectResponse(url="/dev", status_code=302)
    response.set_cookie(
        key=_DEV_SESSION_COOKIE,
        value=session_jwt,
        max_age=_DEV_SESSION_TTL_SEC,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/dev/preview", include_in_schema=False)
async def dev_preview(request: Request):
    """Open extension.html с auto-injected JWT.

    Same JWT что в session cookie, передаём через query — extension.html
    инициализируется через ?dev_jwt=<token> (см. viewer.js preview-mode).
    """
    session = _read_session_cookie(request)
    if not session:
        return RedirectResponse(url="/dev", status_code=302)
    # Просто redirect на extension.html с tokenом
    params = urlencode({"dev_jwt": session["token"], "dev_user": session["login"]})
    return RedirectResponse(url=f"/frontend/extension.html?{params}", status_code=302)


@router.get("/dev/logout", include_in_schema=False)
async def dev_logout():
    """Clear cookie."""
    response = RedirectResponse(url="/dev", status_code=302)
    response.delete_cookie(_DEV_SESSION_COOKIE)
    return response


@router.get("/dev/me", include_in_schema=False)
async def dev_me(request: Request):
    """JSON endpoint для frontend: who am I?"""
    session = _read_session_cookie(request)
    if not session:
        return JSONResponse({"logged_in": False})
    return {
        "logged_in": True,
        "login":     session["login"],
        "user_id":   session["user_id"],
    }


# ── HTML wrapper ──────────────────────────────────────────────────────────────

def _wrap_html(body_html: str) -> str:
    """Простой dark-theme wrapper в Twitch style."""
    return """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>RimLink Dev</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body{background:#0e0e10;color:#efeff1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;box-sizing:border-box;}
.box{max-width:480px;background:#18181b;border:1px solid #2d2d2f;border-radius:14px;padding:32px;text-align:center;}
h1{color:#9147ff;font-size:22px;margin:0 0 14px;}
p{color:#adadb8;line-height:1.5;font-size:14px;}
.btn{display:inline-block;background:#2d2d2f;color:#efeff1;border:1px solid #3d3d3f;border-radius:8px;
     padding:10px 18px;text-decoration:none;font-weight:600;font-size:13px;margin:6px 4px;transition:background .2s;}
.btn:hover{background:#3d3d3f;}
.btn.primary{background:#9147ff;border-color:#9147ff;color:#fff;}
.btn.primary:hover{background:#a96aff;}
pre{background:#0e0e10;border:1px solid #2d2d2f;border-radius:6px;padding:10px;
    font-size:11px;color:#fbbf24;text-align:left;overflow-x:auto;}
</style>
</head><body><div class="box">""" + body_html + """</div></body></html>"""
