"""
Migration M42 — Boosty subscribers table (manual-list MVP).

Sprint 5.31 #45 — Boosty подписки как cosmetic-only badge list.
Sprint 5.33 TOS-COMPLIANCE (2026-05-28): gameplay multipliers за подписки
REMOVED (Twitch ToS prohibits subscription-gated rewards в Extensions —
spirit applies к third-party paid subs тоже). Table остаётся для cosmetic
UI (badges); bannerlord.buy_action больше НЕ использует boosty tier для
price/reward modifications.

Tier (cosmetic-only после 5.33):
  1 = Tier 1 (Бакалавр-уровень — badge BS1)
  2 = Tier 2 (Магистр-уровень — badge BS2)
  3 = Tier 3 (Жнец-уровень — badge BS3)

Historical (DEPRECATED — НЕ применяется):
  ~~tier 1 → price ×0.85, reward ×1.5~~
  ~~tier 2 → price ×0.70, reward ×2.0~~
  ~~tier 3 → price ×0.50, reward ×3.0~~

Backend flow в bannerlord.buy_action (5.33+):
  1. Если broadcaster/moderator role → applies (channel role, ToS OK)
  2. Иначе → (1.0, 1.0) "viewer" — sub status doesn't matter

Idempotent через migrations_applied table.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M42.boosty_subscribers"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_boosty_subscribers (
            channel_id       INTEGER NOT NULL,
            twitch_username  TEXT    NOT NULL,
            tier             INTEGER NOT NULL,
            note             TEXT,
            set_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, twitch_username)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_boosty_subs_channel
        ON bannerlord_boosty_subscribers (channel_id)
    """)

    await conn.commit()
    await _mark_applied(conn, "M42.boosty_subscribers")
    print("M42: bannerlord_boosty_subscribers table created")


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
