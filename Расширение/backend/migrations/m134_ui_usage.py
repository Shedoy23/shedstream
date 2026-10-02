"""M134: bounded UI intent aggregates, separate from accepted/game actions.

No backfill: frozen clients did not send semantic UI events. Viewer identity is
an already-signed Twitch user_id; batch UUIDs only deduplicate transport retries.
"""


async def apply(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS migrations_applied (name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    await conn.execute('''CREATE TABLE IF NOT EXISTS ui_feature_usage (
        channel_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        viewer_id TEXT NOT NULL,
        client TEXT NOT NULL,
        surface TEXT NOT NULL,
        module_id TEXT NOT NULL,
        active_module TEXT NOT NULL,
        kind TEXT NOT NULL,
        feature_key TEXT NOT NULL,
        count INTEGER NOT NULL CHECK(count > 0),
        PRIMARY KEY(channel_id, day, viewer_id, client, surface, module_id,
                    active_module, kind, feature_key)
    )''')
    await conn.execute('''CREATE TABLE IF NOT EXISTS ui_usage_batches (
        channel_id INTEGER NOT NULL,
        viewer_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY(channel_id, viewer_id, batch_id)
    )''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_ui_usage_batches_retention ON ui_usage_batches(channel_id, created_at)')
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M134.ui_usage')")
    await conn.commit()
