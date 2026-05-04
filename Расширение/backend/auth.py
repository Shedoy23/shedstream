"""
auth.py — верификация JWT токенов Twitch Extension.

Вынесено из main.py чтобы rimworld.py мог импортировать без циклической зависимости.
"""

import base64 as _base64

import jwt
from fastapi import Request

from config import CHANNEL_POINTS_CONFIG, DEV_MODE, DEV_USERNAME, TWITCH_EXTENSION_SECRET

# DEV_MODE fallback: подставляем broadcaster_id из конфига (единственный канал
# в single-tenant модели). В multi-tenant прод-сценарии channel_id всегда
# приходит из JWT claim (Twitch Extension Helper подставляет его автоматически).
_DEV_CHANNEL_ID = str(CHANNEL_POINTS_CONFIG.get('broadcaster_id') or '')


def verify_twitch_jwt(request: Request) -> dict:
    """
    Проверяет JWT от Twitch Extension (заголовок X-Twitch-JWT).
    Возвращает dict с:
      - status: 'valid' | 'invalid' | 'none'
      - username: имя пользователя из токена (payload['sub'])
      - user_id: реальный Twitch user_id (если зритель залогинен)
      - channel_id: ID стримера из claim 'channel_id' (broadcaster user_id)

    В production режим 'unsigned' ОТКЛЮЧЕН — любая неверная подпись = отказ.
    Не кидает исключений.
    """
    # DEV_MODE: пропускаем JWT верификацию для локального тестирования.
    # Защита от случайного DEV_MODE=True в проде: bypass работает только если
    # запрос пришёл с localhost. Внешний трафик в любом случае пойдёт через
    # обычную JWT-проверку.
    if DEV_MODE:
        client_ip = (request.client.host if request.client else "")
        if client_ip in ("127.0.0.1", "::1", "localhost"):
            return {
                "status": "valid",
                "username": DEV_USERNAME,
                "channel_id": _DEV_CHANNEL_ID,
            }
        # DEV_MODE + не-localhost → не выдаём bypass, идём по обычному JWT-пути

    token = request.headers.get("X-Twitch-JWT", "").strip()
    if not token:
        return {"status": "none"}

    if not TWITCH_EXTENSION_SECRET:
        return {"status": "invalid", "error": "TWITCH_EXTENSION_SECRET не настроен"}

    try:
        # Twitch использует base64url — заменяем символы и добавляем правильный паддинг
        secret_b64 = TWITCH_EXTENSION_SECRET.replace('-', '+').replace('_', '/')
        padding = 4 - len(secret_b64) % 4
        if padding != 4:
            secret_b64 += '=' * padding
        secret_bytes = _base64.b64decode(secret_b64)
        payload = jwt.decode(
            token,
            secret_bytes,
            algorithms=["HS256"],
            options={"verify_exp": True, "leeway": 60},
        )
        username   = payload.get("sub", "") or payload.get("opaque_user_id", "")
        user_id    = str(payload.get("user_id", ""))
        channel_id = str(payload.get("channel_id", ""))
        return {
            "status": "valid",
            "username": username,
            "user_id": user_id,
            "channel_id": channel_id,
        }
    except Exception as e:
        print(f"[auth] JWT verify failed: {type(e).__name__}: {e}")
        return {"status": "invalid"}
