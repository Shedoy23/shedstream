"""Bind daily reservations to the exact action so late failure cannot erase a retry."""
async def apply(conn):
    cols={r[1] for r in await (await conn.execute('PRAGMA table_info(bannerlord_daily_claims)')).fetchall()}
    if 'action_id' not in cols:
        await conn.execute('ALTER TABLE bannerlord_daily_claims ADD COLUMN action_id TEXT')
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M128.daily_claim_action')")
    await conn.commit()
