"""
Migration M44 — active powers для всех классов (BLT-parity).

Sprint 5.32 — раньше только 4 класса имели active power (berserk/psycho → rage,
knight → retribution, tank → shield_break). У archer / cavalry / horse_archer /
camel_archer / camel_cavalry / infantry активки не было — viewer'у в Бой tab
показывали только 💊 Лечение.

BLT (billw2012/Bannerlord-Twitch) даёт активку каждому классу, чтобы все
рукоприкладные классы могли что-то "выстрелить" во время боя. Используем
existing mod-side механики (rage = outgoing damage mult, retribution_toggle =
incoming reflect, оба обработаны в DamageHookPatch.cs).

Добавляем:
  archer / cavalry / horse_archer / camel_archer / camel_cavalry → rage
     (1.4 / 1.6 / 1.9 multiplier per class_level 1/2/3 — BLT-range numbers)
  infantry → retribution_toggle (20 / 35 / 50 % reflect — tank-similar)

Это даёт каждому классу 1 burst-активку (+ heal_burst всегда доступен).

Mod-side изменений НЕ нужно — `rage` и `retribution_toggle` уже хукнуты в
DamageHookPatch для любого hero вне зависимости от класса. Просто сейчас
бэк не возвращал эти power_key для классов без записи в class_powers.

Idempotent — INSERT OR IGNORE.
"""

_ROWS = [
    # class_key,           power_key,            lvl1, lvl2, lvl3
    ("archer",             "rage",               1.4, 1.6, 1.9),
    ("horse_archer",       "rage",               1.4, 1.6, 1.9),
    ("camel_archer",       "rage",               1.4, 1.6, 1.9),
    ("cavalry",            "rage",               1.4, 1.6, 1.9),
    ("camel_cavalry",      "rage",               1.4, 1.6, 1.9),
    ("infantry",           "retribution_toggle", 20.0, 35.0, 50.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M44.class_actives_for_all"):
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
    await _mark_applied(conn, "M44.class_actives_for_all")
    print(f"M44: class actives added — {inserted}/{len(_ROWS)} rows inserted "
          f"(rest already existed)")


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
