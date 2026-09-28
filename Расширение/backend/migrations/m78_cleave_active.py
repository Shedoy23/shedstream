"""
Migration M78: cleave → active power (#15).

2026-06-17. Рассечение (мили splash-AoE) было ПАССИВОМ: always-on, читался в
DamageHookPatch.ApplyMeleeCleave через cleave_chance_pct на КАЖДОМ мили-хите.
Это давало мили постоянный AoE по толпе, тогда как лучниковый AoE
(explosive_arrows) — активка по запросу. Асимметрия = «лучники бесполезные»
(мили косят несколько за удар всегда, лучник одну цель за стрелу).

Переводим клив в АКТИВКУ (зеркало explosive_arrows):
  • удаляем пассивные cleave_chance_pct строки — mod их больше не читает;
  • сидим активный power_key `cleave` мили-классам. Value = доля урона в splash
    (per level), читается ActiveBuffState только в окне буффа ~45с.

Mod-side: ActivatePowerHandler.ActivateCleave + DamageHookPatch.ApplyMeleeCleave
(теперь от ActiveBuffState, не PowerCache). Backend: cleave в ACTIVE_POWER_KEYS /
POWER_PRICES (350) / POWER_COOLDOWNS (90). Frontend: BNR_POWER_LABELS['cleave'].

Idempotent через migrations_applied['M78.cleave_active'] + INSERT OR IGNORE.
"""

_CLEAVE_ROWS = [
    # class_key,        lvl1, lvl2, lvl3  — доля урона в splash на ≤3 соседей
    ("psycho",          0.45, 0.55, 0.65),   # cleave-король (стеклянный, бьёт сильно)
    ("berserk",         0.40, 0.50, 0.60),
    ("cavalry",         0.30, 0.40, 0.50),
    ("camel_cavalry",   0.30, 0.40, 0.50),
    ("assassin",        0.25, 0.35, 0.45),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M78.cleave_active"):
        return

    # 1. Убираем пассивный cleave_chance_pct — mod его больше не читает.
    await conn.execute(
        "DELETE FROM bannerlord_class_powers WHERE power_key = 'cleave_chance_pct'")

    # 2. Сидим активный `cleave` (доля splash per level) мили-классам.
    inserted = 0
    for class_key, l1, l2, l3 in _CLEAVE_ROWS:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, 'cleave', ?, ?, ?)",
            (class_key, l1, l2, l3))
        if cur.rowcount > 0:
            inserted += 1

    await conn.commit()
    await _mark_applied(conn, "M78.cleave_active")
    print(f"M78: cleave → active ({inserted}/{len(_CLEAVE_ROWS)} rows inserted; "
          f"passive cleave_chance_pct removed)")


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
