# -*- coding: utf-8 -*-
"""M112 — persistent Manager test-action results."""


async def apply(conn) -> None:
    name = "M112.manager_diagnostics"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_diagnostic_actions (
            diagnostic_id TEXT PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            module_id TEXT NOT NULL,
            command_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN
                ('queued','delivered','acked','failed','expired')),
            created_at REAL NOT NULL,
            completed_at REAL,
            error TEXT
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_manager_diagnostics_scope "
        "ON manager_diagnostic_actions(channel_id,module_id,created_at)"
    )
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M112: Manager diagnostic action ledger created")
