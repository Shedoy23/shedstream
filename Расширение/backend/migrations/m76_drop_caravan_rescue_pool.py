"""
Migration M76 — drop caravan rescue-pool table.

Фича «спасение уничтоженного каравана» (crowd-fund rescue pool) удалена:
уничтоженный караван теперь просто исчезает (DELETE), слот владельца
освобождается, зритель создаёт новый. Таблица bannerlord_caravan_rescue_pool
больше не используется → дропаем.

Идемпотентно: маркер M76.drop_caravan_rescue_pool. DROP TABLE IF EXISTS —
безопасно на свежих БД (где таблицы и не было).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M76.drop_caravan_rescue_pool"):
        return

    await conn.execute("DROP TABLE IF EXISTS bannerlord_caravan_rescue_pool")

    await conn.commit()
    await _mark_applied(conn, "M76.drop_caravan_rescue_pool")
    print("M76: bannerlord_caravan_rescue_pool table dropped")


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
