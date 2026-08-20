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
import pathlib as _pathlib
import re
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
# state → (expiry timestamp, safe return path). Очищается lazy при start/callback.
# В одиночном-инстанс прод-сетапе in-memory достаточно.
_STATE_TTL = 300  # 5 минут на завершение OAuth flow
_oauth_states: Dict[str, tuple[float, Optional[str]]] = {}


def _cleanup_expired_states() -> None:
    now = time.time()
    expired = [s for s, value in _oauth_states.items() if value[0] < now]
    for s in expired:
        _oauth_states.pop(s, None)


def _safe_return_to(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    if re.fullmatch(r"/manager/pair\?code=[A-Z0-9]{4}-[A-Z0-9]{4}", value):
        return value
    return None


def _issue_state(return_to: Optional[str] = None) -> str:
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (time.time() + _STATE_TTL, return_to)
    return state


def _consume_state(state: str) -> tuple[bool, Optional[str]]:
    """Проверить и удалить state; вернуть validity + safe post-OAuth path."""
    _cleanup_expired_states()
    value = _oauth_states.pop(state, None)
    if value is None:
        return False, None
    expiry, return_to = value
    return expiry >= time.time(), return_to


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
async def auth_start(request: Request):
    """Начало OAuth flow — генерируем state, редирект на Twitch."""
    if not TWITCH_CLIENT_ID:
        return HTMLResponse(_error_html("OAuth не настроен на сервере (нет TWITCH_CLIENT_ID)."), status_code=503)
    return_to = _safe_return_to(request.query_params.get("return_to", ""))
    state = _issue_state(return_to)
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

    state_valid, return_to = _consume_state(state)
    if not state_valid:
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
    response = RedirectResponse(
        url=return_to or "/streamer/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
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

@router.get("/api/streamer/setup-status")
async def streamer_setup_status(request: Request):
    """Одним ответом: всё ли у стримера работает, а если нет — что делать.

    2026-07-26. Дашборд показывал только технические переключатели — активный
    модуль, токены, ссылку на оверлей. Это интерфейс для того, кто и так всё
    знает, то есть для владельца. Новому стримеру нужны ответы на другие
    вопросы: подключился ли мод, видят ли меня зрители, что осталось сделать,
    почему ничего не происходит.

    Каждый вопрос, на который страница не отвечает сама, превращается в
    сообщение владельцу — а его время главный дефицит проекта.

    Требует session cookie (как и сам дашборд).
    """
    import time

    channel_id = _read_session_cookie(request)
    if channel_id is None:
        return {"success": False, "status": "unauthenticated"}

    db = get_db()
    ch = await db.get_channel(channel_id)
    if not ch:
        return {"success": False, "status": "channel_not_found"}
    active_module = (ch.get("active_module") or "").strip()

    # 2026-08-20. Обе строки ниже раньше врали, и по-разному.
    #
    # «На связи сейчас» бралось из памяти процесса модуля. После КАЖДОГО
    # перезапуска бэкенда там пусто, и дашборд говорил «мод молчит» исправно
    # работающему стримеру. Таблица `module_last_seen` (M109) заведена ровно
    # для этого и переживает перезапуск — она и есть источник.
    #
    # «Хоть раз выходил на связь» считалось по числу героев Bannerlord —
    # независимо от того, какая игра выбрана. У стримера на RimWorld галочка
    # стояла потому, что когда-то играли в Bannerlord. Один и тот же вопрос
    # для трёх игр должен отвечаться одинаково: есть ли отметка о связи
    # ИМЕННО этого модуля.
    online, last_seen_age, ever = False, None, 0
    async with db._connect() as conn:
        if active_module:
            try:
                cur = await conn.execute(
                    "SELECT last_seen_ts FROM module_last_seen "
                    "WHERE channel_id=? AND module_id=?",
                    (channel_id, active_module))
                row = await cur.fetchone()
                if row and row[0]:
                    ever = 1
                    last_seen_age = int(time.time() - float(row[0]))
                    online = last_seen_age < 60
            except Exception:
                pass   # таблицы может не быть на очень старой базе
        cur = await conn.execute(
            "SELECT COUNT(*) FROM viewers WHERE channel_id=?", (channel_id,))
        viewers_total = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT COUNT(*) FROM viewers WHERE channel_id=? "
            "AND last_seen > datetime('now', '-15 minutes')", (channel_id,))
        viewers_active = (await cur.fetchone())[0]

    steps = [
        {"key": "registered", "title": "Канал подключён к платформе",
         "done": True, "hint": ""},
        {"key": "approved", "title": "Доступ открыт",
         "done": bool(ch.get("approved")),
         "hint": "" if ch.get("approved")
                 else "Заявка у меня — напиши в телеграм, открою"},
        {"key": "module", "title": "Выбрана игра",
         "done": bool(active_module),
         "hint": "" if active_module
                 else "Выбери игру кнопкой выше — без неё мод не поймёт, что делать"},
        {"key": "mod_ever", "title": "Мод установлен и хоть раз выходил на связь",
         "done": ever > 0,
         "hint": "" if ever > 0
                 else "Скопируй токен ниже в настройки мода и запусти игру"},
        {"key": "mod_now", "title": "Мод на связи прямо сейчас",
         "done": online,
         "hint": "" if online else (
             "Игра не запущена или мод не может достучаться. "
             "Молчит %d мин." % (last_seen_age // 60)
             if last_seen_age is not None
             else "Сигнала пока не было — запусти игру")},
    ]
    left = [s for s in steps if not s["done"]]

    return {
        "success": True,
        "all_good": not left,
        "next_step": left[0]["title"] if left else "",
        "next_hint": left[0]["hint"] if left else "",
        "steps": steps,
        "active_module": active_module or None,
        "mod_online": online,
        "mod_silent_sec": last_seen_age,
        "viewers_total": viewers_total,
        "viewers_active": viewers_active,
    }

# ── Шаблоны страниц ──────────────────────────────────────────────────────────
# 2026-07-26. Разметка живёт в `backend/templates/*.html` как обычный HTML, а не
# внутри Python-строк. Причина не эстетическая: в f-string каждую фигурную
# скобку CSS и JS надо удваивать, ошибка роняет страницу в 500 на проде, и ни
# один инструмент такой файл не проверит. Отдельный файл открывается в
# браузере, подсвечивается и правится без риска.
#
# Автоэкранирование Jinja ВЫКЛЮЧЕНО намеренно: вызывающий код экранирует сам
# (html.escape для HTML-контекста, json.dumps для JS), как было до переезда.
# Включить — значит экранировать дважды и показать зрителю «&amp;lt;».
_TEMPLATES_DIR = _pathlib.Path(__file__).resolve().parent.parent / "templates"
_template_cache: dict = {}


def _render_template(name: str, **values) -> str:
    """Отрисовать шаблон из `backend/templates/`.

    Кэшируем разобранный шаблон: страница дашборда открывается часто, а читать
    и разбирать 31 КБ на каждый запрос незачем. При правке файла нужен рестарт —
    это осознанно: на проде так и так рестарт, а локально он занимает секунды.
    """
    tpl = _template_cache.get(name)
    if tpl is None:
        import jinja2
        path = _TEMPLATES_DIR / name
        tpl = jinja2.Template(path.read_text(encoding="utf-8"), autoescape=False)
        _template_cache[name] = tpl
    return tpl.render(**values)


def _dashboard_html(ch: dict) -> str:
    """Дашборд стримера. ch — запись из db.get_channel() (без OAuth-токенов).

    2026-07-26: разметка переехала в `templates/streamer_dashboard.html`.
    Раньше это была f-string на 616 строк с 374 удвоенными скобками: каждое
    правило CSS и каждый кусок JS приходилось писать как `{{`/`}}`, иначе
    страница падала в 500 уже на проде. Ни подсветки, ни проверки, ни
    предпросмотра — поэтому любая правка внешнего вида стоила втрое дороже и
    была рискованной. В наших заметках записано, что «кусало на каждой новой
    карточке».

    Переезд сделан механически (разбором кода, не переписыванием) и проверен
    ПОБАЙТОВОЙ сверкой на четырёх наборах данных, включая враждебное имя
    канала. Экранирование осталось прежним: имя приходит из профиля Twitch,
    то есть управляется посторонним, поэтому html.escape/json.dumps здесь, а
    автоэкранирование Jinja намеренно ВЫКЛЮЧЕНО — иначе экранировали бы дважды.
    """
    import html, json

    tier = html.escape((ch.get("tier") or "free").upper())
    tier_color = {"FREE": "#6e6e73", "PRO": "#9147ff", "VIP": "#f4b740"}.get(
        tier, "#6e6e73")
    module_raw = ch.get("active_module") or "—"
    return _render_template(
        "streamer_dashboard.html",
        tier=tier,
        tier_color=tier_color,
        module=html.escape(str(module_raw)),
        module_js=json.dumps(module_raw).replace("</", "<\/"),
        display=html.escape(str(ch.get("display_name") or ch.get("login") or "?")),
        login=html.escape(str(ch.get("login") or "?")),
        channel_id=html.escape(str(ch.get("channel_id") or "?")),
        registered_at=html.escape(str(ch.get("registered_at") or "?")),
        has_oauth=_oauth_badge(ch),
    )


def _oauth_badge(ch: dict) -> str:
    """Состояние токена канала для плитки дашборда.

    2026-07-28. Раньше здесь было `"✅" if ch.get("oauth_access_token") else "—"`,
    то есть галочка означала «поле в базе не пустое». Токен канала умер 10 июля,
    поле осталось заполненным (там лежал протухший шифротекст) — и дашборд три
    недели показывал ✅, пока зрители тратили очки канала и не получали крустики.
    Классический ложный зелёный: индикатор отвечал не на тот вопрос.

    Живость по-настоящему проверяется запросом к Twitch, но дёргать сеть на
    каждую отрисовку страницы нельзя. Зато срок годности лежит рядом, в базе, и
    ничего не стоит: если он в прошлом — продление сломано, потому что исправный
    цикл обновляет токен заранее. Этого достаточно, чтобы поломка была ВИДНА.

    Полная проверка (с обращением к Twitch) — в `scripts/preflight.ps1`.
    """
    if not ch.get("oauth_access_token"):
        return "— нет, нужна авторизация"
    exp = ch.get("oauth_expires_at")
    if not exp:
        return "⚠️ срок неизвестен"
    try:
        import time as _t
        if _parse_iso_to_epoch(exp) < _t.time():
            return "⚠️ ИСТЁК — награды за очки канала не работают, нужна повторная авторизация"
    except Exception:
        return "⚠️ срок неизвестен"
    return "✅"


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


class ModuleSecretMissing(RuntimeError):
    """MODULE_TOKEN_SECRET не задан — подписывать нечем."""


def _module_secret() -> bytes:
    """Ключ подписи module/overlay-токенов. Пустой секрет = отказ (S-15).

    Раньше при пустом `MODULE_TOKEN_SECRET` подпись молча падала на константу
    `unconfigured-module-secret`. Строка лежит в исходниках и в опубликованном
    отчёте аудита, то есть кто угодно мог собрать валидный токен за чужой канал
    и говорить с Module API от имени его мода. Теперь пустой секрет — жёсткий
    отказ: лучше «не работает и видно», чем «работает и открыто всем».
    """
    secret = (MODULE_TOKEN_SECRET or "").encode()
    if not secret:
        raise ModuleSecretMissing(
            "MODULE_TOKEN_SECRET пуст — выдача и проверка module/overlay-токенов "
            "отключены. Задай секрет в .env и перезапусти сервис.")
    return secret


def issue_module_token(channel_id: int, module_id: str,
                        ttl_seconds: int = _MODULE_TOKEN_TTL) -> str:
    """Сгенерировать module-token. Per docs/MODULE_API.md §4.

    HMAC-SHA256(channel_id|module_id|expires_at, MODULE_TOKEN_SECRET).
    """
    expires_at = int(time.time()) + max(60, int(ttl_seconds))
    msg = f"{int(channel_id)}|{module_id}|{expires_at}"
    secret = _module_secret()
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
        secret = _module_secret()
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
    except ModuleSecretMissing as e:
        # Секрета нет — проверить подпись нечем. Отклоняем ВСЕ токены и кричим
        # в лог: молчаливый пропуск здесь означал бы открытую дверь.
        log.error("[module-token] %s", e)
        return None
    except (ValueError, IndexError):
        return None


# ── Overlay-token (A2, 2026-07-02) ────────────────────────────────────────────
# /api/overlay/tts/played мутирует очередь TTS, а id+channel_id публичны (видны в
# /tts/pending) → грифер мог гасить платное TTS (5000💎). Per-channel токен живёт
# в URL OBS-оверлея (секрет, не на стриме). Мутация требует валидный токен.
def issue_overlay_token(channel_id: int) -> str:
    msg = f"overlay|{int(channel_id)}"
    secret = _module_secret()
    return hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()[:32]


def verify_overlay_token(channel_id: int, token: str) -> bool:
    if not token:
        return False
    try:
        expected = issue_overlay_token(channel_id)
    except ModuleSecretMissing as e:
        log.error("[overlay-token] %s", e)
        return False
    return hmac.compare_digest(token, expected)


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
