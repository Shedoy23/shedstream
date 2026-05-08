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
from config import (
    DEFAULT_CHANNEL_ID,
    LOGIN_ATTEMPT_TTL,
    RATE_LIMITS_BY_TIER,
    RATE_LIMIT_DEFAULT_TIER,
    sanitize_username,
    validate_username,
)

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


# ── M4.1: registered channels cache ───────────────────────────────────────────
# In-memory set всех channel_id зарегистрированных в `channels` таблице.
# Заполняется при startup из db.list_channels() и обновляется через
# mark_channel_registered() при OAuth-регистрации (M4.3).
#
# Sync-проверка нужна потому что require_jwt_user/_channel — sync функции,
# а делать async DB hop на каждый JWT-парсинг неприемлемо (TPS).
#
# Когерентность: если пользователь только что зарегистрировался и cache на этом
# процессе ещё не обновлён (мульти-инстанс будущее) — получит 403 один раз,
# на следующем запросе fallback в DB добавим в M5+.
_registered_channels_cache: set = set()
_channels_cache_initialized: bool = False

# M4 follow-up (в): login (lowercase) → channel_id mapping. Нужно IRC-боту
# чтобы при входящем чат-сообщении из канала #foo резолвить broadcaster_id
# для multi-tenant скоупинга. Заполняется одновременно с _registered_*.
_channel_login_to_id: dict = {}

# M5: channel_id → tier ('free' / 'pro' / 'vip'). Заполняется одновременно
# с registered_channels_cache. Используется в check_channel_rate_limit для
# применения tier-based квот. Updates при OAuth-регистрации; runtime tier
# changes (admin upgrade) пока требуют рестарта — TODO M6+.
_channel_tier_cache: dict = {}

# M5: per-channel rate-limit buckets. channel_id → {count, reset}.
# Отличается от _rate_buckets (per-IP, ниже) — этот аккаунт-уровень,
# защищает прод от ситуации «один канал шлёт 10K req/min с разных IP».
_channel_rate_buckets: dict = {}


def is_channel_registered(channel_id: int) -> bool:
    """Зарегистрирован ли канал (есть запись в `channels`).

    До init_registered_channels_cache() возвращает True (fail-open) —
    защита от race на startup, когда первый запрос приходит до init.
    После init — строгая проверка по кэшу.
    """
    if not _channels_cache_initialized:
        return True
    return channel_id in _registered_channels_cache


def get_channel_id_by_login(login: str) -> Optional[int]:
    """M4 follow-up (в): реверсный lookup для IRC-бота. Снимаем `#` префикс
    и lowercase. Возвращает None если канал не зарегистрирован."""
    if not login:
        return None
    return _channel_login_to_id.get(login.lstrip("#").lower())


def get_channel_login_by_id(channel_id: int) -> Optional[str]:
    """Прямой lookup channel_id → login. Используется чтобы slать сообщение
    в правильный IRC-канал (twitchio оперирует именами каналов, не ID)."""
    if channel_id is None:
        return None
    for login, cid in _channel_login_to_id.items():
        if cid == int(channel_id):
            return login
    return None


def set_request_channel_id(channel_id: int) -> None:
    """Public setter для request-context ContextVar. Используется IRC-ботом
    в начале event_message/event_raw_data — после этого все downstream
    db-helpers видят правильный channel_id без явного проброса.
    """
    if channel_id and channel_id > 0:
        _current_channel_id.set(int(channel_id))


