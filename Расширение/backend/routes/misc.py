"""
routes/misc.py — перевод очков, донаты, OBS-оверлей, резолв Twitch ID.
"""
import asyncio
import base64 as _base64
import os
import random

import aiohttp
import aiosqlite
import jwt
from fastapi import APIRouter, Depends, Request

from auth import verify_twitch_jwt
from config import ECONOMY_CONFIG, sanitize_username, validate_username
from dependencies import (
    cache_twitch_login,
    get_bot,
    get_db,
    get_overlay_state,
    require_admin,
    require_stream_live,
    resolve_jwt_login,
    set_overlay_donate,
)
from models import TransferRequest

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

@router.post("/api/points/transfer")
async def transfer_points(request: Request, body: TransferRequest):
    """Перевести очки другому зрителю. Sender берётся из JWT-токена."""
    if err := await require_stream_live():
        return err

    jwt_result = verify_twitch_jwt(request)
    if jwt_result["status"] == "none":
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    if jwt_result["status"] == "invalid":
        return {"success": False, "message": "❌ Неверный или просроченный JWT-токен"}

    sender   = sanitize_username(resolve_jwt_login(jwt_result))
    receiver = sanitize_username(body.receiver)

    if not sender or not validate_username(sender):
        return {"success": False, "message": "❌ Отправитель не найден — открой расширение и войди через Twitch"}
    if not receiver or not validate_username(receiver):
        return {"success": False, "message": "❌ Неверный получатель"}
    if sender == receiver:
        return {"success": False, "message": "Нельзя переводить самому себе"}
    if body.amount < ECONOMY_CONFIG["min_transfer"]:
        return {"success": False, "message": f"Минимальная сумма {ECONOMY_CONFIG['min_transfer']}💎"}

    await get_bot().touch_viewer(sender)

    db             = get_db()
    sender_points  = await db.get_points(sender)
    if sender_points is None:
        return {"success": False, "message": "❌ Отправитель не найден"}
    if sender_points < body.amount:
        return {"success": False, "message": f"У тебя только {sender_points}💎"}

    receiver_points = await db.get_points(receiver)
    if receiver_points is None:
        return {"success": False, "message": "Получатель не найден"}

    if not await db.remove_points(sender, body.amount):
        return {"success": False, "message": "Баланс изменился — попробуй ещё раз"}
    await db.add_points(receiver, body.amount)
    return {"success": True, "message": f"✅ Переведено {body.amount}💎 пользователю @{receiver}"}


# ── Donate ────────────────────────────────────────────────────────────────────

@router.post("/api/donate")
async def handle_donate(request: Request, _admin: str = Depends(require_admin)):
    """Принимает донат и выдаёт очки (1 руб = 50 очков) + предмет если сумма >= 50 руб"""
    from datetime import datetime

    data       = await request.json()
    username   = sanitize_username(data.get("username", ""))
    amount_rub = float(data.get("amount_rub", 0))
    if not username or amount_rub <= 0:
        return {"success": False, "message": "Неверные параметры"}

    POINTS_PER_RUB = ECONOMY_CONFIG["points_per_rub"]
    points = int(amount_rub * POINTS_PER_RUB)
    db     = get_db()
    await db.add_points(username, points)

    gift_item = None
    if amount_rub >= ECONOMY_CONFIG["donation_item_threshold"]:
        if amount_rub >= 1000:
            items = [("корона", 100, "Корона 👑")]
        elif amount_rub >= 500:
            items = [("амулет", 70, "Амулет 🔮"), ("корона", 30, "Корона 👑")]
        elif amount_rub >= 250:
            items = [("камень", 40, "Камень 🪨"), ("амулет", 45, "Амулет 🔮"), ("корона", 15, "Корона 👑")]
        else:
            items = [
                ("деревяшка", 60, "Деревяшка 🪵"),
                ("камень",    28, "Камень 🪨"),
                ("амулет",     9, "Амулет 🔮"),
                ("корона",     3, "Корона 👑"),
            ]
        selected     = random.choices(items, weights=[i[1] for i in items])[0]
        item_name    = selected[0]
        display_name = selected[2]
        await db.give_item(username, item_name)
        gift_item = display_name
        print(f"🎁 Донат {amount_rub}₽ → выдан предмет: {display_name} (@{username})")

    try:
        bot = get_bot()
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                "INSERT INTO event_pool (username, amount, donated_at) VALUES (?, ?, datetime('now'))",
                (username, amount_rub))
            await conn.commit()
        bot.event_manager.donation_total += amount_rub
    except Exception as e:
        print(f"Ошибка обновления рулекциона: {e}")

    msg = f"💰 Донат {amount_rub}₽ принят! +{points}💎"
    if gift_item:
        msg += f" и {gift_item} в инвентарь!"

    set_overlay_donate({
        "username":   username,
        "amount_rub": amount_rub,
        "points":     points,
        "gift":       gift_item,
        "ts":         datetime.now().isoformat(),
    })

    # Чат-оповещение про донат от 100₽. Шлём всегда, чтобы стример мог поблагодарить
    # вслух, и чтобы другие видели что поддержка работает. Ниже 100₽ — шум.
    if amount_rub >= 100:
        try:
            gift_part = f" + {gift_item}" if gift_item else ""
            asyncio.create_task(get_bot().send_message(
                f"💎✨ СПАСИБО @{username} за донат {amount_rub:g}₽! "
                f"+{points:,}💎{gift_part}. Копилка рулекциона пополнена!"
            ))
        except Exception as e:
            print(f"donate chat error: {e}")

    return {"success": True, "points": points, "gift": gift_item, "message": msg}


# ── Overlay ───────────────────────────────────────────────────────────────────

@router.get("/api/overlay/latest")
async def overlay_latest():
    """OBS-оверлей: последние события (джекпот, донат, дроп). Публичный."""
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
