"""
Migration M60 — Inventory unification (Phase B).

Сводим турнир + кузницу в ОДИН инвентарь (bannerlord_custom_items) и
добавляем UX-состояние:
  source  TEXT DEFAULT 'forge'   — откуда предмет: 'forge' | 'tournament'
  claimed INTEGER DEFAULT 0      — 1 если уже «получен в игре» (equip_trophy)

Authority напоминание (ARCH-1): сам реальный предмет живёт в игре (ItemRoster
героя после equip_trophy). Эта таблица — коллекция/витрина + источник payload
для моста equip_trophy. claimed=1 предотвращает повторную выдачу (double bonus).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M60.custom_items_source"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_custom_items)")
    existing = {row[1] for row in await cur.fetchall()}
    if "source" not in existing:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items ADD COLUMN source TEXT DEFAULT 'forge'")
    if "claimed" not in existing:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items ADD COLUMN claimed INTEGER DEFAULT 0")
    print("M60: bannerlord_custom_items.source/claimed added")

    await conn.commit()
    await _mark_applied(conn, "M60.custom_items_source")


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
