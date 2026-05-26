"""
Migration M48 — `bannerlord_heirs` table для heir queue (BLT-parity M2).

Sprint 5.32 — pre-collect heirs of adopted viewers' clans для succession.

Когда у adopted hero'я ребёнок достигает 18+ лет (HeroComesOfAgeEvent в моде),
mod пушит event `hero.heir_came_of_age` с heir_id + parent_username. Backend
INSERT'ит в bannerlord_heirs. На UI viewer видит "наследники в очереди":
сын/дочь #1, #2.

На death героя (existing flow) backend МОЖЕТ pick'нуть first alive heir
вместо create new wanderer (это M2.1 followup activation, сейчас foundation).

Schema:
  channel_id      INTEGER  — FK к channels (multi-tenant scope)
  parent_username TEXT     — viewer login, у кого этот heir
  heir_hero_id    TEXT     — Hero.StringId в TaleWorlds (наследник)
  heir_name       TEXT     — отображаемое имя (для UI)
  came_of_age_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  alive           INTEGER  DEFAULT 1  — снимаем при HeroKilled(heir)
  activated       INTEGER  DEFAULT 0  — set=1 при succession через M2.1

PRIMARY KEY (channel_id, heir_hero_id) — один heir-id не должен дублироваться.
Композитный index для часто-запрашиваемой выборки heirs по parent_username.

Idempotent: CREATE TABLE IF NOT EXISTS.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M48.heir_queue"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_heirs (
            channel_id      INTEGER NOT NULL,
            parent_username TEXT    NOT NULL,
            heir_hero_id    TEXT    NOT NULL,
            heir_name       TEXT,
            came_of_age_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            alive           INTEGER NOT NULL DEFAULT 1,
            activated       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (channel_id, heir_hero_id)
        )
    """)
    print("M48: bannerlord_heirs table created")

    # Lookup index для GET /api/bannerlord/heirs?username=…
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_heirs_parent
        ON bannerlord_heirs(channel_id, parent_username, alive, activated)
    """)
    print("M48: idx_bannerlord_heirs_parent created")

    await conn.commit()
    await _mark_applied(conn, "M48.heir_queue")


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
