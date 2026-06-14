"""
Migration M75 — watch_streaks: статистика серий просмотров (watch streaks).

Twitch автоматически награждает зрителя баллами канала за просмотр N стримов
подряд («смотрит 50-й стрим подряд»). EventSub channel.chat.notification с
notice_type='watch_streak' отдаёт ник + streak_count + начисленные баллы.
Бот молча пишет это сюда (scoped по channel_id) — НЕ спамит в чат. Стример
смотрит лидерборд лояльности в дашборде (кто смотрит дольше всех подряд).

Пассивная аналитика — наград/геймплея зрителям не даёт (Twitch ToS OK).

Upsert по (channel_id, username): streak_count = последний (текущая серия),
best_streak = максимум за всё время, total_points = сумма начисленных баллов.

Идемпотентно: маркер M75.watch_streaks. Новая фича — backfill не нужен.
"""

SCHEMA = """
    channel_id     INTEGER NOT NULL,
    username       TEXT NOT NULL,
    streak_count   INTEGER NOT NULL DEFAULT 0,   -- текущая серия (последняя)
    best_streak    INTEGER NOT NULL DEFAULT 0,   -- максимум за всё время
    total_points   INTEGER NOT NULL DEFAULT 0,   -- сумма начисленных баллов
    last_streak_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id, username)
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M75.watch_streaks"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS watch_streaks ({SCHEMA})")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_watch_streaks_board "
        "ON watch_streaks(channel_id, streak_count DESC)")

    await conn.commit()
    await _mark_applied(conn, "M75.watch_streaks")
    print("M75: watch_streaks table created")


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
