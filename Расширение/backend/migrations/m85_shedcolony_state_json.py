"""
Migration M85: shedcolony — rich colonist state blob.

Adds shedcolony_colonist_state.state_json — the full per-colonist snapshot the mod sends
(hp/max_hp/saturation/happiness/status flags/job/all skills), so the extension can show the
viewer everything about their colonist. The existing hp/job/skills_json/status columns stay
(filled for back-compat); state_json holds the complete blob.

Idempotent: migrations_applied['M85.shedcolony_state_json'] + a column-exists guard.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M85.shedcolony_state_json"):
        return

    cur = await conn.execute("PRAGMA table_info(shedcolony_colonist_state)")
    cols = [r[1] for r in await cur.fetchall()]
    if "state_json" not in cols:
        await conn.execute("ALTER TABLE shedcolony_colonist_state ADD COLUMN state_json TEXT")

    await conn.commit()
    await _mark_applied(conn, "M85.shedcolony_state_json")
    print("M85: shedcolony_colonist_state.state_json added")


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
