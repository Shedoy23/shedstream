"""
Migration M39 — Achievements система для Bannerlord-зрителей.

Sprint 5.29 / BLT-parity #5.

Schema:
  bannerlord_user_stats
    channel_id INT, username TEXT, stat_key TEXT, value INT
    PRIMARY KEY (channel_id, username, stat_key)

  bannerlord_achievements_unlocked
    channel_id INT, username TEXT, achievement_id TEXT, unlocked_at TIMESTAMP
    PRIMARY KEY (channel_id, username, achievement_id)

Stats updated incrementally от events:
  kills (battle.stats_snapshot per username)
  tournament_wins, tournament_participations
  clan_created, kingdom_created, party_created
  level_max, gold_max (high-water-mark от player.state_update)
  children_count (from family_info snapshot)

Achievements — hardcoded в backend/routes/bannerlord_achievements.py
(вынесено отдельно от migration чтобы можно было добавлять без migration'ов).

Idempotent.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M39.achievements"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_user_stats (
            channel_id  INTEGER NOT NULL,
            username    TEXT    NOT NULL,
            stat_key    TEXT    NOT NULL,
            value       INTEGER NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, stat_key)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_stats_user
        ON bannerlord_user_stats (channel_id, username)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_achievements_unlocked (
            channel_id      INTEGER NOT NULL,
            username        TEXT    NOT NULL,
            achievement_id  TEXT    NOT NULL,
            unlocked_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, achievement_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_ach_user
        ON bannerlord_achievements_unlocked (channel_id, username)
    """)

    await conn.commit()
    await _mark_applied(conn, "M39.achievements")
    print("M39: bannerlord_user_stats + bannerlord_achievements_unlocked tables created")


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
