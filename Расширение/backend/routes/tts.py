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

  Streamer (session cookie, M102 — модерация UGC):
    GET  /api/streamer/tts/queue     — очередь + история последних
    POST /api/streamer/tts/hide      — скрыть сообщение (остаётся в истории)
    POST /api/streamer/tts/block     — заблокировать/разблокировать зрителя

Compliance:
  • Crystal-burn (no real $) — §5.2 OK.
  • **Модерация (M102, 2026-07-29).** Раньше здесь стояло «без модерации текста
    (per решение)» — для UGC это не проходит: Twitch требует у расширений с
    пользовательским контентом удаление, блокировку автора и историю, иначе
    одобрение затягивается. Теперь есть: блок-лист зрителей (отказ ДО оплаты),
    скрытие сообщения из очереди с сохранением в истории, кто и когда скрыл.
  • **Чего ещё нет:** синхронизации с банами канала Twitch и AutoMod-проверки —
    для них нужен scope `moderation:read`, которого у токенов нет; его
    добавление потребует повторной авторизации от каждого стримера.
    Решение владельца отдельно, см. DEFERRED.
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


# ─── Модерация (M102) ────────────────────────────────────────────────────────

async def is_tts_blocked(db, channel_id: int, username: str) -> bool:
    """Заблокирован ли зритель для озвучки на этом канале.

    Общая точка для эндпоинта и теста. Отдельная от Twitch-банов: наши права
    не позволяют читать баны канала (нужен scope `moderation:read`), поэтому
    это собственный список стримера.
    """
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM tts_blocked_users "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        return await cur.fetchone() is not None


async def hide_tts_message(db, channel_id: int, msg_id: int, by: str) -> bool:
    """Убрать сообщение из очереди озвучки, сохранив его в истории.

    Возвращает True, если что-то реально скрыли. Идемпотентно: повторный вызов
    вернёт False, а не «скрыл ещё раз».
    """
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE tts_messages "
            "SET moderated_by=?, moderated_at=CURRENT_TIMESTAMP "
            "WHERE channel_id=? AND id=? AND moderated_by IS NULL",
            (by, channel_id, msg_id))
        affected = cur.rowcount
        await conn.commit()
    return affected > 0


async def next_pending_for_overlay(db, channel_id: int):
    """Следующее сообщение для оверлея, или None.

    Общая точка для эндпоинта и теста — чтобы тест проверял ТОТ ЖЕ запрос,
    который реально обслуживает оверлей, а не свою копию.
    """
    async with db._connect() as conn:
        cur = await conn.execute(
            # Скрытое модерацией сообщение остаётся в истории, но не звучит.
            # Статус не меняем — у таблицы жёсткий CHECK на два значения.
            "SELECT id, username, message, created_at "
            "FROM tts_messages "
            "WHERE channel_id = ? AND status = 'pending' "
            "  AND moderated_by IS NULL "
            "ORDER BY created_at ASC LIMIT 1",
            (channel_id,))
        return await cur.fetchone()


async def set_tts_block(db, channel_id: int, username: str, blocked: bool,
                        by: str = "", reason: str = "") -> None:
    """Включить/снять блокировку озвучки для зрителя."""
    async with db._connect() as conn:
        if blocked:
            await conn.execute(
                "INSERT OR REPLACE INTO tts_blocked_users "
                "(channel_id, username, blocked_by, reason) VALUES (?, ?, ?, ?)",
                (channel_id, username, by, reason))
        else:
            await conn.execute(
                "DELETE FROM tts_blocked_users WHERE channel_id=? AND username=?",
                (channel_id, username))
        await conn.commit()


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

    # Модерация (M102): заблокированный стримером зритель не озвучивается.
    # Проверка ДО оплаты — отказ не должен стоить крустиков.
    if await is_tts_blocked(db, channel_id, username):
        return {
            "success": False,
            "message": "🔇 Стример отключил тебе озвучку",
        }

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

    # Debit + queue — атомарно в одной транзакции, с ПОВТОРНОЙ проверкой кулдауна
    # внутри неё: TOCTOU-фикс (два параллельных запроса иначе оба проходят ранний
    # чек и оба списывают) + debit-without-effect (списание и INSERT — одна tx).
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT (strftime('%s','now') - strftime('%s', created_at)) "
                "FROM tts_messages WHERE username = ? AND channel_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (username, channel_id))
            crow = await cur.fetchone()
            if crow and crow[0] is not None and crow[0] < TTS_COOLDOWN_S:
                await conn.execute("ROLLBACK")
                remaining = TTS_COOLDOWN_S - int(crow[0])
                return {"success": False, "message": f"⏳ Подожди ещё {remaining}s"}
            if not await db.remove_points_tx(conn, username, TTS_COST, channel_id):
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Не удалось списать"}
            await conn.execute(
                "INSERT INTO tts_messages "
                "(channel_id, username, message, cost, audio_data) "
                "VALUES (?, ?, ?, ?, ?)",
                (channel_id, username, message, TTS_COST, audio_bytes)
            )
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

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
    row = await next_pending_for_overlay(db, channel_id)

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


