"""Keep personal game progression with the session-owned inventory snapshot."""
async def apply(conn):
    name='M137.bannerlord_progression'  # 02.10: was M135 (clash with m135_skillgames)
    if await (await conn.execute('SELECT 1 FROM migrations_applied WHERE name=?',(name,))).fetchone():
        return
    columns={row[1] for row in await (await conn.execute('PRAGMA table_info(bannerlord_inventory_snapshots)')).fetchall()}
    if 'progression_json' not in columns:
        await conn.execute("ALTER TABLE bannerlord_inventory_snapshots ADD COLUMN progression_json TEXT NOT NULL DEFAULT '{}'")
    await conn.execute('INSERT INTO migrations_applied(name) VALUES(?)',(name,))
    await conn.commit()
