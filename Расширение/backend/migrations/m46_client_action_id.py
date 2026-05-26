"""
Migration M46 — `module_actions.client_action_id` column + unique partial index.

Sprint 5.32 (BLT-parity H1) — idempotent action POST.

Проблема: frontend retry (network blip, slow ACK, multi-click) → второй POST с
тем же intent → backend charge'ит крустики дважды + enqueue два action'а в outbox.
Защита через `inFlight` Set на фронте (audit-fix #35) — спасает от React
double-render, но не от network retry (browser fetch не retry-safe; промежуточный
proxy/CDN может реплеить запрос).

Решение: client_action_id (UUID v4, генерируется на стороне frontend перед POST)
с server-side UNIQUE constraint. Идемпотентность через "вставил → если конфликт
по client_action_id, верни прежний result без charge". BLT-style (BLT использует
Twitch redemption-id как natural key — у нас нет такого, сами генерим).

Schema:
  client_action_id  TEXT NULL  -- backwards-compat (старые actions без id)
  UNIQUE INDEX (channel_id, module_id, client_action_id) WHERE NOT NULL
                    -- partial index: NULL'ы не блокируются (старые actions)

Idempotent: ALTER TABLE ADD COLUMN на existing rows проставит NULL.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M46.client_action_id"):
        return

    # Check existing schema before ALTER.
    cur = await conn.execute("PRAGMA table_info(module_actions)")
    cols = {row[1] for row in await cur.fetchall()}
    if "client_action_id" not in cols:
        await conn.execute(
            "ALTER TABLE module_actions ADD COLUMN client_action_id TEXT"
        )
        print("M46: module_actions.client_action_id column added")
    else:
        print("M46: client_action_id column already exists, skipped ALTER")

    # Partial UNIQUE index — NULL'ы не блокируются, dedup'ятся только
    # реальные id'ы. SQLite поддерживает partial indexes (WHERE clause).
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_module_actions_client_id
        ON module_actions(channel_id, module_id, client_action_id)
        WHERE client_action_id IS NOT NULL
    """)
    print("M46: idx_module_actions_client_id partial unique index created")

    await conn.commit()
    await _mark_applied(conn, "M46.client_action_id")


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
