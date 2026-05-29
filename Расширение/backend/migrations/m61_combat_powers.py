"""
Migration M61 — BLT-parity combat powers (lifesteal / iron-skin / cleave).

2026-05-29. Добавляем 3 типа боевых скилов из BLT, которых у нас не было:

  ПАССИВЫ (всегда-on, читаются в DamageHookPatch через PowerCache; едут к моду
  в `powers` блоке /class-state, в UI не показываются):
    • lifesteal_pct        — вампиризм: % нанесённого урона → хил атакующему
                             (BLT AbsorbHealthPower)
    • damage_reduction_pct — железная кожа: % снижения входящего урона
                             (BLT TakeDamagePower, modifier<100%)
    • cleave_chance_pct    — рассечение: шанс прорубить удар на след. врага
                             (BLT AddDamagePower CutThroughChancePercent;
                              мод: 2-й Harmony patch на MeleeCollisionReaction)

  АКТИВЫ (chat-triggered burst, duration+cooldown; читаются через
  ActiveBuffState как rage/retribution; требуют ACTIVE_POWER_KEYS + POWER_COOLDOWNS
  + BNR_POWER_LABELS):
    • lifesteal_burst — вампиризм-всплеск на ~12с
    • ironskin_toggle — снижение урона на ~12с

Idempotent — INSERT OR IGNORE. Mod-side: DamageHookPatch + новый CleavePatch
читают эти power_key (см. BannerlordLink).
"""

_ROWS = [
    # class_key,         power_key,              lvl1,  lvl2,  lvl3
    # ── ПАССИВ: вампиризм (% урона → хил) ──
    ("assassin",         "lifesteal_pct",          8.0,  14.0, 22.0),
    ("berserk",          "lifesteal_pct",          6.0,  10.0, 16.0),
    ("psycho",           "lifesteal_pct",          5.0,   8.0, 12.0),
    ("knight",           "lifesteal_pct",          4.0,   7.0, 11.0),
    # ── ПАССИВ: железная кожа (% снижения входящего урона) ──
    ("tank",             "damage_reduction_pct",  10.0,  18.0, 28.0),
    ("knight",           "damage_reduction_pct",   8.0,  14.0, 22.0),
    ("heavy_archer",     "damage_reduction_pct",   5.0,   9.0, 14.0),
    ("heavy_crossbow",   "damage_reduction_pct",   5.0,   9.0, 14.0),
    # ── ПАССИВ: рассечение (% шанс прорубить на след. врага) ──
    ("psycho",           "cleave_chance_pct",     15.0,  25.0, 40.0),
    ("berserk",          "cleave_chance_pct",     12.0,  20.0, 32.0),
    ("cavalry",          "cleave_chance_pct",      8.0,  14.0, 22.0),
    ("camel_cavalry",    "cleave_chance_pct",      8.0,  14.0, 22.0),
    # ── АКТИВ: вампиризм-всплеск (% урона → хил на время буффа) ──
    ("assassin",         "lifesteal_burst",       30.0,  45.0, 60.0),
    ("berserk",          "lifesteal_burst",       25.0,  40.0, 55.0),
    # ── АКТИВ: железная кожа-тоггл (% снижения на время буффа) ──
    ("tank",             "ironskin_toggle",       30.0,  45.0, 60.0),
    ("knight",           "ironskin_toggle",       25.0,  40.0, 55.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M61.combat_powers"):
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
    await _mark_applied(conn, "M61.combat_powers")
    print(f"M61: combat powers (lifesteal/iron-skin/cleave) — "
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
