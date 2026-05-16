"""
Migration M21: bannerlord_equipment — stats payload per item.

Раньше table хранила только item_id + item_name. Теперь mod пушит
extended hero.equipment_changed event со stats:
  • tier        — ItemObject.Tier (0-5 → user-facing T1-T6)
  • item_value  — base game price (для display)
  • weight      — вес item'a
  • stats_json  — TEXT с per-type stats:
      weapon: {swing_dmg, swing_spd, thrust_dmg, thrust_spd, length,
               swing_type, thrust_type, accuracy, missile_spd, stack}
      armor:  {head, body, leg, arm}
      horse:  {speed, charge, maneuver, hp}
      shield/other → пустой объект {}

Idempotent через PRAGMA + migrations_applied['M21.equipment_stats'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M21.equipment_stats"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_equipment)")
    existing_cols = {row[1] for row in await cur.fetchall()}

    if "tier" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_equipment ADD COLUMN tier INTEGER"
        )
    if "item_value" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_equipment ADD COLUMN item_value INTEGER"
        )
    if "weight" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_equipment ADD COLUMN weight REAL"
        )
    if "stats_json" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_equipment ADD COLUMN stats_json TEXT"
        )

    await conn.commit()
    await _mark_applied(conn, "M21.equipment_stats")
    print("M21: bannerlord_equipment extended (tier, item_value, weight, stats_json)")


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
