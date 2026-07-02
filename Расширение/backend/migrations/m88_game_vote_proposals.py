"""
Migration M88: «Народный выбор игры» — viewer-предложения в голосование (2026-07-02).

Апгрейд системы голосования (m12): стример-триггерный «открытый» раунд, где зритель
может ПРЕДЛОЖИТЬ свою игру (не только голосовать за шаблонные варианты стримера).
Предложение с вкладом уходит в очередь → стример одобряет → игра появляется в вотуме
с этим пулом. Отклонил → ничего не списывается.

Compliance (docs/COMPLIANCE_GAME_VOTE_2026-07-02.md): UGC-модерация §7 — стример видит
ник автора и удаляет/отклоняет любое предложение; без выплат/возвратов; списание строго
после одобрения (см. database.approve_voting_proposal).

Изменения схемы:
  - voting_events += allow_proposals (0/1) — открытые раунды разрешают предложения.
    Авто-старт по шаблону (m12) остаётся allow_proposals=0 — поведение не меняется.
  - voting_proposals — очередь предложений (pending/approved/rejected) с ником автора
    (§7 attribution) и пледжем (списывается на approve).

Идемпотентно: migrations_applied['M88.game_vote_proposals'] + IF NOT EXISTS + PRAGMA-гард.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M88.game_vote_proposals"):
        return

    # 1. Флаг «раунд разрешает viewer-предложения» на событии голосования.
    if not await _has_column(conn, "voting_events", "allow_proposals"):
        await conn.execute(
            "ALTER TABLE voting_events ADD COLUMN allow_proposals INTEGER NOT NULL DEFAULT 0"
        )

    # 2. Очередь предложений (UGC). channel_id — для tenant-scoping + быстрого списка.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS voting_proposals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL,
            channel_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,              -- ник автора (Twitch login) — §7 attribution
            label       TEXT NOT NULL,              -- предложенное название игры
            pledge      INTEGER NOT NULL DEFAULT 0, -- вклад, списывается на approve
            status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
            option_id   INTEGER,                    -- заполняется на approve (→ voting_options)
            created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_voting_proposals_pending "
        "ON voting_proposals(channel_id, event_id, status)"
    )

    await conn.commit()
    await _mark_applied(conn, "M88.game_vote_proposals")
    print("✅ M88: voting_proposals + voting_events.allow_proposals (Народный выбор игры)")


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in await cur.fetchall())


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
