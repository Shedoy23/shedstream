"""
Migration M93: classes v2 — подгонка пассивок (баланс после m92/брони).

m92 порезала ростер и разложила АКТИВКИ, но пассивные множители остались теми,
что накопились под старый 12-классовый ростер. Аудит боевой базы выявил три
расхождения «числа vs роль»:

1. БЕРСЕРК получил чистый бафф: мод-правка 9c147b0 надела на него броню (был
   единственный класс без шлема/нагрудника — «стеклянная пушка»), но его числа
   остались прежними. При этом он самый популярный класс (14 зрителей из 19) —
   мету это перекашивает. Компенсируем: HP 1.25→1.15, снижение урона 10→4%.
   Урон НЕ трогаем (ignore_armor 50%, two_handed +80%, вампиризм 12% остаются) —
   он должен оставаться страшным, но снова смертным.

2. КОННЫЙ ЛУЧНИК вообще без выживаемости: строк hp_multiplier и
   damage_reduction_pct у него НЕТ → HP ×1.0 и 0% снижения. Самый хрупкий в
   ростере, причём верхом. Добавляем базовую живучесть мобильного стрелка.

3. АРБАЛЕТЧИК противоречит своему же описанию в каталоге («Крепче лучника»):
   HP ×1.1 против ×1.25 у лучника — он СЛАБЕЕ. Поднимаем выше лучника.

Лучник (базовая линия), танк (HP 2.1 / 28%) и кавалерист (2.1 / 22%) не трогаются —
их числа роли уже соответствуют.

Только пассивки. Активки (m92) и структура каталога не затрагиваются.
Idempotent: migrations_applied['M93.classes_v2_balance'] + upsert.
"""

# (class_key, power_key, L1, L2, L3)
_TUNE = [
    # ── 1. Берсерк: компенсация надетой брони (вниз по живучести) ──
    ("berserk",      "hp_multiplier",        1.00, 1.08, 1.15),   # было 1.05/1.15/1.25
    ("berserk",      "damage_reduction_pct", 0.0,  2.0,  4.0),    # было 3/6/10

    # ── 2. Конный лучник: базовая живучесть (строк вообще не было) ──
    ("horse_archer", "hp_multiplier",        1.05, 1.12, 1.20),   # NEW (было отсутствие → 1.0)
    ("horse_archer", "damage_reduction_pct", 4.0,  7.0,  10.0),   # NEW (было отсутствие → 0%)

    # ── 3. Арбалетчик: сделать «крепче лучника» правдой (у лучника 1.25 / 14%) ──
    ("crossbow",     "hp_multiplier",        1.15, 1.28, 1.40),   # было 1.0/-/1.1
    ("crossbow",     "damage_reduction_pct", 6.0,  11.0, 16.0),   # было 5/-/14
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M93.classes_v2_balance"):
        return

    for ck, pk, l1, l2, l3 in _TUNE:
        await conn.execute(
            "INSERT INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(class_key, power_key) DO UPDATE SET "
            "lvl1_value=excluded.lvl1_value, "
            "lvl2_value=excluded.lvl2_value, "
            "lvl3_value=excluded.lvl3_value",
            (ck, pk, l1, l2, l3))

    await conn.commit()
    await _mark_applied(conn, "M93.classes_v2_balance")
    print(f"M93: classes v2 balance — {len(_TUNE)} пассивок подогнано "
          f"(берсерк вниз после брони, конный лучник и арбалетчик вверх)")


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
