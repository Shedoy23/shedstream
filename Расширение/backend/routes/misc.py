"""
routes/misc.py — OBS-оверлей, резолв Twitch ID.

Phase 1.D (2026-05-10): /api/points/transfer + /api/donate удалены
как несовместимые с Twitch Extension Guidelines:
  - transfer: P2P внутренней валюты (серая зона 1, conservative removal)
  - donate: прямая конвертация ₽→крустики (§5.2 + §5.4 + 2026-Bits-tightening)
"""
import base64 as _base64
import os

import aiohttp
import jwt
from fastapi import APIRouter, Request

from auth import verify_twitch_jwt
from config import sanitize_username, validate_username
from dependencies import (
    cache_twitch_login,
    get_db,
    get_overlay_state,
    require_jwt_user,
)

router = APIRouter()

# ── Twitch ID cache ───────────────────────────────────────────────────────────
_twitch_app_token:    str   = None
_twitch_token_expires: float = 0
_twitch_id_cache:     dict  = {}


async def get_twitch_app_token() -> str:
    global _twitch_app_token, _twitch_token_expires
    import time as _t
    client_id     = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise ValueError("TWITCH_CLIENT_ID/SECRET не заданы в .env")
    if _twitch_app_token and _t.time() < _twitch_token_expires - 60:
        return _twitch_app_token
    async with aiohttp.ClientSession() as session:
        async with session.post("https://id.twitch.tv/oauth2/token", data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "client_credentials",
        }) as r:
            data = await r.json()
            _twitch_app_token    = data.get("access_token", "")
            _twitch_token_expires = _t.time() + data.get("expires_in", 3600)
            return _twitch_app_token


# ── Points transfer ───────────────────────────────────────────────────────────
# /api/points/transfer удалён 2026-05-10 (Phase 1.D compliance rework — серая зона
# 1: P2P transfer extension currency, дух 2026-Bits-tightening против off-platform
# value exchange / proxy-for-money). См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.

# ── Donate ────────────────────────────────────────────────────────────────────
# /api/donate удалён 2026-05-10 (Phase 1.D compliance rework — прямое нарушение
# §5.2 (items за money/commerce instruments), §5.4 (commerce instruments for
# donations), §4.5 (off-Twitch action incentivisation), 2026-Bits-tightening.
# Конвертация ₽ → крустики + рандомный предмет — всё под нож разом.
# См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.


# ── Overlay ───────────────────────────────────────────────────────────────────

@router.get("/api/overlay/latest")
async def overlay_latest():
    """OBS-оверлей: последние события (дроп). Публичный.

    jackpot/donate ключи удалены (Phase 8.A.2 / 8.F lexicon+compliance).
    """
    return get_overlay_state()


# ── Twitch user resolver ──────────────────────────────────────────────────────

