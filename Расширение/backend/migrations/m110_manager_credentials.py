# -*- coding: utf-8 -*-
"""M110 — persistent Manager pairing, sessions and revocable module credentials.

Only hashes are stored. The migration introduces no issuance endpoint and does
not change legacy HMAC module-token verification, so deploying the schema alone
cannot alter a running connector.
"""


async def apply(conn) -> None:
    name = "M110.manager_credentials"
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    if await cur.fetchone():
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_pairings (
            id                    TEXT PRIMARY KEY,
            device_challenge      TEXT NOT NULL,
            user_code_hash        TEXT NOT NULL UNIQUE,
            installation_id_hash  TEXT NOT NULL,
            module_id             TEXT NOT NULL,
            channel_id            INTEGER,
            status                TEXT NOT NULL DEFAULT 'pending'
                                  CHECK (status IN (
                                      'pending', 'approved', 'denied',
                                      'exchanged', 'expired')),
            created_at            REAL NOT NULL,
            expires_at            REAL NOT NULL,
            approved_at           REAL,
            exchanged_at          REAL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_manager_pairings_expiry "
        "ON manager_pairings(status, expires_at)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_sessions (
            id                    TEXT PRIMARY KEY,
            channel_id            INTEGER NOT NULL,
            installation_id_hash  TEXT NOT NULL,
            refresh_hash          TEXT NOT NULL UNIQUE,
            refresh_family_id     TEXT NOT NULL,
            created_at            REAL NOT NULL,
            expires_at            REAL NOT NULL,
            last_used_at          REAL,
            revoked_at            REAL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_manager_sessions_channel "
        "ON manager_sessions(channel_id, revoked_at, expires_at)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_manager_sessions_family "
        "ON manager_sessions(refresh_family_id, revoked_at)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS module_credentials (
            id               TEXT PRIMARY KEY,
            channel_id       INTEGER NOT NULL,
            module_id        TEXT NOT NULL,
            secret_hash      TEXT NOT NULL UNIQUE,
            label            TEXT NOT NULL DEFAULT '',
            created_at       REAL NOT NULL,
            expires_at       REAL NOT NULL,
            last_used_at     REAL,
            rotated_from_id  TEXT,
            overlap_until    REAL,
            revoked_at       REAL,
            FOREIGN KEY (rotated_from_id) REFERENCES module_credentials(id)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_module_credentials_scope "
        "ON module_credentials(channel_id, module_id, revoked_at, expires_at)"
    )

    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
    print("✅ M110: Manager pairing and revocable credential ledger created")
