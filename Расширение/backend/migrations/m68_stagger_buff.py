"""
Migration M68 — поднять stagger_immunity к уровню BLT.

2026-06-10. M67 ввёл stagger_immunity_pct, но значения были слишком малы
(berserk L2=30%, L3=40%) → в толпе большинство ударов всё равно станило героя.
BLT шлёт три тира Shrug Off = 15/40/80% (верхний 80%). Поднимаем к этому уровню
(+ мод теперь гасит KnockBack/KnockDown при ShrugOff, как BLT HitBehavior.AddFlags).

UPDATE существующих строк (не INSERT — строки уже есть из M67). Идемпотентно
(фиксированные значения) + защищено маркером migrations_applied.
"""

_ROWS = [
    # class_key,        lvl1, lvl2, lvl3   (BLT top tier = 80%)
    ("tank",            40.0, 60.0, 80.0),
    ("berserk",         40.0, 60.0, 80.0),
    ("psycho",          45.0, 65.0, 85.0),   # самый «безбашенный»
    ("knight",          30.0, 48.0, 68.0),
    ("assassin",        30.0, 48.0, 68.0),
    ("cavalry",         25.0, 45.0, 65.0),
    ("camel_cavalry",   25.0, 45.0, 65.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M68.stagger_buff"):
        return

    updated = 0
    for class_key, l1, l2, l3 in _ROWS:
        cur = await conn.execute(
            "UPDATE bannerlord_class_powers "
            "SET lvl1_value=?, lvl2_value=?, lvl3_value=? "
            "WHERE class_key=? AND power_key='stagger_immunity_pct'",
            (l1, l2, l3, class_key))
        updated += cur.rowcount

    await conn.commit()
    await _mark_applied(conn, "M68.stagger_buff")
    print(f"M68: stagger_immunity raised to BLT level — {updated} rows updated")


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
