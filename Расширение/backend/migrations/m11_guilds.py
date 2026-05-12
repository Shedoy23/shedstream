"""
Migration M11: Guilds base (Phase 3 of COMPLIANCE_REWORK_PLAN.md).

Базовая система гильдий per канал — социальная механика без бустов
накопления (Variant 2a из COMPLIANCE_REWORK_PLAN.md §1 серая зона 3).

Что создаёт:
  - guilds: гильдия per канал, имя UNIQUE within channel
  - guild_members: один юзер = одна гильдия per канал
  - guild_skills: прокачиваемые ветки (placeholder v1, расширяется в Phase 3.1+)
  - guild_contributions: audit-trail вкладов крустиков в balance

Compliance:
  - Создание гильдии: cost 100k💎 (sink крустиков, конкретно §2.4 OK)
  - Прокачка skills: тратит из guild balance (общий sink)
  - НЕТ бустов накопления участникам (Variant 2a — conservative)
  - Master может kick — broadcaster-like control §7.4
  - Tier-gate: только Pro+ каналы могут включать гильдии (future, не сейчас)

Идемпотентно через migrations_applied['M11.guilds'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M11.guilds"):
        return

    # ── guilds ────────────────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guilds (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            name            TEXT NOT NULL,
            tagline         TEXT,
            master_username TEXT NOT NULL,
            balance         INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            disbanded_at    TIMESTAMP
        )
    """)
    # UNIQUE name per channel (case-insensitive комбинация имени — через
    # COLLATE NOCASE в WHERE на selects; UNIQUE на raw value)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_guilds_name_per_channel
            ON guilds(channel_id, name)
            WHERE disbanded_at IS NULL
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_guilds_top_balance
            ON guilds(channel_id, balance DESC)
            WHERE disbanded_at IS NULL
    """)

    # ── guild_members ─────────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_members (
            guild_id    INTEGER NOT NULL,
            channel_id  INTEGER NOT NULL,
            username    TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'member'
                        CHECK (role IN ('master', 'officer', 'member')),
            joined_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, username)
        )
    """)
    # UNIQUE: один юзер = одна гильдия per канал (защита от двойного membership).
    # Партикл — только active (т.е. не из disbanded гильдий).
    # Поскольку SQLite не позволяет CHECK по JOIN, мы полагаемся на
    # application-layer enforcement при insert (проверяем guild не disbanded).
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_guild_members_user_per_channel
            ON guild_members(channel_id, username)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_guild_members_by_guild
            ON guild_members(guild_id, joined_at)
    """)

    # ── guild_skills ──────────────────────────────────────────────────────────
    # Прокачка веток. skill_key — строка идентификатор (например
    # 'extra_member_slots', 'cosmetic_banner_unlock'). level и exp track прогресс.
    # Конкретные skills конфигурируются в config.py (GUILD_SKILLS_CONFIG).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_skills (
            guild_id    INTEGER NOT NULL,
            skill_key   TEXT NOT NULL,
            level       INTEGER NOT NULL DEFAULT 0,
            exp         INTEGER NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, skill_key)
        )
    """)

    # ── guild_contributions ───────────────────────────────────────────────────
    # Audit-trail кто сколько накинул. Для отображения «топ-контрибьюторов»
    # внутри гильдии и для anti-abuse мониторинга.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_contributions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            username        TEXT NOT NULL,
            amount          INTEGER NOT NULL,
            contributed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_guild_contribs_by_guild
            ON guild_contributions(guild_id, contributed_at DESC)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_guild_contribs_top_contributors
            ON guild_contributions(guild_id, username)
    """)

    await conn.commit()
    await _mark_applied(conn, "M11.guilds")
    print("✅ M11: guilds + members + skills + contributions created")


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
