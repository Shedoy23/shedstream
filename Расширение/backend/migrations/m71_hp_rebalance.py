"""
Migration M71 — фикс HP-инверсии (лучники танковее мили).

2026-06-10. M65 ошибочно включил heavy_archer/heavy_crossbow в список «танковых»
классов (_HP_TANKY) и поднял им hp_multiplier ×1.4 вместе с настоящими танками.
Итог (live-лог стрима): heavy_archer L1 hp×1.54 — танковее berserk L3 (1.15) и
cavalry (1.47). Это бьёт прямо в цель «усилить мили».

Фикс:
  • heavy_archer / heavy_crossbow — HP ВНИЗ к до-m65 уровню (1.10/1.20/1.35):
    тяжёлый лучник остаётся бронированным/живучим, но НЕ танковее мили-брузеров.
  • berserk — HP ВВЕРХ (0.90/1.00/1.15 → 1.15/1.30/1.50): рейдж-брузер должен
    соак'ать, а не падать как стекло.
  • assassin / psycho — НЕ трогаем: намеренные стекло-кэнноны (живучесть через
    lifesteal/burst/cleave, не HP). tank/knight/cavalry/camel/archer — уже ок.

Порядок живучести после фикса (L3): knight/tank 2.1 > cavalry 1.75 > berserk 1.5
> heavy_archer/crossbow 1.35 > assassin 1.3 > archer 1.15 > psycho 1.0.

UPDATE существующих строк (post-m65). Идемпотентно (фикс. значения + маркер).
"""

_ROWS = [
    # class_key,        lvl1, lvl2, lvl3
    ("heavy_archer",    1.10, 1.20, 1.35),   # вниз с 1.54/1.68/1.89 (отмена танк-буста m65)
    ("heavy_crossbow",  1.10, 1.20, 1.35),   # вниз с 1.54/1.68/1.89
    ("berserk",         1.15, 1.30, 1.50),   # вверх с 0.90/1.00/1.15 (брузер должен соак'ать)
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M71.hp_rebalance"):
        return

    updated = 0
    for class_key, l1, l2, l3 in _ROWS:
        cur = await conn.execute(
            "UPDATE bannerlord_class_powers "
            "SET lvl1_value=?, lvl2_value=?, lvl3_value=? "
            "WHERE class_key=? AND power_key='hp_multiplier'",
            (l1, l2, l3, class_key))
        updated += cur.rowcount

    await conn.commit()
    await _mark_applied(conn, "M71.hp_rebalance")
    print(f"M71: HP rebalance (heavy-ranged down, berserk up) — {updated} rows updated")


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
