"""
Migration M82: baseline 5% lifesteal для классов без сустейна (owner request).

Владелец: «дать всем ~5% вампиризма, кроме берсерка и убийцы (у них оставить)».
Уже имеют lifesteal_pct ≥5% (не трогаем): archer, crossbow, knight, horse_archer,
+ berserk/assassin (их своё, выше). НЕ имеют совсем → добавляем flat 5/5/5:
tank, legionnaire, spearman, maul, skirmisher, lancer.

lifesteal_pct — пассивка (always-on heal-on-hit), читается модом из PowerCache →
data-only, без пересборки мода.

INSERT OR IGNORE = не перезатираем существующие значения (страховка). Эти 6 строк
не имеют → вставится 5/5/5.

Idempotent: migrations_applied['M82.lifesteal_baseline'].
"""

_BASELINE = ["tank", "legionnaire", "spearman", "maul", "skirmisher", "lancer"]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M82.lifesteal_baseline"):
        return

    for ck in _BASELINE:
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_class_powers "
            "(class_key, power_key, lvl1_value, lvl2_value, lvl3_value) "
            "VALUES (?, 'lifesteal_pct', 5, 5, 5)",
            (ck,))

    await conn.commit()
    await _mark_applied(conn, "M82.lifesteal_baseline")
    print(f"M82: baseline 5% lifesteal → {len(_BASELINE)} classes (insert-if-absent)")


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
