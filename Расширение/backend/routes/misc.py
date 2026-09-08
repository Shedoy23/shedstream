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
from fastapi import APIRouter, Depends, Request

from auth import verify_twitch_jwt
from config import sanitize_username, validate_username
from dependencies import (
    cache_twitch_login,
    get_db,
    get_overlay_state,
    require_admin,
    require_jwt_user,
)

router = APIRouter()


@router.get("/api/core/config")
async def core_config():
    """Балансовые числа ядра (не игрового модуля) — единый источник для фронта.

    ЗАЧЕМ. У Bannerlord и RimWorld такие эндпоинты есть с июля, а ядро осталось
    без: минимальная ставка в голосовании, минимальный вклад, цена гильдии и
    развода жили копиями в voting.js / guilds.js / family.js. Фронт замерзает на
    CDN Twitch до следующего ревью, бэкенд деплоится за минуты — значит любая
    правка цены расходилась бы с интерфейсом на недели. Бэк по-прежнему сам
    проверяет суммы при списании; это только для отображения.

    Публичный: числа не секретны и нужны панели до авторизации.
    """
    from config import (
        FAMILY_CONFIG,
        GUILD_CREATE_COST,
        TTS_COST,
        TTS_MAX_LEN,
        VOTING_BID_PRESETS,
        VOTING_MIN_BID,
        VOTING_PLEDGE_PRESETS,
        VOTING_PROPOSE_MIN_PLEDGE,
    )
    return {
        "voting_min_bid":        VOTING_MIN_BID,
        "voting_min_pledge":     VOTING_PROPOSE_MIN_PLEDGE,
        "voting_bid_presets":    VOTING_BID_PRESETS,
        "voting_pledge_presets": VOTING_PLEDGE_PRESETS,
        "guild_create_cost":     GUILD_CREATE_COST,
        "divorce_cost":          FAMILY_CONFIG["divorce_cost"],
        "tts_cost":              TTS_COST,
        "tts_max_len":           TTS_MAX_LEN,
    }


@router.post("/api/bug-report")
async def submit_bug_report(request: Request):
    """Зритель шлёт багрепорт из расширения → пишется в bug_reports (та же таблица,
    что и чат-команда !баг; стример читает в дашборде). Auth: JWT (username+channel_id
    из токена, никогда из body). Анти-спам: тот же кулдаун, что у !баг."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    body = await request.json()
    msg = (body.get("message") or "").strip()
    if len(msg) < 5:
        return {"success": False, "message": "Опиши проблему подробнее (мин. 5 символов)"}
    import bug_reports
    left = bug_reports.cooldown_left(channel_id, username)
    if left > 0:
        return {"success": False, "message": f"Подожди {left} сек перед следующим багрепортом"}
    await bug_reports.record_bug_report(channel_id, username, msg)
    bug_reports.mark_reported(channel_id, username)
    return {"success": True, "message": "🐛 Спасибо! Багрепорт отправлен стримеру."}


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

    user_id берётся ТОЛЬКО из проверенного JWT.
    Параметр explicit user_id из body больше не принимается — раньше это позволяло
    кому угодно резолвить логин любого Twitch ID для разведки целей.
    """
    try:
        data       = await request.json()
        token_str  = data.get("token", "")
        opaque_id  = data.get("opaque_id", "")

        user_id = None
        verified_opaque_id = None

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
                    verified_opaque_id = (
                        _jwt_payload.get("opaque_user_id")
                        or _jwt_payload.get("sub")
                    )
            except Exception as e:
                print(f"JWT verified decode failed: {e}")

        if not user_id:
            return {"login": None, "error": "Не удалось определить user_id"}

        user_id = str(user_id)
        # Never trust an alias supplied by the client.  Old and new frontends
        # both send auth.userId here; cache it only when the signed token proves
        # that it belongs to this viewer (or it is the same numeric user_id).
        cache_alias = None
        if opaque_id and opaque_id in {user_id, str(verified_opaque_id or "")}:
            cache_alias = opaque_id

        if user_id in _twitch_id_cache:
            login = _twitch_id_cache[user_id]
            if cache_alias:
                _twitch_id_cache[cache_alias] = login
            # M122: сохраняем и на попадании в память — иначе связки тех, кто
            # уже опознан, попали бы в базу только после следующего рестарта,
            # то есть ровно после того сбоя, который мы чиним.
            from dependencies import persist_twitch_login
            await persist_twitch_login(user_id, cache_alias or "", login)
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
                    if cache_alias:
                        _twitch_id_cache[cache_alias] = login
                    cache_twitch_login(user_id, cache_alias, login)
                    # M122: та же связка ложится в базу, иначе перезапуск
                    # бэкенда ослепит все открытые панели до перезагрузки.
                    from dependencies import persist_twitch_login
                    await persist_twitch_login(user_id, cache_alias or "", login)
                    return {"login": login}
                return {"login": None, "error": f"Helix не нашёл user_id={user_id}"}
    except Exception as e:
        print(f"🔥 resolve_twitch_token error: {e}")
        return {"login": None, "error": str(e)}


@router.get("/api/user/resolve-twitch-id")
async def resolve_twitch_id(twitch_id: str, _admin=Depends(require_admin)):
    """Резолв числового Twitch ID → логин.

    Public-gate (2026-07-02): закрыт admin-basic. Ни фронт, ни моды его не зовут
    (enumeration-оракул: numeric id → login). Оставлен для admin-скриптов.
    """
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
