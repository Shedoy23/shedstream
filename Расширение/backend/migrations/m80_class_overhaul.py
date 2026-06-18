"""
Migration M80: class overhaul — 12-class roster (Phase 1).

Reseeds bannerlord_classes to the new distinct-by-design 12-class roster
(weapon-by-WeaponClass + armor weight-band live in the C# ClassLoadout; this
catalog is the display/validation mirror). Remaps existing viewers off the 6
removed keys, soft-deprecates the old rows, and seeds baseline powers for the
5 NEW classes (full power rebalance of all 12 = Phase 2).

Roster (12): tank, berserk, legionnaire*, assassin, spearman*, maul*,
archer, crossbow, skirmisher*, knight, lancer*, horse_archer.   (* = new key)
Removed→remap: heavy_archer→archer, heavy_crossbow→crossbow, psycho→berserk,
cavalry→lancer, camel_cavalry→lancer, camel_archer→horse_archer.

Order is FK-safe: (1) reseed catalog (new keys exist) → (2) remap hero_class
(targets now valid) → (3) deprecate old rows → (4) seed new-class powers.
Powers use only already-implemented power_keys (no new mod-side handling).

Idempotent: migrations_applied['M80.class_overhaul'] + INSERT OR REPLACE / upsert.
"""

# Catalog rows: (class_key, name, formation, slot1, slot2, slot3, slot4, use_horse, use_camel, description)
# formation ∈ Infantry/Ranged/Cavalry/HorseArcher; slots = ItemTypeEnum names ("" = empty).
_CATALOG = [
    # ── INFANTRY ──
    ("tank",         "Латник",         "Infantry",    "OneHandedWeapon", "Shield",          "",                "",                0, 0, "Тяжёлая пехота: булава + большой щит, латы. Несокрушимая стена, бьёт медленно."),
    ("berserk",      "Берсерк",        "Infantry",    "TwoHandedWeapon", "TwoHandedWeapon", "",                "",                0, 0, "Два двуручных топора, голый торс. Косит толпу, но хрупок — стеклянная пушка."),
    ("legionnaire",  "Легионер",       "Infantry",    "OneHandedWeapon", "Shield",          "Thrown",          "",                0, 0, "Меч + щит + дротики. Надёжный строевой боец: метнул — прикрылся."),
    ("assassin",     "Убийца",         "Infantry",    "OneHandedWeapon", "Thrown",          "",                "",                0, 0, "Кинжал + метательные ножи. Быстрый и лёгкий, но хрупкий."),
    ("spearman",     "Копейщик",       "Infantry",    "Polearm",         "Shield",          "",                "",                0, 0, "Двуручное копьё + щит. Длинная досягаемость, рвёт конницу."),
    ("maul",         "Сокрушитель",    "Infantry",    "TwoHandedWeapon", "",                "",                "",                0, 0, "Двуручная булава: проламывает щиты и броню, сбивает с ног. Контр-латник."),
    # ── RANGED (foot) ──
    ("archer",       "Лучник",         "Ranged",      "Bow",             "Arrows",          "Arrows",          "OneHandedWeapon", 0, 0, "Лук + два колчана + кинжал. Кайт и взрывные стрелы, но хрупкий."),
    ("crossbow",     "Арбалетчик",     "Ranged",      "Crossbow",        "Bolts",           "Bolts",           "OneHandedWeapon", 0, 0, "Арбалет: медленный, но бронебойный выстрел. Крепче лучника."),
    ("skirmisher",   "Застрельщик",    "Infantry",    "Thrown",          "Thrown",          "Shield",          "OneHandedWeapon", 0, 0, "Два набора дротиков + малый щит. Барраж по щитам, потом в ближний бой."),
    # ── CAVALRY ──
    ("knight",       "Рыцарь",         "Cavalry",     "Polearm",         "OneHandedWeapon", "Shield",          "",                1, 0, "Тяжёлая конница: копьё-чардж + меч + большой щит. Разящий наскок."),
    ("lancer",       "Улан",           "Cavalry",     "Polearm",         "Thrown",          "OneHandedWeapon", "",                1, 0, "Лёгкая конница: налетел-уколол-метнул-ушёл. Манёвреннее рыцаря."),
    ("horse_archer", "Конный Лучник",  "HorseArcher", "Bow",             "Arrows",          "OneHandedWeapon", "Arrows",          1, 0, "Мобильный конный лучник: кайт верхом, набег."),
]

# Existing viewers remap off removed keys. (old_key, new_key)
_REMAP = [
    ("heavy_archer",   "archer"),
    ("heavy_crossbow", "crossbow"),
    ("psycho",         "berserk"),
    ("cavalry",        "lancer"),
    ("camel_cavalry",  "lancer"),
    ("camel_archer",   "horse_archer"),
]

