"""Index recent module actions by time for the /my-hero refund toast.

25.09.2026: `RECENT_REFUNDS_SQL` (routes/bannerlord.py) looked for refunds of
the last 30 seconds but the only usable index was (channel_id, module_id,
action_id) — every /my-hero poll scanned and sorted all ~27k actions of the
channel (153 ms on prod), about a third of the single CPU during a stream.
"""
async def apply(conn):
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_module_actions_recent "
        "ON module_actions(channel_id, module_id, created_at)")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M132.module_actions_recent_index')")
    await conn.commit()
