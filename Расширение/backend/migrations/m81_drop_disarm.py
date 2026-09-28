"""
Migration M81: drop disarm_burst power rows (weak/unfun active).

disarm_burst (1 случайный враг в 15м роняет оружие на миг) — слабая активка,
владелец просил убрать («чушь полная»). Вдобавок она не была в ACTIVE_POWER_KEYS
→ кнопки не было, активировать нельзя. Удаляем строку(и) power.

(poison_dot + berserker_charge — наоборот, ПОДКЛЮЧЕНЫ в routes/bannerlord.py
ACTIVE_POWER_KEYS — это code-change, не миграция: строки power уже есть.)

Idempotent: migrations_applied['M81.drop_disarm'] + DELETE (no-op если уже нет).
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M81.drop_disarm"):
        return

    await conn.execute(
        "DELETE FROM bannerlord_class_powers WHERE power_key='disarm_burst'")

    await conn.commit()
    await _mark_applied(conn, "M81.drop_disarm")
    print("M81: dropped disarm_burst power rows (weak active, owner-removed)")


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
