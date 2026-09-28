"""M125: save/hero-scoped authoritative equipment snapshots."""


async def apply(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_inventory_snapshots (
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            save_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            hero_id TEXT NOT NULL,
            inventory_seq INTEGER NOT NULL,
            items_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (channel_id, username)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_equipment_sessions (
            channel_id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            session_ts INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied(name) VALUES (?)",
        ("M125.bannerlord_inventory",))
    await conn.commit()
