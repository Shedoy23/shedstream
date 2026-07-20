"""
Migration M92: classes v2 — 12 → 6 базовых классов (SPEC_CLASSES_V2).

Решение владельца: 6 классов, каждый читается с одного кадра и ОЩУЩАЕТСЯ иначе.
Ростер (6): berserk, tank, archer, crossbow, knight, horse_archer.
Уходят (deprecate+remap): legionnaire→tank, spearman→tank, maul→berserk,
assassin→berserk, skirmisher→archer, lancer→knight.

Активки — схема «база всем + 1 фирменная» (ровно 3 кнопки у каждого):
  база:      heal_burst (выдаётся ГЛОБАЛЬНО в routes/bannerlord.py, не сеется тут)
             + rage (сеется каждому из 6)
  фирменная: berserk=cleave, tank=ironskin_toggle, archer=explosive_arrows,
             crossbow=shield_break_burst, knight=berserker_charge,
             horse_archer=poison_dot
Лишние АКТИВКИ у шестёрки снимаем (иначе 4-5 кнопок вместо 3). ПАССИВКИ
(hp_multiplier / lifesteal_pct / dmg_reduction / *_boost / ignore_armor / …)
НЕ трогаем — вампиризм берсерка живёт именно пассивкой lifesteal_pct.

Броня/стиль (культурные скины, квантильные тиры, броня берсерку) — мод-сторона,
коммит 9c147b0, к БД отношения не имеет. Фронт НЕ затронут (заморожен на ревью):
карточки классов и кнопки сил рисуются из данных бэка.

Order FK-safe: (1) каталог 6 (deprecated=0, свежие описания) → (2) remap героев →
(3) deprecate уходящих → (4) активки: посев базы+фирменной → (5) снятие лишних активок.

Idempotent: migrations_applied['M92.classes_v2'] + INSERT OR REPLACE / upsert / DELETE.
"""

# (class_key, name, formation, slot1..slot4, use_horse, use_camel, description)
# Описания переписаны под v2: броня У ВСЕХ (голого торса больше нет), назван
# культурный стиль — зритель понимает, как класс выглядит, до выбора.
_CATALOG = [
    ("berserk",      "Берсерк",        "Infantry",    "TwoHandedWeapon", "TwoHandedWeapon", "",                "",                0, 0,
     "Северянин с двумя двуручными топорами. Косит толпу и лечится с урона, но ловит больше — стеклянная пушка. Стиль: Стургия (меха)."),
    ("tank",         "Латник",         "Infantry",    "OneHandedWeapon", "Shield",          "",                "",                0, 0,
     "Булава + большой щит, тяжёлые латы. Несокрушимая стена: держит удар, сбить с ног почти нельзя. Стиль: Империя (ламелляр)."),
    ("archer",       "Лучник",         "Ranged",      "Bow",             "Arrows",          "Arrows",          "OneHandedWeapon", 0, 0,
     "Лук + два колчана + кинжал. Держит дистанцию и жжёт взрывными стрелами. Стиль: Баттания (лесной капюшон)."),
    ("crossbow",     "Арбалетчик",     "Ranged",      "Crossbow",        "Bolts",           "Bolts",           "OneHandedWeapon", 0, 0,
     "Арбалет: медленный, но пробивает броню и разбивает щиты. Крепче лучника. Стиль: Асераи (пустынный стрелок)."),
    ("knight",       "Кавалерист",     "Cavalry",     "Polearm",         "OneHandedWeapon", "Shield",          "",                1, 0,
     "Конное копьё + меч + большой щит, латы. Таранный наскок и живучесть в седле. Стиль: Вландия (рыцарь)."),
    ("horse_archer", "Конный Лучник",  "HorseArcher", "Bow",             "Arrows",          "OneHandedWeapon", "Arrows",          1, 0,
     "Лук верхом: кайт, набег, отравленные стрелы. Самый мобильный. Стиль: Кузаиты (степь)."),
]

# Уходящие → ближайший по духу из шестёрки. (old_key, new_key)
# ВАЖНО: включает и ЛЕГАСИ-ключи прошлого overhaul'а (m80). Сухой прогон на снапшоте
# прода показал, что у m80 остались НЕперемапленные владельцы: psycho ×2, cavalry ×1 —
# они бы застряли на невыбираемом классе. Мапим всё, что не входит в шестёрку.
_REMAP = [
    # ── уходят в этой миграции (эпоха m80) ──
    ("legionnaire",   "tank"),         # строевой щитовик → щитовик
    ("spearman",      "tank"),         # копьё+щит → щитовик
    ("maul",          "berserk"),      # двуручный дробитель → двуручник
    ("assassin",      "berserk"),      # лёгкий дамаг-дилер → дамаг-дилер
    ("skirmisher",    "archer"),       # дистанционка → дистанционка
    ("lancer",        "knight"),       # лёгкая конница → конница
    # ── легаси-хвосты m80 (депрекейтнуты, но владельцы остались) ──
    ("psycho",        "berserk"),      # двуручник-ярость → берсерк
    ("cavalry",       "knight"),       # конница → конница
    ("camel_cavalry", "knight"),
    ("camel_archer",  "horse_archer"),
    ("heavy_archer",  "archer"),
    ("heavy_crossbow","crossbow"),
    ("infantry",      "tank"),         # мёртвый легаси-ключ из M15
]

# Финальные 6 — для страховочной сети (всё, что не в списке, уводим в дефолт).
_SIX = ("berserk", "tank", "archer", "crossbow", "knight", "horse_archer")
_FALLBACK_CLASS = "berserk"   # самый популярный; лучше живой класс, чем невыбираемый

