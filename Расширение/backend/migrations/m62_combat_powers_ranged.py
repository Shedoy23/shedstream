"""
Migration M62 — balance pass: combat powers для ranged-классов.

2026-05-29. M61 раздал lifesteal/iron-skin/cleave мелишным/танковым/тяжёлым-
ranged/конным классам, но 4 «обычных» дальнобойных остались без единого
нового скила и просели на фоне апнутых соседей:

  archer, crossbow, horse_archer, camel_archer

Cleave — мелишный эффект (по стрелам не срабатывает: MeleeHitCallback),
поэтому ranged компенсируем вампиризмом (lifesteal_pct работает на любой
InflictedDamage, включая стрелы/болты) + лёгкой железной кожей пешим лучникам/
арбалетчикам (конные кайтят — защита им нужна меньше).

Значения чуть ниже melee-аналогов (у ranged есть преимущество дистанции).
Idempotent — INSERT OR IGNORE.
"""

_ROWS = [
    # class_key,        power_key,               lvl1,  lvl2,  lvl3
    # ── archer — пьющие кровь стрелы + лёгкая выживаемость ──
    ("archer",          "lifesteal_pct",          5.0,   8.0, 12.0),
    ("archer",          "damage_reduction_pct",   4.0,   7.0, 10.0),
    # ── crossbow — leech + pavise-tanky (медленная перезарядка компенс. защитой) ──
    ("crossbow",        "lifesteal_pct",          5.0,   8.0, 12.0),
    ("crossbow",        "damage_reduction_pct",   5.0,   9.0, 14.0),
    # ── horse_archer — сильный мобильный sustain (hit & run) ──
    ("horse_archer",    "lifesteal_pct",          6.0,  10.0, 15.0),
    # ── camel_archer — тот же kite-профиль ──
    ("camel_archer",    "lifesteal_pct",          6.0,  10.0, 15.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M62.combat_powers_ranged"):
        return

    inserted = 0
    for class_key, power_key, l1, l2, l3 in _ROWS:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (class_key, power_key, l1, l2, l3))
        if cur.rowcount > 0:
            inserted += 1

    await conn.commit()
    await _mark_applied(conn, "M62.combat_powers_ranged")
    print(f"M62: ranged combat powers (archer/crossbow/horse_archer/camel_archer) "
          f"— {inserted}/{len(_ROWS)} rows inserted (rest already existed)")


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
