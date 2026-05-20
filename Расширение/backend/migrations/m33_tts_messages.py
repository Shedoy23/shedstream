"""
Migration M33: TTS messages queue (Sprint 5.23, 2026-05-21).

Зрители платят 5000💎 чтобы их сообщение озвучилось через Web Speech
API на overlay'е стрима. Полный flow:

  POST /api/tts/submit { message }
    → debit крустиков + INSERT pending row
  GET  /api/overlay/tts/pending?channel_id=X
    → возвращает oldest pending для канала
  POST /api/overlay/tts/played { id }
    → SET status='played' (overlay вызывает после speechSynthesis.onend)

Schema:
  id           — auto, для FIFO ordering
  channel_id   — куда озвучить (multi-tenant scope)
  username     — кто прислал (для on-screen «@user: msg»)
  message      — текст до 200 символов
  cost         — сколько списано (audit)
  status       — pending / played
  created_at   — для cooldown логики (стейтлес: SELECT MAX(created_at)
                 WHERE username=? AND created_at > now-30s)
  played_at    — для retention/analytics

Идемпотентно через migrations_applied['M33.tts_messages'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M33.tts_messages"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tts_messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id   INTEGER NOT NULL,
            username     TEXT NOT NULL,
            message      TEXT NOT NULL,
            cost         INTEGER NOT NULL DEFAULT 5000,
            status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'played')),
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            played_at    TIMESTAMP
        )
    """)
    # Index для overlay poll'а: WHERE channel_id=? AND status='pending'
    # ORDER BY created_at ASC LIMIT 1
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tts_pending
            ON tts_messages(channel_id, status, created_at)
            WHERE status = 'pending'
    """)
    # Index для cooldown lookup: WHERE username=? ORDER BY created_at DESC
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tts_by_user
            ON tts_messages(username, created_at DESC)
    """)

    await conn.commit()
    await _mark_applied(conn, "M33.tts_messages")
    print("✅ M33: tts_messages table created")


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
