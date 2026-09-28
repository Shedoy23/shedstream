"""
Migration M58 — Heritage / Inheritance log.

Sprint 5.33 HERITAGE — closes the lifecycle loop:
  FAM (m49) → giveрs heir
  SHOP/FIEF/CARAVAN (m55-m57) → builds economic empire
  HERITAGE (m58) → empire transcends death

Workflow:
  1. Parent dies → backend collects ALL active assets (workshops/caravans/fiefs).
  2. Backend pushes asset list inside hero.activate_heir payload.
  3. Mod ActivateHeirHandler iterates assets, re-transfers ownership engine-side.
  4. Backend logs each inheritance в bannerlord_inheritance_log (audit).
  5. Frontend "Наследие" section показывает recent events.

Без HERITAGE: engine auto-handles parent death via ApplyByDeath actions →
ownership уходит к random notable. Backend's owner_username preserved
(heir keeps username), но engine sync stops — total_collected freezes.

С HERITAGE: ownership cleanly transfers heir-side, sync resumes.

Schema (audit-only — actual state на assets уже tracked в их таблицах):
  id              INTEGER PK
  channel_id      INT
  parent_username viewer kто умер
  heir_hero_id    engine StringId нового hero
  asset_type      workshop / caravan / fief
  asset_ref       JSON identifier — для workshop: {settlement_id, workshop_type},
                  для caravan: {party_id, caravan_id}, для fief: {fief_id, fief_type}
  asset_name      readable label
  total_value     cumulative dinars accumulated parent'ом (для display)
  inherited_at    TIMESTAMP
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M58.inheritance"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_inheritance_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            parent_username TEXT    NOT NULL,
            heir_hero_id    TEXT    NOT NULL,
            asset_type      TEXT    NOT NULL,
            asset_ref       TEXT,
            asset_name      TEXT,
            total_value     INTEGER NOT NULL DEFAULT 0,
            inherited_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inheritance_parent
        ON bannerlord_inheritance_log(channel_id, parent_username, inherited_at DESC)
    """)
    print("M58: bannerlord_inheritance_log created")

    await conn.commit()
    await _mark_applied(conn, "M58.inheritance")


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