# ─── Эндпоинты модерации для дашборда стримера (M102) ────────────────────────
#
# Авторизация — та же session cookie, что у остальных /api/streamer/*
# (стример прошёл OAuth через /streamer). Не JWT зрителя: это действия
# владельца канала над чужим контентом.


@router.get("/api/streamer/tts/queue")
async def streamer_tts_queue(request: Request):
    """Очередь озвучки + последняя история. Для дашборда."""
    from routes.bannerlord_admin import _require_streamer_session
    ok, channel_id, msg = _require_streamer_session(request)
    if not ok:
        return {"success": False, "message": msg}

    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, username, message, status, created_at, moderated_by "
            "FROM tts_messages WHERE channel_id=? "
            "ORDER BY created_at DESC LIMIT 50",
            (channel_id,))
        rows = await cur.fetchall()
        cur = await conn.execute(
            "SELECT username, reason, blocked_at FROM tts_blocked_users "
            "WHERE channel_id=? ORDER BY blocked_at DESC",
            (channel_id,))
        blocked = await cur.fetchall()

    return {
        "success": True,
        "messages": [
            {"id": r[0], "username": r[1], "text": r[2], "status": r[3],
             "created_at": r[4], "hidden_by": r[5]}
            for r in rows
        ],
        "blocked": [
            {"username": b[0], "reason": b[1], "blocked_at": b[2]}
            for b in blocked
        ],
    }


@router.post("/api/streamer/tts/hide")
async def streamer_tts_hide(request: Request):
    """Убрать сообщение из очереди. В истории оно остаётся — Twitch требует
    хранить историю UGC, а не стирать её."""
    from routes.bannerlord_admin import _require_streamer_session
    ok, channel_id, msg = _require_streamer_session(request)
    if not ok:
        return {"success": False, "message": msg}

    body = await request.json()
    try:
        msg_id = int(body.get("id") or 0)
    except (TypeError, ValueError):
        msg_id = 0
    if msg_id <= 0:
        return {"success": False, "message": "Нужен id сообщения"}

    hidden = await hide_tts_message(get_db(), channel_id, msg_id,
                                    by=str(channel_id))
    return {
        "success": True,
        "hidden": hidden,
        "message": "Сообщение скрыто" if hidden else "Уже было скрыто",
    }


@router.post("/api/streamer/tts/block")
async def streamer_tts_block(request: Request):
    """Заблокировать/разблокировать зрителя для озвучки.

    Body: {"username": str, "blocked": bool, "reason": str}
    """
    from routes.bannerlord_admin import _require_streamer_session
    ok, channel_id, msg = _require_streamer_session(request)
    if not ok:
        return {"success": False, "message": msg}

    body = await request.json()
    username = str(body.get("username") or "").strip().lower()
    if not username:
        return {"success": False, "message": "Нужен username"}
    blocked = bool(body.get("blocked", True))
    reason = str(body.get("reason") or "")[:200]

    await set_tts_block(get_db(), channel_id, username, blocked,
                        by=str(channel_id), reason=reason)
    return {
        "success": True,
        "blocked": blocked,
        "message": f"@{username}: озвучка {'выключена' if blocked else 'включена'}",
    }
