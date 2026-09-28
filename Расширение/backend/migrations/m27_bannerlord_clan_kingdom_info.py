"""
Migration M27: add clan_info_json + kingdom_info_json TEXT columns
to bannerlord_heroes.

Sprint 5.11: Mod пушит structured clan/kingdom info (leader, members,
tier, renown, fiefs, ...) в HeroStateSync. Backend хранит как JSON,
frontend читает в clan/kingdom модалах.

Idempotent через migrations_applied['M27.clan_kingdom_info'] + PRAGMA check.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M27.clan_kingdom_info"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    cols = {row[1] for row in await cur.fetchall()}

    if "clan_info_json" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN clan_info_json TEXT"
        )
    if "kingdom_info_json" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN kingdom_info_json TEXT"
        )

    await conn.commit()
    await _mark_applied(conn, "M27.clan_kingdom_info")
    print("M27: clan_info_json + kingdom_info_json columns added")


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
