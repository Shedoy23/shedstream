"""
Migration M38: add `iteration` column to bannerlord_heroes.

Sprint 5.29 / BLT-parity #7 — heir succession on hero death.
Когда viewer'у убивают героя, мы increment'им iteration. Frontend показывает
"Поколение N" в profile + "Возрождение героя" button → новый wanderer с тем
же username (iteration N+1).

Default 1 для существующих rows. Idempotent через migrations_applied table.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M38.hero_iteration"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    cols = {row[1] for row in await cur.fetchall()}

    if "iteration" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN iteration INTEGER NOT NULL DEFAULT 1"
        )

    await conn.commit()
    await _mark_applied(conn, "M38.hero_iteration")
    print("M38: bannerlord_heroes.iteration column added (default=1)")


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
