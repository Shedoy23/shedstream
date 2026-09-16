"""M126: mirror save-owned build in the existing ordered inventory snapshot."""


async def apply(conn):
    cur = await conn.execute("PRAGMA table_info(bannerlord_inventory_snapshots)")
    if 'build_json' not in {row[1] for row in await cur.fetchall()}:
        await conn.execute("ALTER TABLE bannerlord_inventory_snapshots ADD COLUMN build_json TEXT NOT NULL DEFAULT '{}'")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES (?)", ('M126.bannerlord_build',))
    await conn.commit()
