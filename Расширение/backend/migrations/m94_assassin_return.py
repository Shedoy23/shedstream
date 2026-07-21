"""
Migration M94: возвращение ассасина (7-й класс) с активкой «Невидимость».

m92 убрала ассасина в deprecated: после урезки до 6 классов он был «берсерк с
другим названием» — своей механики у него не было. Механика найдена (враги
теряют захват цели, см. docs/SPEC_ASSASSIN_INVIS.md) → класс возвращается.

Активки — та же схема «база + 1 фирменная» (ровно 3 кнопки):
  база:      heal_burst (глобально в routes/bannerlord.py) + rage
  фирменная: retribution_toggle

ВАЖНО про ключ активки: `retribution_toggle` — это НЕ отражение урона. Ключ
переиспользован под невидимость, потому что фронт заморожен на ревью Twitch, а
там у этого ключа УЖЕ есть ярлык (новый ключ = кнопки у зрителя просто нет).
Мод-сторона (ActivatePowerHandler/PowersMissionBehavior) трактует его как
невидимость, отражение с него снято. В день разморозки фронта — переименовать
в расширении, БД трогать не придётся.

Значения retribution_toggle = ОКНО РАСКРЫТИЯ ПОСЛЕ УДАРА в секундах, поэтому
они ПАДАЮТ с уровнем (прокачка = быстрее растворяешься обратно). Это осознанно,
а не опечатка.

Пассивки ассасина (hp 0.85-1.05 / скорость / body_scale 0.92 / скиллы) остались
от прошлого ростера и роли соответствуют: хрупкий, быстрый, мелкая мишень —
поэтому НЕ трогаем. Правим только каталог + активки.

Мод-сторона (снаряжение, формация, турнир, награда за килл) ассасина не теряла —
она жива с прошлого ростера; добавлен только разбойничий культурный скин.

Idempotent: migrations_applied['M94.assassin_return'] + INSERT OR REPLACE / upsert / DELETE.
"""

_CLASS_KEY = "assassin"

# Описание идёт с бэка и НЕ заморожено — здесь же честно объясняем зрителю
# временное расхождение в подписи кнопки, чтобы не путался в чате.
_DESCRIPTION = (
    "Кинжал и метательные ножи, разбойничий капюшон. Бьёт слабо и умирает быстро — "
    "живёт скрытностью: активка прячет его, и враги теряют цель на 45 секунд "
    "(удар ненадолго выдаёт). Кнопка пока подписана «Стойкость» — переименуем "
    "в ближайшем обновлении расширения."
)

# (class_key, name, formation, slot1..slot4, use_horse, use_camel, description)
_CATALOG_ROW = (
    _CLASS_KEY, "Убийца", "Infantry",
    "OneHandedWeapon", "Thrown", "", "",
    0, 0, _DESCRIPTION,
)

# Активки ассасина. (power_key, L1, L2, L3)
_POWERS = [
    # База. Урон у него низкий — множитель на уровне стрелков, чтобы окно
    # невидимости во что-то конвертировалось.
    ("rage",               1.85, 2.20, 2.55),
    # Фирменная: невидимость. Значение = окно раскрытия после удара (сек), ВНИЗ.
    ("retribution_toggle", 4.00, 3.00, 2.00),
]

# Все известные АКТИВНЫЕ ключи — всё, что не rage/retribution_toggle, снимаем с
# ассасина, иначе у него будет 4-5 кнопок вместо трёх (историю ему насеяли m50/
# m61/m78: poison_dot, lifesteal_burst, cleave). Список, а не «удалить всё» —
# ПАССИВКИ (hp_multiplier / move_speed_pct / lifesteal_pct / *_boost / body_scale)
# трогать нельзя, они и есть его роль.
_ACTIVE_KEYS = (
    "heal_burst", "shield_break_burst", "rage", "retribution_toggle",
    "poison_dot", "disarm_burst", "berserker_charge",
    "lifesteal_burst", "ironskin_toggle", "explosive_arrows", "cleave",
)
_KEEP = ("rage", "retribution_toggle")


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M94.assassin_return"):
        return

    # 1. Каталог: вернуть строку (INSERT OR REPLACE сбросит deprecated в DEFAULT 0,
    #    но ставим явно — не полагаемся на дефолт колонки).
    await conn.execute(
        "INSERT OR REPLACE INTO bannerlord_classes "
        "(class_key, name, formation, slot1, slot2, slot3, slot4, "
        " use_horse, use_camel, description) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _CATALOG_ROW)
    await conn.execute(
        "UPDATE bannerlord_classes SET deprecated=0 WHERE class_key=?", (_CLASS_KEY,))

    # 2. Активки: база + фирменная.
    for pk, l1, l2, l3 in _POWERS:
        await conn.execute(
            "INSERT INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(class_key, power_key) DO UPDATE SET "
            "lvl1_value=excluded.lvl1_value, "
            "lvl2_value=excluded.lvl2_value, "
            "lvl3_value=excluded.lvl3_value",
            (_CLASS_KEY, pk, l1, l2, l3))

    # 3. Снять лишние активки (пассивки не трогаем).
    drop = [k for k in _ACTIVE_KEYS if k not in _KEEP]
    placeholders = ",".join("?" for _ in drop)
    await conn.execute(
        f"DELETE FROM bannerlord_class_powers "
        f"WHERE class_key=? AND power_key IN ({placeholders})",
        (_CLASS_KEY, *drop))

    await conn.commit()
    await _mark_applied(conn, "M94.assassin_return")
    print(f"M94: ассасин возвращён в ростер (7 классов), активки: "
          f"{', '.join(_KEEP)} + heal_burst (глобальный)")


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
