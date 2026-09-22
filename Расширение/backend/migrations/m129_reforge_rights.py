"""Immutable paid requests survive campaign rollback; mirrors may still report truth."""
async def apply(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS bannerlord_reforge_rights(
        channel_id INTEGER NOT NULL, action_id TEXT NOT NULL, save_id TEXT NOT NULL,
        hero_id TEXT NOT NULL, username TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL,
        modifier_id TEXT NOT NULL, rank INTEGER NOT NULL, state TEXT NOT NULL,
        PRIMARY KEY(channel_id,action_id))""")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_reforge_owner ON bannerlord_reforge_rights(channel_id,save_id,hero_id,username,slot,item_id,state)")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M129.reforge_rights')")
    await conn.commit()
