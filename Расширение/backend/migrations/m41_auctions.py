"""
Migration M41 — Auction system для custom items.

Sprint 5.29 / BLT-parity #6 Phase B.

Viewer выставляет custom item на аукцион с reserve_price + timer. Другие
viewers бидят крустиками; каждый bid списывается immediately, отменённый
bid (outbid) рефандится. Истёк timer → highest bidder wins, item transfers,
seller получает крустики (минус 10% commission в pool стримера).

Если ни один bid не достиг reserve — item returns seller'у.

Schema:
  bannerlord_auctions
    id INT PK
    channel_id INT
    seller_username TEXT
    custom_item_id INT  (FK bannerlord_custom_items.id, no cascade — мы handle вручную)
    reserve_price INT  (минимальный bid)
    current_bid INT  (последний bid amount)
    current_bidder TEXT NULL  (кто лидер)
    started_at TIMESTAMP
    ends_at TIMESTAMP
    status TEXT (active | sold | expired_no_bids | cancelled)
    resolved_at TIMESTAMP NULL

  bannerlord_auction_bids
    id INT PK
    auction_id INT
    bidder_username TEXT
    amount INT
    placed_at TIMESTAMP
    refunded INT DEFAULT 0  (was outbid → refunded automatically)

Resolution loop: каждые 30 секунд background task scan'ит active auctions
where ends_at < now → resolve.

Idempotent через migrations_applied.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M41.auctions"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_auctions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            seller_username TEXT    NOT NULL,
            custom_item_id  INTEGER NOT NULL,
            reserve_price   INTEGER NOT NULL,
            current_bid     INTEGER NOT NULL DEFAULT 0,
            current_bidder  TEXT,
            started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ends_at         TIMESTAMP NOT NULL,
            status          TEXT NOT NULL DEFAULT 'active',
            resolved_at     TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_auction_active
        ON bannerlord_auctions (channel_id, status, ends_at)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_auction_bids (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id      INTEGER NOT NULL,
            bidder_username TEXT    NOT NULL,
            amount          INTEGER NOT NULL,
            placed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            refunded        INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_bid_auction
        ON bannerlord_auction_bids (auction_id, refunded)
    """)

    await conn.commit()
    await _mark_applied(conn, "M41.auctions")
    print("M41: bannerlord_auctions + bannerlord_auction_bids tables created")


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
