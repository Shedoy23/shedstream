"""
Migration M22: bannerlord_channel_state — track current_save_id per channel.

Зачем: когда стример переключает save (different campaign), heroes
зрителей из предыдущего save не существуют в новом. Backend должен
сбросить bannerlord_heroes + связанные таблицы, чтобы viewer'ы видели
"Стать героем" (empty state) в extension'е.

Flow:
  1. Mod при Campaign load (CampaignEvents.OnGameLoadFinishedEvent) пушит
     module.session_start с save_id = Campaign.Current.UniqueGameId.
  2. Backend handler сравнивает с last known save_id для channel:
     • match → ничего не делаем (тот же save reloaded — heroes persist)
     • mismatch → DELETE all bannerlord_heroes/skills/equipment/
       attributes/hero_class для channel_id
  3. Update bannerlord_channel_state.current_save_id.

Schema:
  channel_id      INTEGER PRIMARY KEY
  current_save_id TEXT
  last_session_at TIMESTAMP

Idempotent через migrations_applied['M22.channel_state'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M22.channel_state"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_channel_state (
            channel_id      INTEGER PRIMARY KEY,
            current_save_id TEXT,
            last_session_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M22.channel_state")
    print("M22: bannerlord_channel_state created (save-switch tracking)")


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
