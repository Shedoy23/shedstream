"""
routes/streamer.py — M4.3 OAuth flow + M4.4 admin-UI lite dashboard
                     + M4 follow-up (б): OAuth refresh.

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

OAuth refresh (M4 follow-up):
  - get_fresh_oauth_token(channel_id) — lazy refresh, вызывается перед каждым
    user-level API-вызовом. Возвращает None если refresh_token недействителен
    (стример отозвал доступ — нужно re-OAuth).
  - oauth_refresh_loop() — фоновая задача каждый час: проактивно обновляет
    токены за 30 минут до expiry. Так refresh_token не «протухает» от
    бездействия (Twitch инвалидирует unused refresh после ~30 дней).
"""
import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from typing import Dict, Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

log = logging.getLogger("rimlink.streamer")

from config import (
    MODULE_TOKEN_SECRET,
    SESSION_SECRET,
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


def _pending_html(login: str) -> str:
    """M99: страница для стримера, который зарегистрировался, но ещё не одобрен.

    Тон намеренно не извиняющийся и не технический: человек ничего не сделал
    неправильно, ему нужно понять, что произошло и чего ждать. Пустой экран или
    «403» он прочитает как поломку и напишет — то есть ровно та трата времени,
    ради экономии которой ворота и ставятся.
    """
    return f"""
    <!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Заявка принята</title>
    <style>
      body {{ background:#0e0e10; color:#efeff1; font-family:system-ui,-apple-system,
             "Segoe UI",Roboto,sans-serif; display:flex; align-items:center;
             justify-content:center; min-height:100vh; margin:0; padding:24px; }}
      .card {{ max-width:520px; background:#18181b; border:1px solid #2f2f35;
              border-radius:14px; padding:32px; line-height:1.6; }}
      h1 {{ margin:0 0 16px; font-size:22px; }}
      .who {{ color:#a970ff; font-weight:600; }}
      p {{ margin:0 0 14px; color:#c8c8d0; }}
      .tg {{ display:inline-block; margin-top:10px; padding:10px 18px;
            background:#a970ff; color:#fff; text-decoration:none;
            border-radius:8px; font-weight:600; }}
    </style></head><body><div class="card">
      <h1>Заявка принята</h1>
      <p>Канал <span class="who">{login}</span> зарегистрирован. Осталось
         подключение вручную — сейчас я делаю это сам, чтобы помочь с установкой
         мода и убедиться, что всё завелось.</p>
      <p>Повторно регистрироваться не нужно: заявка уже у меня.</p>
      <p>Напиши в телеграм, и подключу — обычно в тот же день.</p>
      <a class="tg" href="https://t.me/ttvshedoy23">Написать @ttvshedoy23</a>
    </div></body></html>
    """


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
    """Twitch вернул code. Меняем на токены, fetch'им user info, регистрируем канал.

    Dispatch: если state начинается с 'dev_' — это flow из /dev (viewer
    test page), передаём управление в routes.dev_login.handle_dev_callback.
    """
    state = request.query_params.get('state', '')
    if state.startswith('dev_'):
        from routes.dev_login import handle_dev_callback
        return await handle_dev_callback(request)

    code = request.query_params.get('code')
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
    mark_channel_registered(channel_id, login=login)

    # M99 — ворота. Регистрация самообслуживаемая, работа — нет. Новый канал
    # приходит «ожидающим»: пока путь установки мода не обкатан чужими руками,
    # каждый неподготовленный стример это вечер переписки вместо разработки.
    # Существующие каналы миграция M99 одобрила, поэтому владелец не закроет
    # сам себя.
    from dependencies import is_channel_approved
    approved = is_channel_approved(channel_id)
    if approved:
        print(f"✅ Streamer registered: {login} (channel_id={channel_id})")
    else:
        print(f"⏳ Streamer PENDING: {login} (channel_id={channel_id}) — "
              f"одобрить: POST /api/admin/approve-channel")
        return HTMLResponse(_pending_html(login))

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
    """HMAC-SHA256 подпись `channel_id|expires_at`. Secret: SESSION_SECRET."""
    msg = f"{channel_id}|{expires_at}"
    secret = (SESSION_SECRET or "").encode()
    sig = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def _verify_session(token: str) -> Optional[int]:
    """Вернуть channel_id если token валиден и не expired.

    Sprint 5.31 #45c — logging для дебага "почему dashboard говорит re-login".
    Каждая ветка отказа логируется с reason'ом. Пустой cookie (anon hit) —
    silent (нет смысла спамить, такие запросы нормальны).
    """
    if not token:
        return None  # no cookie — normal anon hit, skip log
    if not SESSION_SECRET:
        log.error("[session] SESSION_SECRET/TWITCH_EXTENSION_SECRET не заданы — сессии отключены")
        return None
    if token.count('|') != 2:
        log.warning("[session] malformed cookie token (bad pipe count)")
        return None
    try:
        cid_str, exp_str, sig = token.split('|', 2)
        msg = f"{cid_str}|{exp_str}"
        secret = (SESSION_SECRET or "").encode()
        expected = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            log.warning("[session] cookie HMAC mismatch cid=%s — forged or "
                        "TWITCH_EXTENSION_SECRET changed", cid_str)
            return None
        if int(exp_str) < int(time.time()):
            log.info("[session] cookie expired cid=%s exp=%s now=%s",
                     cid_str, exp_str, int(time.time()))
            return None
        return int(cid_str)
    except (ValueError, IndexError) as e:
        log.warning("[session] cookie parse error: %s: %s", type(e).__name__, e)
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
    import html, json
    # Escape all channel-derived strings before they hit the HTML f-string — display_name
    # is attacker-influenced (Twitch profile). HTML contexts get html.escape; the one JS
    # context (markActiveModule) gets json.dumps + </ guard.
    tier = html.escape((ch.get("tier") or "free").upper())
    tier_color = {"FREE": "#6e6e73", "PRO": "#9147ff", "VIP": "#f4b740"}.get(tier, "#6e6e73")
    module_raw = ch.get("active_module") or "—"
    module = html.escape(str(module_raw))
    module_js = json.dumps(module_raw).replace("</", "<\\/")
    display = html.escape(str(ch.get("display_name") or ch.get("login") or "?"))
    login = html.escape(str(ch.get("login") or "?"))
    channel_id = html.escape(str(ch.get("channel_id") or "?"))
    registered_at = html.escape(str(ch.get("registered_at") or "?"))
    has_oauth = "✅" if ch.get("oauth_access_token") else "—"
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Dashboard — {display}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0e0e10;color:#efeff1;margin:0;padding:20px;min-height:100vh;box-sizing:border-box}}
  .wrap{{max-width:840px;margin:40px auto}}
  .header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}}
  .header h1{{margin:0;font-size:22px}}
  .nick{{color:#9147ff}}
  .logout{{background:transparent;color:#adadb8;border:1px solid #3a3a3d;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}}
  .logout:hover{{color:#fff;border-color:#fff}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:32px}}
  .tile{{background:#1f1f23;border-radius:10px;padding:20px}}
  .tile .lbl{{color:#adadb8;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}}
  .tile .val{{font-size:20px;font-weight:600}}
  .tier-badge{{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:700;font-size:14px;color:#fff;background:{tier_color}}}
  .section{{background:#1f1f23;border-radius:10px;padding:24px;margin-bottom:24px}}
  .section h2{{margin:0 0 4px;font-size:18px;color:#c084fc}}
  .section .sub{{color:#adadb8;font-size:13px;margin-bottom:16px}}
  .footnote{{margin-top:28px;color:#6e6e73;font-size:13px;line-height:1.5}}
  code{{background:#1f1f23;padding:2px 8px;border-radius:4px;color:#e0d6ff}}
  /* Boosty admin */
  .boosty-tier-info{{background:rgba(192,132,252,0.07);border:1px solid #3a2a5a;
                     border-radius:6px;padding:10px 14px;font-size:13px;
                     color:#adadb8;line-height:1.6;margin-bottom:14px}}
  .boosty-tier-info b{{color:#c084fc}}
  .boosty-row{{display:flex;align-items:center;gap:10px;padding:8px 12px;
              background:rgba(192,132,252,0.05);border:1px solid #2d2d2f;
              border-radius:6px;margin-bottom:6px;font-size:13px}}
  .boosty-row .u{{flex:1;color:#efeff1;font-weight:700}}
  .boosty-row .t{{color:#c084fc;font-size:12px}}
  .boosty-row .n{{color:#9ca3af;font-style:italic;font-size:12px;flex:1;text-align:right}}
  .boosty-row button{{background:#7f1d1d;color:#fca5a5;border:none;padding:4px 10px;
                      border-radius:4px;cursor:pointer;font-size:12px}}
  .boosty-row button:hover{{background:#991b1b;color:#fff}}
  .boosty-form{{display:grid;grid-template-columns:1fr 90px 1fr auto;gap:8px;
               margin-top:12px;margin-bottom:8px}}
  .boosty-form input,.boosty-form select{{background:#0e0e10;color:#efeff1;
       border:1px solid #3d3d3f;border-radius:5px;padding:8px;font-size:13px}}
  .boosty-form button{{background:#7e22ce;color:#fff;border:none;
                       padding:8px 16px;border-radius:5px;cursor:pointer;
                       font-weight:700;font-size:13px}}
  .boosty-form button:hover{{background:#9333ea}}
  .boosty-bulk{{margin-top:16px;border-top:1px solid #2d2d2f;padding-top:14px}}
  .boosty-bulk textarea{{width:100%;box-sizing:border-box;background:#0e0e10;
      color:#efeff1;border:1px solid #3d3d3f;border-radius:5px;padding:8px;
      font-family:monospace;font-size:12px;min-height:80px;resize:vertical}}
  .boosty-bulk button{{background:#1f1a30;color:#c084fc;border:1px solid #5b21b6;
       padding:8px 16px;border-radius:5px;cursor:pointer;font-size:13px;margin-top:8px}}
  .boosty-empty{{color:#6e6e73;font-style:italic;text-align:center;padding:18px}}
  .boosty-msg{{margin-top:10px;padding:8px 12px;border-radius:5px;font-size:13px;display:none}}
  .boosty-msg.ok{{background:rgba(52,211,153,0.1);border:1px solid #34d399;color:#34d399;display:block}}
  .boosty-msg.err{{background:rgba(248,113,113,0.1);border:1px solid #f87171;color:#f87171;display:block}}
  @media (max-width:640px){{
    .boosty-form{{grid-template-columns:1fr;}}
    .boosty-row{{flex-wrap:wrap}}
  }}
  /* Module tokens */
  .tok-row{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
  .tok-name{{width:90px;font-weight:700;color:#c084fc}}
  .tok-field{{flex:1;min-width:180px;background:#0e0e10;color:#9ca3af;border:1px solid #3d3d3f;border-radius:5px;padding:8px;font-family:monospace;font-size:12px}}
  .tok-copy{{background:#7e22ce;color:#fff;border:none;padding:8px 14px;border-radius:5px;cursor:pointer;font-size:13px;font-weight:700}}
  .tok-copy:hover{{background:#9333ea}}
  .tok-show{{background:transparent;color:#adadb8;border:1px solid #3a3a3d;padding:8px 12px;border-radius:5px;cursor:pointer;font-size:13px}}
  .tok-show:hover{{color:#fff;border-color:#fff}}
  /* Module switcher */
  .mod-switch{{display:flex;gap:10px}}
  .mod-btn{{flex:1;background:#0e0e10;color:#adadb8;border:1px solid #3d3d3f;padding:12px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600}}
  .mod-btn:hover{{border-color:#9147ff;color:#fff}}
  .mod-btn.active{{background:#7e22ce;color:#fff;border-color:#9147ff}}
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
    <div class="tile"><div class="lbl">Twitch login</div><div class="val">{login}</div></div>
    <div class="tile"><div class="lbl">Channel ID</div><div class="val">{channel_id}</div></div>
    <div class="tile"><div class="lbl">Подключён</div><div class="val">{registered_at}</div></div>
    <div class="tile"><div class="lbl">OAuth токен</div><div class="val">{has_oauth}</div></div>
  </div>

  <!-- Переключатель активного модуля -->
  <div class="section">
    <h2>🎮 Активный модуль расширения</h2>
    <div class="sub">Какую игру видят зрители в расширении. Переключение мгновенное — зритель увидит при следующем обновлении (пара секунд).</div>
    <div class="mod-switch">
      <button class="mod-btn" id="mod-btn-bannerlord" onclick="setModule('bannerlord')">⚔️ Bannerlord</button>
      <button class="mod-btn" id="mod-btn-rimworld" onclick="setModule('rimworld')">🪐 RimWorld</button>
      <button class="mod-btn" id="mod-btn-shedcolony" onclick="setModule('shedcolony')">⛏️ Minecraft</button>
    </div>
    <div id="mod-msg" class="boosty-msg"></div>
  </div>
  <script>
  function markActiveModule(mod){{
    ['bannerlord','rimworld','shedcolony'].forEach(function(m){{
      var b = document.getElementById('mod-btn-'+m);
      if(b) b.className = 'mod-btn' + (m === mod ? ' active' : '');
    }});
  }}
  function modMsg(txt, isErr){{
    var m = document.getElementById('mod-msg');
    m.textContent = txt; m.className = 'boosty-msg ' + (isErr ? 'err' : 'ok');
  }}
  async function setModule(mod){{
    try{{
      const r = await fetch('/api/streamer/active-module', {{method:'POST', credentials:'include', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{module_id: mod}})}});
      const d = await r.json();
      if(d.status === 'ok'){{ markActiveModule(d.active_module); modMsg('✅ Активный модуль: ' + d.active_module, false); }}
      else {{ modMsg('Ошибка: ' + (d.status || 'не удалось'), true); }}
    }} catch(e){{ modMsg('Network error: ' + e.message, true); }}
  }}
  markActiveModule({module_js});
  </script>

  <!-- Module-токены (для C#-модов) -->
  <div class="section">
    <h2>🔑 Module-токены</h2>
    <div class="sub">
      Токен авторизации C#-мода. Вставь его в настройки мода (поле «Module-токен»)
      один раз — дальше мод авторизуется сам. <b>Не показывай на стриме.</b>
    </div>
    <div class="tok-row">
      <span class="tok-name">Bannerlord</span>
      <input class="tok-field" id="tok-bannerlord" type="text" readonly placeholder="скрыт — «Копировать» или «Показать»">
      <button class="tok-copy" onclick="copyTok('bannerlord')">📋 Копировать</button>
      <button class="tok-show" onclick="showTok('bannerlord')">👁 Показать</button>
    </div>
    <div class="tok-row">
      <span class="tok-name">RimWorld</span>
      <input class="tok-field" id="tok-rimworld" type="text" readonly placeholder="скрыт — «Копировать» или «Показать»">
      <button class="tok-copy" onclick="copyTok('rimworld')">📋 Копировать</button>
      <button class="tok-show" onclick="showTok('rimworld')">👁 Показать</button>
    </div>
    <div class="tok-row">
      <span class="tok-name">Minecraft</span>
      <input class="tok-field" id="tok-shedcolony" type="text" readonly placeholder="скрыт — «Копировать» или «Показать»">
      <button class="tok-copy" onclick="copyTok('shedcolony')">📋 Копировать</button>
      <button class="tok-show" onclick="showTok('shedcolony')">👁 Показать</button>
    </div>
    <div id="tok-msg" class="boosty-msg"></div>
  </div>
  <script>
  async function fetchTok(mod){{
    const r = await fetch('/api/streamer/module-token?module_id=' + mod, {{credentials:'include'}});
    const d = await r.json();
    if(d.status === 'ok') return d.token;
    tokMsg('Ошибка: ' + (d.status || 'не удалось получить токен'), true);
    return null;
  }}
  async function copyTok(mod){{
    const t = await fetchTok(mod);
    if(!t) return;
    try{{ await navigator.clipboard.writeText(t); tokMsg('✅ ' + mod + '-токен скопирован в буфер', false); }}
    catch(e){{ document.getElementById('tok-'+mod).value = t; tokMsg('Буфер недоступен — токен показан, скопируй вручную', true); }}
  }}
  async function showTok(mod){{
    const t = await fetchTok(mod);
    if(t) document.getElementById('tok-'+mod).value = t;
  }}
  function tokMsg(txt, isErr){{
    const m = document.getElementById('tok-msg');
    m.textContent = txt; m.className = 'boosty-msg ' + (isErr ? 'err' : 'ok');
  }}
  </script>

  <!-- Overlay URL для OBS (A2 2026-07-02) -->
  <div class="section">
    <h2>🖥 URL оверлея для OBS</h2>
    <div class="sub">
      Вставь как <b>Browser Source</b> в OBS. Содержит токен для защиты TTS —
      <b>не показывай на стриме</b>. Если менял оверлей раньше — обнови URL, иначе
      TTS перестанет отмечаться проигранным.
    </div>
    <div class="tok-row">
      <input class="tok-field" id="overlay-url" type="text" readonly placeholder="Нажми «Показать URL»">
      <button class="tok-copy" onclick="copyOverlayUrl()">📋 Копировать</button>
      <button class="tok-show" onclick="showOverlayUrl()">👁 Показать URL</button>
    </div>
    <div id="overlay-url-msg" class="boosty-msg"></div>
  </div>
  <script>
  async function _fetchOverlayUrl(){{
    const r = await fetch('/api/streamer/overlay-url', {{credentials:'include'}});
    const d = await r.json();
    return d.status === 'ok' ? d.url : null;
  }}
  async function showOverlayUrl(){{
    const u = await _fetchOverlayUrl();
    if(u) document.getElementById('overlay-url').value = u;
  }}
  async function copyOverlayUrl(){{
    const u = await _fetchOverlayUrl();
    if(!u) return;
    const m = document.getElementById('overlay-url-msg');
    try{{ await navigator.clipboard.writeText(u); m.textContent = '✅ URL скопирован'; m.className = 'boosty-msg ok'; }}
    catch(e){{ document.getElementById('overlay-url').value = u; m.textContent = 'Буфер недоступен — скопируй вручную'; m.className = 'boosty-msg err'; }}
  }}
  </script>

  <!-- Баг-репорты убраны из дашборда 2026-07-02: техбаги — забота разработчика
       (см. админку /admin), не стримера. Зритель шлёт !баг → падает разработчику. -->

  <!-- Промокоды (self-serve, 2026-07-02) -->
  <div class="section">
    <h2>🎟 Промокоды</h2>
    <div class="sub">
      Создай код — зритель введёт его в расширении и получит крустики. Работает во время стрима.
    </div>
    <div class="boosty-form">
      <input id="promo-code" placeholder="КОД (напр. ЛЕТО2026)" style="text-transform:uppercase;">
      <input id="promo-points" type="number" placeholder="💎" value="1000">
      <input id="promo-uses" type="number" placeholder="лимит (0=∞)" value="1">
      <button onclick="createPromo()">Создать</button>
    </div>
    <div id="promo-msg" class="boosty-msg"></div>
    <div id="promo-list" style="margin-top:12px;"><div class="sub">Загрузка…</div></div>
  </div>
  <script>
  function pEsc(s){{ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
  async function loadPromos(){{
    const list = document.getElementById('promo-list');
    try{{
      const r = await fetch('/api/streamer/promocodes', {{credentials:'include'}});
      const d = await r.json();
      if(d.status !== 'ok'){{ list.innerHTML = '<div class="sub">Ошибка загрузки</div>'; return; }}
      if(!d.promocodes || !d.promocodes.length){{ list.innerHTML = '<div class="sub">Пока нет промокодов.</div>'; return; }}
      list.innerHTML = d.promocodes.map(function(p){{
        const left = p.max_uses > 0 ? (p.max_uses - p.uses) + ' из ' + p.max_uses : '∞';
        return '<div class="boosty-row"><span class="u">' + pEsc(p.code) + '</span>'
          + '<span class="t">' + p.points + '💎</span>'
          + '<span class="n">исп. ' + p.uses + ' · осталось ' + left + '</span>'
          + '<button data-promo-del="' + p.id + '">✖ Удалить</button></div>';
      }}).join('');
      list.querySelectorAll('[data-promo-del]').forEach(function(btn){{
        btn.addEventListener('click', function(){{ deletePromo(btn.getAttribute('data-promo-del')); }});
      }});
    }} catch(e){{ list.innerHTML = '<div class="sub">Network error</div>'; }}
  }}
  async function createPromo(){{
    const code = document.getElementById('promo-code').value.trim();
    const points = parseInt(document.getElementById('promo-points').value || '0', 10);
    const max_uses = parseInt(document.getElementById('promo-uses').value || '1', 10);
    const m = document.getElementById('promo-msg');
    if(!code){{ m.textContent='Укажи код'; m.className='boosty-msg err'; return; }}
    try{{
      const r = await fetch('/api/streamer/promocodes/create', {{method:'POST', credentials:'include', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{code:code, points:points, max_uses:max_uses}})}});
      const d = await r.json();
      m.textContent = d.message || (d.success ? 'OK' : 'Ошибка'); m.className = 'boosty-msg ' + (d.success ? 'ok' : 'err');
      if(d.success){{ document.getElementById('promo-code').value=''; loadPromos(); }}
    }} catch(e){{ m.textContent='Сеть недоступна'; m.className='boosty-msg err'; }}
  }}
  async function deletePromo(id){{
    try{{
      await fetch('/api/streamer/promocodes/' + id, {{method:'DELETE', credentials:'include'}});
      loadPromos();
    }} catch(e){{}}
  }}
  loadPromos();
  </script>

  <!-- Народный выбор игры (M88, 2026-07-02) -->
  <div class="section" id="gamevote-section">
    <h2>🎮 Народный выбор игры</h2>
    <div class="sub">
      Открой раунд — зрители кидают крустики за игры и могут предложить свою.
      Побеждает игра с наибольшим вкладом. Предложения зрителей приходят сюда на одобрение
      (виден ник автора; любое можно отклонить). Вклад автора спишется только после одобрения.
    </div>
    <div class="boosty-form" style="flex-wrap:wrap;">
      <input id="gv-seed" type="text" placeholder="свои игры через запятую (необязательно)" style="flex:1 1 100%;">
      <input id="gv-duration" type="number" placeholder="минут" value="5" style="width:90px;">
      <button id="gv-start-btn" onclick="gvStart()">▶ Открыть раунд</button>
      <button id="gv-finalize-btn" onclick="gvFinalize()" style="display:none;">⏹ Закрыть и подвести итог</button>
    </div>
    <div id="gv-msg" class="boosty-msg"></div>
    <div id="gv-standings" style="margin-top:12px;"></div>
    <div id="gv-pending" style="margin-top:12px;"></div>
  </div>
  <script>
  function gvEsc(s){{ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
  let _gvPollId = null;
  async function gvLoad(){{
    const standings = document.getElementById('gv-standings');
    const pending = document.getElementById('gv-pending');
    const startBtn = document.getElementById('gv-start-btn');
    const finBtn = document.getElementById('gv-finalize-btn');
    try{{
      const r = await fetch('/api/streamer/voting/status', {{credentials:'include'}});
      const d = await r.json();
      if(!d.success){{ standings.innerHTML=''; pending.innerHTML=''; return; }}
      const ev = d.active_event;
      if(!ev){{
        standings.innerHTML = '<div class="sub">Раунд не идёт. Открой новый.</div>';
        pending.innerHTML = '';
        startBtn.style.display=''; finBtn.style.display='none';
        return;
      }}
      startBtn.style.display='none'; finBtn.style.display='';
      const opts = (ev.options||[]).slice().sort(function(a,b){{ return b.pool-a.pool; }});
      let sh = '<div class="sub">Идёт раунд · всего ' + (ev.total_pool||0) + '💎</div>';
      sh += opts.length ? opts.map(function(o){{ return '<div class="boosty-row"><span class="u">'+gvEsc(o.label)+'</span><span class="t">'+o.pool+'💎</span></div>'; }}).join('') : '<div class="sub">Пока нет вариантов — зрители предложат.</div>';
      standings.innerHTML = sh;
      const pend = d.pending||[];
      if(!pend.length){{ pending.innerHTML = '<div class="sub">Нет предложений на одобрение.</div>'; }}
      else{{
        pending.innerHTML = '<div class="sub">На одобрение:</div>' + pend.map(function(p){{
          return '<div class="boosty-row"><span class="u">'+gvEsc(p.label)+'</span>'
            + '<span class="n">от @'+gvEsc(p.username)+' · '+p.pledge+'💎</span>'
            + '<button data-gv-ok="'+p.id+'">✔ Одобрить</button>'
            + '<button data-gv-no="'+p.id+'">✖</button></div>';
        }}).join('');
        pending.querySelectorAll('[data-gv-ok]').forEach(function(b){{ b.addEventListener('click', function(){{ gvApprove(b.getAttribute('data-gv-ok')); }}); }});
        pending.querySelectorAll('[data-gv-no]').forEach(function(b){{ b.addEventListener('click', function(){{ gvReject(b.getAttribute('data-gv-no')); }}); }});
      }}
    }} catch(e){{}}
  }}
  async function gvStart(){{
    const seed = (document.getElementById('gv-seed').value||'').split(',').map(function(s){{ return s.trim(); }}).filter(function(s){{ return s.length; }});
    const mins = parseInt(document.getElementById('gv-duration').value||'5',10);
    const m = document.getElementById('gv-msg');
    try{{
      const r = await fetch('/api/streamer/voting/start', {{method:'POST', credentials:'include', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{duration_sec: (mins>0?mins:5)*60, options: seed}})}});
      const d = await r.json();
      m.textContent = d.message || (d.success?'OK':'Ошибка'); m.className='boosty-msg '+(d.success?'ok':'err');
      gvLoad();
    }} catch(e){{ m.textContent='Сеть недоступна'; m.className='boosty-msg err'; }}
  }}
  async function gvFinalize(){{
    const m = document.getElementById('gv-msg');
    try{{
      const r = await fetch('/api/streamer/voting/finalize', {{method:'POST', credentials:'include'}});
      const d = await r.json();
      m.textContent = d.message || (d.success?'OK':'Ошибка'); m.className='boosty-msg '+(d.success?'ok':'err');
      gvLoad();
    }} catch(e){{ m.textContent='Сеть недоступна'; m.className='boosty-msg err'; }}
  }}
  async function gvApprove(id){{
    try{{ await fetch('/api/streamer/voting/proposals/'+id+'/approve', {{method:'POST', credentials:'include'}}); gvLoad(); }} catch(e){{}}
  }}
  async function gvReject(id){{
    try{{ await fetch('/api/streamer/voting/proposals/'+id+'/reject', {{method:'POST', credentials:'include'}}); gvLoad(); }} catch(e){{}}
  }}
  gvLoad();
  if(_gvPollId) clearInterval(_gvPollId);
  _gvPollId = setInterval(gvLoad, 5000);
  </script>

  <!-- Boosty subscribers admin (Sprint 5.31 #45b) -->
  <div class="section" id="boosty-section">
    <h2>💜 Boosty-подписчики</h2>
    <div class="sub">
      Веди список Twitch-логинов своих Boosty-сабов вручную.
      <br><br>
      ⚠ <b>Важно (Sprint 5.33 ToS compliance, 2026-05-28)</b>: после обновления
      Twitch Extension Developer Agreement, gameplay-бонусы за подписки
      (Twitch sub OR Boosty) <b>УБРАНЫ</b> — это нарушение правил Twitch.
      Cписок остаётся для cosmetic UI (badges в extension), без price/reward
      эффекта.
    </div>
    <div class="boosty-tier-info">
      <b>T1</b> — cosmetic badge (Бакалавр)<br>
      <b>T2</b> — cosmetic badge (Магистр)<br>
      <b>T3</b> — cosmetic badge (Жнец)
    </div>
    <div id="boosty-list"><div class="boosty-empty">Загрузка…</div></div>
    <div class="boosty-form">
      <input id="b-username" type="text" placeholder="twitch_username" autocomplete="off">
      <select id="b-tier">
        <option value="1">T1</option>
        <option value="2">T2</option>
        <option value="3">T3</option>
      </select>
      <input id="b-note" type="text" placeholder="заметка (опционально)" autocomplete="off">
      <button id="b-add">➕ Добавить / Обновить</button>
    </div>
    <div id="boosty-msg" class="boosty-msg"></div>
    <details class="boosty-bulk">
      <summary style="cursor:pointer;color:#adadb8;font-size:13px;">
        📋 Массовая вставка (CSV)
      </summary>
      <div style="color:#6e6e73;font-size:12px;margin:8px 0;">
        Формат: <code>username,tier,note</code> — по одной строке.
        Пример: <code>bobby,2,Магистр</code>
      </div>
      <textarea id="b-bulk-text" placeholder="username,tier,note&#10;another,1,Бакалавр"></textarea>
      <label style="display:flex;align-items:center;gap:6px;margin-top:8px;
                    font-size:12px;color:#adadb8;cursor:pointer;">
        <input id="b-bulk-replace" type="checkbox">
        Полная замена (удалить тех, кого нет в списке)
      </label>
      <button id="b-bulk-apply">📥 Применить</button>
    </details>
  </div>

  <!-- Bannerlord admin tools (Sprint 5.33 RESET-1, 2026-05-28) -->
  <div class="section" id="bnr-admin-section">
    <h2>⚙ Bannerlord — admin tools</h2>
    <div class="sub" style="color:#fb7185;">
      ⚠ <b>Опасные действия.</b> Используй если backend cache десинхронизировался
      с моей кампанией или нужно начать чисто (тест, новый wipe и т.д.).
      Reset удаляет ВСЕ per-channel Bannerlord данные: heroes / workshops /
      fiefs / caravans / heirs / proposals / vassals / party orders / diplomacy /
      tournament queue / auctions / achievements / pending mod actions.
      <b>НЕ удаляются</b>: catalog (classes/powers/upgrades), Boosty list (cosmetic),
      audit events log.
    </div>
    <div style="margin-top:10px;">
      <button id="bnr-reset-preview-btn"
              style="background:#3d3d3f;color:#efeff1;border:1px solid #5d5d5f;
                     padding:8px 14px;border-radius:4px;cursor:pointer;">
        👁 Preview (узнать что будет удалено)
      </button>
      <button id="bnr-reset-confirm-btn"
              style="background:#7f1d1d;color:#fee2e2;border:1px solid #991b1b;
                     padding:8px 14px;border-radius:4px;cursor:pointer;margin-left:6px;">
        🧹 Reset Bannerlord data
      </button>
    </div>
    <div id="bnr-reset-result"
         style="margin-top:12px;padding:8px 12px;background:#0a0a0a;
                border-radius:4px;font-size:11px;color:#adadb8;
                display:none;white-space:pre-wrap;font-family:monospace;">
    </div>
  </div>

  <div class="footnote">
    Расширение установи через <a href="https://dashboard.twitch.tv/extensions" style="color:#9147ff">Twitch Dashboard → Extensions</a>.
    Channel-points и settings (модуль, цены) появятся в следующих релизах M4.5+.
  </div>
</div>

<script>
(function(){{
  const tierLabel = t => t===1?'T1 (cosmetic)' : t===2?'T2 (cosmetic)' : t===3?'T3 (cosmetic)' : '?';
  const esc = s => String(s||'').replace(/[&<>"']/g, c =>
      ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
  const msg = (text, ok) => {{
    const el = document.getElementById('boosty-msg');
    el.textContent = text;
    el.className = 'boosty-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => {{ el.className = 'boosty-msg'; }}, 4000);
  }};
  async function load() {{
    const r = await fetch('/api/dashboard/boosty/subscribers', {{credentials:'include'}});
    const d = await r.json();
    const list = document.getElementById('boosty-list');
    if (!d.success) {{
      list.innerHTML = '<div class="boosty-empty">' + esc(d.message || 'Ошибка') + '</div>';
      return;
    }}
    if (!d.subscribers || d.subscribers.length === 0) {{
      list.innerHTML = '<div class="boosty-empty">Список пуст — добавь подписчиков ниже ↓</div>';
      return;
    }}
    list.innerHTML = d.subscribers.map(s => `
      <div class="boosty-row">
        <span class="u">@${{esc(s.username)}}</span>
        <span class="t">${{tierLabel(s.tier)}}</span>
        ${{s.note ? '<span class="n">' + esc(s.note) + '</span>' : '<span class="n"></span>'}}
        <button data-u="${{esc(s.username)}}">✖ Удалить</button>
      </div>`).join('');
    list.querySelectorAll('button[data-u]').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        const u = btn.getAttribute('data-u');
        if (!confirm('Удалить @' + u + ' из списка?')) return;
        const r = await fetch('/api/dashboard/boosty/subscribers', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{username: u, tier: 0}})
        }});
        const d = await r.json();
        msg(d.message || (d.success ? 'OK' : 'Ошибка'), !!d.success);
        load();
      }});
    }});
  }}
  document.getElementById('b-add').addEventListener('click', async () => {{
    const u = document.getElementById('b-username').value.trim();
    const t = parseInt(document.getElementById('b-tier').value, 10);
    const n = document.getElementById('b-note').value.trim();
    if (!u) {{ msg('Введи twitch username', false); return; }}
    const r = await fetch('/api/dashboard/boosty/subscribers', {{
      method: 'POST',
      credentials: 'include',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{username: u, tier: t, note: n}})
    }});
    const d = await r.json();
    msg(d.message || (d.success ? 'OK' : 'Ошибка'), !!d.success);
    if (d.success) {{
      document.getElementById('b-username').value = '';
      document.getElementById('b-note').value = '';
      load();
    }}
  }});
  document.getElementById('b-bulk-apply').addEventListener('click', async () => {{
    const txt = document.getElementById('b-bulk-text').value.trim();
    if (!txt) {{ msg('Вставь CSV', false); return; }}
    const replace = document.getElementById('b-bulk-replace').checked;
    const entries = [];
    for (const raw of txt.split(/\\r?\\n/)) {{
      const line = raw.trim();
      if (!line) continue;
      const parts = line.split(',').map(p => p.trim());
      const u = parts[0] || '';
      const t = parseInt(parts[1] || '0', 10);
      const note = parts.slice(2).join(',') || '';
      if (!u || t < 1 || t > 3) continue;
      entries.push({{username: u, tier: t, note: note}});
    }}
    if (entries.length === 0) {{
      msg('Не распознано ни одной строки', false);
      return;
    }}
    if (replace && !confirm('Полная замена: всех текущих, кого нет в списке, удалит. Продолжить?')) return;
    const r = await fetch('/api/dashboard/boosty/subscribers/bulk', {{
      method: 'POST',
      credentials: 'include',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{entries: entries, replace_all: replace}})
    }});
    const d = await r.json();
    msg(d.message || (d.success ? 'OK' : 'Ошибка'), !!d.success);
    if (d.success) {{
      document.getElementById('b-bulk-text').value = '';
      load();
    }}
  }});
  load();

  // Sprint 5.33 RESET-1 — Bannerlord admin reset tools.
  // GET preview /api/streamer/bannerlord/reset/preview → table_counts
  // POST /api/streamer/bannerlord/reset с {{confirm_phrase: channel_id}} → wipe.
  const bnrResetOut = document.getElementById('bnr-reset-result');
  const bnrResetShow = (txt, isError) => {{
    bnrResetOut.style.display = 'block';
    bnrResetOut.style.color = isError ? '#fb7185' : '#adadb8';
    bnrResetOut.textContent = txt;
  }};
  document.getElementById('bnr-reset-preview-btn')?.addEventListener('click', async () => {{
    bnrResetShow('Loading preview...', false);
    try {{
      const r = await fetch('/api/streamer/bannerlord/reset/preview', {{
        credentials: 'include',
      }});
      const d = await r.json();
      if (!d.success) {{ bnrResetShow('❌ ' + (d.message || 'Failed'), true); return; }}
      const lines = [];
      lines.push('Channel #' + d.channel_id + ' — total rows: ' + d.total_rows);
      lines.push('');
      lines.push('Per table:');
      const entries = Object.entries(d.table_counts || {{}}).sort((a, b) => (b[1] || 0) - (a[1] || 0));
      for (const [tbl, cnt] of entries) {{
        if (cnt === 0) continue;
        lines.push('  ' + (cnt === -1 ? '?' : String(cnt).padStart(5)) + '  ' + tbl);
      }}
      lines.push('');
      lines.push('Preserved (НЕ удаляются): ' + (d.preserved_tables || []).join(', '));
      bnrResetShow(lines.join('\\n'), false);
    }} catch (e) {{
      bnrResetShow('❌ Network error: ' + e.message, true);
    }}
  }});
  document.getElementById('bnr-reset-confirm-btn')?.addEventListener('click', async () => {{
    // Get current channel_id from session — fetch /api/streamer/me
    let channelId = null;
    try {{
      const meR = await fetch('/api/streamer/me', {{credentials: 'include'}});
      const me = await meR.json();
      channelId = me.id || me.channel_id;
    }} catch (e) {{}}
    if (!channelId) {{
      bnrResetShow('❌ Не удалось определить channel_id (re-login?)', true);
      return;
    }}
    const phrase = prompt(
      'Это удалит ВСЁ per-channel Bannerlord state.\\n\\n' +
      'Для подтверждения введи свой channel_id: ' + channelId
    );
    if (phrase === null) return;
    if (String(phrase).trim() !== String(channelId)) {{
      bnrResetShow('❌ Confirmation mismatch — ничего не удалено', true);
      return;
    }}
    bnrResetShow('Wiping...', false);
    try {{
      const r = await fetch('/api/streamer/bannerlord/reset', {{
        method: 'POST',
        credentials: 'include',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{confirm_phrase: String(channelId)}}),
      }});
      const d = await r.json();
      if (!d.success) {{ bnrResetShow('❌ ' + (d.message || 'Failed'), true); return; }}
      const lines = [];
      lines.push('✅ ' + (d.message || 'Done'));
      lines.push('');
      lines.push('Deleted ' + d.total_deleted + ' rows. Detail:');
      for (const [tbl, cnt] of Object.entries(d.deleted_by_table || {{}})) {{
        if (cnt === 0) continue;
        lines.push('  ' + (cnt === -1 ? '?' : String(cnt).padStart(5)) + '  ' + tbl);
      }}
      bnrResetShow(lines.join('\\n'), false);
    }} catch (e) {{
      bnrResetShow('❌ Network error: ' + e.message, true);
    }}
  }});
}})();
</script>
</body></html>"""


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


# ── Этап 3 step 2: Module token issuance ─────────────────────────────────────

# Module token формат: `channel_id|module_id|expires_at|HMAC` (text-based,
# без зависимости от внешних JWT-библиотек). Long-lived (1 год default) —
# стример вставляет один раз в connector. Ротация через POST /streamer/
# module-token/rotate (future).
_MODULE_TOKEN_TTL = 365 * 24 * 3600  # 1 год


def issue_module_token(channel_id: int, module_id: str,
                        ttl_seconds: int = _MODULE_TOKEN_TTL) -> str:
    """Сгенерировать module-token. Per docs/MODULE_API.md §4.

    HMAC-SHA256(channel_id|module_id|expires_at, MODULE_TOKEN_SECRET).
    """
    expires_at = int(time.time()) + max(60, int(ttl_seconds))
    msg = f"{int(channel_id)}|{module_id}|{expires_at}"
    secret = (MODULE_TOKEN_SECRET or "").encode() or b"unconfigured-module-secret"
    sig = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def verify_module_token(token: str) -> Optional[dict]:
    """Проверить module-token. Returns {channel_id, module_id, expires_at} or None.

    None при: невалидной подписи, expired-токене, малформед-формате.
    Caller должен дополнительно проверить что url-path module_id совпадает
    с token.module_id (mismatch = reject 403, кросс-модульная атака).
    """
    if not token or token.count('|') != 3:
        return None
    try:
        cid_str, module_id, exp_str, sig = token.split('|', 3)
        msg = f"{cid_str}|{module_id}|{exp_str}"
        secret = (MODULE_TOKEN_SECRET or "").encode() or b"unconfigured-module-secret"
        expected = hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        expires_at = int(exp_str)
        if expires_at < int(time.time()):
            return None
        return {
            "channel_id": int(cid_str),
            "module_id": module_id,
            "expires_at": expires_at,
        }
    except (ValueError, IndexError):
        return None


# ── Overlay-token (A2, 2026-07-02) ────────────────────────────────────────────
# /api/overlay/tts/played мутирует очередь TTS, а id+channel_id публичны (видны в
# /tts/pending) → грифер мог гасить платное TTS (5000💎). Per-channel токен живёт
# в URL OBS-оверлея (секрет, не на стриме). Мутация требует валидный токен.
def issue_overlay_token(channel_id: int) -> str:
    msg = f"overlay|{int(channel_id)}"
    secret = (MODULE_TOKEN_SECRET or "").encode() or b"unconfigured-module-secret"
    return hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()[:32]


def verify_overlay_token(channel_id: int, token: str) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, issue_overlay_token(channel_id))


@router.get("/api/streamer/overlay-url", include_in_schema=False)
async def streamer_overlay_url(request: Request):
    """Полный URL оверлея для OBS (с overlay_token). Требует session cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    tok = issue_overlay_token(cid)
    return JSONResponse({
        "status": "ok",
        "url": f"https://shedoy23.ru/overlay.html?channel_id={cid}&overlay_token={tok}",
    })


@router.get("/api/streamer/module-token", include_in_schema=False)
async def streamer_module_token(request: Request):
    """Стример из dashboard'а получает свой long-lived module-token.

    Требует session cookie (M4.4). Возвращает токен — стример копирует его
    в connector (в моде указывает в config'е). Mod использует в
    Authorization: Bearer <token> при вызовах /v1/module/<id>/*.
    """
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    module_id = (request.query_params.get("module_id") or "").strip()
    if not module_id or not module_id.replace("_", "").isalnum():
        return JSONResponse({"status": "invalid_module_id"}, status_code=400)
    # Проверка что module_id зарегистрирован в реестре — не плодим токены для
    # несуществующих модулей (защита от typo / probing).
    from modules._loader import get_module
    if get_module(module_id) is None:
        return JSONResponse(
            {"status": "module_not_found", "module_id": module_id},
            status_code=404,
        )
    token = issue_module_token(cid, module_id)
    return JSONResponse({
        "status": "ok",
        "module_id": module_id,
        "channel_id": cid,
        "token": token,
        "expires_in": _MODULE_TOKEN_TTL,
        "instructions": "Скопируй в config мода как module_token. Без этого connector не сможет слать события.",
    })


@router.post("/api/streamer/active-module", include_in_schema=False)
async def streamer_set_active_module(request: Request):
    """Стример из dashboard переключает активный модуль расширения — что видят
    зрители (bannerlord / rimworld / shedcolony). Требует session cookie. Меняет
    channels.active_module; фронт зрителя подхватывает при следующем опросе."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    module_id = (body.get("module_id") or "").strip()
    if not module_id or not module_id.replace("_", "").isalnum():
        return JSONResponse({"status": "invalid_module_id"}, status_code=400)
    from modules._loader import get_module
    if get_module(module_id) is None:
        return JSONResponse(
            {"status": "module_not_found", "module_id": module_id}, status_code=404)
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE channels SET active_module=? WHERE channel_id=?",
            (module_id, cid))
        await conn.commit()
    return JSONResponse({"status": "ok", "active_module": module_id, "channel_id": cid})


@router.get("/api/streamer/feature-usage", include_in_schema=False)
async def streamer_feature_usage(request: Request):
    """ROADMAP 2.3 — топ/анти-топ используемых фич за окно (по умолчанию 7 дней).
    Для решений «что развивать / что заморозить» от данных. Требует session cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    try:
        days = int(request.query_params.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    db = get_db()
    async with db._connect() as conn:
        rows = await (await conn.execute(
            "SELECT feature_key, SUM(count) AS total FROM feature_usage "
            "WHERE channel_id=? AND day >= date('now', ?) "
            "GROUP BY feature_key ORDER BY total DESC",
            (cid, f"-{days} days"))).fetchall()
    ranked = [{"feature": r[0], "count": r[1]} for r in rows]
    return JSONResponse({
        "status": "ok",
        "days": days,
        "total_features": len(ranked),
        "top": ranked[:10],
        "bottom": list(reversed(ranked[-10:])) if len(ranked) > 10 else [],
    })


# Баг-репорты полностью убраны со стороны стримера 2026-07-02: техбаги расширения —
# забота разработчика. Просмотр + триаж — в админке (/api/admin/bug-reports[/status]).


# ── Промокоды self-serve (2026-07-02): раньше только админ мог создавать, а это
# стримерский инструмент вовлечения. Теперь стример делает свои коды сам, scoped
# по его каналу из session cookie. Админ-эндпоинты в promo.py остались (оверрайд).
@router.get("/api/streamer/promocodes", include_in_schema=False)
async def streamer_get_promos(request: Request):
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    db = get_db()
    async with db._connect() as conn:
        c = await conn.execute(
            "SELECT id, code, points, item_name, max_uses, uses, created_at "
            "FROM promocodes WHERE channel_id = ? ORDER BY id DESC", (cid,))
        rows = await c.fetchall()
    return JSONResponse({"status": "ok", "promocodes": [
        {"id": r[0], "code": r[1], "points": r[2], "item_name": r[3],
         "max_uses": r[4], "uses": r[5], "created_at": r[6]} for r in rows]})


@router.post("/api/streamer/promocodes/create", include_in_schema=False)
async def streamer_create_promo(request: Request):
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    code = str(data.get("code", "")).strip().upper()
    if not code:
        return {"success": False, "message": "Укажи код"}
    try:
        points = int(data.get("points", 0))
        max_uses = int(data.get("max_uses", 1))
    except (TypeError, ValueError):
        return {"success": False, "message": "Очки и лимит — числа"}
    import sqlite3 as _sqlite3
    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute(
                "INSERT INTO promocodes (channel_id, code, points, item_def, item_name, max_uses) "
                "VALUES (?,?,?,?,?,?)", (cid, code, points, None, None, max_uses))
            await conn.commit()
        except _sqlite3.IntegrityError:
            return {"success": False, "message": "Такой промокод уже есть"}
        except Exception as e:
            return {"success": False, "message": f"Ошибка: {e}"}
    return {"success": True, "message": f"✅ Промокод {code} создан"}


@router.delete("/api/streamer/promocodes/{promo_id}", include_in_schema=False)
async def streamer_delete_promo(promo_id: int, request: Request):
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "DELETE FROM promocodes WHERE channel_id = ? AND id = ?", (cid, promo_id))
        await conn.commit()
    return {"success": True}


@router.get("/api/streamer/greet", include_in_schema=False)
async def streamer_greet_get(request: Request):
    """Состояние приветствий ботом в чате: {sub, follow} (m74). Session cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    settings = await get_db().get_channel_greet_settings(cid)
    return JSONResponse({"status": "ok", "channel_id": cid, **settings})


@router.post("/api/streamer/greet", include_in_schema=False)
async def streamer_greet_set(request: Request):
    """Стример вкл/выкл приветствие в чате (m74, scoped по своему каналу).
    Body: {"kind": "sub"|"follow", "enabled": bool}. Только текст, без наград
    — Twitch ToS §5.2."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    kind = (body.get("kind") or "").strip()
    if kind not in ("sub", "follow"):
        return JSONResponse({"status": "invalid_kind"}, status_code=400)
    enabled = bool(body.get("enabled", True))
    await get_db().set_channel_greet_setting(cid, kind, enabled)
    settings = await get_db().get_channel_greet_settings(cid)
    return JSONResponse({"status": "ok", "channel_id": cid, **settings})


@router.get("/api/streamer/watch-streaks", include_in_schema=False)
async def streamer_watch_streaks(request: Request):
    """Лидерборд серий просмотров (watch streaks, m75): кто смотрит дольше
    всех подряд. Пассивная статистика лояльности. Требует session cookie."""
    cid = _read_session_cookie(request)
    if cid is None:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    try:
        limit = int(request.query_params.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    board = await get_db().get_watch_streaks(cid, limit=limit)
    return JSONResponse({
        "status": "ok",
        "channel_id": cid,
        "count": len(board),
        "streaks": board,
    })


# ── M4 follow-up (б): OAuth refresh ──────────────────────────────────────────

# Refresh когда до expiry осталось меньше этого окна (60 сек безопаснее
# чем впритык — учитывает clock skew + network latency).
_REFRESH_LEEWAY_SEC = 60
# Background loop проактивно рефрешит за этим окном до expiry — так
# refresh_token не «протухает» от бездействия (Twitch инвалидирует unused
# через ~30 дней) + token всегда свеж когда понадобится.
_PROACTIVE_REFRESH_WINDOW_SEC = 30 * 60


def _parse_iso_to_epoch(iso_str: Optional[str]) -> float:
    """Convert SQLite TIMESTAMP string (`YYYY-MM-DD HH:MM:SS` UTC) to epoch.
    Возвращает 0 если parse failed → caller трактует как «expired»."""
    if not iso_str:
        return 0.0
    from datetime import datetime, timezone
    try:
        # SQLite формат БЕЗ tz info — кладём UTC
        dt = datetime.strptime(iso_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


async def _refresh_with_twitch(refresh_token: str) -> Optional[dict]:
    """POST на Twitch refresh endpoint. Возвращает dict с access_token/
    refresh_token/expires_in или None при ошибке."""
    payload = {
        'client_id':     TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'grant_type':    'refresh_token',
        'refresh_token': refresh_token,
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post('https://id.twitch.tv/oauth2/token', data=payload, timeout=10) as r:
                if r.status != 200:
                    body = await r.text()
                    print(f"⚠️  OAuth refresh failed: {r.status} {body[:200]}")
                    return None
                return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"⚠️  OAuth refresh network error: {e}")
        return None


async def _refresh_and_save(channel_id: int, refresh_token: str) -> Optional[str]:
    """Refresh токенов + сохранить в БД. Возвращает новый access_token или None."""
    data = await _refresh_with_twitch(refresh_token)
    if not data:
        return None
    new_access = data.get('access_token')
    new_refresh = data.get('refresh_token') or refresh_token  # rotates но defensive
    expires_in = int(data.get('expires_in', 0))
    if not new_access:
        return None
    new_expires_at = _epoch_to_iso(time.time() + max(0, expires_in))
    db = get_db()
    ok = await db.update_channel_oauth(channel_id, new_access, new_refresh, new_expires_at)
    if not ok:
        print(f"⚠️  OAuth refresh: канал {channel_id} не найден в БД (race?)")
        return None
    return new_access


async def get_fresh_oauth_token(channel_id: int) -> Optional[str]:
    """Вернуть валидный access_token для канала, обновив если близок к expiry.

    Returns:
        access_token (str) если канал зарегистрирован и refresh_token валиден.
        None если канал не зарегистрирован, OAuth не пройден, ИЛИ refresh
        отклонён Twitch (стример revoke'нул доступ — нужно re-OAuth).

    Использование: вызывать перед каждым user-level Helix-запросом. Lazy.
    """
    db = get_db()
    ch = await db.get_channel(channel_id)
    if not ch:
        return None
    refresh = ch.get('oauth_refresh_token')
    access = ch.get('oauth_access_token')
    if not (refresh and access):
        return None  # never registered or partial OAuth state

    expires_at = _parse_iso_to_epoch(ch.get('oauth_expires_at'))
    if time.time() < expires_at - _REFRESH_LEEWAY_SEC:
        return access  # ещё валиден

    return await _refresh_and_save(channel_id, refresh)


async def oauth_refresh_loop() -> None:
    """Фоновая задача: проверяет и обновляет токены раз в час.

    Запускается в main.on_startup. При первом старте после M4 deploy этот
    loop ничего не делает (один забекфилленный канал не имеет OAuth-полей —
    тот стример должен пройти OAuth flow один раз через /streamer).

    После того как стримеры зарегистрируются — loop держит их токены свежими.
    """
    db = get_db()
    while True:
        try:
            channels = await db.list_channels()
            now = time.time()
            refreshed = 0
            failed = 0
            for ch in channels:
                cid = ch['channel_id']
                # list_channels возвращает trimmed dict без oauth_*; идём в get_channel.
                full = await db.get_channel(cid)
                if not full:
                    continue
                refresh = full.get('oauth_refresh_token')
                if not refresh:
                    continue  # не прошёл OAuth — ничего не рефрешим
                expires_at = _parse_iso_to_epoch(full.get('oauth_expires_at'))
                if expires_at - now > _PROACTIVE_REFRESH_WINDOW_SEC:
                    continue  # ещё рано
                new_token = await _refresh_and_save(cid, refresh)
                if new_token:
                    refreshed += 1
                    print(f"🔄 OAuth refreshed для channel_id={cid}")
                else:
                    failed += 1
                    print(f"⚠️  OAuth refresh FAILED для channel_id={cid} — стример должен re-OAuth")
            if refreshed or failed:
                print(f"OAuth refresh loop: refreshed={refreshed}, failed={failed}")
        except Exception as e:
            print(f"OAuth refresh loop error: {type(e).__name__}: {e}")
        await asyncio.sleep(3600)
