"""
Migration M65 — BLT-parity power BOOST (2026-06-05).

Поднимаем значения боевых способностей, чтобы использовать новый headroom
мод-капов (rage cap 5→8, lifesteal/hit 100→250, damage_reduction cap 80→90,
HP baseline 2→2.5). До этого каталог-значения сидели намного ниже капов, так
что способности «не дотягивали до BLT».

ВАЖНО — НЕ «плющим» классы в одинаковые числа: масштабируем ПРОПОРЦИОНАЛЬНО
(сохраняет идентичность — assassin лучший лайфстил, berserk/psycho и т.д.).
hp_multiplier бустим ТОЛЬКО устойчивым классам — хрупкие (psycho 0.70,
assassin, archer) остаются стеклянными относительно танков.

UPDATE-миграция: идемпотентна через migrations_applied (apply ровно один раз
на каждой БД; повторный запуск guard'ится — НЕ удваивает scale). Регистрируется
в main.py:run_migrations() ПОСЛЕ seed-миграций (m16/18/44/50/61/62/63), чтобы
масштабировать уже-засеянные значения.
"""

# power_key → коэффициент. Пропорциональный буст (сохраняет порядок классов).
# damage_reduction_pct НЕ трогаем тут — его буст идёт через cap 80→90 + ironskin.
_SCALE = [
    ("rage",             1.35),   # 1.4/1.6/1.9 → ~1.9/2.2/2.6 (под капом 8×)
    ("lifesteal_pct",    1.30),   # assassin 8/14/22 → 10/18/29
    ("lifesteal_burst",  1.35),
    ("ironskin_toggle",  1.25),   # под капом 90%
    ("explosive_arrows", 1.75),   # archer 30/45/60 → ~53/79/105
    ("poison_dot",       1.60),   # assassin 5/8/12 → 8/13/19
]

# hp_multiplier — только устойчивые классы (стекляные psycho/assassin/archer
# НЕ трогаем). Стэкается на 2.5× baseline → танки реально соак'ают.
_HP_TANKY = ["tank", "knight", "heavy_archer", "heavy_crossbow", "cavalry", "camel_cavalry"]
_HP_FACTOR = 1.40

# Заполнить пробел: heavy_archer/heavy_crossbow без активной способности —
# дать им explosive_arrows (missile-AoE; уже в ACTIVE_POWER_KEYS из m63).
_NEW_ROWS = [
    ("heavy_archer",   "explosive_arrows", 50.0, 80.0, 120.0),
    ("heavy_crossbow", "explosive_arrows", 50.0, 80.0, 120.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M65.power_boost"):
        return

    # 1. Пропорциональный scale по power_key (по всем классам этой способности).
    for power_key, factor in _SCALE:
        await conn.execute(
            "UPDATE bannerlord_class_powers SET "
            "  lvl1_value = ROUND(lvl1_value * ?, 2), "
            "  lvl2_value = ROUND(lvl2_value * ?, 2), "
            "  lvl3_value = ROUND(lvl3_value * ?, 2) "
            "WHERE power_key = ?",
            (factor, factor, factor, power_key))

    # 2. hp_multiplier — только танковые классы.
    ph = ",".join("?" * len(_HP_TANKY))
    await conn.execute(
        f"UPDATE bannerlord_class_powers SET "
        f"  lvl1_value = ROUND(lvl1_value * ?, 2), "
        f"  lvl2_value = ROUND(lvl2_value * ?, 2), "
        f"  lvl3_value = ROUND(lvl3_value * ?, 2) "
        f"WHERE power_key = 'hp_multiplier' AND class_key IN ({ph})",
        (_HP_FACTOR, _HP_FACTOR, _HP_FACTOR, *_HP_TANKY))

    # 3. Новые активки для тяжёлых дальнобойных (INSERT OR IGNORE — не перетрёт).
    for class_key, power_key, l1, l2, l3 in _NEW_ROWS:
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (class_key, power_key, l1, l2, l3))

    await conn.commit()
    await _mark_applied(conn, "M65.power_boost")
    print("M65: power boost — scaled rage/lifesteal/ironskin/explosive/poison + "
          "hp_multiplier(tanky ×1.4) + heavy-ranged explosive_arrows")


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
