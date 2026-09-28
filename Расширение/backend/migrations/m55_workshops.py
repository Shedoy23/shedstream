"""
Migration M55 — Workshops (BLT-parity passive income loop).

Sprint 5.33 SHOP — viewer покупает workshop в town'е → mod creates owned
workshop via ChangeOwnerOfWorkshopAction.ApplyByPlayerBuying. Каждый
in-game day mod syncs ProfitMade-Expense diff в backend как event.
Backend конвертирует динары → ⦷ (ratio 100:1) и зачисляет viewer'у.

Backend = source-of-truth для UI (показывает текущий profit), mod source-of-truth
для actual engine state. Sync через daily event hero.workshop_profit_sync.

Schema:
  id              INTEGER PK
  channel_id      INT
  owner_username  viewer (workshop owner via его Hero)
  settlement_id   TaleWorlds Settlement.StringId (town)
  settlement_name UI display
  workshop_type   TaleWorlds WorkshopType.StringId (smithy/brewery/...)
  workshop_type_name UI display
  initial_capital INT — динары paid при создании (refund 50% при sell)
  total_profit    INT — кумулятивный gross profit (динары) since open
  last_synced_at  TIMESTAMP — last mod sync
  last_payout_at  TIMESTAMP — last ⦷ payout to viewer
  status          TEXT (active/sold/destroyed)

UNIQUE — один workshop per (channel, settlement, type) — иначе race conditions
при concurrent buy attempts.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M55.workshops"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_workshops (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id          INTEGER NOT NULL,
            owner_username      TEXT    NOT NULL,
            settlement_id       TEXT    NOT NULL,
            settlement_name     TEXT,
            workshop_type       TEXT    NOT NULL,
            workshop_type_name  TEXT,
            initial_capital     INTEGER NOT NULL DEFAULT 0,
            total_profit        INTEGER NOT NULL DEFAULT 0,
            last_synced_at      TIMESTAMP,
            last_payout_at      TIMESTAMP,
            opened_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status              TEXT    NOT NULL DEFAULT 'active'
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_workshops_owner
        ON bannerlord_workshops(channel_id, owner_username, status)
    """)
    # UNIQUE partial idx — один active workshop per (channel, settlement, type).
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_workshops_unique_active
        ON bannerlord_workshops(channel_id, settlement_id, workshop_type)
        WHERE status = 'active'
    """)
    print("M55: bannerlord_workshops created с indexes")

    await conn.commit()
    await _mark_applied(conn, "M55.workshops")


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
