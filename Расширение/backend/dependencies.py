"""
dependencies.py — общие зависимости для всех роутеров.

Хранит ссылки на db, bot, rate-limit и overlay-состояние.
Инициализируется из main.py при старте. Роутеры импортируют отсюда — без цикла.
"""

import asyncio
import os
import secrets
import time as _time
from collections import defaultdict
from contextvars import ContextVar
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from auth import verify_twitch_jwt
from config import DEFAULT_CHANNEL_ID, LOGIN_ATTEMPT_TTL, sanitize_username, validate_username

# ── Multi-tenant request context ──────────────────────────────────────────────
# ContextVar автоматически пропагируется через `await` в рамках одной asyncio-task'и
# и копируется в child task'и. Routes вызывают require_jwt_user / require_jwt_channel
# в начале handler'а — это устанавливает channel_id в контекст. Все async DB-вызовы
# дальше по цепочке (включая asyncio.create_task(...) для achievements и пр.)
# автоматически видят правильный channel_id без явного проброса.
#
# Background loops (reward_points_loop, drop_loop, market_expiry_loop) НЕ ходят через
# JWT — они передают channel_id явным параметром в db-helpers, что переопределяет
# контекст-фоллбэк.
_current_channel_id: ContextVar[Optional[int]] = ContextVar('current_channel_id', default=None)


def resolve_channel_id(channel_id: Optional[int] = None) -> int:
    """Разрешить channel_id для DB-helper.

    Приоритет:
      1. Явный параметр (background loops, EventSub)
      2. ContextVar (установленный require_jwt_user / require_jwt_channel в JWT-routes)
      3. DEFAULT_CHANNEL_ID (single-tenant fallback из config.py — TODO M4 убрать)

    Это та точка через которую идёт ВЕСЬ выбор channel_id в коде. Если меняется
    политика fallback'а (например, M4 добавит channels-registry и потребует
    явный регистрант) — меняется только эта функция.
    """
    if channel_id is not None and channel_id > 0:
        return channel_id
    ctx_value = _current_channel_id.get()
    if ctx_value is not None and ctx_value > 0:
        return ctx_value
    return DEFAULT_CHANNEL_ID

# ── Shared state ──────────────────────────────────────────────────────────────
_db  = None
_bot = None

# ── Twitch ID → login cache (общий для всех роутеров) ────────────────────────
_twitch_login_cache: dict = {}

def cache_twitch_login(user_id: str, opaque_id: str, login: str) -> None:
    """Сохранить маппинг Twitch ID → логин."""
    if user_id:   _twitch_login_cache[str(user_id)]  = login
    if opaque_id: _twitch_login_cache[str(opaque_id)] = login
    # Также без префикса U
    clean = str(opaque_id).lstrip("U") if opaque_id else ""
    if clean and clean.isdigit():
        _twitch_login_cache[clean] = login

def resolve_jwt_login(jwt_result: dict) -> str:
    """Резолвим реальный логин из JWT-результата через кеш.
    Возвращает логин если найден, иначе пустую строку."""
    user_id = str(jwt_result.get("user_id", ""))
    opaque  = str(jwt_result.get("username", ""))
    clean   = opaque.lstrip("U")
    return (
        _twitch_login_cache.get(user_id)
        or _twitch_login_cache.get(opaque)
        or _twitch_login_cache.get(clean)
        or ""
    )


