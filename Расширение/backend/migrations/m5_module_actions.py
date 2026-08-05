"""
Migration m5_module_actions: outbox для Module API actions (этап 3 step 3).

Таблица очереди actions, которые core отправляет connector'ам игровых модулей.
Connector long-poll'ит `GET /v1/module/<id>/actions?since=<cursor>`, исполняет
команды в игре, отвечает `POST /v1/module/<id>/ack {action_id, success}`.

Lifecycle одной записи:
  queued     — INSERT'нута dispatch_action'ом, ждёт что connector её заберёт
  dispatched — connector long-poll забрал, ждём ACK
  acked      — connector подтвердил успешное исполнение
  failed     — connector ACK'нул с success=false (error_msg хранит причину)

Идемпотентность: PK миграции — `M5.module_actions.create`.
"""


SCHEMA = """
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id    INTEGER NOT NULL,
    module_id     TEXT NOT NULL,
    action_id     TEXT NOT NULL,           -- envelope.id, выданный caller'ом
    type          TEXT NOT NULL,            -- player.spawn / world.trigger_event / pawn.add_gene / ...
    data          TEXT NOT NULL DEFAULT '{}', -- JSON-сериализованный envelope.data
    status        TEXT NOT NULL DEFAULT 'queued',
                                            -- queued / dispatched / acked / failed
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dispatched_at TIMESTAMP,
    acked_at      TIMESTAMP,
    error_msg     TEXT,
    ack_received_at TIMESTAMP,             -- receipt даже для terminal action
    ack_success     INTEGER,               -- 1/0 из последнего ACK connector'а
    ack_error       TEXT                   -- error из последнего ACK
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M5.module_actions.create"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS module_actions ({SCHEMA})")

    # Composite index для long-poll query: WHERE channel_id=? AND module_id=?
    # AND status='queued' AND id > since ORDER BY id LIMIT N.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_module_actions_polling
        ON module_actions(channel_id, module_id, status, id)
    """)
    # Lookup index для ACK по action_id (envelope id, не PK):
    # WHERE channel_id=? AND module_id=? AND action_id=?
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_module_actions_ack
        ON module_actions(channel_id, module_id, action_id)
    """)
    await conn.commit()
    print("✅ M5: module_actions table + indexes created")

    await _mark_applied(conn, "M5.module_actions.create")


async def _ensure_migrations_table(conn) -> None:
    """Создаётся в M1 + M4, defensive duplicate."""
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
