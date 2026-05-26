"""
Migration M52 — Vassal sub-clan system (BLT-parity, Randomchair22 + Lait inspiration).

Sprint 5.33 — viewer-leader клана создаёт *подклан-вассал* через выделение
взрослого ребёнка / адопт companion'а в separate clan. Vassal клан имеет
своего лидера, свой banner, свой income flow. Часть income (default 25%)
от vassal'ских mercenary contracts / фьефов идёт parent clan'у.

BLT (Randomchair22.VassalCommand + .VassalBehavior + Lait's vassal fief fix)
делает то же. Наш use case — Twitch Extension UI вместо chat commands.

Schema:
  id                       INTEGER PK
  channel_id               INT — multi-tenant
  parent_username          viewer-leader (parent clan)
  vassal_clan_id           Clan.StringId TaleWorlds (vassal клан после CreateClan)
  vassal_leader_hero_id    Hero.StringId которого выделили как vassal-leader
  vassal_name              readable (для UI)
  income_share_pct         REAL DEFAULT 25.0 — % parent получает
  banner_code              TEXT — TaleWorlds banner-code string (NULL если default)
  created_at               TIMESTAMP

PRIMARY KEY (channel_id, vassal_clan_id) — один clan = один vassal entry.
Composite index для list-by-parent (часто-запрашиваемый GET).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M52.vassals"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_vassals (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id               INTEGER NOT NULL,
            parent_username          TEXT    NOT NULL,
            vassal_clan_id           TEXT    NOT NULL,
            vassal_leader_hero_id    TEXT    NOT NULL,
            vassal_name              TEXT    NOT NULL,
            income_share_pct         REAL    NOT NULL DEFAULT 25.0,
            banner_code              TEXT,
            created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (channel_id, vassal_clan_id)
        )
    """)
    print("M52: bannerlord_vassals table created")

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_vassals_parent
        ON bannerlord_vassals(channel_id, parent_username)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_vassals_leader
        ON bannerlord_vassals(channel_id, vassal_leader_hero_id)
    """)
    print("M52: indexes created")

    await conn.commit()
    await _mark_applied(conn, "M52.vassals")


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
