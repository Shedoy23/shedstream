"""
Migration M90: shedcolony — colony.targets snapshot table (пикеры Фазы A/B).

shedcolony_targets — один JSON-блоб на канал: доступные исследования + здания с очередью
заказов + статус склада. Мод периодически шлёт colony.targets (full-replace); /capacity
отдаёт блоб фронту → пикеры research/backlog/min-stock показывают реальные цели и серят
недоступное. Аддитивно. Idempotent: migrations_applied['M90.shedcolony_targets'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M90.shedcolony_targets"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_targets (
            channel_id  INTEGER NOT NULL PRIMARY KEY,
            data        TEXT    NOT NULL DEFAULT '{}',
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M90.shedcolony_targets")
    print("M90: shedcolony_targets created")


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
