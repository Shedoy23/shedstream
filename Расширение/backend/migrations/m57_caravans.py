"""
Migration M57 — Caravans (BLT-parity, mobile traveling income).

Sprint 5.33 CARAVAN — закрывает passive income trilogy:
  SHOP   = static personal workshop      (100:1 ratio)
  FIEF   = territorial kingdom-scale     (200:1 ratio)
  CARAVAN = mobile traveling, with risk  (150:1 ratio, capture events)

Workflow:
  1. Viewer buys caravan: hero.buy_caravan (1500⦷ + 15K Hero.Gold capital)
     - Mod calls CaravanPartyComponent.CreateCaravanParty(viewerHero, home, template).
     - Backend INSERTs row с placeholder party_id.
     - Mod пушит hero.caravan_created event с real party_id → backend backfill.

  2. Каждый game-day mod OnDailyTick:
     - Scan MobileParty.AllCaravanParties где IsCaravan и Owner = [BLink] hero.
     - Diff PartyTradeGold vs snapshot → push hero.caravan_profit_sync event.
     - Backend converts to crustic (150:1 ratio), auto-credit.

  3. На MobilePartyDestroyed event (caravan captured/destroyed):
     - Mod пушит hero.caravan_destroyed с {party_id, captor_name}.
     - Backend marks status='destroyed', creates rescue pool entry.
     - Viewers могут pay_caravan_rescue (500⦷ each) — когда pool ≥ cost,
       backend "respawns" caravan: enqueue hero.buy_caravan replacement
       за счёт пула, refund остаток.

Schema:
  bannerlord_caravans:
    id, channel_id, owner_username, party_id (engine StringId),
    home_settlement_id, home_settlement_name,
    initial_capital, total_collected_dinars,
    last_synced_at, opened_at, destroyed_at,
    status (active/destroyed/sold/rescued)

  bannerlord_caravan_rescue_pool (parallel to ransom):
    id, channel_id, caravan_id, contributor, amount, paid_at, status
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M57.caravans"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_caravans (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id               INTEGER NOT NULL,
            owner_username           TEXT    NOT NULL,
            party_id                 TEXT,
            home_settlement_id       TEXT,
            home_settlement_name     TEXT,
            initial_capital          INTEGER NOT NULL DEFAULT 0,
            total_collected_dinars   INTEGER NOT NULL DEFAULT 0,
            last_synced_at           TIMESTAMP,
            opened_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            destroyed_at             TIMESTAMP,
            status                   TEXT    NOT NULL DEFAULT 'active'
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_caravans_owner
        ON bannerlord_caravans(channel_id, owner_username, status)
    """)
    # Lookup index — backend resolve по party_id (mod-side StringId).
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_caravans_party
        ON bannerlord_caravans(channel_id, party_id)
        WHERE party_id IS NOT NULL
    """)
    print("M57: bannerlord_caravans created")

    # Rescue pool — parallel structure к bannerlord_ransom_pool (m54).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_caravan_rescue_pool (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            caravan_id      INTEGER NOT NULL,
            contributor     TEXT    NOT NULL,
            amount          INTEGER NOT NULL,
            paid_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status          TEXT    NOT NULL DEFAULT 'pooled',
            FOREIGN KEY (caravan_id) REFERENCES bannerlord_caravans(id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_caravan_rescue
        ON bannerlord_caravan_rescue_pool(channel_id, caravan_id, status)
    """)
    print("M57: bannerlord_caravan_rescue_pool created")

    await conn.commit()
    await _mark_applied(conn, "M57.caravans")


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
