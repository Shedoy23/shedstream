"""
Migration M51 — Rolled stats для custom items (BLT-parity TOP-3).

Sprint 5.33 — раньше custom_items были чисто decorative (имя + rarity + tier,
никаких stat bonuses). После M51:

  damage_bonus  INT NOT NULL DEFAULT 0   — bonus к outgoing damage (weapon)
  armor_bonus   INT NOT NULL DEFAULT 0   — bonus к incoming damage absorption (armor)
  weight_factor REAL NOT NULL DEFAULT 1.0 — multiplier (lighter armor → speed)
  speed_factor  REAL NOT NULL DEFAULT 1.0 — multiplier movement speed (horse)

Rolls per rarity (handled в _generate_item):
  common    +1-3  / 0.95-1.05 factors
  uncommon  +3-6  / 0.92-1.08
  rare      +6-10 / 0.88-1.12
  epic      +10-15 / 0.85-1.15
  legendary +15-25 / 0.80-1.20

Existing rows получают DEFAULT 0/1.0 — decoration backward-compat.

Idempotent через PRAGMA table_info check.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M51.custom_item_stats"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_custom_items)")
    cols = {row[1] for row in await cur.fetchall()}

    if "damage_bonus" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items "
            "ADD COLUMN damage_bonus INTEGER NOT NULL DEFAULT 0")
    if "armor_bonus" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items "
            "ADD COLUMN armor_bonus INTEGER NOT NULL DEFAULT 0")
    if "weight_factor" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items "
            "ADD COLUMN weight_factor REAL NOT NULL DEFAULT 1.0")
    if "speed_factor" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_custom_items "
            "ADD COLUMN speed_factor REAL NOT NULL DEFAULT 1.0")

    print(f"M51: custom_items stats columns added "
          f"(damage_bonus/armor_bonus/weight_factor/speed_factor)")

    await conn.commit()
    await _mark_applied(conn, "M51.custom_item_stats")


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
