"""
Migration M24: bannerlord_tournament_queue + bannerlord_tournament_state.

BLT-style turnirы для зрителей. Viewer'ы платят entry fee (5K Hero.Gold)
чтобы попасть в очередь, стример заходит в town_arena и через game menu
запускает viewer tournament.

Tables:
  bannerlord_tournament_queue
    channel_id  INTEGER         — tenant
    username    TEXT            — viewer
    entry_fee   INTEGER         — paid Hero.Gold (для refund/payout)
    joined_at   TIMESTAMP       — для сортировки очереди
    PK(channel_id, username)

  bannerlord_tournament_state
    channel_id   INTEGER PK     — singleton per tenant
    status       TEXT           — 'idle' | 'running' | 'finished'
    current_round INTEGER       — 0..3 (4-round bracket, Bannerlord default)
    participants TEXT           — JSON array of usernames (snapshot)
    last_winner  TEXT           — username (последний турнир)
    started_at   TIMESTAMP

Mod является source-of-truth для queue (Hero.Gold списывается там),
backend хранит mirror для UI + bets.

Idempotent через migrations_applied['M24.tournament'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M24.tournament"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_tournament_queue (
            channel_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            entry_fee   INTEGER DEFAULT 0,
            joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_tourn_queue_channel
            ON bannerlord_tournament_queue(channel_id, joined_at)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_tournament_state (
            channel_id    INTEGER PRIMARY KEY,
            status        TEXT DEFAULT 'idle',
            current_round INTEGER DEFAULT 0,
            participants  TEXT,
            last_winner   TEXT,
            started_at    TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M24.tournament")
    print("M24: bannerlord_tournament_queue + _state created")


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
