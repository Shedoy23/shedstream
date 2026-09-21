"""Sequence fence for game-owned tournament queue snapshots."""
async def apply(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS bannerlord_tournament_queue_sync (
        channel_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, queue_seq INTEGER NOT NULL
    )""")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES (?)", ('M128.bannerlord_tournament_queue_sync',))
    await conn.commit()
