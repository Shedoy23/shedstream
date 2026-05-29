"""
Migration M63 — active power «взрывные стрелы» (BLT AddDamagePower AoE).

2026-05-29. Активка для дальнобойных классов: на ~12с все стрелы/болты при
попадании дают AoE по ближайшим врагам (мод: DamageHookPatch.ApplyExplosiveArrows
через отложенную NoSound-очередь — FMOD-safe). Value = урон в центре взрыва
(DamageAtCenter); спад по дистанции считается мод-сайдом.

Классы: archer / crossbow / horse_archer / camel_archer. Болты бьют чуть
сильнее (медленная перезарядка), конные/верблюжьи — чуть слабее (мобильность).

Требует: explosive_arrows в ACTIVE_POWER_KEYS (routes/bannerlord.py) +
POWER_COOLDOWNS (_adapter.py) + BNR_POWER_LABELS (frontend) — иначе кнопка не
появится. Idempotent — INSERT OR IGNORE.
"""

_ROWS = [
    # class_key,        power_key,           lvl1,  lvl2,  lvl3  (DamageAtCenter)
    ("archer",          "explosive_arrows",  30.0,  45.0,  60.0),
    ("crossbow",        "explosive_arrows",  35.0,  50.0,  70.0),
    ("horse_archer",    "explosive_arrows",  25.0,  40.0,  55.0),
    ("camel_archer",    "explosive_arrows",  25.0,  40.0,  55.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M63.explosive_arrows"):
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
    await _mark_applied(conn, "M63.explosive_arrows")
    print(f"M63: explosive_arrows (archer/crossbow/horse_archer/camel_archer) "
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
