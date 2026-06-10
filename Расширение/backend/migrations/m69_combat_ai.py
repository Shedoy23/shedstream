"""
Migration M69 — «умный боевой ИИ» для всех боевых классов.

2026-06-10. BLT не имеет единой галки «умность ИИ», но даёт рычаг: поднять
AI-способности (блок/парри/решения атаки) через AgentDrivenProperties
(StatModifyPower). Вводим power_key `ai_combat_pct` (0..100 → 0..1 ability),
читается в PowersMissionBehavior.ApplyCombatAiTick и переприменяется на 2с-тике
к AIBlockOnDecideAbility / AIParryOnDecideAbility / AIAttackOnDecideChance /
AIDecideOnAttackChance / AIParryOnAttackAbility.

Балансовый нюанс: для лучников это только МЕЛИ-самозащита при наскоке — мод НЕ
трогает скорострельность/точность (AiShootFreq/AiShooterError), чтобы не
усиливать и без того сильный дальний бой. Мили получают полную выгоду.

Тиры (lvl1/2/3):
  • танк/рыцарь    — 50/68/85 (элитные защитники)
  • прочие мили    — 38/55/72 (берсерк/кавалерия/верблюд/психопат/убийца)
  • лучники (×6)   — 30/45/60 (самозащита в ближнем)

Новый power_key долетает до мода генерически через /class-state → PowerCache.
Idempotent — INSERT OR IGNORE.
"""

_ROWS = [
    # class_key,        lvl1, lvl2, lvl3
    ("tank",            50.0, 68.0, 85.0),
    ("knight",          50.0, 68.0, 85.0),
    ("berserk",         38.0, 55.0, 72.0),
    ("cavalry",         38.0, 55.0, 72.0),
    ("camel_cavalry",   38.0, 55.0, 72.0),
    ("psycho",          38.0, 55.0, 72.0),
    ("assassin",        38.0, 55.0, 72.0),
    ("archer",          30.0, 45.0, 60.0),
    ("heavy_archer",    30.0, 45.0, 60.0),
    ("crossbow",        30.0, 45.0, 60.0),
    ("heavy_crossbow",  30.0, 45.0, 60.0),
    ("horse_archer",    30.0, 45.0, 60.0),
    ("camel_archer",    30.0, 45.0, 60.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M69.combat_ai"):
        return

    inserted = 0
    for class_key, l1, l2, l3 in _ROWS:
        cur = await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, 'ai_combat_pct', ?, ?, ?)",
            (class_key, l1, l2, l3))
        if cur.rowcount > 0:
            inserted += 1

    await conn.commit()
    await _mark_applied(conn, "M69.combat_ai")
    print(f"M69: combat AI (ai_combat_pct) — {inserted}/{len(_ROWS)} rows inserted")


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
