"""
Migration M12: Voting events (Phase 4 of COMPLIANCE_REWORK_PLAN.md).

Создаёт инфраструктуру для голосований зрителей за действие стримера.
Compliance: §6.1.4 Twitch Extension Guidelines прямо разрешает voting
activities. Это НЕ wagering (§6.2.6) — outcomes полностью контролируются
самими юзерами через их голоса. Items не выдаются — prize = действие
стримера (не имеет monetary value).

Дизайн:
  - streamer_voting_templates: стример заранее настраивает варианты
    (что играть / стиль прохождения / еда на стриме / etc.) — это
    §6.2.8 protection: catalog задан, не ad-hoc от юзеров
  - voting_events: активное голосование на канале, attaches template
  - voting_options: snapshot вариантов template на момент start
  - voting_bids: вклады крустиков юзеров в опцию
  - Pool наполняется через background loop (1 min watch = 1 unit,
    1 chat = 5 units) — Phase 4.C integration

Schema:
  streamer_voting_templates (id, channel_id, name, options_json, created_at)
  voting_events             (id, channel_id, template_id, started_at,
                             ends_at, finished, winning_option_id,
                             total_pool, status)
  voting_options            (id, event_id, label, description, pool)
  voting_bids               (id, event_id, option_id, channel_id,
                             username, amount, placed_at)

Compliance: refund НЕ делается (collective vote, не commerce).

Идемпотентно через migrations_applied['M12.voting'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M12.voting"):
        return

    # ── streamer_voting_templates ─────────────────────────────────────────────
    # Pre-configured templates стримером. Например:
    #   { "name": "Что играть?", "options": [
    #         {"key":"rimworld",  "label":"RimWorld",  "description":"..."},
    #         {"key":"bannerlord","label":"Bannerlord","description":"..."},
    #     ]}
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS streamer_voting_templates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            name            TEXT NOT NULL,
            options_json    TEXT NOT NULL,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_default      INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voting_templates_by_channel
            ON streamer_voting_templates(channel_id, created_at DESC)
    """)
    # Один is_default=1 шаблон per канал (используется когда auto-start)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_voting_templates_default
            ON streamer_voting_templates(channel_id)
            WHERE is_default = 1
    """)

    # ── voting_events ─────────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS voting_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id          INTEGER NOT NULL,
            template_id         INTEGER,
            template_name       TEXT,
            started_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ends_at             TIMESTAMP NOT NULL,
            finished            INTEGER NOT NULL DEFAULT 0,
            winning_option_id   INTEGER,
            winning_option_key  TEXT,
            winning_option_label TEXT,
            total_pool          INTEGER NOT NULL DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'finished', 'cancelled'))
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voting_events_active
            ON voting_events(channel_id, status)
            WHERE status = 'active'
    """)
    # Один active voting event per channel (только один опрос идёт)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_voting_events_active_per_channel
            ON voting_events(channel_id)
            WHERE status = 'active'
    """)

    # ── voting_options ────────────────────────────────────────────────────────
    # Snapshot опций template на момент event start. Template может изменяться
    # потом — но options события зафиксированы.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS voting_options (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL,
            option_key  TEXT NOT NULL,
            label       TEXT NOT NULL,
            description TEXT,
            pool        INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (event_id) REFERENCES voting_events(id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voting_options_by_event
            ON voting_options(event_id, pool DESC)
    """)

    # ── voting_bids ───────────────────────────────────────────────────────────
    # Audit-trail: кто на что и сколько вкинул. Для top-bidders UI и
    # anti-abuse мониторинга.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS voting_bids (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        INTEGER NOT NULL,
            option_id       INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            username        TEXT NOT NULL,
            amount          INTEGER NOT NULL,
            placed_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voting_bids_by_event
            ON voting_bids(event_id, placed_at DESC)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_voting_bids_by_user
            ON voting_bids(event_id, username)
    """)

    # ── voting_pool_counter (channel-wide pool tracking) ──────────────────────
    # Накопление units от пассивной активности (watch / chat) до достижения
    # порога стартующего event. Один row per channel.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS voting_pool_counters (
            channel_id      INTEGER PRIMARY KEY,
            pool_units      INTEGER NOT NULL DEFAULT 0,
            last_increment_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M12.voting")
    print("✅ M12: voting tables created (templates + events + options + bids + pool_counters)")


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
