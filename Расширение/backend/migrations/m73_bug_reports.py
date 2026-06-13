"""
Migration M73 — bug_reports: багрепорты от зрителей через чат-команду !баг.

Зритель пишет `!баг <текст>` (или `!bug`) в чате канала → бот сохраняет сюда
(scoped по channel_id, мультитенант) и отвечает в чат. Стример читает в дашборде
(карточка «🐞 Баг-репорты»), помечает open/resolved.

Идемпотентно: маркер M73.bug_reports. Новая фича — backfill не нужен.
"""

SCHEMA = """
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id  INTEGER NOT NULL,
    username    TEXT NOT NULL,
    message     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M73.bug_reports"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS bug_reports ({SCHEMA})")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bug_reports_channel "
        "ON bug_reports(channel_id, created_at DESC)")

    await conn.commit()
    await _mark_applied(conn, "M73.bug_reports")
    print("M73: bug_reports table created")


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
