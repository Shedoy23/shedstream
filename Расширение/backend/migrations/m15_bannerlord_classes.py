"""
Migration M15: Bannerlord classes + viewer→class binding.

Class system (inspired by BLT, clean-room re-implementation per LGPL 2.1):
зрители выбирают «класс» для своего hero — это сразу применяет соответствующее
снаряжение (4 weapon slots + horse/camel) и в будущем pasive/active powers.

Schema:
  bannerlord_classes      — dev-defined catalog (seeded в M15)
                             (class_key PK, name, formation, slots, mount, etc.)
  bannerlord_hero_class   — текущий выбранный класс per (channel_id, username)
                             с уровнем (1/2/3 для passive power scaling)

Идемпотентно через migrations_applied['M15.bannerlord_classes'].
"""

# Seeded class definitions. Mirror C# hardcoded dict в SetClassHandler.
# Slot types — Bannerlord ItemObject.ItemTypeEnum (vanilla 1.3.x):
#   OneHandedWeapon, TwoHandedWeapon, Polearm, Bow, Crossbow,
#   Arrows, Bolts, Thrown, Shield, HorseHarness, Horse, Banner
BANNERLORD_CLASSES_SEED = [
    # (class_key, name, formation, slot1, slot2, slot3, slot4, use_horse, use_camel, description)
    ("tank",         "Танк",            "Infantry",       "OneHandedWeapon", "Shield",          "",                "",          0, 0, "Базовый пехотинец, основа любой армии."),
    ("archer",       "Лучник",          "Ranged",         "OneHandedWeapon", "Arrows",          "Arrows",          "Bow",       0, 0, "Стреляет издалека, два колчана и одноручка для ближнего боя."),
    ("heavy_archer", "Тяжёлый Лучник",  "Ranged",         "TwoHandedWeapon", "Arrows",          "Arrows",          "Bow",       0, 0, "Лучник с двуручным оружием и двойным боезапасом."),
    ("crossbow",     "Арбалетчик",      "Ranged",         "OneHandedWeapon", "Bolts",           "Bolts",           "Crossbow",  0, 0, "Медленнее лучника, но пробивает броню; два колчана + одноручка."),
    ("heavy_crossbow","Тяжёлый Арбалетчик","Ranged",      "TwoHandedWeapon", "Bolts",           "Bolts",           "Crossbow",  0, 0, "Арбалетчик с двуручным оружием и двойным боезапасом."),
    ("cavalry",      "Кавалерия",       "Cavalry",        "OneHandedWeapon", "Polearm",         "Shield",          "",          1, 0, "Стандартная конница."),
    ("camel_cavalry","Верблюжья Кавалерия","Cavalry",     "OneHandedWeapon", "Polearm",         "Shield",          "",          0, 1, "Конница на верблюдах (Асерай-стиль)."),
    ("horse_archer", "Конный Лучник",   "HorseArcher",    "Bow",             "Arrows",          "OneHandedWeapon", "Arrows",    1, 0, "Степной лучник верхом, два колчана."),
    ("camel_archer", "Верблюжий Лучник","HorseArcher",    "Bow",             "Arrows",          "OneHandedWeapon", "Arrows",    0, 1, "Конный лучник на верблюде, два колчана."),
    ("psycho",       "Психопат",        "Infantry",       "TwoHandedWeapon", "Thrown",          "Thrown",          "",          0, 0, "Двуручник без брони с двумя наборами метательных — глубокая ярость."),
    ("berserk",      "Берсерк",         "Infantry",       "TwoHandedWeapon", "TwoHandedWeapon", "",                "",          0, 0, "Два двуручных оружия — высокий урон."),
    ("assassin",     "Убийца",          "Infantry",       "OneHandedWeapon", "OneHandedWeapon", "Thrown",          "",          0, 0, "Кинжалы + метательные ножи."),
    ("knight",       "Рыцарь",          "Cavalry",        "OneHandedWeapon", "Shield",          "Polearm",         "",          1, 0, "Тяжёлая конница с щитом, копьём и мечом."),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M15.bannerlord_classes"):
        return

    # ── bannerlord_classes (catalog) ──────────────────────────────────────────
    # Dev-defined, immutable после release (только deprecate, не delete —
    # иначе сломаются hero_class refs). Pattern зеркал pet_catalog (M13).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_classes (
            class_key    TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            formation    TEXT NOT NULL,
            slot1        TEXT,                -- ItemTypeEnum (vanilla 1.3.x)
            slot2        TEXT,
            slot3        TEXT,
            slot4        TEXT,
            use_horse    INTEGER NOT NULL DEFAULT 0,
            use_camel    INTEGER NOT NULL DEFAULT 0,
            description  TEXT,
            deprecated   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for row in BANNERLORD_CLASSES_SEED:
        ck, name, formation, s1, s2, s3, s4, horse, camel, descr = row
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_classes "
            "(class_key, name, formation, slot1, slot2, slot3, slot4, use_horse, use_camel, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ck, name, formation, s1, s2, s3, s4, horse, camel, descr)
        )

    # ── bannerlord_hero_class (current class per viewer) ──────────────────────
    # Composite PK (channel_id, username). hero_class_level = 1/2/3 для
    # scaling passive powers (Sprint 4.2+). class_key FK → bannerlord_classes.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_hero_class (
            channel_id      INTEGER NOT NULL,
            username        TEXT NOT NULL,
            class_key       TEXT NOT NULL,
            class_level     INTEGER NOT NULL DEFAULT 1,
            chosen_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username),
            FOREIGN KEY (class_key) REFERENCES bannerlord_classes(class_key)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_hero_class_class
            ON bannerlord_hero_class(class_key)
    """)

    await conn.commit()
    await _mark_applied(conn, "M15.bannerlord_classes")
    print(f"✅ M15: bannerlord_classes seeded ({len(BANNERLORD_CLASSES_SEED)} classes) + hero_class table")


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
