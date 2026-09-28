"""M127: native party ownership/availability travels with its ordered snapshot."""


async def apply(conn):
    cur = await conn.execute("PRAGMA table_info(bannerlord_inventory_snapshots)")
    if 'inventory_state_json' not in {row[1] for row in await cur.fetchall()}:
        await conn.execute("ALTER TABLE bannerlord_inventory_snapshots ADD COLUMN inventory_state_json TEXT NOT NULL DEFAULT '{}'")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES (?)", ('M127.bannerlord_inventory_state',))
    await conn.commit()
