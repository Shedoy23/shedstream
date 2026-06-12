"""
Migration M72 — feature_usage: лёгкий счётчик использования фич (ROADMAP 2.3).

Per-(channel, feature, day) счётчик. Инкрементится feature_usage.record_feature_use()
в точках диспетчеризации действий (старт — bannerlord buy_action). Нужен чтобы
решения «что развивать / что заморозить» шли от данных (правило «фича входит —
фича выходит»), а не от наития.

Backfill истории из module_actions (bannerlord-действия с created_at) — чтобы
топ/анти-топ был наполнен сразу, а не с нуля.

Идемпотентно: маркер M72.feature_usage.
"""

SCHEMA = """
    channel_id   INTEGER NOT NULL,
    feature_key  TEXT NOT NULL,        -- 'bannerlord:hero.set_class', 'rimworld:create-pawn', ...
    day          TEXT NOT NULL,         -- 'YYYY-MM-DD' (UTC)
    count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, feature_key, day)
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M72.feature_usage"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS feature_usage ({SCHEMA})")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feature_usage_day "
        "ON feature_usage(channel_id, day)")

    # Backfill из module_actions (bannerlord). Best-effort: если таблицы нет или
    # схема иная — стартуем с нуля, не падаем.
    backfilled = 0
    try:
        cur = await conn.execute("""
            INSERT INTO feature_usage (channel_id, feature_key, day, count)
            SELECT channel_id, 'bannerlord:' || type, date(created_at), COUNT(*)
            FROM module_actions
            WHERE module_id = 'bannerlord' AND created_at IS NOT NULL
            GROUP BY channel_id, type, date(created_at)
            ON CONFLICT(channel_id, feature_key, day)
            DO UPDATE SET count = excluded.count
        """)
        backfilled = cur.rowcount
    except Exception as e:
        print(f"⚠️ M72 backfill из module_actions пропущен: {e}")

    await conn.commit()
    await _mark_applied(conn, "M72.feature_usage")
    print(f"M72: feature_usage table created (+{backfilled} backfilled rows)")


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
