"""
Migration M9: Cases (Phase 2 of COMPLIANCE_REWORK_PLAN.md).

Создаёт инфраструктуру для системы кейсов 4 тиров с фиксированной наградой
крустиков. Кейсы выдаются за активность (квесты / streak / watch milestones /
сезонные итоги / drops) и открываются юзером в любое время. Награда
детерминированная per tier — никакого RNG в содержимом.

Tier rewards (зафиксировано в config.py.CASE_TIER_REWARDS, не в БД —
позволяет менять баланс через config без миграции):
  common      →  1 000 💎
  rare        →  10 000 💎
  epic        →  100 000 💎
  legendary   →  500 000 💎

Tables:
  cases — каждый выданный кейс, отдельная запись
    PK: id (autoincrement)
    UNIQUE: (channel_id, username, awarded_at, source, tier) — защита от
            случайного двойного INSERT, не critical
    opened_at NULL = ещё не открыт; NOT NULL = открыт, reward_points
    зафиксирован на момент открытия (защита от изменений CASE_TIER_REWARDS
    задним числом)

  case_triggers_fired — идемпотентность one-time triggers
    PK: (channel_id, username, trigger_key)
    Пример trigger_key: 'watch_100h', 'streak_10', 'season_2026_Q1_top1'
    Защищает от повторной выдачи кейса за один и тот же milestone
    Daily quests НЕ идут через эту таблицу (идемпотентность через
    quests.day_date).

Идемпотентно через migrations_applied['M9.cases'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M9.cases"):
        return

    # ── cases ──────────────────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id     INTEGER NOT NULL,
            username       TEXT NOT NULL,
            tier           TEXT NOT NULL CHECK (tier IN ('common', 'rare', 'epic', 'legendary')),
            source         TEXT NOT NULL,
            awarded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            opened_at      TIMESTAMP,
            reward_points  INTEGER
        )
    """)

    # Index: список кейсов юзера (сортировка по awarded_at для UI)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cases_user
            ON cases(channel_id, username, awarded_at DESC)
    """)

    # Partial index: быстрый поиск НЕ открытых (UI чаще запрашивает только закрытые)
    # SQLite поддерживает partial indexes с 3.8.0 (2014). На проде 3.45 — OK.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cases_unopened
            ON cases(channel_id, username)
            WHERE opened_at IS NULL
    """)

    # ── case_triggers_fired ────────────────────────────────────────────────────
    # Идемпотентность для one-time triggers
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS case_triggers_fired (
            channel_id    INTEGER NOT NULL,
            username      TEXT NOT NULL,
            trigger_key   TEXT NOT NULL,
            case_id       INTEGER NOT NULL,
            fired_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, trigger_key)
        )
    """)

    # Audit-индекс: какие триггеры сработали для канала (admin диагностика)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_triggers_channel
            ON case_triggers_fired(channel_id, fired_at DESC)
    """)

    await conn.commit()
    await _mark_applied(conn, "M9.cases")
    print("✅ M9: cases + case_triggers_fired tables created")


async def _ensure_migrations_table(conn) -> None:
    """Defensive duplicate (создаётся в M1/M4/M5/M6/M7/M8)."""
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