@router.post("/api/user/resolve-twitch-token")
async def resolve_twitch_token(request: Request):
    """Декодируем JWT → числовой user_id → логин через Helix API.

    user_id берётся ТОЛЬКО из проверенного JWT (или из opaque_id fallback).
    Параметр explicit user_id из body больше не принимается — раньше это позволяло
    кому угодно резолвить логин любого Twitch ID для разведки целей.
    """
    try:
        data       = await request.json()
        token_str  = data.get("token", "")
        opaque_id  = data.get("opaque_id", "")

        if opaque_id and opaque_id in _twitch_id_cache:
            return {"login": _twitch_id_cache[opaque_id], "cached": True}

        user_id = None

        if token_str:
            try:
                secret_b64 = os.getenv("TWITCH_EXTENSION_SECRET", "")
                if secret_b64:
                    # base64url → base64 с правильным паддингом
                    secret_b64n = secret_b64.replace('-', '+').replace('_', '/')
                    pad = 4 - len(secret_b64n) % 4
                    if pad != 4:
                        secret_b64n += '=' * pad
                    secret_bytes  = _base64.b64decode(secret_b64n)
                    _jwt_payload  = jwt.decode(
                        token_str, secret_bytes, algorithms=["HS256"],
                        options={"verify_exp": True, "leeway": 60})
                    user_id = _jwt_payload.get("user_id")
            except Exception as e:
                print(f"JWT verified decode failed: {e}")

        # Fallback: извлекаем числовой ID из opaque_id
        # До sharing: "U12345678", после sharing: "12345678" (без U)
        if not user_id and opaque_id:
            candidate = opaque_id[1:] if opaque_id.startswith("U") else opaque_id
            if candidate.isdigit():
                user_id = candidate

        if not user_id:
            return {"login": None, "error": "Не удалось определить user_id"}

        if user_id in _twitch_id_cache:
            login = _twitch_id_cache[user_id]
            if opaque_id:
                _twitch_id_cache[opaque_id] = login
            return {"login": login, "cached": True}

        client_id = os.getenv("TWITCH_CLIENT_ID", "")
        if not client_id:
            return {"login": None, "error": "TWITCH_CLIENT_ID не задан"}

        app_token = await get_twitch_app_token()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.twitch.tv/helix/users?id={user_id}",
                headers={"Client-ID": client_id, "Authorization": f"Bearer {app_token}"},
            ) as r:
                resp = await r.json()
                if r.status == 401 or resp.get("status") == 401:
                    global _twitch_app_token, _twitch_token_expires
                    _twitch_app_token    = None
                    _twitch_token_expires = 0
                    app_token = await get_twitch_app_token()
                    async with session.get(
                        f"https://api.twitch.tv/helix/users?id={user_id}",
                        headers={"Client-ID": client_id, "Authorization": f"Bearer {app_token}"},
                    ) as r2:
                        resp = await r2.json()

                if resp.get("data"):
                    login = resp["data"][0]["login"]
                    _twitch_id_cache[user_id] = login
                    if opaque_id:
                        _twitch_id_cache[opaque_id] = login
                    cache_twitch_login(user_id, opaque_id, login)
                    return {"login": login}
                return {"login": None, "error": f"Helix не нашёл user_id={user_id}"}
    except Exception as e:
        print(f"🔥 resolve_twitch_token error: {e}")
        return {"login": None, "error": str(e)}


@router.get("/api/user/resolve-twitch-id")
async def resolve_twitch_id(twitch_id: str):
    """Резолв числового Twitch ID → логин."""
    candidate = twitch_id[1:] if twitch_id.startswith("U") else twitch_id
    if not candidate.isdigit():
        return {"login": None, "error": "opaque ID — используй /resolve-twitch-token"}
    if candidate in _twitch_id_cache:
        return {"login": _twitch_id_cache[candidate], "cached": True}
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    if not client_id:
        return {"login": None, "error": "TWITCH_CLIENT_ID не задан"}
    try:
        app_token = await get_twitch_app_token()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.twitch.tv/helix/users?id={candidate}",
                headers={"Client-ID": client_id, "Authorization": f"Bearer {app_token}"},
            ) as r:
                resp = await r.json()
                if resp.get("data"):
                    login = resp["data"][0]["login"]
                    _twitch_id_cache[candidate] = login
                    return {"login": login}
                return {"login": None}
    except Exception as e:
        return {"login": None, "error": str(e)}


@router.post("/api/user/map-twitch-id")
async def map_twitch_id(request: Request):
    """Подтвердить уже закэшированный маппинг своего twitch_id → login.

    БЕЗОПАСНОСТЬ: эндпоинт больше НЕ создаёт новые маппинги по login из body.
    Раньше можно было вызвать с `{twitch_id: <my_user_id>, login: <victim_login>}` и
    отравить кэш — твой собственный JWT после этого резолвился в логин жертвы,
    и все твои авторизованные действия зачитывались на её счёт.

    Новые маппинги создаются только через `/api/user/resolve-twitch-token`,
    который верифицирует логин через Helix API (источник правды).
    """
    jwt_result = verify_twitch_jwt(request)
    if jwt_result["status"] != "valid":
        return {"status": "unauthorized"}

    jwt_user_id = str(jwt_result.get("user_id", ""))
    if not jwt_user_id:
        return {"status": "no_user_id", "message": "Логин-через-Twitch требуется"}

    cached = _twitch_id_cache.get(jwt_user_id)
    if cached:
        return {"status": "ok", "login": cached}

    return {"status": "needs_resolve",
            "message": "Кэш не заполнен — вызови /api/user/resolve-twitch-token"}
