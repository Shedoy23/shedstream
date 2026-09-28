# -*- coding: utf-8 -*-
"""M111 — bind every Manager session to the module approved in pairing.

Rows created by an experimental pre-M111 build remain NULL and are denied by
credential issuance. No existing production connector/session is affected.
"""


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in await cur.fetchall())


async def apply(conn) -> None:
    name = "M111.manager_session_scope"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name=?", (name,)
    )
    if await cur.fetchone():
        return

    if not await _has_column(conn, "manager_sessions", "module_id"):
        await conn.execute("ALTER TABLE manager_sessions ADD COLUMN module_id TEXT")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_manager_sessions_scope "
        "ON manager_sessions(channel_id, module_id, revoked_at, expires_at)"
    )
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M111: Manager sessions bound to approved module scope")
