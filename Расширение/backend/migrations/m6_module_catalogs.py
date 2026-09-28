"""
Migration m6_module_catalogs: generic catalog storage для Module API
(этап 3 step 4).

Module connector публикует свой каталог через `module.catalog_update`
event (см. docs/MODULE_API.md §9). Каталог = набор entries (shop items,
events, и пр.). Per MULTITENANT_PLAN.md §H — session-scoped: при
`module.session_start` каталоги канала очищаются, мод заново публикует
актуальные.

Таблица — generic, не привязана к RimWorld-specific схеме (которая
живёт в shop_catalog / rimworld_event_catalog). Когда Step 5/6 wrapper
migration перепишет legacy /api/rimworld/catalog/* — они начнут читать
эту таблицу. До тех пор две схемы существуют параллельно.

Идемпотентно через `migrations_applied['M6.module_catalogs.create']`.
"""


SCHEMA = """
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL,
    module_id    TEXT NOT NULL,
    catalog_type TEXT NOT NULL,        -- 'shop' | 'events' | future
    entry_id     TEXT NOT NULL,        -- opaque ID от мода (item def_name,
                                       -- event def_name, etc.) — уникален в
                                       -- рамках (channel, module, catalog_type)
    payload      TEXT NOT NULL,        -- JSON-сериализованный полный entry
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel_id, module_id, catalog_type, entry_id)
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M6.module_catalogs.create"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS module_catalogs ({SCHEMA})")
    # Index для list-all SELECT'а (frontend читает целый каталог).
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_module_catalogs_lookup
        ON module_catalogs(channel_id, module_id, catalog_type)
    """)
    await conn.commit()
    print("✅ M6: module_catalogs table + index created")

    await _mark_applied(conn, "M6.module_catalogs.create")


async def _ensure_migrations_table(conn) -> None:
    """Defensive duplicate (создаётся в M1/M4/M5)."""
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
