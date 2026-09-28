"""
Migration M36: Bannerlord hero family info (Sprint 5.27c, 2026-05-21).

ALTER bannerlord_heroes add:
  • is_female INTEGER (0 male / 1 female / NULL unknown)
  • family_info_json TEXT — JSON {spouse, children[], father, mother, sibling_count}

Mod synca эту info через HeroStateSync (BuildFamilyInfo).

Идемпотентно: ALTER ADD COLUMN в try/except (повтор миграции = column
уже есть → silent skip).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M36.bannerlord_family"):
        return

    for col_def in [
        "is_female INTEGER",
        "family_info_json TEXT",
    ]:
        try:
            col_name = col_def.split(" ", 1)[0]
            await conn.execute(
                f"ALTER TABLE bannerlord_heroes ADD COLUMN {col_def}")
        except Exception:
            pass  # already exists

    await conn.commit()
    await _mark_applied(conn, "M36.bannerlord_family")
    print("✅ M36: bannerlord_heroes + is_female + family_info_json")


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
