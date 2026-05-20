"""
Migration M26: add `focus` column to bannerlord_skills.

Sprint 5.8: viewer-side focus point investment (BLT-style). Mod пушит
полный snapshot focus values в HeroStateSync.Push, backend UPSERT'ит
сюда. Frontend modal отображает focus stars (F0-F5) per skill.

Schema delta:
  bannerlord_skills.focus INTEGER DEFAULT 0  (range 0-5)

Idempotent через migrations_applied['M26.focus'] + sqlite column check.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M26.focus"):
        return

    # SQLite: ALTER TABLE ADD COLUMN — check first via PRAGMA.
    cur = await conn.execute("PRAGMA table_info(bannerlord_skills)")
    cols = {row[1] for row in await cur.fetchall()}
    if "focus" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_skills ADD COLUMN focus INTEGER DEFAULT 0"
        )

    await conn.commit()
    await _mark_applied(conn, "M26.focus")
    print("M26: bannerlord_skills.focus column added")


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
