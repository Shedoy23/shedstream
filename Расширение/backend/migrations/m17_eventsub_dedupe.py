"""
Migration M17: EventSub message dedupe table (Phase A — security).

Twitch EventSub шлёт каждое событие до 5 раз при 5xx/timeout от нашего callback'а.
Без идемпотентности это даёт двойные начисления (channel_points, future cheer/bits),
ложные TG-нотификации и неверный stream-live-state.

Решение: общая таблица seen-message-id с TTL.

Schema:
  eventsub_seen
    - message_id  (PK)         — Twitch-Eventsub-Message-Id (UUID-формат)
    - channel_id  (broadcaster) — для multi-tenant аналитики
    - event_type               — channel.channel_points_*, stream.online, ...
    - seen_at     (unix ts)    — для TTL-cleanup

  idx_eventsub_seen_seen_at — индекс для batch-delete по TTL

TTL: 24 часа. Twitch retry-окно — 1 час (5 попыток с back-off), 24h это safety
margin. После TTL запись удаляется фоновой задачей в main.py.

Идемпотентность миграции через migrations_applied['M17.eventsub_dedupe'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M17.eventsub_dedupe"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS eventsub_seen (
            message_id  TEXT NOT NULL PRIMARY KEY,
            channel_id  INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            seen_at     REAL NOT NULL
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eventsub_seen_seen_at
            ON eventsub_seen(seen_at)
    """)
    await conn.commit()
    await _mark_applied(conn, "M17.eventsub_dedupe")
    print("✅ M17: eventsub_seen table created (dedupe + TTL index)")


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
