"""
Migration M70 — bannerlord_heroes.combat_stance.

2026-06-10. Зритель выбирает боевую стойку СВОЕГО бойца: defensive / balanced /
aggressive (сдвиг блок/парри vs атака в боевом ИИ). Мод применяет (PowerCache +
PowersMissionBehavior.ApplyCombatAiTick) и эхо-пушит стойку сюда через
player.state_update; /my-hero и /class-state отдают её фронту/моду.

Guarded ALTER (PRAGMA table_info) — идемпотентно на existing prod БД.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M70.combat_stance"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    cols = [r[1] for r in await cur.fetchall()]
    if "combat_stance" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes "
            "ADD COLUMN combat_stance TEXT DEFAULT 'balanced'")
        print("M70: bannerlord_heroes.combat_stance column added")
    else:
        print("M70: combat_stance column already exists")

    await conn.commit()
    await _mark_applied(conn, "M70.combat_stance")


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
