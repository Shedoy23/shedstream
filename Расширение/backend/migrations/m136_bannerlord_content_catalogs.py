"""Game-owned content snapshots, including explicitly empty catalogs."""
async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    name = 'M136.bannerlord_content_catalogs'  # 02.10: was M134, renumbered to avoid clash with m134_ui_usage (skill-minigames)
    if await (await conn.execute('SELECT 1 FROM migrations_applied WHERE name=?', (name,))).fetchone():
        return
    await conn.execute('''CREATE TABLE IF NOT EXISTS bannerlord_content_catalogs (
        channel_id INTEGER NOT NULL,
        catalog_type TEXT NOT NULL,
        save_id TEXT NOT NULL,
        equipment_session_id TEXT NOT NULL,
        catalog_seq INTEGER NOT NULL,
        entries_json TEXT NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(channel_id, catalog_type)
    )''')
    await conn.execute('INSERT INTO migrations_applied(name) VALUES(?)', (name,))
    await conn.commit()
