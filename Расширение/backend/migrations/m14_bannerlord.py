"""
Migration M14: Bannerlord-specific схема (Phase 9 — Bannerlord module MVP).

Это **второй gaming-модуль** платформы (первый — RimWorld). Все таблицы
TENANT-scoped (channel_id в PK) — Bannerlord runs per-streamer как и
RimWorld. Cross-channel exception (pets) — отдельный case.

Compliance:
  - Игровая state, не финансовая — нет direct money flow в этих таблицах
  - Heroes / equipment / skills — это game-objects, не digital goods
    для пользователей (§5.3 cosmetic-only не применимо)
  - События логируются для audit, не для рекламы

Schema:
  bannerlord_heroes      — viewer → NPC-герой mapping ((channel_id, username) PK)
  bannerlord_skills      — skill points per hero ((channel_id, username, skill_key) PK)
  bannerlord_attributes  — attribute values per hero (vigor/control/...)
  bannerlord_equipment   — equipment slots per hero (weapon_0/.../armor/horse)
  bannerlord_events_log  — audit log (battle outcomes, hero deaths, sieges, ...)

Идемпотентно через migrations_applied['M14.bannerlord'].

См. docs/BANNERLORD_MVP.md §3 для деталей и rationale.
"""

# Bannerlord skill keys (из vanilla игры, без DLC):
# https://bannerlord.fandom.com/wiki/Skills
BANNERLORD_SKILLS = (
    'one_handed', 'two_handed', 'polearm', 'bow', 'crossbow', 'throwing',
    'riding', 'athletics', 'crafting',
    'tactics', 'scouting',
    'roguery', 'charm', 'leadership',
    'trade', 'steward', 'medicine', 'engineering',
)

# Bannerlord 6 attributes (vanilla, без DLC):
BANNERLORD_ATTRIBUTES = (
    'vigor', 'control', 'endurance', 'cunning', 'social', 'intelligence',
)

# Equipment slots (vanilla, без DLC):
# weapon_0..weapon_3 — main hand 4 weapon slots
# armor — body armor
# helmet — head armor
# legs — leg armor
# gloves — hand armor
# horse — mount
# horse_harness — mount armor
BANNERLORD_EQUIPMENT_SLOTS = (
    'weapon_0', 'weapon_1', 'weapon_2', 'weapon_3',
    'armor', 'helmet', 'legs', 'gloves',
    'horse', 'horse_harness',
)


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M14.bannerlord"):
        return

    # ── bannerlord_heroes ─────────────────────────────────────────────────────
    # TENANT-scoped (channel_id в PK). 1 hero per (channel, viewer username).
    # hero_id — Bannerlord internal Hero.StringId, нужен mod'у для повторного
    # резолва после save reload.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_heroes (
            channel_id   INTEGER NOT NULL,
            username     TEXT NOT NULL,
            hero_id      TEXT NOT NULL,
            display_name TEXT NOT NULL,
            culture      TEXT,
            is_alive     INTEGER NOT NULL DEFAULT 1,
            is_prisoner  INTEGER NOT NULL DEFAULT 0,
            gold         INTEGER NOT NULL DEFAULT 0,
            location     TEXT,
            adopted_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_sync    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username)
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bannerlord_heroes_hero_id
            ON bannerlord_heroes(channel_id, hero_id)
    """)
    # Index для быстрого lookup heroes на канале
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_heroes_alive
            ON bannerlord_heroes(channel_id, is_alive)
    """)

    # ── bannerlord_skills ─────────────────────────────────────────────────────
    # Composite PK: per-hero per-skill.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_skills (
            channel_id INTEGER NOT NULL,
            username   TEXT NOT NULL,
            skill_key  TEXT NOT NULL,
            level      INTEGER NOT NULL DEFAULT 0,
            xp         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (channel_id, username, skill_key)
        )
    """)

    # ── bannerlord_attributes ─────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_attributes (
            channel_id INTEGER NOT NULL,
            username   TEXT NOT NULL,
            attribute  TEXT NOT NULL,
            value      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (channel_id, username, attribute)
        )
    """)

    # ── bannerlord_equipment ──────────────────────────────────────────────────
    # item_id — Bannerlord ItemObject.StringId (для re-resolve в моде)
    # item_name — human-readable (для UI без обращения к моду)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_equipment (
            channel_id INTEGER NOT NULL,
            username   TEXT NOT NULL,
            slot       TEXT NOT NULL,
            item_id    TEXT,
            item_name  TEXT,
            PRIMARY KEY (channel_id, username, slot)
        )
    """)

    # ── bannerlord_events_log ─────────────────────────────────────────────────
    # Append-only audit. payload — JSON string с event-specific данными.
    # Не для state — state в heroes/skills/equipment.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_events_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            username   TEXT,
            payload    TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_events_channel
            ON bannerlord_events_log(channel_id, created_at DESC)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_events_user
            ON bannerlord_events_log(channel_id, username, created_at DESC)
            WHERE username IS NOT NULL
    """)

    await conn.commit()
    await _mark_applied(conn, "M14.bannerlord")
    print(
        f"✅ M14: bannerlord tables created "
        f"({len(BANNERLORD_SKILLS)} skill_keys, "
        f"{len(BANNERLORD_ATTRIBUTES)} attributes, "
        f"{len(BANNERLORD_EQUIPMENT_SLOTS)} equipment slots)"
    )


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