def require_jwt_user(request: Request) -> Optional[Tuple[str, int]]:
    """
    Возвращает (sanitized_login, channel_id) или None.

    None означает что endpoint должен вернуть {"success": False, "message": ...}.
    Используется как замена `username` из request body — JWT-резолв
    единственный достоверный источник имени зрителя И стримера.

    Возвращает None если:
      - JWT-токена нет в заголовке X-Twitch-JWT
      - JWT невалиден или просрочен
      - JWT валиден но логин не резолвится (зритель должен открыть
        расширение и нажать «Login with Twitch» чтобы заполнить кэш)
      - JWT не содержит channel_id (broadcaster context отсутствует —
        не должно случаться в Twitch Extension JWT)

    channel_id — это broadcaster's Twitch user_id (int). Все TENANT-таблицы
    скоупятся по нему. См. MULTITENANT_PLAN.md §E.
    """
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") != "valid":
        return None
    login = sanitize_username(resolve_jwt_login(jwt_result))
    if not login or not validate_username(login):
        return None
    raw_channel = jwt_result.get("channel_id") or ""
    try:
        channel_id = int(raw_channel)
    except (TypeError, ValueError):
        return None
    if channel_id <= 0:
        return None
    # Кладём channel_id в контекст текущей request-task'и — все async db-вызовы
    # дальше по цепочке (включая create_task(...) child'ов) автоматически
    # увидят его через resolve_channel_id() без явного проброса.
    _current_channel_id.set(channel_id)
    return (login, channel_id)


def require_jwt_channel(request: Request) -> Optional[int]:
    """
    Возвращает channel_id из JWT или None.

    Облегчённая версия `require_jwt_user`: НЕ требует чтобы JWT-логин
    резолвился (зритель мог не залогиниться через Twitch). Только проверяет
    что JWT валиден и содержит broadcaster context.

    Используется эндпоинтами где username приходит из body/mod-команды,
    а JWT нужен только как «I'm in channel X»-контекст для multi-tenant
    скоупинга. См. rimworld.py shop endpoints.
    """
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") != "valid":
        return None
    raw_channel = jwt_result.get("channel_id") or ""
    try:
        channel_id = int(raw_channel)
    except (TypeError, ValueError):
        return None
    if channel_id <= 0:
        return None
    # См. require_jwt_user — устанавливаем channel_id в context для авто-проброса.
    _current_channel_id.set(channel_id)
    return channel_id

# ── Rate limiting ─────────────────────────────────────────────────────────────
_rate_buckets: dict = defaultdict(lambda: {"count": 0, "reset": 0.0})
_RATE_LIMIT       = 30      # запросов в минуту на IP по умолчанию
_RATE_BUCKETS_MAX = 10_000  # максимум уникальных IP в памяти

# ── Overlay state ─────────────────────────────────────────────────────────────
_overlay_jackpot = None   # {id, username, win, bet, ts}
_overlay_drop    = None   # {id, username, item_name, rarity, ts}


def set_db(db) -> None:
    global _db
    _db = db


def set_bot(bot) -> None:
    global _bot
    _bot = bot


def get_db():
    """Возвращает экземпляр Database."""
    if _db is None:
        raise RuntimeError("Database не инициализирована. Вызовите set_db() в main.py")
    return _db


def get_bot():
    """Возвращает экземпляр BotCore."""
    if _bot is None:
        raise RuntimeError("BotCore не инициализирован. Вызовите set_bot() в main.py")
    return _bot


# ── Rate limit helpers ────────────────────────────────────────────────────────

def check_rate_limit(ip: str, limit: int = _RATE_LIMIT) -> bool:
    """True = разрешить, False = заблокировать."""
    now = _time.time()
    b = _rate_buckets[ip]
    if now > b["reset"]:
        b["count"] = 0
        b["reset"] = now + 60
    b["count"] += 1
    return b["count"] <= limit

async def rate_cleanup_loop():
    """Фоновая задача: чистит просроченные rate-limit бакеты раз в 5 минут."""
    while True:
        await asyncio.sleep(300)
        now = _time.time()
        expired = [ip for ip, b in _rate_buckets.items() if now > b["reset"] + 120]
        for ip in expired:
            del _rate_buckets[ip]
        if len(_rate_buckets) > _RATE_BUCKETS_MAX:
            oldest = sorted(_rate_buckets.items(), key=lambda x: x[1]["reset"])
            for ip, _ in oldest[:len(_rate_buckets) - _RATE_BUCKETS_MAX]:
                del _rate_buckets[ip]


# ── Overlay state helpers ─────────────────────────────────────────────────────

