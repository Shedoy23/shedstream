"""
Migration M79: class balance pass (audit 2026-06-17).

Цель — выровнять классы по боевой эффективности (заработок-через-стрики
владелец чинит отдельно). Принципы:
  • мили-бруизеры (berserk/psycho/assassin) — урон ОСТАВЛЯЕМ, режем защиту/сустейн
    → высокий риск/ревард, их можно сфокусить и убить;
  • танки (tank/knight) — живучесть оставляем, лишний урон/дубль-активку режем;
  • стрелки — добавляем выживаемость (стаггер-иммун + чуть hp/dmg-red), чтобы
    переживали наскок мили (главный остаток bug #15: 0% стаггер → оглушали
    намертво). Оффенс стрелков НЕ трогаем — rage (×урон выстрела) + explosive_arrows
    остаются их бёрстом.
  • конница — не трогаем (сбалансированный hit-run).

Чистим legacy-призрак `infantry` (нет в каталоге M15, неосиротевшая строка от m44).
rage НИГДЕ не удаляем — он множит и урон выстрелов (ApplyRageOutgoing без missile-гейта).

Механики уже есть мод-сайд (stagger_immunity_pct / damage_reduction_pct / hp_multiplier
читаются из этих значений) → миграция data-only, без пересборки мода.

Idempotent: migrations_applied['M79.class_balance'] + upsert (ON CONFLICT).
"""

# Upsert (вставит если нет, перезапишет если есть). (class_key, power_key, L1, L2, L3)
_SET = [
    # ── МИЛИ: режем защиту/сустейн, оффенс не трогаем ──
    ("berserk",  "hp_multiplier",        1.05, 1.15, 1.25),   # было 1.15/1.3/1.5
    ("berserk",  "damage_reduction_pct", 3.0,  6.0,  10.0),   # было 6/12/18
    ("berserk",  "lifesteal_pct",        5.0,  8.0,  12.0),   # было 7.8/13/20.8
    ("berserk",  "stagger_immunity_pct", 30.0, 45.0, 60.0),   # было 40/60/80
    ("psycho",   "stagger_immunity_pct", 30.0, 45.0, 60.0),   # было 45/65/85 (стеклянного можно ловить)
    ("assassin", "lifesteal_pct",        6.0,  11.0, 16.0),   # было 10.4/18.2/28.6 (не бессмертный)
    ("knight",   "ignore_armor_pct",     8.0,  15.0, 25.0),   # было 10/20/35
    ("tank",     "ignore_armor_pct",     8.0,  15.0, 25.0),   # было 10/25/40 (щит, не дамагер)
    # ── СТРЕЛКИ: только выживаемость ──
    ("archer",         "stagger_immunity_pct", 10.0, 15.0, 20.0),   # было 0 (нет строки)
    ("archer",         "damage_reduction_pct", 6.0,  10.0, 14.0),   # было 4/7/10
    ("archer",         "hp_multiplier",        1.05, 1.15, 1.25),   # было 0.95/1.05/1.15
    ("heavy_archer",   "stagger_immunity_pct", 10.0, 15.0, 20.0),
    ("crossbow",       "stagger_immunity_pct", 10.0, 15.0, 20.0),
    ("crossbow",       "hp_multiplier",        1.0,  1.05, 1.1),    # было нет строки (база 2.5×)
    ("heavy_crossbow", "stagger_immunity_pct", 10.0, 15.0, 20.0),
    ("horse_archer",   "stagger_immunity_pct", 8.0,  12.0, 15.0),   # мобильность — основная защита
    ("camel_archer",   "stagger_immunity_pct", 8.0,  12.0, 15.0),
]

# Удаляем строки. (class_key, power_key)
_DELETE = [
    ("knight", "retribution_toggle"),   # дубль к ironskin_toggle — knight перегружен 2 защ-активками
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M79.class_balance"):
        return

    for ck, pk, l1, l2, l3 in _SET:
        await conn.execute(
            "INSERT INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(class_key, power_key) DO UPDATE SET "
            "lvl1_value=excluded.lvl1_value, "
            "lvl2_value=excluded.lvl2_value, "
            "lvl3_value=excluded.lvl3_value",
            (ck, pk, l1, l2, l3))

    for ck, pk in _DELETE:
        await conn.execute(
            "DELETE FROM bannerlord_class_powers WHERE class_key=? AND power_key=?",
            (ck, pk))

    # legacy-призрак: класс infantry не выбирается (нет в M15-каталоге).
    await conn.execute(
        "DELETE FROM bannerlord_class_powers WHERE class_key='infantry'")

    await conn.commit()
    await _mark_applied(conn, "M79.class_balance")
    print(f"M79: class balance pass — {len(_SET)} upserts, "
          f"{len(_DELETE)} deletes + legacy infantry cleanup")


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
