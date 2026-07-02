"""
routes/tts.py — Озвучка сообщений зрителями (Sprint 5.23, 2026-05-21).

Платный TTS-донат: зритель за 5000💎 (TTS_COST) отправляет текст до 200
символов, overlay'й стрима воспроизводит mp3 через <audio>. Cooldown
30s между сообщениями.

Server-side TTS через gTTS (Google Translate TTS, free, ru-RU). На submit
генерируем mp3, сохраняем как BLOB в tts_messages.audio_data. Overlay
получает audio_url, играет через Audio().

Архитектурное решение (Sprint 5.23 patch): изначально пробовали Web
Speech API — speechSynthesis.speak() прямо в overlay.html. OBS Browser
Source (Chromium-CEF) этот API поддерживает плохо: speak() не выводит
аудио надёжно, события onend/onerror не всегда срабатывают. Переключение
на серверный mp3 — robust для OBS.

Endpoints:
  Viewer (JWT):
    POST /api/tts/submit             — debit + gTTS-генерация + queue
  Overlay (public):
    GET  /api/overlay/tts/pending    — oldest pending + audio_url
    POST /api/overlay/tts/played     — mark played после <audio> ended
    GET  /api/tts/audio/{id}.mp3     — раздаёт mp3 из BLOB'а

Compliance:
  • Crystal-burn (no real $) — §5.2 OK.
  • Без модерации текста (per решение).
"""
import asyncio
import io

from fastapi import APIRouter, Request
from fastapi.responses import Response

from config import TTS_COST, TTS_COOLDOWN_S, TTS_MAX_LEN
from dependencies import (
    get_db, require_jwt_user, require_stream_live,
    resolve_channel_id_or_default,
)

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}


def _generate_tts_mp3(text: str) -> bytes:
    """Sync gTTS вызов — генерирует mp3 в память. Запускаем через
    asyncio.to_thread из async endpoint'а чтобы не блочить event loop.
    Raises Exception если gTTS API недоступен (offline / rate-limit)."""
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text, lang='ru', slow=False).write_to_fp(buf)
    return buf.getvalue()


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
            "FROM tts_messages WHERE username = ? AND channel_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (username, channel_id)
        )
        row = await cur.fetchone()
        if row and row[0] is not None and row[0] < TTS_COOLDOWN_S:
            remaining = TTS_COOLDOWN_S - int(row[0])
            return {
                "success": False,
                "message": f"⏳ Подожди ещё {remaining}s",
            }

    # Balance check (debit ПОСЛЕ успешной gTTS генерации чтобы при
    # сетевой ошибке gTTS юзер не потерял крустики)
    points = await db.get_points(username)
    if points < TTS_COST:
        return {
            "success": False,
            "message": f"Нужно {TTS_COST}💎 (у тебя {points}💎)",
        }

    # Generate mp3 через gTTS. Sync вызов → в thread pool.
    try:
        audio_bytes = await asyncio.to_thread(_generate_tts_mp3, message)
    except Exception as e:
        print(f"[tts] gTTS generation failed: {type(e).__name__}: {e}")
        return {
            "success": False,
            "message": "❌ Ошибка TTS-сервиса, попробуй позже",
        }

    if not audio_bytes:
        return {"success": False, "message": "❌ Пустой результат TTS"}

    # Debit + queue
    if not await db.remove_points(username, TTS_COST):
        return {"success": False, "message": "Не удалось списать"}

    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO tts_messages "
            "(channel_id, username, message, cost, audio_data) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel_id, username, message, TTS_COST, audio_bytes)
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
            "audio_url":  f"/api/tts/audio/{row[0]}.mp3?channel_id={channel_id}",
        },
    }


@router.get("/api/tts/audio/{msg_id}.mp3")
async def tts_audio(msg_id: int, channel_id: int = 0):
    """Раздаёт mp3 для конкретного message id из audio_data BLOB.

    Public — overlay.html без auth. id + channel_id указаны в URL (overlay
    берёт готовый audio_url из /api/overlay/tts/pending). Скоуп по channel_id —
    иначе любой overlay скачивает аудио чужого канала по голому id.
    Кеширование браузером отключено (Cache-Control: no-cache).
    """
    if channel_id <= 0:
        channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT audio_data FROM tts_messages WHERE id = ? AND channel_id = ?",
            (msg_id, channel_id)
        )
        row = await cur.fetchone()

    if not row or not row[0]:
        return Response(status_code=404)

    return Response(
        content=row[0],
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/api/overlay/tts/played")
async def tts_played(request: Request):
    """Overlay → mark message played после speechSynthesis.onend.

    Body: {"id": int, "channel_id": int}
    Скоуп по channel_id — иначе overlay чужого канала может пометить
    played'нутым (и тем самым «проглотить») TTS этого канала.
    """
    data = await request.json()
    try:
        msg_id = int(data.get("id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверный id"}
    if msg_id <= 0:
        return {"success": False, "message": "id обязателен"}
    try:
        channel_id = int(data.get("channel_id", 0))
    except (TypeError, ValueError):
        channel_id = 0
    if channel_id <= 0:
        channel_id = resolve_channel_id_or_default()

    # A2 (2026-07-02): мутацию гейтим overlay-токеном (id+channel_id публичны →
    # без токена грифер гасил бы платное TTS). Токен в URL OBS-оверлея.
    from routes.streamer import verify_overlay_token  # lazy import: avoid cycle
    if not verify_overlay_token(channel_id, (data.get("overlay_token") or "").strip()):
        return {"success": False, "message": "overlay token invalid"}

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE tts_messages "
            "SET status = 'played', played_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND channel_id = ? AND status = 'pending'",
            (msg_id, channel_id)
        )
        await conn.commit()
        updated = cur.rowcount

    return {"success": True, "updated": updated}