_DEPRECATE = ["legionnaire", "spearman", "maul", "assassin", "skirmisher", "lancer"]

# Активки: (class_key, power_key, L1, L2, L3).
# rage — база всем; фирменные значения взяты из уже обкатанных строк (см. прод),
# чтобы не перебалансировать вслепую: rage 1.89/2.22/2.56 = «стрелковый» баланс,
# у берсерка исторически чуть ниже (1.76/…/2.43) — оставляем как есть, не трогаем.
_POWERS = [
    # ── база: rage каждому из 6 (у berserk/archer/horse_archer уже есть — upsert
    #    сохранит их значения только если совпадут; пишем их же цифры) ──
    ("berserk",      "rage", 1.76, 2.10, 2.43),
    ("archer",       "rage", 1.89, 2.22, 2.56),
    ("horse_archer", "rage", 1.89, 2.22, 2.56),
    ("tank",         "rage", 1.60, 1.90, 2.20),   # NEW: танку ярость слабее (он не про урон)
    ("crossbow",     "rage", 1.89, 2.22, 2.56),   # NEW
    ("knight",       "rage", 1.80, 2.10, 2.40),   # NEW
    # ── фирменные ──
    ("berserk",      "cleave",             0.40,  0.50,  0.60),   # как было
    ("tank",         "ironskin_toggle",   37.50, 56.25, 75.00),   # как было
    ("archer",       "explosive_arrows",  52.50, 78.75, 105.0),   # как было
    ("crossbow",     "shield_break_burst", 8.00, 10.00, 12.00),   # NEW (был у maul: 8/-/12)
    ("knight",       "berserker_charge",  50.00, 75.00, 100.0),   # NEW (был у berserk)
    ("horse_archer", "poison_dot",         8.00, 13.60, 19.20),   # NEW (был у assassin)
]

# Лишние АКТИВКИ у шестёрки → снять (пассивки не трогаем!). (class_key, power_key)
_DROP_ACTIVES = [
    ("berserk",      "berserker_charge"),   # уехал кавалеристу
    ("berserk",      "lifesteal_burst"),    # на полку; вампиризм остаётся ПАССИВКОЙ lifesteal_pct
    ("tank",         "shield_break_burst"), # уехал арбалетчику
    ("crossbow",     "explosive_arrows"),   # взрывные — идентичность лучника
    ("knight",       "ironskin_toggle"),    # уехал танку
    ("horse_archer", "explosive_arrows"),   # взрывные — идентичность лучника
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M92.classes_v2"):
        return

    # 1. Каталог шестёрки (deprecated=0 + свежие описания).
    for row in _CATALOG:
        await conn.execute(
            "INSERT OR REPLACE INTO bannerlord_classes "
            "(class_key, name, formation, slot1, slot2, slot3, slot4, "
            " use_horse, use_camel, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row)

    # 2. Remap живых героев с уходящих/легаси ключей (цели уже существуют → FK-safe).
    for old, new in _REMAP:
        await conn.execute(
            "UPDATE bannerlord_hero_class SET class_key=? WHERE class_key=?",
            (new, old))

    # 2b. Страховочная сеть: ЛЮБОЙ оставшийся ключ вне шестёрки (неизвестный легаси,
    # ручная правка, будущий дрейф) → дефолт. Иначе зритель застрянет на классе,
    # которого нет в picker'е: карточка не подсветится, силы могут не прийти.
    placeholders = ",".join("?" for _ in _SIX)
    cur = await conn.execute(
        f"SELECT class_key, COUNT(*) FROM bannerlord_hero_class "
        f"WHERE class_key NOT IN ({placeholders}) GROUP BY class_key", _SIX)
    stragglers = await cur.fetchall()
    if stragglers:
        await conn.execute(
            f"UPDATE bannerlord_hero_class SET class_key=? "
            f"WHERE class_key NOT IN ({placeholders})",
            (_FALLBACK_CLASS, *_SIX))
        print(f"M92: страховочная сеть увела в '{_FALLBACK_CLASS}': "
              + ", ".join(f"{k}×{n}" for k, n in stragglers))

    # 3. Soft-deprecate уходящих (скрыты из picker'а, строки живут для истории/FK).
    for ck in _DEPRECATE:
        await conn.execute(
            "UPDATE bannerlord_classes SET deprecated=1 WHERE class_key=?", (ck,))

    # 4. Активки: база (rage) + фирменная.
    for ck, pk, l1, l2, l3 in _POWERS:
        await conn.execute(
            "INSERT INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(class_key, power_key) DO UPDATE SET "
            "lvl1_value=excluded.lvl1_value, "
            "lvl2_value=excluded.lvl2_value, "
            "lvl3_value=excluded.lvl3_value",
            (ck, pk, l1, l2, l3))

    # 5. Снять лишние АКТИВКИ (ровно 3 кнопки: heal глобально + rage + фирменная).
    for ck, pk in _DROP_ACTIVES:
        await conn.execute(
            "DELETE FROM bannerlord_class_powers WHERE class_key=? AND power_key=?",
            (ck, pk))

    await conn.commit()
    await _mark_applied(conn, "M92.classes_v2")
    print(f"M92: classes v2 — {len(_CATALOG)} активных класса, "
          f"{len(_REMAP)} remap-правил, {len(_DEPRECATE)} deprecated, "
          f"{len(_POWERS)} power-строк, {len(_DROP_ACTIVES)} лишних активок снято")


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
