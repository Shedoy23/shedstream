"""
Migration M23: bannerlord_retinue — hero's свита (BLT-style).

Каждый viewer владеет hero'ем + до 10 retinue troops. Команда
`hero.recruit_troops`:
  • Empty slot → add basic troop из hero culture (Tier 1)
  • Max → upgrade lowest-tier troop (engine UpgradeTargets.SelectRandom)
Cost: per-tier (in-game Hero.Gold) — mirror BLT defaults.

При summon hero в battle (player.spawn) — mod также spawn'ит retinue
agents рядом с hero (BLT pattern, BLTSummonBehavior).

Schema:
  channel_id  INTEGER
  username    TEXT
  slot_index  INTEGER          — 0..MAX_RETINUE-1
  troop_id    TEXT             — current CharacterObject.StringId
  troop_name  TEXT             — display name (для UI)
  tier        INTEGER          — engine tier 0-5
  PRIMARY KEY (channel_id, username, slot_index)

Idempotent через migrations_applied['M23.retinue'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M23.retinue"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_retinue (
            channel_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            slot_index  INTEGER NOT NULL,
            troop_id    TEXT NOT NULL,
            troop_name  TEXT,
            tier        INTEGER DEFAULT 0,
            PRIMARY KEY (channel_id, username, slot_index)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_retinue_lookup
            ON bannerlord_retinue(channel_id, username)
    """)

    await conn.commit()
    await _mark_applied(conn, "M23.retinue")
    print("M23: bannerlord_retinue created (BLT-style свита)")


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
