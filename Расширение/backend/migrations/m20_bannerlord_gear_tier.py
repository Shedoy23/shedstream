"""
Migration M20: bannerlord_heroes.gear_tier — 6-tier equipment progression.

Sprint после M19. Зрители прокачивают экипировку через `!снаряга` /
extension button: tier 0 (стартовая wanderer-snar) → 1 → 2 → ... → 6.
Каждый upgrade replace'ит slot items на random item того же ItemType
с матчем `ItemObject.Tier == gear_tier - 1` (engine tiers 0-5 ↔ user-facing 1-6).

Цены прогрессивные, чтобы tier 6 требовал серьёзного гринда крустиков.
Стоимость зашита в backend (TIER_COSTS) — server-side enforced, viewer
не может купить за бесплатно (см. routes/bannerlord.py).

BLT inspired (EquipHero.cs CostTier1-6: 25k/50k/100k/175k/275k/400k dinars).
У нас крустики, не dinars — цены отдельные.

Schema:
  gear_tier INTEGER DEFAULT 0  — 0 = базовый wanderer snar (не upgraded);
                                  1-6 = current tier через upgrade

Идемпотентно через PRAGMA + migrations_applied['M20.bannerlord_gear_tier'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M20.bannerlord_gear_tier"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    existing_cols = {row[1] for row in await cur.fetchall()}

    if "gear_tier" not in existing_cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN gear_tier INTEGER DEFAULT 0"
        )

    await conn.commit()
    await _mark_applied(conn, "M20.bannerlord_gear_tier")
    print("M20: bannerlord_heroes.gear_tier added (default 0)")


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