def set_overlay_jackpot(data: Optional[dict]) -> None:
    global _overlay_jackpot
    _overlay_jackpot = data

def set_overlay_drop(data: Optional[dict]) -> None:
    global _overlay_drop
    _overlay_drop = data

_overlay_donate = None   # {username, amount_rub, points, gift, ts}

def set_overlay_donate(data: Optional[dict]) -> None:
    global _overlay_donate
    _overlay_donate = data

def get_overlay_state() -> dict:
    return {"jackpot": _overlay_jackpot, "drop": _overlay_drop, "donate": _overlay_donate}


# ── Last event winner ─────────────────────────────────────────────────────────

_last_event_winner = None  # {has_winner, winner, message, prize, ended_at}

def set_last_event_winner(data: Optional[dict]) -> None:
    global _last_event_winner
    _last_event_winner = data

def get_last_event_winner() -> Optional[dict]:
    return _last_event_winner


# ── Admin auth ────────────────────────────────────────────────────────────────

_security = HTTPBasic()
_failed_login_attempts: dict = {}
_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
_raw_admin_password = os.getenv("ADMIN_PASSWORD", "")
if not _raw_admin_password:
    _raw_admin_password = secrets.token_hex(16)
    print(
        "⚠️  ADMIN_PASSWORD не задан в .env — сгенерирован временный: "
        f"{_raw_admin_password}\n"
        "    Он поменяется при следующем рестарте. Пропиши ADMIN_PASSWORD в .env, "
        "чтобы не терять доступ к /admin."
    )
_ADMIN_PASSWORD = _raw_admin_password

# Брутфорс-защита: блокируем IP после LOGIN_ATTEMPT_MAX неудач в окне LOGIN_ATTEMPT_TTL.
# При успешном входе счётчик IP сбрасывается. Без этого 8-значный пароль подбирается
# простым curl-скриптом за минуты.
LOGIN_ATTEMPT_MAX = 10


def require_admin(credentials: HTTPBasicCredentials = Depends(_security), request: Request = None):
    """Защита всех /admin и /api/admin роутов через HTTP Basic Auth."""
    global _failed_login_attempts
    now = _time.time()
    ip  = (request.client.host if request and request.client else None) or credentials.username

    _failed_login_attempts = {k: v for k, v in _failed_login_attempts.items()
                               if now - v["first"] < LOGIN_ATTEMPT_TTL}

    bucket = _failed_login_attempts.get(ip)
    if bucket and bucket["count"] >= LOGIN_ATTEMPT_MAX:
        retry_minutes = max(1, int((LOGIN_ATTEMPT_TTL - (now - bucket["first"])) / 60) + 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много неудачных попыток. Попробуй через {retry_minutes} мин.",
        )

    ok_user = secrets.compare_digest(credentials.username.encode(), _ADMIN_USERNAME.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), _ADMIN_PASSWORD.encode())

    if ok_user and ok_pass:
        _failed_login_attempts.pop(ip, None)
        return

    if ip not in _failed_login_attempts:
        _failed_login_attempts[ip] = {"count": 0, "first": now}
    _failed_login_attempts[ip]["count"] += 1
    _failed_login_attempts[ip]["last"]   = now
    count = _failed_login_attempts[ip]["count"]
    print(f"🚨 Failed login #{count}/{LOGIN_ATTEMPT_MAX} for '{credentials.username}' from {ip}")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин или пароль",
        headers={"WWW-Authenticate": "Basic"},
    )


# ── Stream check ──────────────────────────────────────────────────────────────

async def require_stream_live() -> Optional[dict]:
    """
    Возвращает None если стрим идёт — можно продолжать.
    Возвращает error-dict если стрим офлайн.
    Использование: if err := await require_stream_live(): return err
    """
    _STREAM_OFFLINE_MSG = {"success": False, "message": "⚡ Доступно только во время стрима"}
    try:
        live = await get_bot()._is_stream_live()
        if not live:
            return _STREAM_OFFLINE_MSG
    except Exception:
        pass  # при ошибке проверки не блокируем
    return None
