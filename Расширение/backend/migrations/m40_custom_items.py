"""
Migration M40 — Custom items (Smithing / Trophy collection).

Sprint 5.29 / BLT-parity #6 MVP scope.

Текущая итерация: items как trophy collection (backend-only). Viewer
покупает «Smith» action → backend generates random custom item (rarity +
name), сохраняет в bannerlord_custom_items. UI показывает inventory.

Future iterations:
  - Real Bannerlord ItemObject creation в моде (HeroEquipment integration)
  - Auction system (BLT pattern: reserve + countdown + BidOnItem action)
  - Item transfer between viewers
  - NameItem (rename trophy)

Schema:
  bannerlord_custom_items
    id INT PK
    channel_id INT NOT NULL
    owner_username TEXT NOT NULL
    base_type TEXT NOT NULL    -- weapon|armor|horse
    base_subtype TEXT          -- sword|axe|bow|helmet|cuirass|...
    custom_name TEXT NOT NULL   -- "Frostbite Greatsword"
    rarity TEXT NOT NULL DEFAULT 'common'  -- common|uncommon|rare|epic|legendary
    tier INT NOT NULL DEFAULT 1
    icon TEXT                   -- emoji-icon для UI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

Idempotent через migrations_applied.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M40.custom_items"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_custom_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            owner_username  TEXT    NOT NULL,
            base_type       TEXT    NOT NULL,
            base_subtype    TEXT,
            custom_name     TEXT    NOT NULL,
            rarity          TEXT    NOT NULL DEFAULT 'common',
            tier            INTEGER NOT NULL DEFAULT 1,
            icon            TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_custom_owner
        ON bannerlord_custom_items (channel_id, owner_username)
    """)

    await conn.commit()
    await _mark_applied(conn, "M40.custom_items")
    print("M40: bannerlord_custom_items table created")


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
