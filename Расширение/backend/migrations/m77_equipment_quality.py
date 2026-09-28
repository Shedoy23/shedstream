"""
Migration M77: bannerlord_equipment — quality колонка.

2026-06-15 «Кузница» (перековка качества). Раньше table не хранила качество
предмета (ItemModifier), поэтому фронт не мог показать, какие предметы уже
топовые, а какие стоит перековать. Mod теперь пушит в hero.equipment_changed
поле `quality`:
  • один из: poor / inferior / common / fine / masterwork / legendary
  • NULL  — у предмета нет модификатора (базовое качество)

Фронт рисует бейдж качества в Экипировке и в Кузнице.

Idempotent через PRAGMA + migrations_applied['M77.equipment_quality'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M77.equipment_quality"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_equipment)")
    existing_cols = {row[1] for row in await cur.fetchall()}

    if "quality" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_equipment ADD COLUMN quality TEXT"
        )

    await conn.commit()
    await _mark_applied(conn, "M77.equipment_quality")
    print("M77: bannerlord_equipment extended (quality)")


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
