"""
Migration M17: Bannerlord active powers seed + armor_bypass_pct fixup.

Sprint 4.5 changes:
  1. **Fixup:** объединить `armor_bypass_pct` → `ignore_armor_pct`. M16 seed
     ошибочно разнёс одинаковую механику на 2 ключа (для crossbow vs melee).
     DamageHookPatch (C# mod, Sprint 4.4) уже обрабатывает оба как alias,
     но БД consolidate'им чтобы было одно имя.

  2. **Seed active powers** — расширяет `bannerlord_class_powers`:
       tank    → shield_break_burst   (radius метры: 6/8/10)
       psycho  → rage                 (damage multi: 1.4/1.6/1.8)
       berserk → rage                 (damage multi: 1.3/1.5/1.8)
       knight  → retribution_toggle   (extra reflect %: 20/35/50)

     C# mod (ActivatePowerHandler) читает эти значения из PowerCache
     при `power.activate`. Duration захардкожен в C# (30s для rage,
     60s для retribution_toggle) — backend может override через
     data.duration_s.

Идемпотентно через migrations_applied['M17.bannerlord_active_powers'].
Safe to re-run.
"""

# (class_key, power_key, lvl1, lvl2, lvl3)
ACTIVE_POWERS_SEED = [
    # Tank — мгновенный AoE shield-break (radius in m)
    ("tank", "shield_break_burst", 6.0, 8.0, 10.0),

    # Psycho / Berserk — temporary outgoing damage multi
    ("psycho",  "rage", 1.4, 1.6, 1.8),
    ("berserk", "rage", 1.3, 1.5, 1.8),

    # Knight — extra reflect % (overlay поверх damage_reflect_pct если есть)
    ("knight", "retribution_toggle", 20.0, 35.0, 50.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M17.bannerlord_active_powers"):
        return

    # ── 1. Fixup armor_bypass_pct → ignore_armor_pct ──────────────────────
    # PRIMARY KEY (class_key, power_key) → если у класса уже есть
    # ignore_armor_pct, INSERT OR REPLACE через CTE. На M16 seed конфликтов
    # нет (crossbow/heavy_crossbow имеют только armor_bypass_pct;
    # tank/berserk/knight имеют только ignore_armor_pct).
    # Но защитимся: DELETE conflicting target rows ДО update.
    await conn.execute("""
        DELETE FROM bannerlord_class_powers
         WHERE power_key = 'ignore_armor_pct'
           AND class_key IN (
               SELECT class_key FROM bannerlord_class_powers
                WHERE power_key = 'armor_bypass_pct'
           )
    """)
    await conn.execute("""
        UPDATE bannerlord_class_powers
           SET power_key = 'ignore_armor_pct'
         WHERE power_key = 'armor_bypass_pct'
    """)

    # ── 2. Seed active powers ─────────────────────────────────────────────
    for row in ACTIVE_POWERS_SEED:
        ck, pk, v1, v2, v3 = row
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (ck, pk, v1, v2, v3)
        )

    await conn.commit()
    await _mark_applied(conn, "M17.bannerlord_active_powers")
    print(
        f"✅ M17: armor_bypass_pct→ignore_armor_pct fixup + "
        f"{len(ACTIVE_POWERS_SEED)} active powers seeded"
    )


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
