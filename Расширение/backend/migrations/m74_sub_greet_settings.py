"""
Migration M74 — channel_greet_settings: per-channel toggle бота-приветствия
в чате для подписок И фолловов (раздельно).

Бот пишет ТЕКСТОВОЕ приветствие в чат при:
  - подписке / ресабе / подарке  → sub_enabled
    (EventSub channel.subscribe / channel.subscription.message / .gift)
  - новом фолловере               → follow_enabled
    (EventSub channel.follow v2)

БЕЗ выдачи крустиков/динаров/наград — только текст (Twitch ToS §5.2: никаких
gameplay-привилегий за саб; sub-бонусы мы уже вырезали ранее). Два раздельных
флага: фолловы спамнее сабов (фолоу-боты), стример может выключить именно их,
не трогая приветствие подписчиков.

Default ON для обоих — новый канал приветствует сразу, без backfill.

Идемпотентно: маркер M74.greet_settings.
"""

SCHEMA = """
    channel_id     INTEGER PRIMARY KEY,
    sub_enabled    INTEGER NOT NULL DEFAULT 1,
    follow_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M74.greet_settings"):
        return

    await conn.execute(
        f"CREATE TABLE IF NOT EXISTS channel_greet_settings ({SCHEMA})")

    await conn.commit()
    await _mark_applied(conn, "M74.greet_settings")
    print("M74: channel_greet_settings table created")


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
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
    await conn.commit()
