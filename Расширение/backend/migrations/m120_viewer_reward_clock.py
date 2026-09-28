"""Server reward clock survives retries, parallel workers and process restarts."""


async def apply(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS viewer_reward_clock (
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            last_tick INTEGER NOT NULL,
            PRIMARY KEY(channel_id, username)
        )
    """)
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied(name) VALUES (?)",
        ("M120.viewer_reward_clock",))
    await conn.commit()
