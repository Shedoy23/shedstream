"""
Migration M56 — Fief tributes (BLT-parity, kingdom-scale passive income).

Sprint 5.33 FIEF — viewer-owned fiefs (town/castle/village) автоматически
генерируют ⦷ через engine-natural income. Mod каждый game-day diff'ит
Town.Gold / Village.Hearth, backend конвертирует в crustic (200:1 — fiefs
дают меньше per dinar чем workshops чтобы не overpower клан-leader'ов).

Optional active action: hero.tribute_boost — 2000⦷ → 7 days +50% tribute
multiplier на конкретный fief. Король может концентрировать buff на топ-fief.

Schema:
  id                    INTEGER PK
  channel_id            INT
  owner_username        viewer (Hero owner)
  fief_id               TaleWorlds Settlement.StringId
  fief_name             UI display
  fief_type             town / castle / village
  total_collected_dinars INT cumulative
  boost_until           TIMESTAMP nullable — active boost expiry
  last_synced_at        TIMESTAMP

UNIQUE — (channel_id, fief_id) — один fief = один row (даже если переходит
между viewers, тот же row обновляется с новым owner_username).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M56.fiefs"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_fiefs (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id               INTEGER NOT NULL,
            owner_username           TEXT    NOT NULL,
            fief_id                  TEXT    NOT NULL,
            fief_name                TEXT,
            fief_type                TEXT    NOT NULL,
            total_collected_dinars   INTEGER NOT NULL DEFAULT 0,
            boost_until              TIMESTAMP,
            last_synced_at           TIMESTAMP,
            opened_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, fief_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fiefs_owner
        ON bannerlord_fiefs(channel_id, owner_username)
    """)
    print("M56: bannerlord_fiefs created")

    await conn.commit()
    await _mark_applied(conn, "M56.fiefs")


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
