"""
Migration M83: shedcolony — link + state таблицы для модуля ShedColony.

shedcolony_colony_link    — связь зритель ↔ колонист (1 зритель = 1 колонист на канал).
shedcolony_colonist_state — снимок состояния колониста (hp / работа / скиллы), пушится модом.

Мультитенант: channel_id первым столбцом, в каждом UNIQUE/PK. Аддитивно (новые таблицы) —
другие модули/игры не трогает. Idempotent: migrations_applied['M83.shedcolony'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M83.shedcolony"):
        return

    # Связь зритель ↔ колонист.
    #   UNIQUE(channel_id, viewer_id)  = 1 зритель → 1 колонист
    #   UNIQUE(channel_id, citizen_id) = 1 колонист → 1 зритель
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_colony_link (
            channel_id  INTEGER NOT NULL,
            viewer_id   TEXT    NOT NULL,
            citizen_id  TEXT    NOT NULL,
            colony_id   TEXT    NOT NULL,
            colony_dim  TEXT,
            status      TEXT    NOT NULL DEFAULT 'active',
            linked_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            died_at     TIMESTAMP,
            UNIQUE (channel_id, viewer_id),
            UNIQUE (channel_id, citizen_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shedcolony_link_lookup
            ON shedcolony_colony_link(channel_id, status)
    """)

    # Снимок состояния колониста (upsert на каждый пуш мода).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS shedcolony_colonist_state (
            channel_id  INTEGER NOT NULL,
            citizen_id  TEXT    NOT NULL,
            hp          REAL,
            job         TEXT,
            skills_json TEXT,
            status      TEXT    NOT NULL DEFAULT 'active',
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, citizen_id)
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M83.shedcolony")
    print("M83: shedcolony_colony_link + shedcolony_colonist_state created")


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
