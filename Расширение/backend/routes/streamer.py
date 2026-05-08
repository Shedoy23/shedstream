"""
routes/streamer.py — M4.3 OAuth flow + M4.4 admin-UI lite dashboard.

Стример заходит на /streamer, нажимает «Sign in with Twitch», проходит OAuth
консент, и после callback'а попадает в реестр `channels`. Получает signed
session cookie и редиректится на /streamer/dashboard где видит свой статус.

OAuth + dashboard flow:
  1. GET /streamer                     — landing с кнопкой login (или редирект
                                          на dashboard если cookie уже валиден)
  2. GET /api/streamer/auth/start      — генерирует CSRF-state, 302 на Twitch
  3. GET /api/streamer/auth/callback   — обмен code → tokens, Helix /users,
                                          upsert в channels, set cookie, 302
                                          на /streamer/dashboard
  4. GET /streamer/dashboard           — требует cookie, рендерит статус
  5. GET /api/streamer/me              — JSON для возможной dynamic-UI (M4+)
  6. POST /streamer/logout             — очищает cookie

Cookie session — HMAC-SHA256 подпись `channel_id|expires_at` с
TWITCH_EXTENSION_SECRET. TTL 30 дней. HttpOnly, Secure, SameSite=Lax.

Token refresh access_token'а — out of scope. M4.5 будет dёргать refresh_token
при expires_at < now перед EventSub-вызовами.
"""
import asyncio
import hashlib
import hmac
import secrets
import time
from typing import Dict, Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import (
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    TWITCH_EXTENSION_SECRET,
    TWITCH_OAUTH_REDIRECT_URI,
    TWITCH_OAUTH_SCOPES,
)
from dependencies import get_db, mark_channel_registered

router = APIRouter()

# ── State store (CSRF-защита OAuth flow) ──────────────────────────────────────
# state → expiry timestamp. Очищается lazy при каждом start/callback.
# В одиночном-инстанс прод-сетапе in-memory достаточно.
_STATE_TTL = 300  # 5 минут на завершение OAuth flow
_oauth_states: Dict[str, float] = {}


def _cleanup_expired_states() -> None:
    now = time.time()
    expired = [s for s, exp in _oauth_states.items() if exp < now]
    for s in expired:
        _oauth_states.pop(s, None)


def _issue_state() -> str:
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time() + _STATE_TTL
    return state


def _consume_state(state: str) -> bool:
    """Проверить и удалить state. True если валиден и не expired."""
    _cleanup_expired_states()
    expiry = _oauth_states.pop(state, None)
    return expiry is not None and expiry >= time.time()


