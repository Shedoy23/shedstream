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
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

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


def require_admin(credentials: HTTPBasicCredentials = Depends(_security), request: Request = None):
    """Защита всех /admin и /api/admin роутов через HTTP Basic Auth."""
    global _failed_login_attempts
    ok_user = secrets.compare_digest(credentials.username.encode(), _ADMIN_USERNAME.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), _ADMIN_PASSWORD.encode())
    if not (ok_user and ok_pass):
        now = _time.time()
        ip  = (request.client.host if request and request.client else None) or credentials.username
        if ip not in _failed_login_attempts:
            _failed_login_attempts[ip] = {"count": 0, "first": now}
        _failed_login_attempts[ip]["count"] += 1
        _failed_login_attempts[ip]["last"]   = now
        count = _failed_login_attempts[ip]["count"]
        print(f"🚨 Failed login attempt #{count} for user '{credentials.username}'")
        from config import LOGIN_ATTEMPT_TTL
        _failed_login_attempts = {k: v for k, v in _failed_login_attempts.items()
                                   if now - v["first"] < LOGIN_ATTEMPT_TTL}
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
