"""
Migration M28: add `is_elite` flag to bannerlord_retinue.

Sprint 5.14: BLT-style elite retinue. Mod использует `culture.EliteBasicTroop`
(vs обычный BasicTroop). Upgrade chain автоматически elite (engine
UpgradeTargets).

UI flag для badge "★ Элит" в extension. Cost 3× обычного (Hero.Gold).

Idempotent через migrations_applied['M28.retinue_elite'] + PRAGMA check.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M28.retinue_elite"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_retinue)")
    cols = {row[1] for row in await cur.fetchall()}
    if "is_elite" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_retinue ADD COLUMN is_elite INTEGER DEFAULT 0"
        )

    await conn.commit()
    await _mark_applied(conn, "M28.retinue_elite")
    print("M28: bannerlord_retinue.is_elite column added")


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