# ── HTML pages ────────────────────────────────────────────────────────────────
_LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Подключить расширение — Shedoy23 Platform</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #18181b; color: #efeff1;
           display: flex; flex-direction: column; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { max-width: 480px; background: #1f1f23; border-radius: 12px; padding: 40px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.3); text-align: center; }
    h1 { font-size: 28px; margin: 0 0 12px; }
    p { color: #adadb8; line-height: 1.5; margin: 0 0 24px; }
    .btn { display: inline-block; background: #9147ff; color: #fff; padding: 14px 32px;
           text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px;
           transition: background 0.15s; }
    .btn:hover { background: #772ce8; }
    .footer { margin-top: 24px; font-size: 13px; color: #6e6e73; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Подключи расширение к каналу</h1>
    <p>После авторизации через Twitch твой канал попадёт в реестр платформы и расширение начнёт работать у твоих зрителей.</p>
    <a class="btn" href="/api/streamer/auth/start">Войти через Twitch</a>
    <div class="footer">Запрашиваемые разрешения: чтение профиля и channel points redemptions (для будущей интеграции).</div>
  </div>
</body>
</html>"""


def _error_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Ошибка</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#18181b;color:#efeff1;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px}}
.card{{max-width:480px;background:#1f1f23;border-radius:12px;padding:40px;text-align:center}}
h1{{color:#ff4444;margin:0 0 12px}}p{{color:#adadb8;margin:0 0 16px}}
a{{color:#9147ff;text-decoration:none}}</style></head>
<body><div class="card"><h1>Не получилось</h1><p>{message}</p><p><a href="/streamer">← Попробовать снова</a></p></div></body></html>"""


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("/streamer", include_in_schema=False)
async def streamer_landing(request: Request):
    """Лендинг для стримеров. Если cookie валиден — редирект на dashboard."""
    cid = _read_session_cookie(request)
    if cid is not None:
        return RedirectResponse(url="/streamer/dashboard", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(_LOGIN_HTML)


@router.get("/api/streamer/auth/start", include_in_schema=False)
async def auth_start():
    """Начало OAuth flow — генерируем state, редирект на Twitch."""
    if not TWITCH_CLIENT_ID:
        return HTMLResponse(_error_html("OAuth не настроен на сервере (нет TWITCH_CLIENT_ID)."), status_code=503)
    state = _issue_state()
    params = {
        'client_id':     TWITCH_CLIENT_ID,
        'redirect_uri':  TWITCH_OAUTH_REDIRECT_URI,
        'response_type': 'code',
        'scope':         TWITCH_OAUTH_SCOPES,
        'state':         state,
        # force_verify=true чтобы стример видел консент даже после первой авторизации.
        # Без этого Twitch silently approve'ит — менее прозрачно для пользователя.
        'force_verify':  'true',
    }
    return RedirectResponse(
        f"https://id.twitch.tv/oauth2/authorize?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/api/streamer/auth/callback", include_in_schema=False)
async def auth_callback(request: Request):
    """Twitch вернул code. Меняем на токены, fetch'им user info, регистрируем канал."""
    code = request.query_params.get('code')
    state = request.query_params.get('state', '')
    error = request.query_params.get('error')

    if error:
        # User clicked Cancel или Twitch вернул ошибку
        desc = request.query_params.get('error_description', 'OAuth был отменён.')
        return HTMLResponse(_error_html(f"Twitch: {desc}"), status_code=400)

    if not code:
        return HTMLResponse(_error_html("Нет authorization code в запросе."), status_code=400)

    if not _consume_state(state):
        return HTMLResponse(
            _error_html("CSRF state не валиден или истёк — открой /streamer заново."),
            status_code=400,
        )

    if not (TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET):
        return HTMLResponse(_error_html("OAuth не настроен на сервере."), status_code=503)

    # Step 1: code → tokens
    token_data = await _exchange_code_for_tokens(code)
    if not token_data:
        return HTMLResponse(_error_html("Не удалось обменять code на токен (Twitch отклонил)."), status_code=502)

    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')
    expires_in = token_data.get('expires_in', 0)
    if not access_token:
        return HTMLResponse(_error_html("Twitch не вернул access_token."), status_code=502)

    # Step 2: fetch user info через Helix /users (текущий пользователь по токену)
    user_info = await _fetch_user_info(access_token)
    if not user_info:
        return HTMLResponse(_error_html("Не удалось получить профиль из Twitch Helix API."), status_code=502)

    try:
        channel_id = int(user_info['id'])
    except (KeyError, TypeError, ValueError):
        return HTMLResponse(_error_html("Twitch профиль без user_id."), status_code=502)

    login = (user_info.get('login') or '').lower()
    display_name = user_info.get('display_name') or login
    if not login:
        return HTMLResponse(_error_html("Twitch профиль без login."), status_code=502)

    # Step 3: upsert в channels + обновить in-memory cache (M4.1)
    expires_at_iso = _epoch_to_iso(time.time() + max(0, int(expires_in)))
    db = get_db()
    await db.upsert_channel(
        channel_id=channel_id,
        login=login,
        display_name=display_name,
        oauth_access_token=access_token,
        oauth_refresh_token=refresh_token,
        oauth_expires_at=expires_at_iso,
    )
    mark_channel_registered(channel_id)
    print(f"✅ Streamer registered: {login} (channel_id={channel_id})")

    # M4.4: signed cookie + redirect на dashboard.
    response = RedirectResponse(url="/streamer/dashboard", status_code=status.HTTP_302_FOUND)
    _set_session_cookie(response, channel_id)
    return response


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _exchange_code_for_tokens(code: str) -> Optional[dict]:
    payload = {
        'client_id':     TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'code':          code,
        'grant_type':    'authorization_code',
        'redirect_uri':  TWITCH_OAUTH_REDIRECT_URI,
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post('https://id.twitch.tv/oauth2/token', data=payload, timeout=10) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"⚠️  OAuth token exchange failed: {r.status} {body[:200]}")
                    return None
                return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️  OAuth token exchange network error: {e}")
        return None


async def _fetch_user_info(access_token: str) -> Optional[dict]:
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Client-Id':     TWITCH_CLIENT_ID,
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get('https://api.twitch.tv/helix/users', headers=headers, timeout=10) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"⚠️  Helix /users failed: {r.status} {body[:200]}")
                    return None
                data = await r.json()
                items = data.get('data', [])
                return items[0] if items else None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️  Helix /users network error: {e}")
        return None


def _epoch_to_iso(epoch: float) -> str:
    """Convert epoch seconds to ISO 8601 UTC for SQLite TIMESTAMP column."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


# ── M4.4: Signed session cookies + dashboard ──────────────────────────────────

_SESSION_COOKIE_NAME = "streamer_session"
_SESSION_TTL = 30 * 24 * 3600  # 30 дней


def _sign_session(channel_id: int, expires_at: int) -> str:
    """HMAC-SHA256 подпись `channel_id|expires_at`. Secret: TWITCH_EXTENSION_SECRET."""
    msg = f"{channel_id}|{expires_at}"
    secret = (TWITCH_EXTENSION_SECRET or "").encode() or b"unconfigured-extension-secret"
    sig = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def _verify_session(token: str) -> Optional[int]:
    """Вернуть channel_id если token валиден и не expired."""
    if not token or token.count('|') != 2:
        return None
    try:
        cid_str, exp_str, sig = token.split('|', 2)
        msg = f"{cid_str}|{exp_str}"
        secret = (TWITCH_EXTENSION_SECRET or "").encode() or b"unconfigured-extension-secret"
        expected = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_str) < int(time.time()):
            return None
        return int(cid_str)
    except (ValueError, IndexError):
        return None


def _set_session_cookie(response: Response, channel_id: int) -> None:
    expires_at = int(time.time()) + _SESSION_TTL
    token = _sign_session(channel_id, expires_at)
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=token,
        max_age=_SESSION_TTL,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_SESSION_COOKIE_NAME, path="/")


def _read_session_cookie(request: Request) -> Optional[int]:
    token = request.cookies.get(_SESSION_COOKIE_NAME, "")
    return _verify_session(token)


# ── Dashboard endpoints ──────────────────────────────────────────────────────

def _dashboard_html(ch: dict) -> str:
    """Inline dashboard. ch — record из db.get_channel() (без OAuth tokens)."""
    tier = (ch.get("tier") or "free").upper()
    tier_color = {"FREE": "#6e6e73", "PRO": "#9147ff", "VIP": "#f4b740"}.get(tier, "#6e6e73")
    module = ch.get("active_module") or "—"
    display = ch.get("display_name") or ch.get("login") or "?"
    registered_at = ch.get("registered_at") or "?"
    has_oauth = "✅" if ch.get("oauth_access_token") else "—"
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Dashboard — {display}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0e0e10;color:#efeff1;margin:0;padding:20px;min-height:100vh;box-sizing:border-box}}
  .wrap{{max-width:720px;margin:40px auto}}
  .header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}}
  .header h1{{margin:0;font-size:22px}}
  .nick{{color:#9147ff}}
  .logout{{background:transparent;color:#adadb8;border:1px solid #3a3a3d;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}}
  .logout:hover{{color:#fff;border-color:#fff}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}
  .tile{{background:#1f1f23;border-radius:10px;padding:20px}}
  .tile .lbl{{color:#adadb8;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}}
  .tile .val{{font-size:20px;font-weight:600}}
  .tier-badge{{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:700;font-size:14px;color:#fff;background:{tier_color}}}
  .footnote{{margin-top:28px;color:#6e6e73;font-size:13px;line-height:1.5}}
  code{{background:#1f1f23;padding:2px 8px;border-radius:4px;color:#e0d6ff}}
</style></head>
<body><div class="wrap">
  <div class="header">
    <h1>Привет, <span class="nick">{display}</span></h1>
    <form action="/streamer/logout" method="post" style="margin:0">
      <button type="submit" class="logout">Выйти</button>
    </form>
  </div>
  <div class="grid">
    <div class="tile"><div class="lbl">Тариф</div><div class="val"><span class="tier-badge">{tier}</span></div></div>
    <div class="tile"><div class="lbl">Активный модуль</div><div class="val">{module}</div></div>
    <div class="tile"><div class="lbl">Twitch login</div><div class="val">{ch.get("login","?")}</div></div>
    <div class="tile"><div class="lbl">Channel ID</div><div class="val">{ch.get("channel_id","?")}</div></div>
    <div class="tile"><div class="lbl">Подключён</div><div class="val">{registered_at}</div></div>
    <div class="tile"><div class="lbl">OAuth токен</div><div class="val">{has_oauth}</div></div>
  </div>
  <div class="footnote">
    Расширение установи через <a href="https://dashboard.twitch.tv/extensions" style="color:#9147ff">Twitch Dashboard → Extensions</a>.
    Channel-points и settings (модуль, цены) появятся в следующих релизах M4.5+.
  </div>
</div></body></html>"""


@router.get("/streamer/dashboard", include_in_schema=False)
async def streamer_dashboard(request: Request):
    """Dashboard стримера. Требует валидную session cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return RedirectResponse(url="/streamer", status_code=status.HTTP_302_FOUND)
    db = get_db()
    ch = await db.get_channel(cid)
    if not ch:
        # Cookie указывает на несуществующий канал (был удалён?). Чистим cookie + редирект.
        resp = RedirectResponse(url="/streamer", status_code=status.HTTP_302_FOUND)
        _clear_session_cookie(resp)
        return resp
    return HTMLResponse(_dashboard_html(ch))


@router.get("/api/streamer/me", include_in_schema=False)
async def streamer_me(request: Request):
    """JSON-версия статуса для возможного dynamic-UI. Требует cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    db = get_db()
    ch = await db.get_channel(cid)
    if not ch:
        return JSONResponse({"status": "channel_not_found"}, status_code=404)
    # Не отдаём OAuth-токены наружу — даже владельцу канала.
    safe = {k: v for k, v in ch.items() if not k.startswith("oauth_")}
    safe["has_oauth"] = bool(ch.get("oauth_access_token"))
    return JSONResponse(safe)


@router.post("/streamer/logout", include_in_schema=False)
async def streamer_logout():
    resp = RedirectResponse(url="/streamer", status_code=status.HTTP_302_FOUND)
    _clear_session_cookie(resp)
    return resp
