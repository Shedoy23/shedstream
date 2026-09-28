"""
Migration M16: Bannerlord class passive powers (Sprint 4.2).

Per-class power scaling table. Mod при agent build applies все powers
текущего класса hero'я на levels 1/2/3.

Power types (vanilla 1.3.x):
  hp_multiplier        — *X multiplier на BaseHealthLimit
  athletic_skill_boost — +N к Athletics skill
  body_scale           — *X на agent body size
  armor_bypass_pct     — % damage bypass armor
  damage_reflect_pct   — % incoming damage reflected
  ignore_armor_pct     — % armor ignored на melee hit

Schema:
  bannerlord_class_powers — per (class_key, power_key)
    columns: lvl1_value REAL, lvl2_value REAL, lvl3_value REAL

Идемпотентно через migrations_applied['M16.bannerlord_class_powers'].
"""

# Seed: 13 classes × 3-4 powers each (level scaling 1/2/3).
# Power names НАШИ (rebrand перед public release per compliance discussion).
# Values тоже чуть другие vs BLT (110/130/160 vs 120/135/160 etc.) —
# differentiation, не точная mirror.
BANNERLORD_CLASS_POWERS_SEED = [
    # (class_key, power_key, lvl1, lvl2, lvl3)
    # === TANK — крепкий пехотинец ===
    ("tank", "hp_multiplier",     1.15, 1.30, 1.50),
    ("tank", "athletic_skill_boost", 10,   25,   45),
    ("tank", "ignore_armor_pct",   10,   25,   40),
    ("tank", "body_scale",         1.15, 1.15, 1.15),

    # === ARCHER — стандартный лучник ===
    ("archer", "hp_multiplier",     0.95, 1.05, 1.15),
    ("archer", "bow_skill_boost",   20,   40,   70),

    # === HEAVY_ARCHER — лучник в броне ===
    ("heavy_archer", "hp_multiplier",     1.10, 1.20, 1.35),
    ("heavy_archer", "bow_skill_boost",   15,   30,   50),

    # === CROSSBOW — арбалетчик ===
    ("crossbow", "crossbow_skill_boost", 25,   50,   80),
    ("crossbow", "armor_bypass_pct",     10,   20,   35),

    # === HEAVY_CROSSBOW ===
    ("heavy_crossbow", "hp_multiplier",         1.10, 1.20, 1.35),
    ("heavy_crossbow", "crossbow_skill_boost",  20,   40,   65),

    # === CAVALRY ===
    ("cavalry", "riding_skill_boost", 25,   50,   80),
    ("cavalry", "hp_multiplier",      1.05, 1.15, 1.25),

    # === CAMEL_CAVALRY ===
    ("camel_cavalry", "riding_skill_boost", 25,   50,   80),
    ("camel_cavalry", "hp_multiplier",      1.05, 1.15, 1.25),

    # === HORSE_ARCHER ===
    ("horse_archer", "bow_skill_boost",    20,   40,   65),
    ("horse_archer", "riding_skill_boost", 20,   40,   65),

    # === CAMEL_ARCHER ===
    ("camel_archer", "bow_skill_boost",    20,   40,   65),
    ("camel_archer", "riding_skill_boost", 20,   40,   65),

    # === PSYCHO — двуручник без брони ===
    ("psycho", "hp_multiplier",       0.70, 0.70, 0.70),  # хрупкий
    ("psycho", "two_handed_skill_boost", 30,   60,   100),
    ("psycho", "damage_reflect_pct",  10,   25,   40),

    # === BERSERK — два двуручных ===
    ("berserk", "hp_multiplier",         0.90, 1.00, 1.15),
    ("berserk", "two_handed_skill_boost", 25,   50,   80),
    ("berserk", "ignore_armor_pct",      15,   30,   50),

    # === ASSASSIN — лёгкий dual-wield ===
    ("assassin", "hp_multiplier",         0.85, 0.95, 1.05),
    ("assassin", "one_handed_skill_boost", 25,   50,   80),
    ("assassin", "throwing_skill_boost",   20,   40,   65),
    ("assassin", "body_scale",            0.92, 0.92, 0.92),

    # === KNIGHT ===
    ("knight", "hp_multiplier",        1.20, 1.30, 1.50),
    ("knight", "polearm_skill_boost",  20,   40,   65),
    ("knight", "ignore_armor_pct",     10,   20,   35),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M16.bannerlord_class_powers"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_class_powers (
            class_key   TEXT NOT NULL,
            power_key   TEXT NOT NULL,
            lvl1_value  REAL NOT NULL,
            lvl2_value  REAL NOT NULL,
            lvl3_value  REAL NOT NULL,
            PRIMARY KEY (class_key, power_key)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_class_powers_lookup
            ON bannerlord_class_powers(class_key)
    """)

    for row in BANNERLORD_CLASS_POWERS_SEED:
        ck, pk, v1, v2, v3 = row
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (ck, pk, v1, v2, v3)
        )

    await conn.commit()
    await _mark_applied(conn, "M16.bannerlord_class_powers")
    print(f"✅ M16: bannerlord_class_powers seeded ({len(BANNERLORD_CLASS_POWERS_SEED)} entries)")


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
