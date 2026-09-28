"""
Migration M47 — `bannerlord_heroes.tournament_wins` column.

Sprint 5.32 (BLT-parity H8) — persistent anti-snowball debuff.

Раньше TournamentMissionBehavior._recentWinners был **static List в C#** —
жил только пока процесс мода в памяти. При reload save файла / restart игры
весь debuff сбрасывался. Стример рестартует игру → анти-сноубол выключился,
не зная об этом → топ-1 viewer снова безнаказанно доминирует.

Решение: persistent storage на стороне backend.
  bannerlord_heroes.tournament_wins INT NOT NULL DEFAULT 0
  ↑ инкрементируется через player.state_update events
  ↑ mod при старте турнира GET'ит top-N usernames для анти-сноубол list'а

Idempotent: ALTER TABLE ADD COLUMN на existing rows проставит DEFAULT 0.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M47.tournament_wins"):
        return

    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    cols = {row[1] for row in await cur.fetchall()}
    if "tournament_wins" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_heroes "
            "ADD COLUMN tournament_wins INTEGER NOT NULL DEFAULT 0"
        )
        print("M47: bannerlord_heroes.tournament_wins column added")
    else:
        print("M47: tournament_wins column already exists, skipped ALTER")

    # Index для быстрого `ORDER BY tournament_wins DESC LIMIT N` на старте турнира.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_heroes_tournament_wins
        ON bannerlord_heroes(channel_id, tournament_wins DESC)
    """)

    await conn.commit()
    await _mark_applied(conn, "M47.tournament_wins")


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
