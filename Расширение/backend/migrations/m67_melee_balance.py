"""
Migration M67 — баланс милигероев (Package C).

2026-06-10. Лучники сильнее милишников: бьют безопасно издалека + рабочий AoE
(explosive_arrows), а сигнатурный мили-AoE (cleave) был мёртв (CleavePatch
yield break, нативный краш на 1.3.15). Не доливаем HP (милишники и так ведут) —
даём им то, чего реально не хватает:

  • damage_reduction_pct — танковость «голым» фронтовым милишникам (свалка).
    Раньше cavalry/camel/berserk/assassin/psycho имели 0 (только tank/knight).
  • move_speed_pct (НОВЫЙ ключ) — добег/анти-кайт ПЕШИМ милишникам: читается в
    PowersMissionBehavior.ApplyPassivePowers → Agent.SetMaximumSpeedLimit.
    Конным (cavalry/camel/knight/horse_archer) не даём — они и так мобильны.
  • stagger_immunity_pct (НОВЫЙ ключ) — шанс «не застрять в стане»: читается в
    DamageHookPatch (victim) → BlowFlags.ShrugOff на входящий удар.
  • cleave_chance_pct — расширяем на assassin. Сам cleave переехал из мёртвого
    CleavePatch в DamageHookPatch (мили-хит → splash-AoE через ту же безопасную
    отложенную очередь, что explosive_arrows).

Новые power_key долетают до мода генерически через /api/bannerlord/class-state
(SELECT * FROM bannerlord_class_powers) → PowerCache. Бэкенд-код не меняется.
Силы привязаны к КЛАССУ → существующие герои получают их на следующем
session_start без ре-адопта.

Значения — стартовые, тюнить по живым данным (намеренно умеренно: «чуть
подбалансить», не делать милишников доминирующими).

Idempotent — INSERT OR IGNORE.
"""

_ROWS = [
    # class_key,        power_key,               lvl1,  lvl2,  lvl3
    # ── НОВОЕ: damage_reduction для «голых» фронтовых милишников (свалка) ──
    ("cavalry",         "damage_reduction_pct",   8.0,  14.0, 20.0),
    ("camel_cavalry",   "damage_reduction_pct",   8.0,  14.0, 20.0),
    ("berserk",         "damage_reduction_pct",   6.0,  12.0, 18.0),
    ("assassin",        "damage_reduction_pct",   4.0,   8.0, 12.0),  # лёгкий
    ("psycho",          "damage_reduction_pct",   4.0,   8.0, 12.0),  # стекло — малая
    # ── НОВОЕ: move_speed для ПЕШИХ милишников (добег / анти-кайт лучниками) ──
    ("tank",            "move_speed_pct",         6.0,  10.0, 14.0),
    ("berserk",         "move_speed_pct",        10.0,  15.0, 20.0),
    ("psycho",          "move_speed_pct",        12.0,  18.0, 24.0),
    ("assassin",        "move_speed_pct",        12.0,  18.0, 24.0),
    # ── НОВОЕ: stagger_immunity (не застревают в стане при ударе) ──
    ("tank",            "stagger_immunity_pct",  20.0,  30.0, 40.0),
    ("knight",          "stagger_immunity_pct",  15.0,  25.0, 35.0),
    ("berserk",         "stagger_immunity_pct",  20.0,  30.0, 40.0),
    ("psycho",          "stagger_immunity_pct",  25.0,  35.0, 45.0),
    ("assassin",        "stagger_immunity_pct",  15.0,  22.0, 30.0),
    ("cavalry",         "stagger_immunity_pct",  12.0,  20.0, 28.0),
    ("camel_cavalry",   "stagger_immunity_pct",  12.0,  20.0, 28.0),
    # ── РАСШИРЕНИЕ cleave на assassin (был только berserk/psycho/cavalry/camel) ──
    ("assassin",        "cleave_chance_pct",      6.0,  12.0, 18.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M67.melee_balance"):
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
    await _mark_applied(conn, "M67.melee_balance")
    print(f"M67: melee balance (dmg_reduction/move_speed/stagger/cleave) — "
          f"{inserted}/{len(_ROWS)} rows inserted (rest already existed)")


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
