"""
Migration M49 — `bannerlord_marriage_proposals` table для viewer↔viewer
браков между их детьми (BLT-parity, Randomchair22 fork inspiration).

Sprint 5.33 — viewer A проdpoзpaгaет viewer B'у "поженить наших детей".
Target user принимает / отклоняет / proposal expires через 24h.
При accept'е mod-handler `hero.activate_marriage` физически жениет 2 героев
в game world. Дети живут отдельно, могут иметь grandchildren (loop retention).

Schema:
  id                       INTEGER PK auto-increment
  channel_id               INT — multi-tenant scope
  proposer_username        viewer A
  proposer_child_hero_id   Hero.StringId ребёнка A
  proposer_child_name      readable name (для UI)
  target_username          viewer B
  target_child_hero_id     Hero.StringId ребёнка B
  target_child_name        readable name
  status                   'pending' | 'accepted' | 'rejected' | 'expired' | 'cancelled'
  created_at, expires_at (default +24h), resolved_at

Idempotent: CREATE TABLE IF NOT EXISTS.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M49.marriage_proposals"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_marriage_proposals (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id              INTEGER NOT NULL,
            proposer_username       TEXT    NOT NULL,
            proposer_child_hero_id  TEXT    NOT NULL,
            proposer_child_name     TEXT    NOT NULL,
            target_username         TEXT    NOT NULL,
            target_child_hero_id    TEXT    NOT NULL,
            target_child_name       TEXT    NOT NULL,
            status                  TEXT    NOT NULL DEFAULT 'pending',
            created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at              TIMESTAMP NOT NULL,
            resolved_at             TIMESTAMP
        )
    """)
    print("M49: bannerlord_marriage_proposals table created")

    # Inbox lookup для UI (GET /api/bannerlord/proposals/incoming?user=...)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_proposals_target
        ON bannerlord_marriage_proposals(channel_id, target_username, status, created_at)
    """)
    # Outbox lookup
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_proposals_proposer
        ON bannerlord_marriage_proposals(channel_id, proposer_username, status, created_at)
    """)
    # Dedup constraint — нельзя 2 pending proposals для одной пары детей одновременно.
    # SQLite partial unique index — works как у m46.
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_unique_pending
        ON bannerlord_marriage_proposals(channel_id, proposer_child_hero_id, target_child_hero_id)
        WHERE status = 'pending'
    """)
    print("M49: indexes created")

    await conn.commit()
    await _mark_applied(conn, "M49.marriage_proposals")


async def _ensure_migrations_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
