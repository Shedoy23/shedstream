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
    """Вернуть channel_id если token валиден и не expired.

    Sprint 5.31 #45c — logging для дебага "почему dashboard говорит re-login".
    Каждая ветка отказа логируется с reason'ом. Пустой cookie (anon hit) —
    silent (нет смысла спамить, такие запросы нормальны).
    """
    if not token:
        return None  # no cookie — normal anon hit, skip log
    if token.count('|') != 2:
        log.warning("[session] malformed cookie token (bad pipe count)")
        return None
    try:
        cid_str, exp_str, sig = token.split('|', 2)
        msg = f"{cid_str}|{exp_str}"
        secret = (TWITCH_EXTENSION_SECRET or "").encode() or b"unconfigured-extension-secret"
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
