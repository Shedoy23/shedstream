"""
Migration M42 — Boosty subscribers table (manual-list MVP).

Sprint 5.31 #45 — Boosty подписки как аналог Twitch sub'ов. Boosty не имеет
matching API между Boosty profile и Twitch identity, поэтому streamer ведёт
список вручную через admin panel.

Tier:
  1 = Tier 1 (минимальный paid)
  2 = Tier 2 (средний)
  3 = Tier 3 (максимальный)

Boost multipliers тот же что Twitch sub (см. twitch_subs.SUB_BOOSTS):
  tier 1 → price ×0.85, reward ×1.5
  tier 2 → price ×0.70, reward ×2.0
  tier 3 → price ×0.50, reward ×3.0

Backend flow в bannerlord.buy_action:
  1. Если broadcaster/moderator role → applies (как было)
  2. Иначе: lookup boosty_subscribers tier — если есть, используем
  3. Иначе: lookup Helix Twitch sub tier
  4. Иначе: viewer (1.0×)

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