# Old catalog rows to soft-deprecate (kept for FK / history, hidden from picker).
_DEPRECATE = ["heavy_archer", "heavy_crossbow", "psycho",
              "cavalry", "camel_cavalry", "camel_archer"]

# Baseline powers for the 5 NEW classes (full rebalance of all 12 = Phase 2).
# Only already-implemented power_keys. (class_key, power_key, L1, L2, L3)
_POWERS = [
    # legionnaire — balanced line-fighter
    ("legionnaire", "hp_multiplier",         1.2,  1.35, 1.5),
    ("legionnaire", "one_handed_skill_boost", 20,   40,   60),
    ("legionnaire", "throwing_skill_boost",   15,   30,   50),
    ("legionnaire", "damage_reduction_pct",   6.0,  10.0, 14.0),
    ("legionnaire", "stagger_immunity_pct",   20.0, 35.0, 50.0),
    ("legionnaire", "rage",                   1.3,  1.45, 1.6),   # active
    # spearman — anti-cavalry holder
    ("spearman", "hp_multiplier",         1.1,  1.3,  1.5),
    ("spearman", "polearm_skill_boost",   20,   45,   70),
    ("spearman", "damage_reduction_pct",  6.0,  12.0, 18.0),
    ("spearman", "stagger_immunity_pct",  25.0, 45.0, 65.0),
    ("spearman", "athletic_skill_boost",  10,   20,   35),
    ("spearman", "ironskin_toggle",       25.0, 40.0, 55.0),     # active
    # maul — anti-armor crusher (blunt)
    ("maul", "hp_multiplier",         1.2,  1.4,  1.6),
    ("maul", "two_handed_skill_boost", 25,   50,   80),
    ("maul", "ignore_armor_pct",      25.0, 40.0, 55.0),
    ("maul", "stagger_immunity_pct",  30.0, 50.0, 70.0),
    ("maul", "damage_reduction_pct",  6.0,  12.0, 18.0),
    ("maul", "shield_break_burst",    8,    10,   12),           # active
    # skirmisher — javelin barrage
    ("skirmisher", "hp_multiplier",         1.0,  1.15, 1.3),
    ("skirmisher", "throwing_skill_boost",  25,   50,   75),
    ("skirmisher", "one_handed_skill_boost", 10,   20,   35),
    ("skirmisher", "damage_reduction_pct",  5.0,  9.0,  14.0),
    ("skirmisher", "stagger_immunity_pct",  15.0, 25.0, 35.0),
    ("skirmisher", "explosive_arrows",      50,   75,   100),    # active (triggers on thrown missiles too)
    # lancer — light hit-and-run cavalry
    ("lancer", "hp_multiplier",        1.2,  1.4,  1.6),
    ("lancer", "polearm_skill_boost",  20,   40,   65),
    ("lancer", "throwing_skill_boost", 15,   30,   50),
    ("lancer", "riding_skill_boost",   25,   50,   75),
    ("lancer", "damage_reduction_pct", 6.0,  12.0, 18.0),
    ("lancer", "rage",                 1.3,  1.45, 1.6),         # active
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M80.class_overhaul"):
        return

    # 1. Reseed catalog (full row replace keyed on class_key PK; deprecated→0).
    for row in _CATALOG:
        await conn.execute(
            "INSERT OR REPLACE INTO bannerlord_classes "
            "(class_key, name, formation, slot1, slot2, slot3, slot4, "
            " use_horse, use_camel, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row)

    # 2. Remap existing viewers off removed keys (targets now exist → FK-safe).
    for old, new in _REMAP:
        await conn.execute(
            "UPDATE bannerlord_hero_class SET class_key=? WHERE class_key=?",
            (new, old))

    # 3. Soft-deprecate the old catalog rows (hidden from picker, kept for FK/history).
    for ck in _DEPRECATE:
        await conn.execute(
            "UPDATE bannerlord_classes SET deprecated=1 WHERE class_key=?", (ck,))

    # 4. Seed baseline powers for the 5 NEW classes (upsert).
    for ck, pk, l1, l2, l3 in _POWERS:
        await conn.execute(
            "INSERT INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(class_key, power_key) DO UPDATE SET "
            "lvl1_value=excluded.lvl1_value, "
            "lvl2_value=excluded.lvl2_value, "
            "lvl3_value=excluded.lvl3_value",
            (ck, pk, l1, l2, l3))

    await conn.commit()
    await _mark_applied(conn, "M80.class_overhaul")
    print(f"M80: class overhaul — {len(_CATALOG)} catalog rows, "
          f"{len(_REMAP)} remaps, {len(_DEPRECATE)} deprecated, "
          f"{len(_POWERS)} power rows for 5 new classes")


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
