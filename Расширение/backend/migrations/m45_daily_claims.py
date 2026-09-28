"""
Migration M45 — `bannerlord_daily_claims` table.

Sprint 5.32 (BLT-parity #46) — daily rewards для виральности UX. Viewer
получает 1 раз в день (UTC) либо 100K💰 динаров либо 50K XP в random skill.
Открывает расширение каждый день за бонусом → больше engagement, больше
shoppers для крустиков.

Reset cycle: midnight UTC. PRIMARY KEY (channel_id, username, claim_date) —
дубликат INSERT'а тихо проваливается (ON CONFLICT DO NOTHING), но эндпойнт
checks before INSERT и возвращает "уже забирал".

reward_type: 'gold' | 'xp' (что viewer выбрал).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M45.daily_claims"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_daily_claims (
            channel_id  INTEGER NOT NULL,
            username    TEXT    NOT NULL,
            claim_date  DATE    NOT NULL,
            reward_type TEXT    NOT NULL,
            claimed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, claim_date)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_claims_channel_user
        ON bannerlord_daily_claims (channel_id, username, claim_date DESC)
    """)

    await conn.commit()
    await _mark_applied(conn, "M45.daily_claims")
    print("M45: bannerlord_daily_claims table created")


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
