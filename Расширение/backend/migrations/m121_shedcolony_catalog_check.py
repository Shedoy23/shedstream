"""
Migration M121: shedcolony — что из каталога товаров реально существует в сборке.

shedcolony_catalog_check — один JSON-блоб на канал: {"missing": [id, ...],
"checked": N}. Мод сверяет каталог бэкенда с реестром предметов СВОЕЙ сборки и
шлёт отсутствующее (colony.catalog); `/api/shedcolony/config` гасит такие
позиции, и зритель не платит за то, чего в игре нет.

Причина: 05.09 в RimWorld сабля Wolfein собрала 5 покупок по 5520💎 и 0
успехов — товар в каталоге был, в сборке его не было. Здесь тот же класс
закрывается до покупки. Аддитивно. Idempotent: migrations_applied['M121.shedcolony_catalog_check'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M121.shedcolony_catalog_check"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_catalog_check (
            channel_id  INTEGER NOT NULL PRIMARY KEY,
            data        TEXT    NOT NULL DEFAULT '{}',
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M121.shedcolony_catalog_check")
    print("M121: shedcolony_catalog_check created")


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
