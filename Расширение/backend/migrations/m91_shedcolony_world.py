"""
Migration M91: shedcolony — текущий мир канала (world-switch detection).

shedcolony_world — один world_id на канал (имя уровня + сид, шлёт мод в snapshot/capacity).
Корень проблемы (2026-07-03): colony_id=1 в КАЖДОМ мире MineColonies → соло-мир и сервер
неразличимы → стейт прошлого мира залипал в расширении. Теперь смена world_id = авто-сброс
(линки → dead, стейт/цели/вакансии → wipe) в ShedColonyAdapter._check_world_switch.
Аддитивно. Idempotent: migrations_applied['M91.shedcolony_world'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M91.shedcolony_world"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_world (
            channel_id  INTEGER NOT NULL PRIMARY KEY,
            world_id    TEXT    NOT NULL,
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M91.shedcolony_world")
    print("M91: shedcolony_world created")


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
