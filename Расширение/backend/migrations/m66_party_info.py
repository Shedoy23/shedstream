"""
Migration M66 — party_info_json column on bannerlord_heroes.

Мод (HeroStateSync.BuildPartyInfo) пушит инфо об отряде зрителя на карте
(size / текущая задача движка DefaultBehavior / цель / в армии) внутри
player.state_update. Backend хранит как JSON (как clan_info/kingdom_info/
family_info), фронт показывает в секции «Приказы отряда».
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M66.party_info"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    existing = {row[1] for row in await cur.fetchall()}
    if "party_info_json" not in existing:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN party_info_json TEXT")
    print("M66: bannerlord_heroes.party_info_json added")

    await conn.commit()
    await _mark_applied(conn, "M66.party_info")


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