def mark_channel_registered(channel_id: int, login: Optional[str] = None,
                              tier: Optional[str] = None) -> None:
    """Добавить канал в cache. Вызывается M4.3 OAuth callback'ом
    после db.upsert_channel(). Без этого канал получает 403 до рестарта.

    M4 follow-up (в): login параметр обновляет login→id mapping чтобы
    IRC-бот мог скоупить чат-сообщения от только что зарегистрированного
    канала (если он успеет джойнить — late-join handled in future).

    M5: tier параметр кэширует тариф для check_channel_rate_limit.
    Default — RATE_LIMIT_DEFAULT_TIER (free), upsert_channel в OAuth flow
    тоже создаёт запись с tier='free' для новых регистрантов."""
    if channel_id and channel_id > 0:
        cid = int(channel_id)
        _registered_channels_cache.add(cid)
        if login:
            _channel_login_to_id[login.lower().lstrip("#")] = cid
        _channel_tier_cache[cid] = (tier or RATE_LIMIT_DEFAULT_TIER).lower()


async def init_registered_channels_cache(db) -> None:
    """Загрузить registered channels из БД. Вызывается из main.py startup
    ПОСЛЕ run_migrations() (m4_channels.apply должен был backfill'ить
    существующего стримера)."""
    global _channels_cache_initialized
    rows = await db.list_channels()
    _registered_channels_cache.clear()
    _channel_login_to_id.clear()
    _channel_tier_cache.clear()
    for r in rows:
        cid = int(r["channel_id"])
        _registered_channels_cache.add(cid)
        login = r.get("login")
        if login:
            _channel_login_to_id[login.lower()] = cid
        tier = (r.get("tier") or RATE_LIMIT_DEFAULT_TIER).lower()
        _channel_tier_cache[cid] = tier
    _channels_cache_initialized = True
    print(f"✅ Registered channels cache: {len(_registered_channels_cache)} channels loaded "
          f"(login→id map: {len(_channel_login_to_id)}, tier-cache: {len(_channel_tier_cache)})")


# ── M5: Per-channel rate limits ──────────────────────────────────────────────

def check_channel_rate_limit(channel_id: int) -> bool:
    """True = разрешить, False = заблокировать (429).

    Per-channel sliding window per минуту. Tier-based квоты:
        free → 300 req/min (по умолчанию)
        pro  → 1200 req/min
        vip  → 6000 req/min
    Override через .env RATE_LIMIT_FREE / _PRO / _VIP.

    Применяется в require_jwt_user/_channel — JWT-аутентифицированные
    запросы для канала X считаются в bucket этого канала. Background
    loops НЕ ходят через JWT и не считаются (намеренно — они под нашим
    контролем).
    """
    tier = _channel_tier_cache.get(channel_id, RATE_LIMIT_DEFAULT_TIER)
    limit = RATE_LIMITS_BY_TIER.get(tier, RATE_LIMITS_BY_TIER[RATE_LIMIT_DEFAULT_TIER])
    now = _time.time()
    bucket = _channel_rate_buckets.setdefault(int(channel_id), {"count": 0, "reset": 0.0})
    if now > bucket["reset"]:
        bucket["count"] = 0
        bucket["reset"] = now + 60
    bucket["count"] += 1
    return bucket["count"] <= limit


async def channel_rate_cleanup_loop():
    """Чистит просроченные channel rate-limit бакеты раз в 5 минут.
    Аналог rate_cleanup_loop для per-IP, но для per-channel."""
    while True:
        await asyncio.sleep(300)
        now = _time.time()
        expired = [cid for cid, b in _channel_rate_buckets.items() if now > b["reset"] + 120]
        for cid in expired:
            del _channel_rate_buckets[cid]


