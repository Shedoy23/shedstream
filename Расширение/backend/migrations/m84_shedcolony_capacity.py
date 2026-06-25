"""
Migration M84: shedcolony — capacity snapshot tables (для slot-availability UI).

shedcolony_capacity       — свободные слоты по профессиям (мод пушит colony.capacity).
shedcolony_capacity_meta  — колони-уровень: свободные койки.

Мод периодически шлёт снимок → расширение показывает зрителю, какие работы/койки свободны
(серая кнопка, если слота нет). Аддитивно. Idempotent: migrations_applied['M84.shedcolony_capacity'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M84.shedcolony_capacity"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_capacity (
            channel_id   INTEGER NOT NULL,
            job_key      TEXT    NOT NULL,
            free_slots   INTEGER NOT NULL DEFAULT 0,
            total_slots  INTEGER NOT NULL DEFAULT 0,
            updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, job_key)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_capacity_meta (
            channel_id  INTEGER NOT NULL PRIMARY KEY,
            free_beds   INTEGER NOT NULL DEFAULT 0,
            total_beds  INTEGER NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M84.shedcolony_capacity")
    print("M84: shedcolony_capacity + shedcolony_capacity_meta created")


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
