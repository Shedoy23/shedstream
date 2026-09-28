"""
Migration M50 — Character Effects (BLT-Buffet inspired) для variety классов.

Sprint 5.33 — расширяет bannerlord_class_powers seed на 3 new effects:

  poison_dot         — assassin
    Random enemy получает DoT 5/8/12 dmg/sec, 10s. Greenish particle.

  disarm_burst       — horse_archer / camel_archer
    Random enemy роняет wielded weapon. Instant flash particle.

  berserker_charge   — psycho / berserk
    Self +50/+70/+100% movement speed 8s. Red trail particle.

Каждый — 3 levels (lvl1/2/3) согласно class_level.

Idempotent: INSERT OR IGNORE по PRIMARY KEY (class_key, power_key).
"""

_ROWS = [
    # class_key,        power_key,            lvl1, lvl2, lvl3
    ("assassin",        "poison_dot",         5.0,  8.0,  12.0),
    ("horse_archer",    "disarm_burst",       1.0,  1.0,  1.0),    # binary action; lvl изменяет cooldown via POWER_COOLDOWNS
    ("camel_archer",    "disarm_burst",       1.0,  1.0,  1.0),
    ("psycho",          "berserker_charge",   50.0, 70.0, 100.0),  # speed bonus %
    ("berserk",         "berserker_charge",   50.0, 70.0, 100.0),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M50.character_effects"):
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
    await _mark_applied(conn, "M50.character_effects")
    print(f"M50: character effects seeded — {inserted}/{len(_ROWS)} new rows")


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
