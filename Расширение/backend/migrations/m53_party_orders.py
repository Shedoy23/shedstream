"""
Migration M53 — Party orders (BLT-parity, Randomchair22 PartyOrderBehavior).

Sprint 5.33 — viewer-clan-leader устанавливает strategic order на свою party:
  siege <town>      — осаждать settlement
  defend <town>     — защищать settlement
  patrol <area>     — патрулировать (random near settlement)
  raid <village>    — налёт на деревню
  garrison <fort>   — закрепиться (sit + defend)
  release           — cancel current order, AI берёт обычное поведение

Mod-side PartyOrderBehavior каждый game-час re-issues order чтобы engine AI
не дрейфовал. Backend хранит state — переживает game restart.

Schema:
  id                   INTEGER PK
  channel_id           INT — multi-tenant
  owner_username       viewer (clan leader)
  order_type           TEXT enum (siege/defend/patrol/raid/garrison)
  target_settlement_id TaleWorlds Settlement.StringId (NULL для release)
  target_settlement_name TEXT — readable для UI
  issued_at            TIMESTAMP
  expires_at           TIMESTAMP — default +7 game days
  status               TEXT (active/cancelled/expired/completed)

Один active order per viewer — UNIQUE partial index (status='active').
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M53.party_orders"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_party_orders (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id             INTEGER NOT NULL,
            owner_username         TEXT    NOT NULL,
            order_type             TEXT    NOT NULL,
            target_settlement_id   TEXT,
            target_settlement_name TEXT,
            issued_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at             TIMESTAMP NOT NULL,
            status                 TEXT    NOT NULL DEFAULT 'active'
        )
    """)
    print("M53: bannerlord_party_orders table created")

    # Lookup index — viewer часто читает свой active order.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_party_orders_owner
        ON bannerlord_party_orders(channel_id, owner_username, status)
    """)
    # UNIQUE — один active order per viewer.
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_party_orders_active_unique
        ON bannerlord_party_orders(channel_id, owner_username)
        WHERE status = 'active'
    """)
    print("M53: indexes created")

    await conn.commit()
    await _mark_applied(conn, "M53.party_orders")


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
