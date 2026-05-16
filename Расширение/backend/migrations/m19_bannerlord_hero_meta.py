"""
Migration M19: extend bannerlord_heroes с level/clan_name/kingdom_name.

Sprint после 5.1c — UI хочет показывать viewer'у:
  • Уровень его героя (Hero.Level)
  • Клан, в котором состоит (Hero.Clan.Name; "не вступил" если null)
  • Королевство (Hero.Clan.Kingdom.Name; "не вступил" если null)

Mod пушит эти поля через `player.state_update` event (расширен в Sprint).
Adapter применяет dynamic UPDATE если field в whitelist'е.

Schema:
  level         INTEGER DEFAULT 1  — уровень героя (1+)
  clan_name     TEXT NULL          — название клана (NULL = не в клане)
  kingdom_name  TEXT NULL          — название королевства (NULL = независимый)

Идемпотентно: PRAGMA table_info чек перед каждым ADD COLUMN +
migrations_applied['M19.bannerlord_hero_meta'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M19.bannerlord_hero_meta"):
        return

    # SQLite ADD COLUMN не atomic-multiple — каждая ALTER отдельно.
    # Check existing columns чтобы не fail на повторных запусках (если
    # migrations_applied row пропал но колонки уже есть).
    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    existing_cols = {row[1] for row in await cur.fetchall()}

    if "level" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN level INTEGER DEFAULT 1"
        )
    if "clan_name" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN clan_name TEXT"
        )
    if "kingdom_name" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN kingdom_name TEXT"
        )

    await conn.commit()
    await _mark_applied(conn, "M19.bannerlord_hero_meta")
    print("M19: bannerlord_heroes extended (level, clan_name, kingdom_name)")


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
