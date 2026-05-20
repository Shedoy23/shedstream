"""
routes/tts.py — Озвучка сообщений зрителями (Sprint 5.23, 2026-05-21).

Платный TTS-донат: зритель за 5000💎 (TTS_COST) отправляет текст до 200
символов, overlay'й стрима озвучивает через Web Speech API. Cooldown
30s между сообщениями одного юзера.

Endpoints:
  Viewer (JWT):
    POST /api/tts/submit             — submit {message}, debit, queue
  Overlay (public, channel_id query):
    GET  /api/overlay/tts/pending    — oldest pending message для канала
    POST /api/overlay/tts/played     — {id}, mark played после speechEnd

Compliance:
  • Crystal-burn механика (внутренняя валюта, no real $).
  • НЕТ модерации текста (per Sprint 5.23 решение) — ответственность на
    стримере: банит обидчиков в чате/extension.
  • Streamer-toggle off-by-default НЕ реализуем для MVP (если будет
    abuse — потом добавим channel_tts_settings таблицу как у pets).
"""
from fastapi import APIRouter, Request

from config import TTS_COST, TTS_COOLDOWN_S, TTS_MAX_LEN
from dependencies import (
    get_db, require_jwt_user, require_stream_live,
    resolve_channel_id_or_default,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


@router.post("/api/tts/submit")
async def tts_submit(request: Request):
    """Зритель отправляет сообщение → debit крустиков + queue для overlay'я.

    Body: {"message": str}
    """
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    from dependencies import get_bot
    await get_bot().touch_viewer(username)

    data = await request.json()
    message = str(data.get("message", "") or "").strip()
    if not message:
        return {"success": False, "message": "Сообщение не может быть пустым"}
    if len(message) > TTS_MAX_LEN:
        return {
            "success": False,
            "message": f"Слишком длинно (макс {TTS_MAX_LEN} символов)",
        }

    db = get_db()

    # Cooldown check — stateless, читаем последнее сообщение этого юзера
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT (strftime('%s','now') - strftime('%s', created_at)) "
            "FROM tts_messages WHERE username = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (username,)
        )
        row = await cur.fetchone()
        if row and row[0] is not None and row[0] < TTS_COOLDOWN_S:
            remaining = TTS_COOLDOWN_S - int(row[0])
            return {
                "success": False,
                "message": f"⏳ Подожди ещё {remaining}s",
            }

    # Balance check + debit
    points = await db.get_points(username)
    if points < TTS_COST:
        return {
            "success": False,
            "message": f"Нужно {TTS_COST}💎 (у тебя {points}💎)",
        }
    if not await db.remove_points(username, TTS_COST):
        return {"success": False, "message": "Не удалось списать"}

    # Queue
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO tts_messages (channel_id, username, message, cost) "
            "VALUES (?, ?, ?, ?)",
            (channel_id, username, message, TTS_COST)
        )
        await conn.commit()

    return {
        "success": True,
        "message": f"🎤 Озвучится скоро (-{TTS_COST}💎)",
        "cost": TTS_COST,
    }


@router.get("/api/overlay/tts/pending")
async def tts_pending(channel_id: int = 0):
    """Overlay-poll: oldest pending message для канала (или null).

    Public endpoint — overlay.html не имеет Twitch auth context.
    """
    if channel_id <= 0:
        channel_id = resolve_channel_id_or_default()

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, username, message, created_at "
            "FROM tts_messages "
            "WHERE channel_id = ? AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT 1",
            (channel_id,)
        )
        row = await cur.fetchone()

    if not row:
        return {"success": True, "message": None}

    return {
        "success": True,
        "message": {
            "id":         row[0],
            "username":   row[1],
            "text":       row[2],
            "created_at": row[3],
        },
    }


@router.post("/api/overlay/tts/played")
async def tts_played(request: Request):
    """Overlay → mark message played после speechSynthesis.onend.

    Body: {"id": int}
    """
    data = await request.json()
    try:
        msg_id = int(data.get("id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный id"}
    if msg_id <= 0:
        return {"success": False, "message": "id обязателен"}

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE tts_messages "
            "SET status = 'played', played_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (msg_id,)
        )
        await conn.commit()
        updated = cur.rowcount

    return {"success": True, "updated": updated}
