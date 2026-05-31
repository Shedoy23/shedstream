"""
Migration M64 — лук/арбалет: мелишный сайдарм + второй колчан.

2026-05-29. Дальнобойным классам добавлен второй боезапас и мелишное оружие
(полный «complete archer» loadout, BLT-style):

    archer          OneHandedWeapon + Arrows + Arrows          + Bow
    heavy_archer    TwoHandedWeapon + Arrows + Arrows          + Bow
    crossbow        OneHandedWeapon + Bolts  + Bolts           + Crossbow
    heavy_crossbow  TwoHandedWeapon + Bolts  + Bolts           + Crossbow
    horse_archer    Bow             + Arrows + OneHandedWeapon  + Arrows
    camel_archer    Bow             + Arrows + OneHandedWeapon  + Arrows

Тяжёлые варианты теперь = 2H melee + двойной боезапас (Щит убран ради 2-го
колчана и двуручки). Базовые = 1H + двойной боезапас. Конные/верблюжьи
лучники — 1H + 2-й колчан (Щит у них и не было).

Плюс psycho получил два набора метательных в свободные слоты:

    psycho          TwoHandedWeapon + Thrown + Thrown

M15 seed уже правлен для свежих установок; эта миграция обновляет
существующие prod-строки bannerlord_classes (catalog отдаётся фронту в
/api/bannerlord/classes → class picker). Реальный equip делает C#-мод по
своему hardcoded dict (SetClassHandler/UpgradeGearHandler), здесь только
витрина. Idempotent — фиксированный UPDATE + migrations_applied guard.
"""

# class_key → (slot1, slot2, slot3, slot4)
_ROWS = [
    ("archer",         "OneHandedWeapon", "Arrows", "Arrows",          "Bow"),
    ("heavy_archer",   "TwoHandedWeapon", "Arrows", "Arrows",          "Bow"),
    ("crossbow",       "OneHandedWeapon", "Bolts",  "Bolts",           "Crossbow"),
    ("heavy_crossbow", "TwoHandedWeapon", "Bolts",  "Bolts",           "Crossbow"),
    ("horse_archer",   "Bow",             "Arrows", "OneHandedWeapon", "Arrows"),
    ("camel_archer",   "Bow",             "Arrows", "OneHandedWeapon", "Arrows"),
    ("psycho",         "TwoHandedWeapon", "Thrown", "Thrown",          ""),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M64.ranged_loadout_quivers"):
        return

    updated = 0
    for class_key, s1, s2, s3, s4 in _ROWS:
        cur = await conn.execute(
            "UPDATE bannerlord_classes SET slot1=?, slot2=?, slot3=?, slot4=? "
            "WHERE class_key=?",
            (s1, s2, s3, s4, class_key))
        if cur.rowcount > 0:
            updated += 1

    await conn.commit()
    await _mark_applied(conn, "M64.ranged_loadout_quivers")
    print(f"M64: ranged loadout (archer/crossbow/horse_archer/camel_archer) "
          f"— {updated}/{len(_ROWS)} catalog rows updated (1H + 2nd quiver)")


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
