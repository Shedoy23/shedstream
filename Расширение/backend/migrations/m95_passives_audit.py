"""
Migration M95: аудит пассивок — развести роли 7 классов.

m92/m93 разложили АКТИВКИ и поправили три расхождения в живучести, но полную
матрицу пассивок никто не сверял. Дамп прода (17 ключей × 7 классов) выявил
четыре поломки роли, а не «чуть не те цифры»:

1. ВАМПИРИЗМ РАЗМЫТ. lifesteal_pct есть у всех семи, причём берсерк — заявленный
   вампир — в нём ХУДШИЙ (12% на L3), а конный лучник 19.5%, ассасин 16%, лучник
   и арбалетчик 15.6%. Стрелок лечится, стреляя издалека, лучше, чем берсерк в
   свалке. Чиним НЕ подъёмом берсерка (m93 намеренно держит его 12% — он самый
   популярный класс, 11 из 18, мету перекашивать нельзя), а снятием вампиризма
   с тех, кому он не по роли: стрелки не лечатся выстрелами вообще, у ассасина и
   кавалериста опускаем НИЖЕ берсерка. Берсерк становится топом, не изменившись.

2. КАВАЛЕРИСТ = ТАНК ВЕРХОМ. HP 2.1 vs 2.1, снижение урона 22% vs 28% — при этом
   он ещё и мобильный, и с таранным наскоком. Двух «самых крепких» быть не должно:
   опускаем кавалериста заметно ниже танка, вершина живучести остаётся одна.

3. ДЫРЫ В НАВЫКАХ (не баланс, забытые строки). Латник машет булавой с нулевым
   навыком оружия (прокачана только атлетика). Кавалерист — без верховой езды,
   хотя у конного лучника она есть. Добавляем обе.

4. У АССАСИНА НОЛЬ ПРОБИТИЯ БРОНИ. Кинжал по латнику ничего не делает → его 45
   секунд невидимости не конвертируются в киллы вообще. Даём точечное пробитие
   (ниже берсерка, около арбалетчика) — иначе фирменная активка бессмысленна.

НЕ трогаем сознательно: берсерка (m93 только что откалибровала), танка (эталон
живучести), скорость танка (медленный танк не доходит до боя — зрителю скучно),
stagger ассасина (застан-локанный хрупкий = мёртвый), damage_reflect_pct (не
выдан НИКОМУ — мёртвый груз, но чужой: удалять код не наше дело).

Idempotent: migrations_applied['M95.passives_audit'] + upsert / DELETE.
"""

# (class_key, power_key, L1, L2, L3) — upsert
_TUNE = [
    # ── 2. Кавалерист: развести с танком (танк остаётся вершиной живучести) ──
    ("knight", "hp_multiplier",        1.45, 1.62, 1.80),   # было 1.68/1.89/2.10
    ("knight", "damage_reduction_pct", 6.0,  11.0, 16.0),   # было 8/15/22

    # ── 3. Дыры в навыках ──
    ("tank",   "one_handed_skill_boost", 20, 42, 65),       # НЕ БЫЛО: булава без навыка
    ("knight", "riding_skill_boost",     20, 42, 65),       # НЕ БЫЛО: конник без верховой

    # ── 4. Ассасин: точечное пробитие, иначе невидимость не во что конвертировать ──
    ("assassin", "ignore_armor_pct",   10.0, 20.0, 30.0),   # НЕ БЫЛО (у берсерка 15/50)

    # ── 1. Вампиризм: опустить НИЖЕ берсерка (берсерк 5/8.5/12 не трогаем) ──
    ("assassin", "lifesteal_pct",       4.0,  7.0, 10.0),   # было 6/11/16 (был ВЫШЕ берсерка)
    ("knight",   "lifesteal_pct",       3.0,  5.5,  8.0),   # было 5.2/9.75/14.3
]

# Вампиризм снять полностью: стрелок не лечится выстрелом, танк держит бронёй.
_DROP = [
    ("archer",       "lifesteal_pct"),   # было 6.5/15.6
    ("crossbow",     "lifesteal_pct"),   # было 6.5/15.6
    ("horse_archer", "lifesteal_pct"),   # было 7.8/19.5 — самый высокий в ростере
    ("tank",         "lifesteal_pct"),   # было 5/5 — шум, роли не соответствует
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M95.passives_audit"):
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

    for ck, pk in _DROP:
        await conn.execute(
            "DELETE FROM bannerlord_class_powers WHERE class_key=? AND power_key=?",
            (ck, pk))

    await conn.commit()
    await _mark_applied(conn, "M95.passives_audit")
    print(f"M95: пассивки — {len(_TUNE)} строк подогнано, "
          f"{len(_DROP)} вампиризмов снято (берсерк стал топом, не изменившись)")


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
