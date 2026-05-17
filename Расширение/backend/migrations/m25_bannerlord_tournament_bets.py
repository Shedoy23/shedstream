"""
Migration M25: bannerlord_tournament_bets — viewer ставки на турнир.

BLT-style betting. Когда турнир начинается (status='running'), viewer'ы
ставят крустики на участников. Bet active только на текущий round —
после round_ended payout рассчитывается, неправильные ставки burn'ятся,
правильные получают долю pot'а по ставке.

Schema:
  channel_id     INTEGER         — tenant
  bettor         TEXT            — viewer who bet (lower)
  target         TEXT            — participant username (lower)
  amount         INTEGER         — крустики ставка
  round_index    INTEGER         — round when bet placed (0..3)
  resolved       INTEGER         — 0=open, 1=won, 2=lost
  payout         INTEGER         — крустики (после resolve)
  placed_at      TIMESTAMP
  PK(channel_id, bettor, round_index)  — 1 ставка на раунд

Idempotent через migrations_applied['M25.tournament_bets'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M25.tournament_bets"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_tournament_bets (
            channel_id   INTEGER NOT NULL,
            bettor       TEXT NOT NULL,
            target       TEXT NOT NULL,
            amount       INTEGER NOT NULL,
            round_index  INTEGER DEFAULT 0,
            resolved     INTEGER DEFAULT 0,
            payout       INTEGER DEFAULT 0,
            placed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, bettor, round_index)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bannerlord_bets_target
            ON bannerlord_tournament_bets(channel_id, target, round_index)
    """)

    await conn.commit()
    await _mark_applied(conn, "M25.tournament_bets")
    print("M25: bannerlord_tournament_bets created (viewer betting)")


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