def resolve_channel_id(channel_id: Optional[int] = None) -> int:
    """Разрешить channel_id для DB-helper. **Строгая** версия (M4 follow-up а).

    Приоритет:
      1. Явный параметр (background loops, EventSub передающий broadcaster_id)
      2. ContextVar (установленный require_jwt_user / require_jwt_channel в
         JWT-routes ИЛИ set_request_channel_id в IRC-handlers)

    Если ни то, ни другое не дало ответ — поднимает RuntimeError. Это значит:
      - Request handler не вызвал require_jwt_*  → bug, надо исправить
      - Background task не передал channel_id явно → bug, надо исправить
      - Startup-time код не set'нул ContextVar → bug, надо исправить

    Для интеграционных границ где channel_id легитимно неизвестен на текущем
    уровне зрелости (мод без HMAC, IRC USERNOTICE pre-(в), admin до per-channel
    UI) — используй `resolve_channel_id_or_default()` с явным fallback'ом
    на DEFAULT_CHANNEL_ID. Этот fallback означает «знаю что в multi-tenant
    может быть некорректно — TODO исправить когда дойдут руки».
    """
    if channel_id is not None and channel_id > 0:
        return channel_id
    ctx_value = _current_channel_id.get()
    if ctx_value is not None and ctx_value > 0:
        return ctx_value
    raise RuntimeError(
        "channel_id not resolvable: ни явный параметр, ни ContextVar не дали ответ. "
        "Request handler должен вызвать require_jwt_user/_channel; background task — "
        "передать channel_id= явно; startup-job — итерировать по каналам и set_request_channel_id. "
        "Для legacy-точек без JWT см. resolve_channel_id_or_default()."
    )


def resolve_channel_id_or_default(channel_id: Optional[int] = None) -> int:
    """Явная soft-версия — для integration boundaries где channel_id легитимно
    неизвестен на текущем уровне зрелости платформы.

    Семантически identical к `resolve_channel_id` сейчас (оба возвращают
    DEFAULT_CHANNEL_ID если не разрешить из параметра/ContextVar). Цель —
    discoverability: grep по `_or_default` показывает все legacy-точки,
    которые нужно перевести на explicit channel_id перед тем как
    `resolve_channel_id` станет строгим.

    Текущие callers (M4.2):
      - rimworld.py mod endpoints (TODO M4.5+: HMAC + channel_id из мода)
      - main.py IRC bot handlers (TODO M4.5: channel.id из twitchio)
      - main.py EventSub fallback (defensive — payload без broadcaster невозможен)
      - routes/admin.py (TODO M4.4: per-channel admin UI)
      - routes/craft.py (TODO M4.4: require_jwt_user)
      - bot_core.py drop_loop crash-recovery cache
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


def _raise_channel_not_registered(channel_id: int) -> None:
    """M4.1: Канал не в реестре — попроси стримера зарегистрироваться.

    Frontend ловит 403 + status='channel_not_registered' и показывает
    «Стример не подключил расширение — попроси его зайти на shedoy23.ru/streamer».
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "status": "channel_not_registered",
            "channel_id": channel_id,
            "message": "Стример не подключил расширение к платформе",
        },
    )


def _raise_channel_rate_limited(channel_id: int) -> None:
    """M5: Per-channel rate limit exceeded → 429."""
    tier = _channel_tier_cache.get(channel_id, RATE_LIMIT_DEFAULT_TIER)
    limit = RATE_LIMITS_BY_TIER.get(tier, RATE_LIMITS_BY_TIER[RATE_LIMIT_DEFAULT_TIER])
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "status": "channel_rate_limited",
            "channel_id": channel_id,
            "tier": tier,
            "limit_per_min": limit,
            "message": "Превышен лимит запросов канала. Попробуй через минуту или попроси стримера обновить тариф.",
        },
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

    Поднимает HTTPException(403) если:
      - JWT валиден, но channel_id не зарегистрирован в `channels`-реестре
        (стример ещё не прошёл OAuth на shedoy23.ru/streamer)

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
    if not is_channel_registered(channel_id):
        _raise_channel_not_registered(channel_id)
    # M5: per-channel rate limit. После успешной registration check.
    if not check_channel_rate_limit(channel_id):
        _raise_channel_rate_limited(channel_id)
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

    Поднимает HTTPException(403) если канал не в реестре (M4.1).

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
    if not is_channel_registered(channel_id):
        _raise_channel_not_registered(channel_id)
    # M5: per-channel rate limit.
    if not check_channel_rate_limit(channel_id):
        _raise_channel_rate_limited(channel_id)
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
