"""
Migration M34: tts_messages.audio_data BLOB (Sprint 5.23 fix, 2026-05-21).

После релиза TTS обнаружили что OBS Browser Source (Chromium-CEF) плохо
поддерживает Web Speech API — speechSynthesis.speak() не воспроизводит
аудио надёжно. Переключаемся на серверный TTS через gTTS (Google
Translate TTS, free, ru-RU). gTTS генерирует mp3 на бэке, overlay
играет через <audio> элемент.

Schema change: ADD COLUMN audio_data BLOB к tts_messages. Идемпотентно
через try/except (SQLite ALTER ADD COLUMN не fails на повторе если есть
LANGUAGE-specific guard).

Также drain existing pending messages (без audio_data) — помечаем
played чтобы overlay не застрял на них.

Идемпотентно через migrations_applied['M34.tts_audio_blob'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M34.tts_audio_blob"):
        return

    # ADD COLUMN audio_data (idempotent через try)
    try:
        await conn.execute("ALTER TABLE tts_messages ADD COLUMN audio_data BLOB")
    except Exception:
        # Колонка уже есть (повторный запуск миграции)
        pass

    # Drain pending messages без audio_data — overlay их не сможет сыграть.
    # Marks played to clean up queue. Real users могут заново отправить.
    await conn.execute(
        "UPDATE tts_messages SET status = 'played', "
        "played_at = CURRENT_TIMESTAMP "
        "WHERE status = 'pending' AND audio_data IS NULL"
    )

    await conn.commit()
    await _mark_applied(conn, "M34.tts_audio_blob")
    print("✅ M34: tts_messages.audio_data BLOB + drained legacy pending")


async def _ensure_migrations_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
